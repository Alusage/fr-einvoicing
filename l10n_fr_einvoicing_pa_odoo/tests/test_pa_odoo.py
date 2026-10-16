# Copyright 2026 Alusage (https://alusage.fr/)
# @author: Nicolas Jeudy <nicolas@alusage.fr>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import base64
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import file_open, mute_logger

# Upstream logs every flow error at ERROR level, which the test runner would
# count as a failure: the scenarios expecting one mute it.
FLOW_LOGGER = "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_log"

# Stands for the OAuth session upstream opens on SUPER PDP. Nothing may use it
# to reach the Odoo platform, and nothing on the Odoo side may replace it for
# the directory.
SUPERPDP_SESSION = object()

UUID_IN = "11111111-1111-1111-1111-111111111111"
UUID_OUT = "22222222-2222-2222-2222-222222222222"


@tagged("post_install", "-at_install")
class TestPaOdoo(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env["res.company"].create(
            {
                "name": "Test PA Odoo",
                "country_id": cls.env.ref("base.fr").id,
                "fr_ctc_transport_odoo": True,
                "fr_ctc_event_auto_send_in_hand": False,
                "currency_id": cls.env.ref("base.EUR").id,
            }
        )
        cls.other_company = cls.env["res.company"].create(
            {
                "name": "Test SUPER PDP",
                "country_id": cls.env.ref("base.fr").id,
            }
        )
        private_key = cls.env["certificate.key"].create(
            {
                "name": "Test key PA Odoo",
                "content": base64.b64encode(
                    file_open(
                        "l10n_fr_pdp/tests/test_files/assets/private_key.pem", "rb"
                    ).read()
                ),
            }
        )
        cls.edi_user = cls.env["account_edi_proxy_client.user"].create(
            {
                "id_client": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                "proxy_type": "pdp",
                "edi_mode": "test",
                "edi_identification": "0225:123456782_12345678200015",
                "private_key_id": private_key.id,
                "company_id": cls.company.id,
            }
        )

    def setUp(self):
        super().setUp()
        self.calls = []
        # What the fake platform answers, by endpoint.
        self.answers = {}
        test = self

        def fake_call_peppol_proxy(edi_user, endpoint, params=None):
            test.calls.append((edi_user, endpoint, params))
            # "/api/pdp/1/ack" is answered under "1/ack".
            answer = test.answers.get("/".join(endpoint.rsplit("/", 2)[-2:]))
            if isinstance(answer, Exception):
                raise answer
            return answer if answer is not None else {}

        proxy_user_cls = type(self.env["account_edi_proxy_client.user"])
        company_cls = type(self.env["res.company"])
        self.startPatcher(
            patch.object(proxy_user_cls, "_call_peppol_proxy", fake_call_peppol_proxy)
        )
        self.startPatcher(
            patch.object(
                proxy_user_cls,
                "_peppol_get_decoded_document",
                lambda edi_user, content: b"<Invoice/>",
            )
        )
        # Upstream's session opening is replaced below the company method, so
        # that the bridge's own override of it is what the tests exercise.
        self.superpdp_sessions = []

        def fake_get_session(*args, **kwargs):
            test.superpdp_sessions.append(args)
            return SUPERPDP_SESSION

        self.startPatcher(
            patch(
                "odoo.addons.l10n_fr_einvoicing.models.res_company.get_session",
                fake_get_session,
            )
        )
        self.startPatcher(
            patch.object(
                company_cls, "_fr_ctc_credentials", lambda company: ("id", "secret")
            )
        )
        # The outgoing cron waits a few seconds before reading the statuses.
        self.startPatcher(
            patch("odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow.time.sleep")
        )

    def _result(self):
        return {"logs": [], "new_count": 0, "updated_count": 0}

    def _endpoints(self):
        return [endpoint.rsplit("/", 1)[-1] for _user, endpoint, _params in self.calls]

    def _out_flow(self, company=None, **vals):
        values = {
            "company_id": (company or self.company).id,
            "direction": "out",
            "state": "generated",
            "syntax": "FRR",
            "file_bin": base64.b64encode(b"<Report/>"),
            "filename": "report.xml",
        }
        values.update(vals)
        return self.env["fr.einvoicing.flow"].create(values)

    # The switch

    def test_switch_follows_the_setting(self):
        self.assertTrue(self.company._fr_ctc_is_pa_odoo())
        self.assertFalse(self.other_company._fr_ctc_is_pa_odoo())
        self.assertEqual(self.company._fr_ctc_get_transport_session(), self.edi_user)
        self.assertIs(
            self.other_company._fr_ctc_get_transport_session(), SUPERPDP_SESSION
        )
        self.company.fr_ctc_transport_odoo = False
        self.assertFalse(self.company._fr_ctc_is_pa_odoo())
        self.assertIs(self.company._fr_ctc_get_transport_session(), SUPERPDP_SESSION)

    def test_accredited_platform_stays_superpdp(self):
        self.assertEqual(self.company.fr_ctc_accredited_platform, "superpdp")
        selection = dict(
            self.env["res.company"]._fields["fr_ctc_accredited_platform"].selection
        )
        self.assertNotIn("odoo", selection)

    def test_settings_expose_the_setting(self):
        settings = self.env["res.config.settings"].with_company(self.company).create({})
        self.assertTrue(settings.fr_ctc_transport_odoo)

    def test_unregistered_company_cannot_transport(self):
        self.edi_user.unlink()
        with self.assertRaises(UserError):
            self.company._fr_ctc_get_transport_session()

    # The directory stays on SUPER PDP

    def test_session_stays_superpdp_outside_transport(self):
        """The session the directory and the lookups use is never the proxy."""
        self.assertIs(self.company._fr_ctc_get_session(), SUPERPDP_SESSION)

    def test_transport_gets_proxy_without_superpdp(self):
        company = self.company.with_context(fr_ctc_transport=True)
        self.assertEqual(company._fr_ctc_get_session(), self.edi_user)
        self.assertFalse(self.superpdp_sessions)
        other = self.other_company.with_context(fr_ctc_transport=True)
        self.assertIs(other._fr_ctc_get_session(), SUPERPDP_SESSION)

    def test_directory_sync_in_transport_uses_superpdp(self):
        """A sync started during a transport still talks to SUPER PDP."""
        partner = self.env["res.partner"].create(
            {"name": "Directory partner", "is_company": True}
        )
        seen = []
        partner_cls = type(self.env["res.partner"])
        with patch.object(
            partner_cls,
            "_fr_directory_sync",
            lambda partner, session, result: seen.append(session),
        ):
            partner.with_context(fr_ctc_transport=True)._fr_directory_sync_logs(
                self.company, "Test"
            )
        self.assertEqual(seen, [SUPERPDP_SESSION])

    def test_directory_sync_uses_superpdp_session(self):
        partner = self.env["res.partner"].create(
            {"name": "Directory partner", "is_company": True}
        )
        seen = []

        def fake_sync(partner, session, result):
            seen.append(session)

        partner_cls = type(self.env["res.partner"])
        with patch.object(partner_cls, "_fr_directory_sync", fake_sync):
            partner._fr_directory_sync_logs(self.company, "Test")
        self.assertEqual(seen, [SUPERPDP_SESSION])
        self.assertFalse(self.calls)

    # Sending

    def test_send_ereporting_flow_through_proxy(self):
        flow = self._out_flow()
        self.answers["1/send_document"] = {"ppf_messages": [{"uuid": UUID_OUT}]}
        result = self._result()
        flow._send(SUPERPDP_SESSION, result)
        self.assertEqual(self._endpoints(), ["send_document"])
        edi_user, endpoint, params = self.calls[0]
        self.assertEqual(edi_user, self.edi_user)
        self.assertEqual(endpoint, "/api/pdp/1/send_document")
        self.assertEqual(params["documents"][0]["flow_number"], 10)
        self.assertEqual(flow.state, "sent")
        self.assertEqual(flow.identifier, UUID_OUT)

    def test_send_invoice_flow_carries_receiver(self):
        flow = self._out_flow(syntax="UBL", filename="invoice.xml")
        self.answers["1/send_document"] = {"messages": [{"message_uuid": UUID_OUT}]}
        flow_cls = type(self.env["fr.einvoicing.flow"])
        with patch.object(
            flow_cls, "_fr_ctc_odoo_receiver", lambda flow: "0225:315143296_94565"
        ):
            flow._send(SUPERPDP_SESSION, self._result())
        document = self.calls[0][2]["documents"][0]
        self.assertEqual(document["flow_number"], 2)
        self.assertEqual(document["receiver"], "0225:315143296_94565")
        self.assertEqual(flow.state, "sent")

    @mute_logger(FLOW_LOGGER)
    def test_send_without_registration_logs_error(self):
        self.edi_user.unlink()
        flow = self._out_flow()
        result = self._result()
        flow._send(SUPERPDP_SESSION, result)
        self.assertFalse(self.calls)
        self.assertEqual(flow.state, "generated")
        self.assertIn("error", [log_type for log_type, _msg in result["logs"]])

    # Status

    def test_status_done_is_acknowledged(self):
        flow = self._out_flow(state="sent", identifier=UUID_OUT)
        self.answers["1/get_document"] = {UUID_OUT: {"state": "done"}}
        flow._update_status(SUPERPDP_SESSION, self._result())
        self.assertEqual(flow.state, "done")
        self.assertEqual(self._endpoints(), ["get_document", "ack"])
        self.assertEqual(self.calls[1][2], {"message_uuids": [UUID_OUT]})

    def test_status_not_ready_is_not_acknowledged(self):
        flow = self._out_flow(state="sent", identifier=UUID_OUT)
        self.answers["1/get_document"] = {UUID_OUT: {"error": {"code": 702}}}
        flow._update_status(SUPERPDP_SESSION, self._result())
        self.assertEqual(flow.state, "sent")
        self.assertEqual(self._endpoints(), ["get_document"])

    # Reception and acknowledgement

    def _incoming_messages(self):
        self.answers["1/get_all_documents"] = {
            "messages": [
                {
                    "uuid": UUID_IN,
                    "document_type": "Invoice",
                    "sender": "0225:813487899",
                    "receiver": "0225:123456782_12345678200015",
                }
            ]
        }
        self.answers["1/get_document"] = {
            UUID_IN: {"enc_key": "key", "document": "doc"}
        }

    def test_import_acknowledges_once_landed(self):
        self._incoming_messages()
        flow_cls = type(self.env["fr.einvoicing.flow"])
        with patch.object(
            flow_cls, "_import_supplier_invoice", lambda flow, result: (True, {})
        ):
            flows = self.company._fr_ctc_run_import(SUPERPDP_SESSION, self._result())
        self.assertEqual(len(flows), 1)
        self.assertEqual(flows.identifier, UUID_IN)
        self.assertEqual(flows.type, "SupplierInvoice")
        self.assertEqual(flows.syntax, "UBL")
        self.assertEqual(flows.state, "done")
        self.assertEqual(
            self._endpoints(), ["get_all_documents", "get_document", "ack"]
        )
        for edi_user, _endpoint, _params in self.calls:
            self.assertEqual(edi_user, self.edi_user)
        self.assertEqual(self.calls[2][2], {"message_uuids": [UUID_IN]})

    def test_failed_import_is_not_acknowledged(self):
        self._incoming_messages()
        flow_cls = type(self.env["fr.einvoicing.flow"])
        with patch.object(
            flow_cls, "_import_supplier_invoice", lambda flow, result: (False, {})
        ):
            flows = self.company._fr_ctc_run_import(SUPERPDP_SESSION, self._result())
        self.assertEqual(flows.state, "error")
        self.assertEqual(self._endpoints(), ["get_all_documents", "get_document"])

    def test_retried_flow_is_acknowledged(self):
        """A flow left downloaded by an earlier run is acknowledged on success."""
        flow = self.env["fr.einvoicing.flow"].create(
            {
                "company_id": self.company.id,
                "direction": "in",
                "type": "SupplierInvoice",
                "syntax": "UBL",
                "identifier": UUID_IN,
                "state": "downloaded",
                "file_bin": base64.b64encode(b"<Invoice/>"),
                "filename": f"{UUID_IN}.xml",
            }
        )
        flow_cls = type(self.env["fr.einvoicing.flow"])
        with patch.object(
            flow_cls, "_import_supplier_invoice", lambda f, r: (True, {})
        ):
            flow._process(self._result())
        self.assertEqual(flow.state, "done")
        self.assertEqual(self._endpoints(), ["ack"])

    # A company without the setting is left alone

    @mute_logger(FLOW_LOGGER)
    def test_company_without_setting_keeps_superpdp_transport(self):
        # Upstream also wants a processing rule before it sends anything.
        flow = self._out_flow(company=self.other_company, processing_rule="B2C")
        seen = []

        def fake_send_flow_parsed(session, *args, **kwargs):
            seen.append(session)
            raise RuntimeError("SUPER PDP reached")

        with patch(
            "odoo.addons.l10n_fr_einvoicing.models.fr_einvoicing_flow."
            "send_flow_parsed",
            fake_send_flow_parsed,
        ):
            flow._send(SUPERPDP_SESSION, self._result())
        self.assertEqual(seen, [SUPERPDP_SESSION])
        self.assertFalse(self.calls)

    def test_native_chain_only_for_companies_without_setting(self):
        self.assertFalse(self.edi_user._fr_ctc_odoo_others())
        self.company.fr_ctc_transport_odoo = False
        self.assertEqual(self.edi_user._fr_ctc_odoo_others(), self.edi_user)

    def test_native_send_method_withdrawn(self):
        send = self.env["account.move.send"]
        self.assertFalse(send._is_applicable_to_company("peppol", self.company))

    def test_cron_sees_company_without_auth_method(self):
        self.company.partner_id.write(
            {
                "fr_directory_entity_type": "private",
                "fr_directory_last_sync_date": fields.Date.today(),
            }
        )
        self.assertFalse(self.company.fr_ctc_auth_method)
        self.assertIn(self.company, self.env["fr.einvoicing.flow"]._cron_companies())

    # The crons carry everything through the Odoo platform

    def _only_our_company(self):
        flow_cls = type(self.env["fr.einvoicing.flow"])
        # Kept in the cron's environment, as upstream's search would be.
        return patch.object(
            flow_cls,
            "_cron_companies",
            lambda flow: self.company.with_env(flow.env),
        )

    def test_out_cron_does_not_open_superpdp_session(self):
        flow = self._out_flow()
        self.answers["1/send_document"] = {"ppf_messages": [{"uuid": UUID_OUT}]}
        self.answers["1/get_document"] = {UUID_OUT: {"error": {"code": 702}}}
        with self._only_our_company():
            self.env["fr.einvoicing.flow"]._out_cron()
        self.assertFalse(self.superpdp_sessions)
        self.assertEqual(flow.state, "sent")
        self.assertEqual(self._endpoints(), ["send_document", "get_document"])

    def test_in_cron_does_not_open_superpdp_session(self):
        self._incoming_messages()
        flow_cls = type(self.env["fr.einvoicing.flow"])
        with (
            self._only_our_company(),
            patch.object(
                flow_cls, "_import_supplier_invoice", lambda flow, result: (True, {})
            ),
        ):
            self.env["fr.einvoicing.flow"]._in_cron()
        self.assertFalse(self.superpdp_sessions)
        self.assertEqual(
            self._endpoints(), ["get_all_documents", "get_document", "ack"]
        )

    def test_vendor_bills_not_fetched_when_disabled(self):
        self.company.fr_ctc_get_in_invoice = False
        self._incoming_messages()
        flows = self.company._fr_ctc_run_import(SUPERPDP_SESSION, self._result())
        self.assertFalse(flows)
        self.assertEqual(self._endpoints(), ["get_all_documents"])

    def test_lifecycle_still_fetched_when_bills_disabled(self):
        self.company.fr_ctc_get_in_invoice = False
        self.answers["1/get_all_documents"] = {
            "messages": [
                {
                    "uuid": UUID_IN,
                    "document_type": "CrossDomainAcknowledgementAndResponse",
                }
            ]
        }
        flows = self.company._fr_ctc_run_import(
            SUPERPDP_SESSION, self._result(), download_and_process=False
        )
        self.assertEqual(flows.type, "CustomerInvoiceLC")
        self.assertEqual(flows.syntax, "CDAR")

    # Nothing else talks to SUPER PDP about the flows

    def test_native_ereporting_off(self):
        self.company.l10n_fr_pdp_send_to_ppf = True
        self.assertFalse(self.company.l10n_fr_f10_enable_reporting)

    def test_readable_view_not_fetched(self):
        self.assertFalse(self.company.fr_ctc_auto_download_readable_invoice)
        self.assertTrue(self.other_company.fr_ctc_auto_download_readable_invoice)
        self.other_company.fr_ctc_transport_odoo = True
        self.assertFalse(self.other_company.fr_ctc_auto_download_readable_invoice)
        move = self.env["account.move"].new({"company_id": self.company.id})
        with self.assertRaises(UserError):
            move.fr_ctc_get_readable_invoice_button()
