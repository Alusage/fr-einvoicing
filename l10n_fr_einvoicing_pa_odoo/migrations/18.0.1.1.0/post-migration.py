# Copyright 2026 Alusage (https://alusage.fr/)
# @author: Nicolas Jeudy <nicolas@alusage.fr>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


def migrate(cr, version):
    """Turn the former "odoo" accredited platform into the transport setting.

    The platform selection no longer offers "odoo": the directory stays on
    SUPER PDP and only the transport moves. A company left on the dropped
    value would hold a platform no code answers for.
    """
    if not version:
        return
    cr.execute(
        """
        UPDATE res_company
           SET fr_ctc_transport_odoo = TRUE,
               fr_ctc_accredited_platform = 'superpdp'
         WHERE fr_ctc_accredited_platform = 'odoo'
        """
    )
