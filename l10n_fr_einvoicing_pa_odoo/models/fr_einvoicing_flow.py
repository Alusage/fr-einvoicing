# Copyright 2026 Alusage (https://alusage.fr/)
# @author: Nicolas Jeudy <nicolas@alusage.fr>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import base64
import logging

from odoo import api, fields, models

logger = logging.getLogger(__name__)

# Value of `fr_ctc_accredited_platform` this module answers for. Spelled out
# here rather than imported from the company, so each file reads on its own.
PLATFORM = "odoo"

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

# What the platform answers about a sent message, and what it means for the
# flow. Its other states -- ready, to_send, processing -- mean the message is
# still on its way: the flow stays as it is and the next run asks again.
FLOW_STATE_BY_MESSAGE_STATE = {"done": "done", "error": "error"}

# The platform reports "request not ready" with this code. It is not a
# failure: reading it as one would mark a flow in error while it travels.
MESSAGE_NOT_READY_CODE = 702


class FrEinvoicingFlow(models.Model):
    _inherit = "fr.einvoicing.flow"

    @api.model
    def _cron_companies(self):
        """Let a company reach the crons without an authentication method.

        Upstream requires one, which is right for the AFNOR API: without
        OAuth credentials there is nothing to open a session with. The Odoo
        platform signs each request with the proxy user's key instead, so a
        company on it never has one -- and would silently be skipped by both
        crons, neither sending nor importing anything.
        """
        return super()._cron_companies() | (
            self.env["res.company"]
            .sudo()
            .search(
                [
                    ("fr_ctc_accredited_platform", "=", PLATFORM),
                    ("partner_id.fr_directory_entity_type", "=", "private"),
                ]
            )
        )

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

    def _update_status(self, session, result):
        """Ask the Odoo platform what became of a sent flow.

        Nothing is acknowledged here, unlike the native status cron: an
        acknowledgement drops the message from the platform for good, and a
        status reading is no reason to give up the right to read it again.
        """
        self.ensure_one()
        if not self.company_id._fr_ctc_is_pa_odoo():
            return super()._update_status(session, result)
        log_obj = self.env["fr.einvoicing.log"]
        if self.direction != "out" or self.state != "sent":
            return
        if not self.identifier:
            log_obj._warning_log(
                result, f"Flow {self.display_name} has no identifier to ask about."
            )
            return
        edi_user = session
        try:
            answer = edi_user._call_peppol_proxy(
                edi_user._get_peppol_proxy_endpoint("1/get_document"),
                {"message_uuids": [self.identifier]},
            )
            content = answer[self.identifier]
        except Exception as err:
            log_obj._error_log(
                result,
                f"Failed to read the status of flow {self.display_name}: {err}",
            )
            self.sudo().write({"odoo_error_details": str(err)})
            return
        error = content.get("error")
        if error:
            if error.get("code") == MESSAGE_NOT_READY_CODE:
                # Still travelling: ask again on the next run.
                return
            self.sudo().write(
                {"state": "error", "ap_error_details": str(error)}
            )
            log_obj._error_log(
                result, f"The platform reports an error on flow {self.display_name}."
            )
            return
        state = FLOW_STATE_BY_MESSAGE_STATE.get(content.get("state"))
        if not state:
            return
        self.sudo().write(
            {
                "state": state,
                "updated_at": fields.Datetime.now(),
                "odoo_error_details": False,
            }
        )
        log_obj._info_log(result, f"Flow {self.display_name} is now {state}.")
        if "updated_count" in result:
            result["updated_count"] += 1
