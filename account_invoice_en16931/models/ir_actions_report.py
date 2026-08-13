# Copyright 2016-2026 Akretion France (http://www.akretion.com)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from io import BytesIO

from odoo import api, models


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    @api.model
    def _get_en16931_invoice_reports(self):
        """Report actions rendering the human-readable customer invoice.

        Resolved through the XML IDs of the actions, never through their
        report_name: report_name is a plain field, and repointing the standard
        invoice action to a custom QWeb template is a very common
        customisation. When that happens, the standard report_name literals
        used by account (_is_invoice_report) no longer match anything, and
        env.ref() on them returns the ir.ui.view of the same name.
        """
        reports = self.browse()
        for xmlid in (
            "account.account_invoices",
            "account.account_invoices_without_payment",
        ):
            reports |= self.env.ref(xmlid, raise_if_not_found=False) or self.browse()
        return reports

    def _is_en16931_invoice_report(self):
        """15.0: the report is self, so there is nothing to resolve.

        The report hooks take a report_ref and account exposes
        _is_invoice_report() only from 16.0 on. Here _post_pdf() runs on the
        report record itself, which account compares the same way
        (`if self in invoice_reports` in its own _render_qweb_pdf()).
        """
        self.ensure_one()
        return self in self._get_en16931_invoice_reports()

    def _post_pdf(self, save_in_attachment, pdf_content=None, res_ids=None):
        """15.0 counterpart of the 16.0 _render_qweb_pdf_prepare_streams().

        16.0 renders one stream per record and lets modules rework each of
        them; 15.0 renders the whole batch as a single pdf_content and offers
        this hook instead, which is where account_invoice_facturx embeds its
        own Factur-X XML. Same caveats as upstream: printing regenerates the
        XML even when the invoice is read back from its attachment, and
        opening the invoice from the attachment gives the "original" XML.

        Called with res_ids=None when the PDF comes from the attachment, hence
        the guard.
        """
        if (
            pdf_content
            and res_ids
            and len(res_ids) == 1
            and len(self) == 1
            and self._is_en16931_invoice_report()
            and not self.env.context.get("regular_pdf_invoice")
        ):
            move = self.env["account.move"].browse(res_ids)
            invoice_format = move._get_pdf_invoice_format()
            if invoice_format:
                with BytesIO(pdf_content) as pdf_bytesio:
                    move._regular_pdf_invoice_to_en16931_pdf_invoice(
                        pdf_bytesio, invoice_format
                    )
                    pdf_bytesio.seek(0)
                    pdf_content = pdf_bytesio.read()
        return super()._post_pdf(
            save_in_attachment, pdf_content=pdf_content, res_ids=res_ids
        )
