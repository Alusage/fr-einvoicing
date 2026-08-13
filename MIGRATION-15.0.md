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
| `l10n_fr_einvoicing_import` | Unchanged from 16.0, on the ported `account_invoice_import` (see below). |
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

## Install and test run on 15.0

Run on a jarvis 15.0 worktree (`fr-einvoicing-erp15-15`, branch `dev`), Python 3.9, database
created **without** demo data:

```
odoo-dev -d odoo-dev -i account_invoice_en16931,account_invoice_en16931_py3o,\
l10n_fr_account_invoice_en16931,l10n_fr_einvoicing,l10n_fr_einvoicing_batch_payment,\
l10n_fr_einvoicing_directory_import,l10n_fr_einvoicing_purchase,l10n_fr_einvoicing_sale,\
l10n_fr_einvoicing_import,account_invoice_import,l10n_fr_account_tax_unece \
  --stop-after-init --http-port=8899
```

All of them install (69 modules loaded, none in error), and the suite passes:
**`0 failed, 0 error(s) of 49 tests`** — the same 49 tests as on 16.0.

⚠️ `--http-port` on a free port is mandatory: the container entrypoint runs a resident Odoo on
8069, and sharing the port makes core `HttpCase` tests hit the resident server. On an empty
database the resident may also initialise it concurrently, which breaks the registry
(`duplicate key … pg_type_typname_nsp_index`) — that happened once here.

### What the run actually caught

Nothing in the tax layer, and nothing in the report layer: every failure was a 16.0 API that
static reading had missed.

| Symptom | Cause | Fix |
|---|---|---|
| `<xpath expr="//div[@name='partner_address_country']…">` cannot be located | that wrapper div appeared in 16.0 | anchor on the `o_address_format` div followed by `vat` |
| `<xpath expr="//widget[@name='account_file_uploader']…">` cannot be located | the widget appeared in 16.0 | anchor on `<a class="o_button_upload_bill">`, which also disambiguates |
| `unknown parameter 'precompute'` × 6 | field parameter added in 16.0 | dropped |
| `'res.partner' object has no attribute 'invalidate_recordset'` × 15 | 16.0 ORM API | `invalidate_cache(fnames, ids)` |
| `'Environment' object has no attribute 'flush_all'` × 9 | 16.0 ORM API, **in production code** (the CSV import batch loop) | `BaseModel.flush()` + `env.cache.invalidate()` |
| `module 'odoo.fields' has no attribute 'Json'` | `fields.Json` is 16.0 | Text field holding the JSON string |
| `Unknown field "account.account.account_type"` | the account type refactor is 16.0 | `user_type_id` / `internal_group` |
| `No module named 'PyPDF2.utils'` | OCA `pdf_helper` 15.0 vs PyPDF2 ≥ 2.0 — **not a backport artefact** | try `PyPDF2.errors` first |

The four `External ID not found` errors (`product.product_product_1`, `base.res_partner_1/2/4`) come
from `base_business_document_import` and `account_invoice_import` tests reaching for demo records on a
database created without demo data. To be re-run on a demo database.

## End-to-end run: a real invoice, validated by Saxon

Installing and passing the unit tests proves nothing about the output — and a schematron check is
**silently skipped** when no Saxon server answers, after which the library still logs
`successfully validated`. So the port was exercised on a real invoice, with the local `saxon-server`
container (`ghcr.io/alusage/saxon-server:v1.15-alusage.2`) and the codedb served by Odoo itself:

```
en16931.saxon_server_url             = http://saxon-server:5000/transform
en16931.saxon_server_codedb_base_url = http://<odoo-container-alias>:8069/en16931/
```

Setup: French chart of accounts, seller and buyer with valid SIREN/NIC/VAT triplets, both registered
as `private` directory entities, `VATEX-FR-FRANCHISE` set on the two exempt taxes (categoy E — the
auto-mapping only covers K and G, by design). Invoice: two lines, one with a 5 % discount, at 20 %
VAT — **HT 182.25, VAT 36.45, TTC 218.70**.

Result:

| Output | Size | Time | Schematrons |
|---|---|---|---|
| CII (`factur-x`, extended-ctc-fr) | 8 280 B | 0.34 s | `base` + `fr-ctc` |
| UBL 2.1 (extended-ctc-fr) | 5 783 B | 0.35 s | `base` + `fr-ctc` |
| Factur-X PDF | 35 303 B | 3.29 s | `base` + `fr-ctc` |

The three traces that prove a run really validated: `docker logs saxon-server` shows two lines per
check, the Odoo log shows the codedb being fetched
(`Replaced codedb XML file by custom URL …FACTUR-X_EXTENDED_codedb.xml`), and
`grep -ci 'Skipping schematron'` returns **0**.

The PDF carries `factur-x.xml` (8 272 B, extracted back with `get_facturx_xml_from_pdf`), a `%PDF-1.7`
header and an OutputIntent — so `_post_pdf()`, the Factur-X injection and `convert_to_pdfa()` all
work on 15.0. Full PDF/A-3 conformance was not re-checked with veraPDF here.

### The bug only this run could find

`account.move.line.display_type` gained `'product'` in 16.0, where it is required; on 15.0 the
selection is `False` / `line_section` / `line_note`, so a product line is falsy. Every line filter in
the stack tested `display_type == "product"`, so **BG-25 came out empty and BT-106/BT-109 at zero**:
a well-formed invoice with a VAT breakdown and no invoice line. Install was happy, the 49 unit tests
were happy, and the schematron caught it immediately (`BR-FXEXT-S-08`: `SumBT131 : 0, NBlines : 0`
against `basisAmount : 182.25`, plus `BR-FREXT-CO-15`).

### Environment: pin PyPDF2

Odoo 15 pins `PyPDF2==1.26.0` and `odoo.tools.pdf` uses `PdfFileWriter`/`PdfFileReader`, **removed in
PyPDF2 3.0**. The generated client requirements list `PyPDF2` unpinned, so pip installs 3.0.1 and
every PDF operation raises `DeprecationError: PdfFileWriter is deprecated and was removed`. Pin
`PyPDF2==1.26.0`. `factur-x` uses the separate `pypdf` package (6.x) and is unaffected — both live
side by side.

## Run on a database with demo data

The 15.0 entrypoint of the jarvis container creates its database **without** demo data (note that
`--without-demo=False` does not help: any non-empty value is truthy, so it also means *no demo*;
just omit the option). On a database created with demo:

* the whole stack installs, and **the four demo invoices of the French company are posted** — unlike
  16.0, where they stayed in draft. The difference is install order: `l10n_fr_account_tax_unece`
  being part of the same `-i` list, the taxes carry their UNECE codes before the demo is posted;
* the suite passes end to end: **`0 failed, 0 error(s) of 79 tests`**, covering the nine modules of
  this stack plus `account_invoice_import`, `base_business_document_import` and `pdf_helper`.

### Three more 16.0-isms, only demo data could reveal them

All of them in `account_invoice_import`, none in this repository:

| Symptom | Cause | Fix |
|---|---|---|
| lines dropped on import | the wizard **writes** `display_type: "product"` | drop the key; a product line is falsy on 15.0 |
| `Invalid field 'partner_id' on model 'product.supplierinfo'` | renamed from `name` in 16.0 | back to `name` |
| `Cannot create unbalanced journal entry` | 16.0 recomputes dynamic lines on `create()` | `check_move_validity=False` + `_recompute_dynamic_lines()` + `_check_balanced()`, as the 14.0 module did |
| `'account.move' object has no attribute '_check_total_amount'` | core method added in 16.0, working on `tax_totals` (`tax_totals_json` on 15.0) | carried in the module, forcing the difference onto the first tax line |

## PDF/A-3 conformance

veraPDF (`verapdf/cli`, flavour 3b) on the generated Factur-X PDF: **`PASS`**. So
`convert_to_pdfa()` produces a conformant PDF/A-3b on 15.0, as it does on 16.0.
