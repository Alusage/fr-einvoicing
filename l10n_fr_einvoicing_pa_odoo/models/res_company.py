# Copyright 2026 Alusage (https://alusage.fr/)
# @author: Nicolas Jeudy <nicolas@alusage.fr>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
from datetime import timedelta

from odoo import _, fields, models
from odoo.exceptions import UserError

logger = logging.getLogger(__name__)

PLATFORM = "odoo"

# What the platform calls an incoming document, and what Akretion calls the
# matching flow. A lifecycle answer reaches us through the same channel as an
# invoice, so the sorting cannot be skipped: an invoice goes to the OCA
# import, a lifecycle answer to the CDAR parsing.
CDAR_DOCUMENT_TYPE = "CrossDomainAcknowledgementAndResponse"
FLOW_TYPE_BY_DOCUMENT_TYPE = {
    "Invoice": "SupplierInvoice",
    "CreditNote": "SupplierInvoice",
    "Factur-X": "SupplierInvoice",
    CDAR_DOCUMENT_TYPE: "CustomerInvoiceLC",
}

# The syntax Akretion reads off a flow, which the platform states as a
# document type instead. It matters beyond bookkeeping: the download names
# the file after it, and the processing decodes a CDAR on it.
SYNTAX_BY_DOCUMENT_TYPE = {
    "Invoice": "UBL",
    "CreditNote": "UBL",
    "Factur-X": "Factur-X",
    CDAR_DOCUMENT_TYPE: "CDAR",
}


class ResCompany(models.Model):
    _inherit = "res.company"

    def _fr_ctc_is_pa_odoo(self):
        """Return True when this company routes its flows through the Odoo PA.

        Every override of this module is guarded by this method rather than by
        the environment: a database may hold companies on SUPER PDP, companies
        on the Odoo PA, and companies using the native module on its own.
        """
        self.ensure_one()
        return self.fr_ctc_accredited_platform == PLATFORM

    def _fr_ctc_get_session(self):
        """Return the native proxy user instead of an OAuth session.

        The Odoo PA authenticates each request by signing it with the proxy
        user's key, so there is no OAuth session to open and no client
        credentials to read -- `_fr_ctc_credentials` would raise, since
        `fr_ctc_auth_method` is empty for this platform. The proxy user plays
        the part of the session for every network method of this module.
        """
        self.ensure_one()
        if not self._fr_ctc_is_pa_odoo():
            return super()._fr_ctc_get_session()
        edi_user = self.account_peppol_edi_user
        if not edi_user:
            raise UserError(
                _(
                    "Company '%s' is set to send through the Odoo accredited "
                    "platform, but it is not registered on it yet.",
                    self.display_name,
                )
            )
        return edi_user

    def _fr_ctc_odoo_prepare_in_flow(self, message):
        """Turn one platform message into the flow values Akretion expects.

        Only the naming differs: the platform states a `document_type` where
        Akretion states a flow `type`, and the sorting between an invoice and
        a lifecycle answer rides on it.
        """
        self.ensure_one()
        document_type = message.get("document_type")
        return {
            "direction": "in",
            "identifier": message.get("uuid"),
            "type": FLOW_TYPE_BY_DOCUMENT_TYPE.get(document_type),
            "syntax": SYNTAX_BY_DOCUMENT_TYPE.get(document_type),
            "company_id": self.id,
        }

    def _fr_ctc_run_import(self, session, result, download_and_process=True):
        """List the incoming documents on the Odoo platform.

        Nothing is acknowledged here. Acknowledging a message drops it from
        the platform for good, so it may only happen once the invoice has
        actually been imported -- otherwise a failing import would lose the
        document with no way to ask for it again.
        """
        self.ensure_one()
        if not self._fr_ctc_is_pa_odoo():
            return super()._fr_ctc_run_import(
                session, result, download_and_process=download_and_process
            )
        log_obj = self.env["fr.einvoicing.log"]
        flow_obj = self.env["fr.einvoicing.flow"]
        edi_user = session
        try:
            answer = edi_user._call_peppol_proxy(
                edi_user._get_peppol_proxy_endpoint("1/get_all_documents"),
                {
                    "domain": {
                        "direction": "incoming",
                        "errors": False,
                        "receiver_identifier": edi_user.edi_identification,
                    }
                },
            )
        except Exception as err:
            log_obj._error_log(
                result, f"Failed to list the flows of {self.display_name}: {err}"
            )
            return flow_obj
        messages = answer.get("messages", [])
        # Bounded the way upstream bounds its own duplicate search: a flow
        # older than that window will not come back from the platform anyway,
        # and reading every identifier ever received would grow without end.
        limit_create_date = self._fr_ctc_import_updated_after() - timedelta(90)
        known = {
            x["identifier"]
            for x in flow_obj.sudo().search_read(
                [
                    ("company_id", "=", self.id),
                    ("identifier", "!=", False),
                    ("create_date", ">=", limit_create_date),
                ],
                ["identifier"],
            )
        }
        to_create = []
        for message in messages:
            uuid = message.get("uuid")
            if not uuid:
                continue
            # A self-addressed message -- a company genuinely invoicing itself
            # -- carries a UUID the outgoing flow already holds. Skipping it as
            # a duplicate would drop the vendor bill, and it is exactly how the
            # reception gets tested on a single registered company.
            self_addressed = (
                message.get("sender") and message["sender"] == message.get("receiver")
            )
            if uuid in known and not self_addressed:
                continue
            to_create.append(self._fr_ctc_odoo_prepare_in_flow(message))
        now_dt = fields.Datetime.now()
        flows = flow_obj.sudo().create(to_create) if to_create else flow_obj
        self.sudo().write({"fr_ctc_last_flow_import_datetime": now_dt})
        if "new_count" in result:
            result["new_count"] += len(flows)
        if download_and_process:
            for flow in flows:
                flow._download(session, result)
                if flow.state == "downloaded":
                    flow._process(result)
        return flows
