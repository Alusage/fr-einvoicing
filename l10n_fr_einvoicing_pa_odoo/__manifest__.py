# Copyright 2026 Alusage (https://alusage.fr/)
# @author: Nicolas Jeudy <nicolas@alusage.fr>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "France eInvoicing - Odoo accredited platform",
    "version": "18.0.1.0.0",
    "category": "Accounting",
    "license": "AGPL-3",
    "summary": "Send and receive fr-einvoicing flows through the Odoo accredited platform",
    "author": "Alusage",
    "maintainers": ["njeudy"],
    "website": "https://github.com/Alusage/fr-einvoicing",
    # The generation, the directory and the tracking models stay Akretion's;
    # only the two network calls are routed to the native Odoo proxy, whose
    # registration and KYC stay l10n_fr_pdp's.
    "depends": [
        "l10n_fr_einvoicing",
        "l10n_fr_pdp",
    ],
    "installable": True,
}
