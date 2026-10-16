# Copyright 2026 Alusage (https://alusage.fr/)
# @author: Nicolas Jeudy <nicolas@alusage.fr>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import _, fields, models
from odoo.exceptions import UserError


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

    fr_ctc_transport_odoo = fields.Boolean(related="company_id.fr_ctc_transport_odoo")

    def fr_ctc_get_readable_invoice_button(self):
        """Refuse to fetch a readable view for a bill from the Odoo platform.

        Upstream asks SUPER PDP for it, which never saw the flow: its
        identifier is the Odoo platform's. The button is hidden for these
        companies; this guards a call made another way.
        """
        for move in self:
            if move.company_id._fr_ctc_is_pa_odoo():
                raise UserError(
                    _(
                        "The Odoo accredited platform does not provide a readable "
                        "version of vendor bill %s.",
                        move.display_name,
                    )
                )
        return super().fr_ctc_get_readable_invoice_button()

    def fr_ctc_send_invoice_immediately_button(self):
        """Send through the Odoo platform without opening a SUPER PDP session."""
        return super(
            AccountMove, self.with_context(fr_ctc_transport=True)
        ).fr_ctc_send_invoice_immediately_button()
