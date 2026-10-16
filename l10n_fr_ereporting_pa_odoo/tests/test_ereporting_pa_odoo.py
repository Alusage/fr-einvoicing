# Copyright 2026 Alusage (https://alusage.fr/)
# @author: Nicolas Jeudy <nicolas@alusage.fr>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestEreportingPaOdoo(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env["res.company"].create(
            {
                "name": "Test e-reporting PA Odoo",
                "country_id": cls.env.ref("base.fr").id,
                "fr_ctc_transport_odoo": True,
            }
        )

    def _sender(self):
        report = self.env["fr.ereporting"].new(
            {
                "company_id": self.company.id,
                "type": "out_transaction",
                "transmission_type": "initial",
                # A transaction report starts on day 1, 11 or 21.
                "start_date": fields.Date.today().replace(day=1),
            }
        )
        partner_cls = type(self.env["res.partner"])
        with patch.object(
            partner_cls, "_get_siren", lambda partner, raise_if_none=False: "919891770"
        ):
            data_dict = report._prepare_common_data_dict("TEST-1")
        return {key: data_dict[key] for key in ("TT-7", "TT-8", "TT-9", "TT-11")}

    def test_sender_is_the_odoo_platform(self):
        self.assertEqual(
            self._sender(),
            {
                "TT-7": "0238",
                "TT-8": "2728",
                "TT-9": "PDP_2728",
                "TT-11": "pdp@odoo.com",
            },
        )

    def test_sender_unchanged_without_the_setting(self):
        self.company.fr_ctc_transport_odoo = False
        sender = self._sender()
        self.assertEqual(sender["TT-9"], "SUPER PDP")
        self.assertEqual(sender["TT-8"], "4242")
