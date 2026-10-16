# Copyright 2026 Alusage (https://alusage.fr/)
# @author: Nicolas Jeudy <nicolas@alusage.fr>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Apply the new computes to the companies already on the bridge.

    An update does not recompute the existing rows of a field that gains a
    compute or a dependency: without this, a company on the bridge would keep
    the native e-reporting on, and the readable view download, until its
    setting is touched again.
    """
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    companies = env["res.company"].search([("fr_ctc_transport_odoo", "=", True)])
    for fname in (
        "fr_ctc_auto_download_readable_invoice",
        "l10n_fr_f10_enable_reporting",
    ):
        env.add_to_compute(companies._fields[fname], companies)
    env.flush_all()
