# Copyright 2026 Alusage (https://alusage.fr/)
# @author: Nicolas Jeudy <nicolas@alusage.fr>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

logger = logging.getLogger(__name__)

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

    # The accredited platform setting keeps answering for the directory, which
    # the Odoo platform does not offer. This one moves the whole transport --
    # invoices, vendor bills, statuses, lifecycles and e-reporting -- so a
    # company can stay on SUPER PDP for its directory lines alone.
    fr_ctc_transport_odoo = fields.Boolean(
        string="Send and receive through the Odoo accredited platform",
        help="Send the outgoing flows, receive the incoming ones and read their "
        "status through the Odoo accredited platform, with the registration made "
        "by the native French e-invoicing module. The directory lookups keep "
        "using the accredited platform selected above and its credentials.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("fr_ctc_transport_odoo"):
                vals.update(self._fr_ctc_odoo_transport_vals())
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("fr_ctc_transport_odoo"):
            vals = dict(vals, **self._fr_ctc_odoo_transport_vals())
        return super().write(vals)

    @api.model
    def _fr_ctc_odoo_transport_vals(self):
        """Return what checking the setting turns off along with it.

        Upstream downloads the readable view of a vendor bill from SUPER PDP,
        which never sees the flows of a company on the Odoo platform. Written
        rather than computed: the upstream default would win over a compute
        on a company created with the setting already checked.
        """
        return {"fr_ctc_auto_download_readable_invoice": False}

    @api.depends("fr_ctc_transport_odoo")
    def _compute_l10n_fr_f10_enable_reporting(self):
        """Keep the native e-reporting off for a company on this bridge.

        Its flux 10 comes from Akretion's e-reporting and travels through the
        bridge. The native one switches itself on as soon as the company
        reports to the PPF -- which an invoice sent through the bridge needs --
        and both would then report the same period. The companies are taken
        out before the native compute runs, which would otherwise already
        have recomputed their invoices for flux 10.
        """
        bridged = self.filtered(lambda c: c.fr_ctc_transport_odoo)
        bridged.l10n_fr_f10_enable_reporting = False
        return super(ResCompany, self - bridged)._compute_l10n_fr_f10_enable_reporting()

    def _fr_ctc_is_pa_odoo(self):
        """Return True when this company routes its flows through the Odoo PA.

        Every override of this module is guarded by this method rather than by
        the environment: a database may hold companies on SUPER PDP, companies
        on the Odoo PA, and companies using the native module on its own.
        """
        self.ensure_one()
        return self.fr_ctc_transport_odoo

    def _fr_ctc_get_session(self):
        """Hand out the proxy user when the caller is about to transport.

        Two platforms are at play, and upstream hands one session to
        everything. The transport entry points -- the crons, the send, import,
        download and status buttons -- set `fr_ctc_transport` in the context:
        for them, a company on the Odoo platform gets its proxy user, and no
        SUPER PDP session is opened, so an expired token or a SUPER PDP outage
        does not hold its flows back. Every other caller -- the directory sync,
        the API test -- still gets SUPER PDP, which is the safe default for a
        caller this module does not know about: it queries an API the Odoo
        platform does not have.
        """
        self.ensure_one()
        if self.env.context.get("fr_ctc_transport") and self._fr_ctc_is_pa_odoo():
            return self._fr_ctc_get_transport_session()
        return super()._fr_ctc_get_session()

    def _fr_ctc_get_transport_session(self):
        """Return what the flows travel with: the native proxy user, if any.

        The transport methods of this module call it themselves, whatever
        session their caller passed them, so a transport entry point this
        module does not wrap still reaches the right platform. The Odoo
        platform authenticates each request by signing it with the proxy
        user's key, so there is no OAuth session to open here.
        """
        self.ensure_one()
        if not self._fr_ctc_is_pa_odoo():
            return self.with_context(fr_ctc_transport=False)._fr_ctc_get_session()
        edi_user = self.account_peppol_edi_user
        if not edi_user:
            raise UserError(
                _(
                    "Company '%s' is set to send and receive through the Odoo "
                    "accredited platform, but it is not registered on it yet.",
                    self.display_name,
                )
            )
        return edi_user

    def fr_ctc_run_import_log(self, origin):
        return super(
            ResCompany, self.with_context(fr_ctc_transport=True)
        ).fr_ctc_run_import_log(origin)

    def _fr_ctc_test_api(self):
        # Tests the SUPER PDP connection, which the directory relies on.
        return super(
            ResCompany, self.with_context(fr_ctc_transport=False)
        )._fr_ctc_test_api()

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
        """List the incoming documents on the Odoo platform, then process them.

        Nothing is acknowledged on listing or on download. Acknowledging a
        message drops it from the platform for good, so it only happens once
        the flow reports the document actually landed -- otherwise a failing
        import would lose it with no way to ask for it again.
        """
        self.ensure_one()
        if not self._fr_ctc_is_pa_odoo():
            return super()._fr_ctc_run_import(
                session, result, download_and_process=download_and_process
            )
        log_obj = self.env["fr.einvoicing.log"]
        flow_obj = self.env["fr.einvoicing.flow"]
        try:
            # The session the caller passed is the SUPER PDP one.
            edi_user = self._fr_ctc_get_transport_session()
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
            vals = self._fr_ctc_odoo_prepare_in_flow(message)
            if vals["type"] == "SupplierInvoice" and not self.fr_ctc_get_in_invoice:
                # Left on the platform, unacknowledged, as upstream leaves the
                # vendor bills it does not ask for.
                continue
            # A self-addressed message -- a company genuinely invoicing itself
            # -- carries a UUID the outgoing flow already holds. Skipping it as
            # a duplicate would drop the vendor bill, and it is exactly how the
            # reception gets tested on a single registered company.
            self_addressed = message.get("sender") and message["sender"] == message.get(
                "receiver"
            )
            if uuid in known and not self_addressed:
                continue
            to_create.append(vals)
        now_dt = fields.Datetime.now()
        flows = flow_obj.sudo().create(to_create) if to_create else flow_obj
        self.sudo().write({"fr_ctc_last_flow_import_datetime": now_dt})
        if "new_count" in result:
            result["new_count"] += len(flows)
        if download_and_process:
            for flow in flows:
                flow._download(edi_user, result)
                if flow.state == "downloaded":
                    # The acknowledgement is not sent from here: `_process`
                    # carries it, so that a flow retried by a later cron run
                    # is acknowledged too.
                    flow._process(result)
        return flows
