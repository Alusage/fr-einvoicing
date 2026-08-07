# Copyright 2026 Sudokeys
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDirectoryCompanyPartner(TransactionCase):
    """A bulk directory import must never mark the company's own partner.

    account.move carries `fr_directory_company_entity_type`, a related on
    `company_id.partner_id.fr_directory_entity_type`, and the stored
    `fr_einvoicing_required` depends on it. Writing that single partner marks
    every move of the company dirty, and the next flush recomputes the whole
    invoice table in one pass — MemoryError on a real database. Batching by
    partner does not help: the company always appears in the directory return,
    since it is registered there itself.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Line = cls.env["fr.directory.line"]
        cls.company = cls.env.company
        cls.company_partner = cls.company.partner_id.commercial_partner_id
        # Cleared in SQL on purpose: writing this field through the ORM would
        # mark every move of the company dirty — the very blow-up under test.
        cls.env.cr.execute(
            "UPDATE res_partner SET fr_directory_entity_type = NULL WHERE id = %s",
            (cls.company_partner.id,),
        )
        cls.env.invalidate_all()
        cls.customer = cls.env["res.partner"].create(
            {"name": "Directory Test Customer", "is_company": True}
        )
        # The setter replays the recompute over the company's whole invoice
        # history. Point it at a company with no moves, so the test measures the
        # behaviour and not the size of whatever database it runs against.
        cls.empty_company = cls._make_empty_company()

    @classmethod
    def _make_empty_company(cls):
        """A company with no moves, or None when this database forbids one.

        Client databases add their own NOT NULL columns on res_company, which a
        bare create() cannot satisfy. Skipping beats hardcoding a field that
        only exists on one customer's database.
        """
        try:
            with cls.env.cr.savepoint():
                return cls.env["res.company"].create({"name": "Directory Test Co"})
        except Exception:
            return None

    def test_company_partner_excluded_from_bulk_marking(self):
        """The company partner is skipped; an ordinary partner is still marked."""
        self.Line._directory_mark_partners_registered(
            self.company_partner | self.customer
        )
        self.assertFalse(
            self.company_partner.fr_directory_entity_type,
            "The company's own partner must not be marked by a bulk import: it "
            "dirties fr_einvoicing_required on every move of the company.",
        )
        self.assertEqual(
            self.customer.fr_directory_entity_type,
            "private",
            "Ordinary partners must still be marked as before.",
        )

    def test_company_partners_helper(self):
        """The helper lists company partners and only those."""
        partners = self.Line._directory_company_partners()
        self.assertIn(self.company_partner, partners)
        self.assertNotIn(self.customer, partners)

    def test_import_of_a_return_containing_the_company(self):
        """The real failing case: a return that includes the company's own SIREN.

        Reproduces adresses_de_facturation1.csv, where the Olinn IT SIREN
        appeared nine times and blew up the import.
        """
        siren = self.company_partner._get_siren(raise_if_none=False)
        if not siren:
            self.skipTest("The company partner has no SIREN in this database.")
        content = (
            "SIREN,Présent dans l'annuaire de la facturation électronique,"
            "Plateforme agréée rattachée,Adresse de facturation,"
            "Adresse de facturation active\n"
            f"{siren},Oui,Non,{siren},Oui\n"
            f"{siren},Oui,Oui,{siren}_CONSO,Non\n"
        )
        self.Line._directory_import_csv(content.encode("utf-8"))
        self.assertFalse(
            self.company_partner.fr_directory_entity_type,
            "Importing a return that contains the company must not mark it.",
        )

    def test_set_company_entity_type_applies_the_value(self):
        """The one-off setter does what the import deliberately refuses to do."""
        if not self.empty_company:
            self.skipTest("This database forbids creating a bare res.company.")
        recomputed = self.Line._directory_set_company_entity_type(
            self.empty_company, "private"
        )
        self.assertEqual(
            self.empty_company.partner_id.fr_directory_entity_type, "private"
        )
        self.assertEqual(recomputed, 0, "A new company has no move to recompute.")

    def test_set_company_entity_type_is_idempotent(self):
        """Re-setting the same value must not start a recompute pass.

        Checked on the real company, whose value is planted in SQL so the test
        itself never queues a recompute over its invoice history.
        """
        self.env.cr.execute(
            "UPDATE res_partner SET fr_directory_entity_type = 'private' "
            "WHERE id = %s",
            (self.company_partner.id,),
        )
        self.env.invalidate_all()
        self.assertEqual(
            self.Line._directory_set_company_entity_type(self.company, "private"),
            0,
        )
