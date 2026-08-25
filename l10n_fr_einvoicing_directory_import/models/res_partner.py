# Copyright 2026 Sudokeys
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import models


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _default_fr_directory_line(self):
        """Return the directory line to use as the partner's default one (BT-49).

        Base rule: the partner's only line, when it has exactly one. An empty
        recordset means "no obvious choice" and leaves the manual selector
        untouched.

        A method of its own on purpose: which line addresses a company is a
        business decision that varies from one installation to the next (per
        establishment SIRET, per routing code, per subsidiary), so it is meant
        to be overridden rather than patched into the CSV import.
        """
        self.ensure_one()
        # fr_directory_line_ids leaves out disabled lines: the One2many is
        # filtered on `active`, itself computed from the state.
        lines = self.fr_directory_line_ids
        if len(lines) == 1:
            return lines
        return self.env["fr.directory.line"].browse()
