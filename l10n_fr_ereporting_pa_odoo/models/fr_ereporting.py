# Copyright 2026 Alusage (https://alusage.fr/)
# @author: Nicolas Jeudy <nicolas@alusage.fr>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models

# The sender block of a flux 10 (TT-7 to TT-11) names the accredited platform
# that transmits it. These are the values the native module writes for the
# Odoo platform, in l10n_fr_pdp/models/pdp_flow_xml_builder.py
# (_add_report_header): its registration number with the scheme of the
# accredited platforms, its name and its contact address.
ODOO_PLATFORM_SENDER = {
    "TT-7": "0238",
    "TT-8": "2728",
    "TT-9": "PDP_2728",
    "TT-10": "WK",
    "TT-11": "pdp@odoo.com",
}


class FrEreporting(models.Model):
    _inherit = "fr.ereporting"

    def _prepare_common_data_dict(self, identifier):
        """Name the Odoo platform as the sender of the report it carries.

        Upstream names the platform selected on the company, which stays
        SUPER PDP for the directory when the bridge carries the flows.
        """
        data_dict = super()._prepare_common_data_dict(identifier)
        if self.company_id._fr_ctc_is_pa_odoo():
            data_dict.update(ODOO_PLATFORM_SENDER)
        return data_dict
