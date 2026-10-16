# Copyright 2026 Alusage (https://alusage.fr/)
# @author: Nicolas Jeudy <nicolas@alusage.fr>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Bring the companies already on the bridge in line with the setting.

    An update does not recompute the existing rows of a field whose compute
    gains a dependency, and does not replay a write: without this, a company
    on the bridge would keep the native e-reporting on, and the readable view
    download from SUPER PDP, until its setting is touched again.
    """
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    companies = env["res.company"].search([("fr_ctc_transport_odoo", "=", True)])
    companies.write(companies._fr_ctc_odoo_transport_vals())
    env.add_to_compute(companies._fields["l10n_fr_f10_enable_reporting"], companies)
    env.flush_all()
