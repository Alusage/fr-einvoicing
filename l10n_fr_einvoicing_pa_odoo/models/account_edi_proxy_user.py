# Copyright 2026 Alusage (https://alusage.fr/)
# @author: Nicolas Jeudy <nicolas@alusage.fr>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import models

logger = logging.getLogger(__name__)


class AccountEdiProxyClientUser(models.Model):
    _inherit = "account_edi_proxy_client.user"

    def _fr_ctc_odoo_others(self):
        """Return the users whose company does not go through this bridge.

        The three native crons select their users on the very conditions that
        make the transport usable, so they cannot be disarmed by a setting
        without losing the transport itself. They are narrowed here instead,
        company by company: a database may well hold companies on this bridge
        and companies driven by the native module alone.
        """
        return self.filtered(lambda u: not u.company_id._fr_ctc_is_pa_odoo())

    def _peppol_get_new_documents(self):
        """Leave the incoming documents to Akretion's own import cron.

        Both would otherwise fetch the same messages, and the native one
        creates the invoice itself, which is exactly what this bridge exists
        to route through the OCA import instead.
        """
        return super(
            AccountEdiProxyClientUser, self._fr_ctc_odoo_others()
        )._peppol_get_new_documents()

    def _pdp_get_regulatory_documents(self):
        """Skip the regulatory documents, which the native cron acknowledges.

        Acknowledging drops a message from the platform for good: were this
        left on, it would silently consume answers Akretion's chain never got
        to see.
        """
        return super(
            AccountEdiProxyClientUser, self._fr_ctc_odoo_others()
        )._pdp_get_regulatory_documents()

    def _pdp_send_lifecycles(self):
        """Leave the lifecycle answers to Akretion's events."""
        return super(
            AccountEdiProxyClientUser, self._fr_ctc_odoo_others()
        )._pdp_send_lifecycles()
