# Copyright 2026 Alusage (https://alusage.fr/)
# @author: Nicolas Jeudy <nicolas@alusage.fr>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models


class FrEinvoicingEvent(models.Model):
    _inherit = "fr.einvoicing.event"

    def _auto_process(self):
        """Send a lifecycle event right away, as a transport entry point."""
        return super(
            FrEinvoicingEvent, self.with_context(fr_ctc_transport=True)
        )._auto_process()
