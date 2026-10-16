# Copyright 2026 Alusage (https://alusage.fr/)
# @author: Nicolas Jeudy <nicolas@alusage.fr>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    # The directory stays on SUPER PDP whatever carries the flows. A sync may
    # run in the middle of a transport -- posting an invoice syncs its
    # customer first -- so the transport flag is cleared here rather than
    # trusted to be absent.

    def _fr_directory_sync_logs(self, company, origin):
        return super(
            ResPartner, self.with_context(fr_ctc_transport=False)
        )._fr_directory_sync_logs(company, origin)

    @api.model
    def _fr_directory_sync_cron(self):
        return super(
            ResPartner, self.with_context(fr_ctc_transport=False)
        )._fr_directory_sync_cron()
