# Copyright 2026 Alusage (https://alusage.fr/)
# @author: Nicolas Jeudy <nicolas@alusage.fr>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import base64
import logging

from odoo import fields, models

logger = logging.getLogger(__name__)

# The Odoo platform addresses a French party as "<EAS>:<endpoint>", where the
# endpoint reads SIREN[_SIRET][_suffix] -- the very grammar of a directory
# line's identifier, so it travels as it is.
FR_EAS = "0225"

# Flow numbers of the French reform: 2 carries an invoice, 10 an e-reporting
# report. The platform reads them from the document itself.
FLOW_NUMBER_INVOICE = 2
FLOW_NUMBER_EREPORTING = 10

# Syntax of an e-reporting flow, as Akretion's e-reporting module sets it.
EREPORTING_SYNTAX = "FRR"

# What the platform calls an incoming document, and what Akretion calls the
# matching flow. A lifecycle answer reaches us under the same channel as an
# invoice, which is why the sorting cannot be skipped.
CDAR_DOCUMENT_TYPE = "CrossDomainAcknowledgementAndResponse"
INVOICE_DOCUMENT_TYPES = ("Invoice", "CreditNote", "Factur-X")


class FrEinvoicingFlow(models.Model):
    _inherit = "fr.einvoicing.flow"

    def _fr_ctc_odoo_receiver(self):
        """Return the "<EAS>:<endpoint>" the Odoo platform routes on.

        The address comes from the directory line the flow already resolved,
        so the routing keeps following Akretion's directory rather than the
        partner's native Peppol fields.
        """
        self.ensure_one()
        move = self.move_id or self.event_id.move_id
        line = move.fr_directory_line_id
        if not line:
            return False
        return f"{FR_EAS}:{line.identifier}"

    def _fr_ctc_odoo_document(self):
        """Build the document the Odoo platform expects for this flow."""
        self.ensure_one()
        company = self.company_id
        document = {
            "filename": self.filename,
            # `file_bin` already holds base64, which is what the platform reads
            # under the `ubl` key -- a name it keeps even for an e-reporting
            # report, which is not UBL.
            "ubl": self.file_bin.decode(),
        }
        if self.syntax == EREPORTING_SYNTAX:
            document["flow_number"] = FLOW_NUMBER_EREPORTING
        else:
            document.update(
                {
                    "flow_number": FLOW_NUMBER_INVOICE,
                    "receiver": self._fr_ctc_odoo_receiver(),
                    "force_peppol_only": not company.l10n_fr_pdp_send_to_ppf,
                }
            )
        return document

    def _send(self, session, result):
        """Hand the flow to the Odoo platform instead of the AFNOR API.

        Akretion calls its own API inline, so routing elsewhere means writing
        this method again rather than extending it: the guards below mirror
        the upstream ones and must be re-read whenever upstream changes. The
        fix belongs upstream, as an extension point around the call itself.
        """
        self.ensure_one()
        if not self.company_id._fr_ctc_is_pa_odoo():
            return super()._send(session, result)
        log_obj = self.env["fr.einvoicing.log"]
        if self.direction != "out":
            logger.info("Flow %s is not outgoing, skipped", self.display_name)
            return
        if self.state != "generated":
            logger.info(
                "Flow %s is in state %s, not generated, skipped",
                self.display_name,
                self.state,
            )
            return
        if not self.file_bin or not self.filename:
            log_obj._warning_log(
                result, f"Flow {self.display_name} has no file to send."
            )
            return
        if self.identifier:
            # Upstream's own guard against sending the same flow twice.
            log_obj._warning_log(
                result,
                f"Flow {self.display_name} already has identifier "
                f"{self.identifier} and was not sent again.",
            )
            return
        document = self._fr_ctc_odoo_document()
        if document.get("flow_number") == FLOW_NUMBER_INVOICE and not document.get(
            "receiver"
        ):
            log_obj._error_log(
                result,
                f"Flow {self.display_name} has no directory line, so the Odoo "
                "platform has no address to route it to.",
            )
            return
        # `session` is the native proxy user, as `_fr_ctc_get_session` returns
        # it for this platform.
        edi_user = session
        try:
            res = edi_user._call_peppol_proxy(
                edi_user._get_peppol_proxy_endpoint("1/send_document"),
                {"documents": [document]},
            )
        except Exception as err:
            log_obj._error_log(
                result, f"Failed to send flow {self.display_name}: {err}"
            )
            # Leave the state at 'generated', as upstream does: the next cron
            # run picks the flow up again.
            self.sudo().write({"odoo_error_details": str(err)})
            return
        identifier = self._fr_ctc_odoo_identifier(res)
        if not identifier:
            log_obj._error_log(
                result,
                f"The Odoo platform accepted flow {self.display_name} without "
                f"returning an identifier. Answer: {res}",
            )
            self.sudo().write({"odoo_error_details": f"No identifier in {res}"})
            return
        now = fields.Datetime.now()
        move = self.move_id or self.event_id.move_id
        self.sudo().write(
            {
                "identifier": identifier,
                "submitted_at": now,
                "updated_at": now,
                "state": "sent",
                "odoo_error_details": False,
                "fr_directory_line_peppol_status": (
                    move.fr_directory_line_id.peppol_status or False
                ),
            }
        )
        log_obj._info_log(result, f"Flow {self.display_name} sent to the Odoo platform.")
        if "updated_count" in result:
            result["updated_count"] += 1
        if self.move_ids:
            self.move_ids.filtered(lambda x: not x.is_move_sent).sudo().write(
                {"is_move_sent": True}
            )

    def _fr_ctc_odoo_identifier(self, res):
        """Read the platform's identifier out of a send answer.

        An invoice answers under `messages`, an e-reporting report under
        `ppf_messages`, with a different key for the identifier itself.
        """
        self.ensure_one()
        messages = res.get("messages") or []
        if messages:
            return messages[0].get("message_uuid")
        ppf_messages = res.get("ppf_messages") or []
        if ppf_messages:
            return ppf_messages[0].get("uuid")
        return False

    def _download(self, session, result):
        """Fetch the incoming document from the Odoo platform.

        The platform hands the document encrypted; decrypting it yields the
        raw bytes upstream's own download produces, so the rest of the chain
        -- `_process`, the CDAR parsing, the OCA import -- is untouched.
        """
        self.ensure_one()
        if not self.company_id._fr_ctc_is_pa_odoo():
            return super()._download(session, result)
        log_obj = self.env["fr.einvoicing.log"]
        if self.direction != "in":
            logger.info("Flow %s is not incoming, skipped", self.display_name)
            return
        if self.state != "created":
            logger.info(
                "Flow %s is in state %s, not created, skipped",
                self.display_name,
                self.state,
            )
            return
        if not self.identifier:
            log_obj._warning_log(
                result, f"Flow {self.display_name} has no identifier to download."
            )
            return
        edi_user = session
        try:
            answer = edi_user._call_peppol_proxy(
                edi_user._get_peppol_proxy_endpoint("1/get_document"),
                {"message_uuids": [self.identifier]},
            )
            content = answer[self.identifier]
            file_bin = edi_user._peppol_get_decoded_document(content)
        except Exception as err:
            log_obj._error_log(
                result, f"Failed to download flow {self.display_name}: {err}"
            )
            return
        self.sudo().write(
            {
                "file_bin": base64.encodebytes(file_bin),
                "filename": (
                    f"{self.identifier}.pdf"
                    if self.syntax == "Factur-X"
                    else f"{self.identifier}.xml"
                ),
                "state": "downloaded",
            }
        )
        if "updated_count" in result:
            result["updated_count"] += 1
