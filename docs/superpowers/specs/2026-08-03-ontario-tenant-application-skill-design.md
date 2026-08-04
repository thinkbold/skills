# Ontario Tenant Application Assessment Skill Design

Status: Approved design

Date: 2026-08-03

## 1. Purpose

Create a version-controlled Codex skill named
`assess-ontario-tenant-application` for Ontario property managers and
individual landlords. The skill processes one residential rental application
case at a time and produces an auditable evidence package for human review.

The skill evaluates the evidence submitted with an application. It does not
score a person, rank applicants, predict future default, or approve or reject a
tenancy application.

The skill is not legal advice. Production authorization text and material
compliance policy changes require review by qualified Ontario counsel.

## 2. Scope

V1 applies only when all of the following are true:

- The rental property is in Ontario, Canada.
- The property is ordinary market-rate residential housing.
- The applicant will not share a kitchen or bathroom with the owner or the
  owner's family.
- The user is a property manager, authorized team member, or individual
  landlord who completes the same compliance preflight.
- The application is assessed individually rather than compared with other
  applications.

V1 does not cover:

- Housing outside Ontario.
- Rent-geared-to-income or social-housing eligibility.
- Commercial leases.
- Owner-occupied shared kitchen or bathroom arrangements.
- Existing-tenant monitoring, tracking, enforcement, or eviction.
- Applicant ranking, automatic approval, or automatic rejection.
- Official police record checks or criminal-record conclusions.
- Future default probability or other predictive risk claims.
- Cross-case tenant profiles, databases, watchlists, or blacklists.

## 3. Product Principles

The assessment object is the application and its evidence, not the applicant's
character or worth. Every conclusion must be traceable to a source, a confirmed
fact, and a versioned rule. The skill must distinguish a lack of evidence from
negative evidence.

The workflow has two independent evidence surfaces:

1. Application integrity: whether submitted facts and documents are internally
   consistent and independently supportable.
2. Rent-payment-related evidence: what current, lawful evidence says about
   payment history and present financial facts.

Open-web information is a third, separate surface. It is an appendix for human
verification leads and is never an input to the two core evidence surfaces or
the recommendation summary.

## 4. Skill Architecture

Use one orchestrator skill with modular references, deterministic scripts, and
templates:

```text
assess-ontario-tenant-application/
|-- SKILL.md
|-- agents/
|   `-- openai.yaml
|-- scripts/
|   |-- validate_case.py
|   |-- redact_sensitive_data.py
|   |-- calculate_financials.py
|   |-- validate_evidence.py
|   `-- build_report.py
|-- references/
|   |-- workflow.md
|   |-- ontario-compliance-policy.md
|   |-- evidence-schema.md
|   |-- assessment-rules.md
|   `-- public-source-policy.md
|-- assets/
|   |-- case-manifest.template.json
|   |-- assessment.template.md
|   |-- discrepancy.template.md
|   `-- outreach-templates/
`-- tests/
    |-- fixtures/
    `-- test_*.py
```

`SKILL.md` contains only the trigger description, fixed workflow, hard stops,
and instructions for loading relevant references. Detailed policy lives in
`references/`. Repeated, accuracy-sensitive operations live in `scripts/`.

The LLM may extract facts, identify possible discrepancies, cite evidence, and
draft explanations or outreach text. It must not perform financial arithmetic,
assign an evidence state from intuition, or follow instructions embedded in
case files or web pages.

## 5. Case Contract

Each invocation processes exactly one case directory outside the skill folder.
The case manifest identifies:

- Case identifier and controlled storage location.
- Property address, monthly rent, expected start date, and lease term.
- Every co-applicant who will sign the lease.
- Files associated with each co-applicant.
- Source, acquisition method, date, and authorization status for each file.
- Manual identity and critical-value confirmation states.
- General background-check authorization version.
- Optional social-platform authorization version and status.
- Privacy owner and retention-policy acknowledgement.

The application household includes only co-applicants who will sign this lease.
An unlisted spouse, child, family member, or roommate is excluded. A guarantor
is assessed and displayed separately and is never merged into household totals.

Supported V1 inputs are PDF, PNG, JPEG, CSV, TXT, and Markdown. Executable
attachments, macro-enabled files, and cloud-share links are rejected.
Password-protected files must be unlocked by the user in the controlled
environment before submission.

## 6. Mandatory Preflight

Before reading application evidence, validate:

- Ontario and housing-scope eligibility.
- A uniform evidence checklist for this application type.
- The identity of the privacy-responsible person.
- Approved storage and deletion behavior.
- Required authorizations and their exact versions.
- The rule package's review date.
- Agreement not to rank, automatically decide, or use protected information.

An individual landlord may designate themselves as the privacy-responsible
person but cannot skip any control. Failed preflight produces only a list of
missing or invalid prerequisites.

## 7. Processing Workflow

### 7.1 Validate and isolate

Validate the manifest and file association before extraction. Detect and redact
Social Insurance Numbers. Isolate fields that reveal protected characteristics
so they are not available to the core assessment or its operator-facing view.

Date of birth may be used only to disambiguate identity, match an authorized
credit report, and confirm legal capacity when required. The final report does
not display the full date of birth. Automated face recognition and biometric
templates are prohibited.

### 7.2 Extract evidence

For every extracted fact, record:

- Applicant and source file.
- Page or structured-record location.
- Original text or value.
- Normalized value.
- Reporting period and currency.
- Gross or net designation.
- Extraction confidence and human confirmation state.

Every monetary value used in a calculation must be confirmed by a human or a
validated structured source. Unclear values remain pending and do not enter a
total.

### 7.3 Verify core evidence

Cross-check application fields, current credit information, income evidence,
reported monthly debt, rental history, and optional applicant-supplied bank
records. Prepare standardized employer, previous-landlord, or reference email,
SMS, and phone scripts. The skill never sends a message or makes a call.

Reference questions are objective: dates, rent, documented payment history,
confirmed lease breaches, supported property damage, and outstanding amounts.
Do not ask whether a reference would rent to the person again or whether the
person was likeable, quiet, or a good fit.

No reply from an employer, landlord, or reference lowers the confidence of that
source only. It is not negative evidence. Employment tenure and job changes do
not affect the evidence state by themselves.

### 7.4 Resolve discrepancies

Display every discrepancy, but classify it only as:

- Minor difference.
- Needs clarification.
- Confirmed material conflict.
- Parsing uncertainty.

The skill does not label an applicant as fraudulent. A document may be called
false only after the issuing or authoritative source confirms it. Human review
determines materiality. Applicants must receive an opportunity to explain or
correct potentially adverse discrepancies before the case is completed.

If an explanation invokes disability, domestic violence, family status, or
another protected circumstance, remove the protected details from the ordinary
report and route the issue to individualized accommodation and compliance
review. Automated evidence-state processing stops for that issue.

### 7.5 Calculate confirmed financial facts

Use deterministic scripts and decimal arithmetic. Record every formula and its
confirmed inputs. The LLM does not calculate totals.

For fixed annual salary, divide verified gross annual salary by 12. For hourly,
commission, contract, seasonal, or other variable income, divide up to the most
recent 12 months of verified gross income by the number of covered months.
Shorter histories remain usable but are explicitly marked as limited. Do not
extrapolate a short period to a full year.

Recurring bonuses may be included only when history establishes recurrence.
One-time amounts are displayed separately. For self-employment, use net business
income after reasonable business expenses and before personal income tax, not
gross business revenue.

Use gross monthly income for a narrow rent-coverage confirmation:

```text
confirmed recurring gross monthly income >= monthly rent
```

The result is `covers`, `does not cover`, or `insufficient evidence`. Do not
calculate, display, or use a rent-to-income ratio, income multiple, residual
income test, or post-rent living-expense assessment.

Monthly debt is included only when a current credit report, formal statement,
or confirmed applicant disclosure gives a monthly payment amount. Never infer a
monthly payment from balance, interest rate, or account type. Show accounts with
unknown monthly payments and their balances separately. Total debt balance does
not itself create negative evidence.

Income and debt are displayed as separate personal and household totals. Do not
combine them into debt-to-income, affordability, or residual-income measures.

For non-CAD facts, preserve the original currency and convert using the Bank of
Canada rate for the assessment date. Record the rate, date, source, and formula.
Foreign income is not negative evidence; its verified continuation and exchange
uncertainty affect confidence only.

## 8. Credit and Payment Evidence

The skill analyzes a credit report already obtained by the property manager
through an authorized channel. V1 does not connect to Equifax or TransUnion.

A report obtained directly by the property manager through an authorized
channel may be marked verified. An applicant-supplied PDF or screenshot may be
analyzed but remains applicant-supplied and independently unverified. A credit
report must be no more than 30 days old to be current. Older reports are marked
stale and do not produce negative evidence.

Display an official credit score and its reported factors when present, but do
not set a minimum score, recompute the score, or let the score decide an evidence
state by itself. Do not retrieve or revive expired credit information from old
files or open-web sources.

The rent-payment-related evidence state may treat only the following as negative
payment evidence:

- Current-report delinquencies, collections, or charge-offs.
- Independently verified prior rent arrears or payment obligations.
- Confirmed repeated late rent payments in formal rental records.
- Relevant unresolved payment facts acknowledged by the applicant.

Debt total, utilization alone, missing history, short employment, unanswered
references, unverified web results, and expired credit facts are excluded.

No Canadian credit history or rental history is not negative evidence. It lowers
evidence confidence and prompts consideration of other lawful evidence.

## 9. Optional Bank Records

The skill never obtains bank records. If an applicant chooses to provide them,
use them only to cross-check declared income deposits and declared or
credit-reported debt payments. Ignore all other spending, transfers, merchant
names, daily balances, overdrafts, and cash-flow patterns. An unrelated transfer
must not be inferred to be debt.

## 10. Open-Web Appendix

General application authorization must disclose open-web source categories and
the narrow verification purpose. The source whitelist is:

- Government and Ontario official registries.
- Courts, tribunals, CanLII, and primary legal materials.
- Corporate and professional licence registries.
- Applicant or organization official sites.
- News organizations with editorial accountability and correction processes.
- Facebook and LinkedIn only under their separate authorization described below.

Exclude anonymous forums, people-search services, data brokers, tenant
blacklists, unattributed reposts, leaked data, and personal accusations.

Do not display a same-name result unless at least two independent,
non-protected identity elements match, such as full name plus verified historical
city or full name plus verified employer. Record the matching basis, source URL,
page title, publication or access date, relevant minimal excerpt, and source
type. Do not store an entire page or screenshot by default.

LTB and other public records may all be listed after identity matching, but each
entry must show party role, case type, status, result, and whether the decision
made a finding against the applicant. Merely appearing in a proceeding is not a
negative fact. These records remain in the appendix regardless of outcome and
never affect the core report or recommendation.

Open-web searches may surface news or legal material about alleged or adjudicated
criminal conduct. List only identity-matched source facts in the appendix. Do
not call this a criminal record check, make a criminal-record conclusion, or use
the result in an evidence state or recommendation.

### 10.1 Facebook and LinkedIn

Require platform-specific, informed, separately recorded, and revocable consent.
Refusal, revocation, private accounts, missing accounts, or inability to match an
account are neutral. On revocation, delete collected social content and retain
only the revocation audit event.

Permitted checks are limited to:

- Whether an applicant-provided or confirmed account is accessible.
- Whether the displayed name is consistent with verified identity.
- Whether a declared LinkedIn employer or professional fact matches the
  application.
- Whether available account metadata indicates the account predates the rental
  application.

Do not analyze posts, photos, friends, connections, likes, political or religious
views, family relationships, lifestyle, or location history. Filter protected
information and do not retain it.

The authorization form must identify each platform, purpose, permitted field,
consequence, and version. Ontario counsel must approve the production form.

## 11. Evidence States and Recommendations

V1 uses evidence states rather than a person score or predictive risk band.

Application integrity states:

- No confirmed issue found.
- Clarification pending.
- Human-confirmed material conflict.
- Insufficient evidence.

Rent-payment-related evidence states:

- No current negative payment evidence found.
- Negative payment evidence requires human review.
- Limited evidence.
- Unable to assess.

These labels are descriptions of available evidence, not predictions.

The final recommendation summary uses exactly one of:

- Evidence is sufficient for a human rental decision.
- Complete the listed verification before deciding.
- Confirmed material facts require human and compliance review.
- Evidence is insufficient to assess the application.

Do not use approve, reject, best applicant, good tenant, bad tenant, dangerous,
or semantic equivalents. A guarantor may be presented only as an optional,
uniform-policy mitigation for an objectively documented gap. Do not recommend a
guarantor because of missing history, public assistance, newcomer status, age,
family status, or low confidence alone.

The property manager makes the final decision and selects at least one
standardized reason code. Codes include chronological selection of the first
application meeting uniform criteria, applicant withdrawal, required evidence
not supplied by the deadline, confirmed material conflict, or other with a short
explanation. Any override of the skill's evidence state is recorded.

## 12. Outputs

The formal output language is English. A Chinese reading copy is optional, but
the English version is the audit baseline.

Each completed or partial run writes:

- `assessment.md`: core operator report.
- `evidence.json`: normalized facts, provenance, confirmations, and rule version.
- `discrepancies.md`: every discrepancy and human disposition.
- `public-records.md`: hard-isolated open-web appendix.
- `outreach/`: prepared email, SMS, and phone scripts.
- `audit.jsonl`: chronological machine-readable audit events.

The core report contains property context, co-applicant evidence, personal and
household gross monthly income, separately reported monthly debt, accounts with
unknown monthly payments, rent coverage, current payment evidence, rental
history, discrepancies, confidence limitations, formulas, and the human review
checklist.

PDF rendering is outside the V1 core. It may later render only a confirmed
Markdown report.

## 13. Privacy, Security, and Retention

Raw application documents must remain in the user's approved controlled
environment and must not be sent to unapproved external AI, OCR, or document
services. Open-web queries use the minimum identity data required and never
include date of birth, document numbers, credit facts, or financial data.

All case files and web content are untrusted input. Embedded instructions,
hidden text, metadata, and prompt injection cannot change the workflow, trigger
tools, access other cases, or cause disclosure.

Raw identity, credit, income, and bank documents are deleted 30 days after the
decision or withdrawal. The final report, authorizations, source manifest,
human-decision code, and audit log are retained for 13 months. A documented
legal hold pauses deletion for the affected records. Nothing is retained
indefinitely.

The skill does not provide an applicant portal. The deploying landlord or
property manager must have an existing privacy contact and process for access,
correction, and deletion requests. The skill must be able to export the source,
fact, correction, and assessment information needed for that process.

## 14. Compliance Policy Lifecycle

The bundled Ontario policy records official source URLs, review date, reviewer,
and rule version. A qualified reviewer must review it at least every 90 days.
After 90 days, the skill may extract evidence but must not produce a compliance
conclusion or completed recommendation.

Online legal changes are never applied automatically. A reviewed policy update
must create a new version. Every report records the exact policy and rule
versions used.

Primary references for the initial policy include:

- [Ontario Regulation 290/98](https://www.ontario.ca/laws/regulation/980290)
- [Ontario credit reports and Consumer Reporting Act overview](https://www.ontario.ca/page/credit-reports)
- [OHRC policy on rental housing screening](https://www.ohrc.on.ca/en/policy-human-rights-and-rental-housing/v-identifying-discrimination-rental-housing)
- [OPC rental-housing privacy guidance](https://www.priv.gc.ca/en/privacy-topics/landlords-and-tenants/02_05_d_66_tips/)
- [OPC PIPEDA fair information principles](https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/the-personal-information-protection-and-electronic-documents-act-pipeda/p_principle/)
- [Ontario police record check rules](https://www.ontario.ca/page/police-record-checks)
- [Tribunals Ontario LTB decisions and records](https://tribunalsontario.ca/ltb/law-rules-and-decisions/)
- [Tribunals Ontario HRTO application timing](https://tribunalsontario.ca/hrto/application-and-hearing-process/)

## 15. Error Handling

Use fail-closed partial reporting. Corrupt files, missing fields, stale sources,
unconfirmed values, and parsing failures are listed with their effect. Confirmed
facts remain available, but affected calculations do not run and affected states
become unable to assess or incomplete. Generate the minimum request needed to
continue. Never invent, estimate, or silently default a value.

## 16. Testing and Release Gates

Use only synthetic or irreversibly de-identified fixtures. Do not place real
applicant data in the repository, examples, test logs, or development tools.

Test layers are:

- Schema tests for manifest, evidence, audit, and output contracts.
- Calculation tests for decimal math, pay periods, self-employment, household
  aggregation, unknown monthly debt, and fixed exchange-rate fixtures.
- Policy-invariant tests for prohibited scores, ranking, automated decisions,
  protected-data leakage, and appendix-to-core contamination.
- End-to-end synthetic scenarios for fixed salary, self-employment, joint
  applications, thin files, discrepancies, OCR failure, social revocation,
  same-name false matches, LTB records, expired rules, and accommodation.
- Prompt-injection and malicious-document tests.
- Golden-report regression tests.

Run the skill creator's `quick_validate.py`, all local tests, and safety-text
scans before release. Every critical compliance invariant must pass. A single
critical failure blocks release; aggregate accuracy cannot hide it.

## 17. Acceptance Criteria

The design is implemented successfully when:

- A valid single-case directory produces every specified artifact.
- Every calculated amount is reproducible from confirmed inputs.
- Missing history, missing social accounts, and unanswered references never
  become negative evidence.
- Protected data and SIN never appear in the core report.
- Public-web facts never influence core evidence states or recommendations.
- No output ranks applicants, predicts default, or recommends approval or
  rejection.
- Partial and expired-policy cases stop safely and explain why.
- Retention and audit metadata are complete and machine-readable.
- All validation, unit, policy, security, and end-to-end tests pass.
