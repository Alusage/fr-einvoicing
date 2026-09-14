# Copyright 2026 Alusage (https://alusage.fr/)
# @author: Nicolas Jeudy <nicolas@alusage.fr>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import _, models
from odoo.exceptions import UserError

logger = logging.getLogger(__name__)

PLATFORM = "odoo"


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
