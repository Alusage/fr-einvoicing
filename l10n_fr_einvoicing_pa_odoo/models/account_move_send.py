# Copyright 2026 Alusage (https://alusage.fr/)
# @author: Nicolas Jeudy <nicolas@alusage.fr>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models


class AccountMoveSend(models.AbstractModel):
    _inherit = "account.move.send"

    def _is_applicable_to_company(self, method, company):
        """Take the native sending method off the table for these companies.

        Sending is driven by Akretion's flows here, so leaving the native
        method available would let the same invoice go out twice, once from
        each chain -- and the second one would carry the natively generated
        file rather than the one the bridge is meant to send.
        """
        if method == "peppol" and company._fr_ctc_is_pa_odoo():
            return False
        return super()._is_applicable_to_company(method, company)
