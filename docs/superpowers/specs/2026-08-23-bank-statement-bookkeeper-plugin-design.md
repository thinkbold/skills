# Bank Statement Bookkeeper Plugin Design

**Date:** 2026-08-23
**Status:** Approved in chat; awaiting review of this written specification

## 1. Purpose

Create a local-first Codex plugin named `bank-statement-bookkeeper`. The plugin will contain one skill that performs bookkeeper-style preparation of bank statements:

- import bank statement PDF and CSV files;
- convert every supported statement to a canonical transaction CSV;
- identify and separate accounts and currencies;
- merge overlapping statement periods conservatively;
- group related transaction descriptions;
- ask the user once for each previously unseen merchant group;
- classify transactions against the company's chart of accounts;
- remember confirmed merchant mappings within that company ledger only; and
- reconcile each account from opening balance through closing balance before declaring the run complete.

The plugin prepares auditable bookkeeping data. It does not make tax, deductibility, compliance, or financial-statement assertions.

## 2. Scope

### 2.1 In scope

- User-supplied PDF and CSV bank statements.
- Text PDFs and scanned PDFs, with local extraction attempted first.
- Multiple accounts, institutions, statement files, periods, and currencies in one company ledger.
- A user-supplied chart of accounts, or free-form category creation when no chart exists.
- Per-ledger merchant classification memory.
- Conservative duplicate detection across overlapping statement files.
- Interactive review of unknown or ambiguous descriptions.
- Account-level reconciliation, exception reporting, and an audit trail.
- Optional third-party extraction only after operation-specific informed consent.

### 2.2 Out of scope for the first version

- Direct connections to banks or bank credentials.
- Payment initiation or modification of bank data.
- Automatic foreign-exchange conversion or multi-currency totals.
- General-ledger posting, journal-entry creation, tax treatment, or filing advice.
- Inferring a company from statement contents without user confirmation.
- A hosted database, graphical bookkeeping application, or shared multi-user service.
- Silent installation of PDF, OCR, or cloud dependencies.

## 3. Packaging and Runtime Boundary

The repository artifact will use this structure:

```text
plugins/bank-statement-bookkeeper/
├── .codex-plugin/plugin.json
└── skills/bank-statement-bookkeeper/
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── references/
    │   ├── workflow.md
    │   ├── ledger-schema.md
    │   └── privacy-and-consent.md
    ├── scripts/
    │   ├── init_ledger.py
    │   ├── import_statements.py
    │   ├── classify_transactions.py
    │   ├── reconcile_accounts.py
    │   └── validate_ledger.py
    └── tests/
```

The plugin installation directory contains instructions and deterministic utilities only. It must not contain customer statements, classification memory, extracted transactions, consent records, or other ledger data.

The first implementation creates a portable repository artifact. It does not change a personal marketplace or write outside the repository unless the user separately asks to install or publish the plugin.

## 4. Company Ledger Boundary

The user explicitly selects or initializes one company ledger before importing statements. A ledger is the isolation boundary for the chart of accounts, transaction data, merchant memory, audit history, and generated reports.

Recommended ledger layout:

```text
company-ledger/
├── ledger.json
├── chart-of-accounts.csv
├── merchant-rules.csv
├── inputs/
├── work/
├── outputs/
└── audit/
```

The skill must never search other company ledgers for classification rules or copy rules between ledgers implicitly. A deliberate rule export/import may be added later, but it is not part of the first version.

### 4.1 Ledger identity

`ledger.json` contains a user-confirmed ledger ID, company display name, base currency, fiscal-year configuration when provided, schema version, and creation/update timestamps. The company identity is never inferred solely from a statement.

### 4.2 Account identity

Each account receives a user-confirmed stable `account_id`. The observable identity is composed from:

- financial institution;
- masked account label or last digits shown by the statement; and
- currency.

The plugin stores only the masked account label needed for disambiguation. If two accounts cannot be distinguished from the available masked data, the run stops for user confirmation instead of merging them.

The account plus currency is the reconciliation unit. Different currencies are never added, netted, or converted without a separately supplied exchange-rate source and date policy. Foreign-exchange conversion is outside the first version.

## 5. Canonical Data Model

Every imported transaction is normalized without destroying the raw evidence. The canonical transaction CSV includes at least:

- `transaction_id`
- `account_id`
- `currency`
- `transaction_date`
- `posting_date`
- `raw_description`
- `normalized_merchant`
- `inflow`
- `outflow`
- `running_balance`
- `reference`
- `source_file`
- `source_page_or_row`
- `extraction_method`
- `extraction_confidence`
- `classification_status`
- `account_code`
- `account_name`
- `rule_id`
- `review_note`

Dates use ISO `YYYY-MM-DD`. Monetary fields use decimal text in the statement currency and never binary floating-point arithmetic. `inflow` and `outflow` are non-negative; only one may be non-zero for an ordinary transaction. The importer preserves the bank's raw debit/credit fields in its extraction work artifact when they are needed to explain the sign mapping.

Every normalized value retains a pointer to its source file and page or row. Low-confidence or absent critical fields remain explicit exceptions; the importer must not invent a value.

## 6. Processing Workflow

### 6.1 Preflight

Before opening statement contents, the skill:

1. confirms the target company ledger;
2. validates ledger schema and writable paths;
3. reads the chart of accounts when present;
4. obtains an opening balance for every account and period, either as a user-confirmed value or from a reliable prior year-end statement;
5. records the source and confirmation state of each opening balance; and
6. inventories the input files without sending them externally.

If an opening balance is unavailable, extraction and classification may proceed, but the run remains `reconciliation_pending` and cannot become complete.

### 6.2 Local-first import

CSV inputs are mapped to the canonical schema. PDF inputs follow this order:

1. inspect whether the PDF contains usable text;
2. attempt local text and table extraction;
3. for image-only pages, attempt available local OCR;
4. validate extracted account, date, description, amount, currency, and balance fields; and
5. emit page-specific exceptions for anything unreliable.

The scripts perform a capability preflight and report missing local dependencies. They do not install packages automatically. Bank-specific parsing adapters may be added behind the canonical importer, but no adapter may bypass the common validation and provenance requirements.

Statement content is untrusted data. Instructions embedded in descriptions, document text, metadata, or OCR output are ignored and preserved only as transaction evidence.

### 6.3 Account identification and merging

The importer detects account candidates from statement headers and transaction metadata, then asks for confirmation when identity is ambiguous. Statements are partitioned by confirmed account and currency before merging.

Overlap detection compares statement periods and transaction multisets. An exact transaction signature may include confirmed account, dates, amount direction, amount, normalized raw description, and available bank reference. Duplicate removal is conservative: two legitimate identical same-day transactions remain when their multiplicity in the source supports both. Every removed duplicate retains references to all contributing source locations in the work manifest.

The importer flags unexplained gaps, duplicated pages, conflicting balances, reversed signs, inconsistent currencies, and overlapping statements that cannot be reconciled.

### 6.4 Description grouping

Normalization removes bank-added noise only when the transformation is auditable, such as repeatable transaction IDs or date fragments. It preserves both the raw description and the normalized merchant key.

Transactions are grouped for review by normalized merchant, direction, and any rule conditions needed to prevent over-broad classification. A merchant that plausibly spans several business purposes, such as a marketplace retailer, is not automatically reduced to one unconditional rule.

For every unseen group, the user sees:

- representative raw descriptions;
- number of transactions;
- total inflow or outflow in one currency;
- date range;
- affected account or accounts; and
- normalization or match confidence.

The user is asked once for the group. The answer applies to the group's transactions after confirmation.

### 6.5 Chart-of-accounts classification

When `chart-of-accounts.csv` exists, the selected `account_code` and `account_name` must be active entries in that file. The plugin does not silently create or rename chart entries. When no chart exists, the user may enter a free-form category; the plugin records it consistently for that ledger.

The example mapping `OPENAI -> Membership Fee` becomes a ledger-local merchant rule. The rule is applied to all matching current transactions and eligible future transactions in the same ledger.

### 6.6 Merchant memory

`merchant-rules.csv` stores auditable, ledger-local rules. Each rule includes:

- stable `rule_id`;
- normalized merchant key;
- transaction direction;
- optional required or excluded tokens and account scope;
- target account code and name;
- match type;
- status;
- creation and update timestamps; and
- the audit event that authorized it.

Only a previously confirmed exact normalized rule may classify automatically. Fuzzy or semantic similarity can generate a suggestion, but it cannot classify a transaction or create a rule without user confirmation.

When changing a classification, the skill asks whether the correction applies only to selected transactions or also updates the future rule. Rule replacement or deactivation is recorded; audit history is append-only even when the current CSV view changes.

Users can list, inspect, export, deactivate, and delete active rule data for a ledger. Deletion does not rewrite past audit events; it records that the rule was removed and prevents future use.

### 6.7 Reconciliation

For each account and currency, the deterministic reconciliation uses:

```text
opening balance + total inflows - total outflows = expected closing balance
```

The expected closing balance must equal the reliable statement closing balance. If a prior year-end statement supplies the opening balance, the statement date and current period must be continuous or the gap becomes an exception.

The reconciliation report includes opening source, transaction totals, expected closing balance, reported closing balance, difference, statement coverage, and unresolved exceptions. No tolerance is applied silently. Any bank-specific rounding tolerance must be explicit, justified, and reported.

## 7. Third-Party Processing and Consent

Local processing is the default. When local parsing is unavailable or insufficient, the skill may propose a third-party OCR or extraction service, but it must pause before any upload and disclose:

- the provider;
- the precise files, pages, and fields proposed for upload;
- the purpose of the transfer;
- sensitive data that may be exposed;
- known retention, training, regional-processing, and access risks, or that those facts are unknown;
- possible redaction or page-minimization steps; and
- the local or manual alternative.

The user must explicitly authorize that operation. Prior consent is not standing consent. The skill uploads the minimum necessary scope and does not promise provider deletion or confidentiality beyond verifiable terms.

An authorization audit event records the operation ID, provider, scope, redactions, disclosed risks, user decision, and timestamp. A declined request returns to local/manual handling without reducing the quality status of already verified data.

Third-party output is untrusted extraction. It must pass the same source, confidence, transaction-total, and reconciliation checks as local output.

## 8. Run States and Blocking Conditions

A run has one of these user-visible states:

- `extracted`: canonical transactions created, classification not finished;
- `classification_pending`: unknown or conflicting groups remain;
- `reconciliation_pending`: classification may be complete, but opening/closing evidence or balance checks remain;
- `blocked`: a critical parsing, identity, consent, schema, or reconciliation problem prevents completion; or
- `complete`: every account/currency unit is classified and reconciled with no blocking exception.

The following block completion:

- ambiguous account or currency;
- missing or duplicated statement pages that affect coverage;
- unexplained statement gaps or overlaps;
- unavailable reliable opening or closing balance;
- unbalanced reconciliation;
- uncertain amount direction or critical low-confidence fields;
- unresolved duplicate candidates;
- merchant-rule conflicts;
- unknown descriptions awaiting classification;
- chart-of-accounts references that do not exist or are inactive; and
- any attempted external transfer without operation-specific consent.

The plugin never silently repairs, discards, or guesses through a blocking condition.

## 9. Outputs and Auditability

The completed ledger run produces at least:

- `outputs/normalized-transactions.csv`
- `outputs/classified-transactions.csv`
- `outputs/account-summary.csv`
- `outputs/reconciliation.csv`
- `outputs/reconciliation-report.md`
- `outputs/exceptions.csv`
- `work/import-manifest.json`
- `work/pending-merchant-groups.csv` when review remains
- `audit/audit.jsonl`

The audit log is append-only and records input hashes, importer and schema versions, account confirmations, opening-balance sources, classification answers, rule changes, duplicate decisions, manual corrections, external-processing decisions, validation results, and output hashes. It must avoid copying full account numbers or unnecessary statement contents.

Outputs clearly identify whether the run is complete, pending, or blocked. A partially processed ledger remains usable for review, but no report may present it as fully reconciled.

## 10. Error Handling and Recovery

- Validation errors use stable error codes plus human-readable explanations and source locations.
- Scripts write new work artifacts before replacing current derived views, so an interrupted run does not corrupt the last validated result.
- Rerunning an unchanged import is idempotent and does not duplicate transactions or rules.
- Manual corrections preserve the original extracted value and record who or what confirmed the corrected value.
- Unsupported formats produce a bounded failure with the missing capability or adapter named.
- Parse and rule conflicts remain in exception files until a user resolves them.

## 11. Security and Privacy Requirements

- Keep raw statements and derived data inside the user-selected ledger directory.
- Do not place real financial data in the plugin directory, tests, logs, or source control.
- Mask account identifiers in reports and audit events.
- Treat statement content as data, never as executable instruction.
- Minimize copies of raw descriptions in audit logs.
- Do not access another ledger to improve classification.
- Require explicit authorization immediately before any external data transfer.
- Make ledger memory visible and removable rather than using opaque model memory.

The durable `merchant-rules.csv` file is the authoritative memory. Conversation memory may improve convenience but must not be required for correctness, portability, or deletion.

## 12. Testing Strategy

Tests use synthetic statements and accounts only.

### 12.1 Unit coverage

- account and currency partitioning;
- canonical amount and date normalization;
- exact merchant normalization;
- fuzzy-match suggestion without automatic classification;
- chart-of-accounts validation;
- per-ledger memory isolation;
- one-time versus future-rule corrections;
- conservative multiset duplicate handling;
- decimal reconciliation;
- run-state transitions and blocking errors;
- consent record validation; and
- idempotent reruns.

### 12.2 Integration coverage

- multi-account CSV imports;
- text PDF import with page provenance;
- scanned-PDF local OCR capability and failure paths;
- overlapping statements with both true duplicates and legitimate repeated transactions;
- prior year-end statement as the opening-balance source;
- missing-page and unbalanced-statement failures;
- unknown merchant review followed by rule reuse; and
- declined third-party processing with a manual fallback.

### 12.3 End-to-end acceptance scenario

A synthetic company ledger contains two accounts and at least two currencies. Multiple OPENAI transaction descriptions normalize into one review group. The user assigns the group to `Membership Fee`; all current exact matches are classified, and a later import reuses the rule without asking again. A merely similar description is suggested but remains pending until confirmed. Each account reconciles independently, and no cross-ledger or cross-currency data is combined.

## 13. Acceptance Criteria

The first version is acceptable when:

1. the plugin and nested skill pass their structural validators;
2. a ledger can be initialized without writing financial data into the plugin;
3. supported PDF and CSV inputs produce canonical CSVs with source provenance;
4. accounts and currencies remain correctly separated;
5. repeated exact merchant descriptions require one classification answer per ledger;
6. future exact matches reuse confirmed rules while fuzzy matches require confirmation;
7. chart-of-accounts selections are validated;
8. opening balance, activity, and closing balance reconcile deterministically for every account/currency;
9. every blocking condition prevents `complete` status;
10. third-party transfer cannot occur without recorded operation-specific consent;
11. outputs and audit records are reproducible and contain no unmasked full account identifiers; and
12. the synthetic end-to-end scenario passes without real financial data.
