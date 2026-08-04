# Evidence Field Contract

## Case Manifest

`case-manifest.json` is one JSON object with:

- `schema_version`, `case_id`.
- `jurisdiction`: `country: CA`, `province: ON`.
- `housing`: market type, shared-space flag, address, CAD rent, start date, term.
- `applicants`: only lease signers, each with a stable `applicant_id` and associated files.
- `privacy`: responsible person, controlled-storage confirmation, access/correction-process confirmation.
- `authorizations.general`: exact version, signature date, open-web disclosure.
- `authorizations.social`: status and individually granted platforms.
- `decision`: pending/completed/withdrawn status, applicable date, legal hold.

Paths must be case-relative. Supported extensions are `.pdf`, `.png`, `.jpg`, `.jpeg`, `.csv`, `.txt`, and `.md`.

## Extracted Evidence

`work/extracted-evidence.json` contains:

- `core.evidence_available`.
- `core.credit_history_available` and `core.rental_history_available` when known.
- `core.credit_report`: acquisition, generated date, reported official score, reported factors.
- `core_facts`: normalized facts with provenance.
- `discrepancies`: source-to-source differences and human status.
- `payment_facts`: only explicit payment-related facts.
- `financial_input`: deterministic calculation inputs.
- `public_records`: found whitelist records proposed for the appendix.
- `public_search_outcomes`: neutral platform/source search status, including no match.
- `accommodation_review_required`.

Every `core_facts` item should include `applicant_id`, `fact_type`, `original_value`, `normalized_value`, `source_file`, `location`, reporting period if relevant, currency if relevant, gross/net basis, extraction confidence, and `confirmed`.

## Financial Input

`financial_input` contains `monthly_rent_cad`, `exchange_rates`, `incomes`, and `debts`.

Income records include applicant, amount, period, currency, confirmation, recurrence, and basis. Allowed bases are gross employment or net business income after business expenses and before personal tax. Variable totals use `period_total` with `months_covered` from 1 through 12.

Debt records include applicant, balance, explicit monthly payment or null, currency, and confirmation. Null monthly payment means unknown; never estimate it from a balance.

Non-CAD records require a stored Bank of Canada rate, date, and source.

## Discrepancies

Use only `minor_difference`, `needs_clarification`, `confirmed_material_conflict`, or `parsing_uncertainty`. A material conflict affects state only after a human confirms it. Record the compared sources and human disposition.

## Public Records

Each proposed record includes source type, URL, minimal title/excerpt metadata, access/publication date, and at least two non-protected `identity_matches`. LTB records also include party role, case type, status, result, and whether the decision made a finding against the applicant.

Social records may contain only identity existence/name consistency, declared professional fact matches, and permitted account-age metadata. Never include posts, photos, friends, connections, likes, beliefs, family, lifestyle, or location history.

## Outputs

Core outputs are `assessment.md`, `evidence.json`, and `discrepancies.md`. Public data belongs only in `public-records.md` and public work records. `human-decision.json` remains blank until completed by the property manager. `audit.jsonl` contains one JSON object per line.
