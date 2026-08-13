# Backport EN16931 → Odoo 15.0

Working branch: `MIG-15.0-account_invoice_en16931`, branched off
`MIG-16.0-account_invoice_en16931` — **not** off `18.0`. Everything the 16.0 backport had to
rewrite for the 18.0 tax engine applies unchanged here, so the 16.0 branch is the only sane
starting point. Read [`MIGRATION-16.0.md`](MIGRATION-16.0.md) first: this file only covers what
16.0 → 15.0 adds on top.

## Scope

| Module | Status |
|---|---|
| `account_invoice_en16931` | Ported. Report layer moved back to `_post_pdf()`. |
| `l10n_fr_account_invoice_en16931` | Unchanged from 16.0. |
| `l10n_fr_einvoicing` | Unchanged from 16.0. |
| `l10n_fr_einvoicing_purchase` | Unchanged from 16.0. |
| `l10n_fr_einvoicing_sale` | Unchanged from 16.0. |
| `l10n_fr_einvoicing_batch_payment` | Unchanged from 16.0 (`account_payment_order` exists on 15.0). |
| `l10n_fr_einvoicing_directory_import` | Unchanged from 16.0. |
| `account_invoice_en16931_py3o` | Unchanged from 16.0 (`report_py3o` 15.0 keeps the same `py3o.report._postprocess_report`). |
| `l10n_fr_einvoicing_import` | `installable: False` — `account_invoice_import` is missing on 15.0, see below. |
| `l10n_fr_einvoicing_dashboard_banner` | `installable: False` — `account_dashboard_banner` is 16.0-only. |

## What carries over untouched

The expensive part of the 16.0 backport does not need a second pass:

* **Tax layer** — `compute_all()` has the same signature on 15.0. The only 16.0 addition is the
  `fixed_multiplicator` kwarg, which this code never passes. `_get_query_tax_details_from_domain()`
  is on 15.0 too, so the BG-23 VAT breakdown is unchanged.
* **`_("txt") % arg`** — `GettextAlias.__call__(source, *args, **kwargs)` is identical on 15.0 and
  16.0, so the calls rewritten for 16.0 stay as they are.
* **View syntax** — `attrs=`, `<tree>`, `o_setting_box`: same on 15.0.
* **PDF/A-3** — `odoo.tools.pdf.OdooPdfFileWriter.convert_to_pdfa()` already exists on 15.0, and its
  implementation is byte-for-byte the 16.0 one, so `_en16931_pdf_to_pdfa()` is unchanged. The
  `fonttools<4.34` pin still applies for the same reason (`getGlyphSet()._hmtx`).
* **Data files** — every field used in `data/` and `security/` exists on 15.0, including
  `mail.activity.type.res_model` (added well before 16.0) and the `ir.cron` fields.

No JS anywhere in the stack, so the OWL 1 / OWL 2 split is a non-issue.

## What had to be rewritten: the report layer

`ir.actions.report` was reworked in 16.0 into per-record streams. On 15.0 none of this exists:

| 16.0 | 15.0 |
|---|---|
| `_render_qweb_pdf_prepare_streams(report_ref, data, res_ids)` | no such hook — the whole batch is one `pdf_content` |
| `_get_report(report_ref)` (base), `_is_invoice_report(report_ref)` (account) | absent |
| `_render(report_ref, res_ids)` | `_render(res_ids)`, called on the report record |

The Factur-X injection therefore moves to **`_post_pdf(save_in_attachment, pdf_content, res_ids)`**,
which is where `account_invoice_facturx` embeds its own XML on OCA/edi 15.0 — same author, same
place, so the upstream caveats carry over verbatim: printing regenerates the XML even when the
invoice is read back from its attachment, and opening the invoice from the attachment yields the
"original" XML. `_post_pdf()` is also called with `res_ids=None` when the PDF comes from the
attachment, hence the guard.

Resolving the invoice report needs no `report_ref`: on 15.0 `_post_pdf()` runs on the report record
itself, so `self in self._get_en16931_invoice_reports()` is enough — and it is how `account` itself
compares reports on this version (`if self in invoice_reports`, in its own `_render_qweb_pdf()`).

## OCA prerequisites missing on 15.0

Two of them had landed upstream on 16.0 while that backport was running. On 15.0 they are simply
absent, and are carried on Alusage branches until the OCA PRs are merged:

1. **VATEX codes** on `account_tax_unece` — `data/unece_tax_vatex.xml`, `unece_vatex_id`,
   `_compute_unece_vatex_id()`.
   [`Alusage/community-data-files@15.0-add-unece-vatex`](https://github.com/Alusage/community-data-files/tree/15.0-add-unece-vatex):
   the two upstream 16.0 commits cherry-picked, migration renamed `15.0.2.0.0`, tree view re-anchored
   on `description` (its 15.0 anchor) instead of `country_id`.
2. **`l10n_fr_siret` helpers** — `is_france_country`, `_get_siren()`, `_get_siret()`, `_get_nic()`,
   and the VAT↔SIREN consistency check.
   [`Alusage/l10n-france@15.0-siret-get-methods`](https://github.com/Alusage/l10n-france/tree/15.0-siret-get-methods):
   upstream `9e662b1a` plus its `self.env._` follow-up. The partner form keeps its 15.0 layout —
   `l10n_fr_siret` still defines `company_registry` itself on 15.0, and the SIREN/NIC pair still
   lives in an `oe_edit_only` div — with only the `is_france_country` condition added.

   ⚠️ Same warning as on 16.0: that commit extends `_check_siret` to `vat`, so any partner carrying
   an inconsistent VAT/SIREN pair is rejected on load, demo data included.

3. **`account_invoice_import`** — never migrated to 15.0 at all: OCA/edi carries it on 14.0 and
   16.0, with nothing in between, and `base_business_document_import` is missing too. Both are
   ported from 16.0 (not forward-ported from 14.0: the wizard was largely rewritten in between, and
   16.0 is the API `l10n_fr_einvoicing_import` consumes) on
   [`Alusage/edi@15.0-mig-account_invoice_import`](https://github.com/Alusage/edi/tree/15.0-mig-account_invoice_import).
   Neither module uses any 16.0-only ORM or view syntax, so the port is the 16.0 code with the
   manifest versions moved and the 16.0 migration scripts dropped.

`l10n_fr_account_tax_unece`, `intrastat_base`, `account_payment_order`, `account_payment_mode`,
`account_payment_partner`, `sale_commercial_partner`, `report_py3o`, `pdf_helper` and the four
`*_unece` data modules all exist on OCA 15.0 as is.

## Python

The jarvis 15.0 image runs **Python 3.9**. `factur-x>=6.7` requires ≥3.8, `pypdf` ≥3.9,
`pyfrctc>=0.15` ≥3.8, and `fonttools<4.34` predates the 3.10 floor of current fontTools — the whole
dependency set installs on 3.9.

## Upstream

There is no `15.0` branch on `akretion/fr-einvoicing`; one was requested in
[issue #52](https://github.com/akretion/fr-einvoicing/issues/52), as was done for 16.0 (#28) and
19.0 (#35).
