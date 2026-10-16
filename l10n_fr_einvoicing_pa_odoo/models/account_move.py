# Copyright 2026 Alusage (https://alusage.fr/)
# @author: Nicolas Jeudy <nicolas@alusage.fr>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, models


class AccountMove(models.Model):
    _inherit = "account.move"

    def _compute_pdp_can_send_response(self):
        """Keep the native lifecycle answer out of the way of Akretion's.

        On posting a purchase invoice, the native module answers the platform
        by itself. Akretion's chain raises its own lifecycle events, so both
        running would acknowledge the same invoice twice -- outwards, to the
        platform.

        This is a migration guard more than a daily one: the native answer
        needs `peppol_message_uuid` and `peppol_is_sent`, which only the
        native send writes, so an invoice sent through this bridge never gets
        them. An invoice sent natively *before* a company moved over does.
        """
        super()._compute_pdp_can_send_response()
        for move in self:
            if move.company_id._fr_ctc_is_pa_odoo():
                move.pdp_can_send_response = False

    @api.depends("fr_einvoicing_flow_id")
    def _compute_fr_einvoicing_show_readable_invoice_button(self):
        """Hide the readable view of a vendor bill received from the Odoo PA.

        Upstream fetches it from SUPER PDP, which never saw that flow: the
        identifier is the Odoo platform's, so asking for it there can only
        fail. The Odoo platform has no readable view to offer instead.
        """
        res = super()._compute_fr_einvoicing_show_readable_invoice_button()
        for move in self:
            if move.company_id._fr_ctc_is_pa_odoo():
                move.fr_einvoicing_show_readable_invoice_button = False
        return res
