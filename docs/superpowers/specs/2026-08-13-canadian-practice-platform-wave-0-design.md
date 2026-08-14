# Canadian Practice Platform — Wave 0 Foundation Design

**Date:** 2026-08-13
**Status:** Approved in sections; awaiting review of this written specification

## 1. Purpose

Design the first independently deliverable subsystem of a Canada-only,
multi-tenant bookkeeping, tax, payroll, dispute, and assurance platform for
Canadian accounting and tax firms.

The product will be reached through a Codex/ChatGPT plugin, a practice
workspace, and a bilingual client portal. The plugin is an interaction and
workflow layer. Authoritative accounting data, evidence, calculations,
permissions, and approvals live in a Canadian-hosted backend.

Wave 0 establishes the shared foundation on which every later tax,
jurisdiction, payroll, dispute, and assurance module depends. It does not
implement production tax formulas, file returns, represent a taxpayer, or
issue an assurance opinion.

## 2. Confirmed Product Decisions

The final product scope is broader than the narrow prototype recommended in
the initial feasibility research. The following decisions supersede that
narrow recommendation:

- Canada only. Non-resident, United States, foreign-affiliate, transfer-pricing,
  T106, T1134, T1135, and other international work is out of scope.
- B2B first. Accounting and tax firms are the primary customers. Their clients
  use a portal for documents, facts, consent, authorization, and status.
- Canadian entity coverage includes resident corporations, CCPCs, sole
  proprietorships, partnerships, trusts, non-profits, and charities.
- National jurisdiction coverage includes federal requirements, Quebec,
  Alberta corporate returns, GST/HST, QST, and applicable PST/RST regimes.
- Payroll includes federal/CRA and Quebec-specific obligations, with other
  province-specific requirements represented by versioned jurisdiction packs.
- Later modules include tax optimization, risk-rated aggressive strategies,
  CRA reviews/audits/objections, authorized representation workflow, and
  assurance audit/review engagements.
- The current operator is not a licensed CPA or public accounting firm.
  Restricted outcomes therefore require an external, appropriately qualified
  CPA, public accountant, or lawyer, depending on the work and jurisdiction.
- All production customer content and derived content—including databases,
  files, indexes, queues, logs, backups, and disaster-recovery copies—remains
  in Canada. Customer data is not used to train models.
- English and French are first-class from the first production release. The
  user or engagement selects the language; English is the default.
- The final scope is complete, but delivery occurs through independently
  reviewed module waves rather than a big-bang release.

## 3. Feasibility Conclusion

The product is feasible as a regulated-workflow platform with deterministic
accounting and calculation services, versioned rules, evidence lineage, and
mandatory human responsibility gates.

It is not credible as a prompt-only skill. The reference repository provides a
useful router-plus-focused-skills pattern, but it lacks the tests, schemas,
permissions, immutable records, calculation controls, and professional
sign-off mechanisms required here.

Direct autonomous filing is not a Wave 0 assumption. CRA workflows currently
centre on certified software, portal channels, filer credentials, and explicit
representative authorization. Filing integrations will be designed as a
separate module and may use certified software or qualified partners rather
than direct submission by the plugin.

## 4. Platform Decomposition

The platform uses a modular regulated-platform architecture. It begins as a
modular monolith at the domain layer, with strict module contracts and a
transactional outbox. A module may be extracted into a service later without
changing its domain contract.

### 4.1 Interaction channels

- **Codex/ChatGPT plugin:** conversational intake, routing, explanation, and
  approved backend actions. It never holds the system of record.
- **Practice workspace:** firm administration, bookkeeping, workpapers,
  exception handling, review, approval, and release.
- **Client portal:** bilingual document collection, fact confirmation,
  consent, authorization, questions, and status.

All channels use the same backend authorization and policy services. No
channel has a privileged bypass path.

### 4.2 Shared core

- Tenant, firm, user, client, entity, and engagement registry.
- Hybrid ledger ingestion and platform-native double-entry ledger.
- Canonical accounting model and locked engagement snapshots.
- Document store, evidence graph, and workpaper lifecycle.
- Role, credential, consent, authorization, and policy engine.
- Versioned rule and primary-source registry.
- Deterministic calculation interface.
- Immutable audit log and transactional outbox.
- English/French rendering and terminology support.

### 4.3 Domain modules built in later waves

- Bookkeeping and period close.
- Direct tax for all supported Canadian entity types.
- Federal, provincial, and Quebec payroll.
- GST/HST, QST, PST, and RST.
- Tax planning and risk-rated aggressive positions.
- CRA review, audit, objection, and representation case management.
- Assurance audit/review engagement workflow and opinion support.
- Banking, accounting-platform, certified-software, and filing handoffs.

### 4.4 Release waves

1. **Wave 0 — Foundation:** tenancy, entity and engagement registry, hybrid
   ledger, canonical accounting layer, evidence, workpapers, snapshots,
   permissions, professional gates, audit log, and bilingual infrastructure.
2. **Wave 1 — Core operations:** bookkeeping/close plus basic direct-tax,
   indirect-tax, and payroll packs selected for pilot customers.
3. **Wave 2 — National breadth:** remaining entity and jurisdiction packs,
   including dedicated Quebec and Alberta corporate tracks.
4. **Wave 3 — Advisory and disputes:** tax planning, aggressive-position risk
   workflow, CRA reviews/audits, objections, and representation controls.
5. **Wave 4 — Assurance and filing integrations:** audit/review engagement
   system, licensed opinion release, certified-software and filing handoffs.

The scope of later waves is a product commitment, not a claim that Wave 0 can
perform those services.

## 5. Wave 0 Goals and Non-Goals

### 5.1 Goals

Wave 0 must:

- isolate data and authorization by tenant, firm, client, entity, and
  engagement;
- support an external accounting system or a platform-native ledger as the
  daily bookkeeping system of record;
- normalize either source into one canonical accounting model;
- build, validate, lock, release, and supersede reproducible engagement
  snapshots;
- trace every material accounting assertion and workpaper conclusion to its
  evidence, rule version, and accountable humans;
- enforce server-side professional and client approval gates;
- provide complete, append-only operational and decision history;
- preserve facts and amounts across English and French output; and
- fail closed when data, rules, evidence, authorization, or credentials are
  insufficient.

### 5.2 Non-goals

Wave 0 will not:

- calculate a production Canadian return, payroll, QST/PST/GST/HST liability,
  or assurance conclusion;
- submit or amend a statutory filing;
- connect to CRA or Revenu Québec as an authorized representative;
- provide tax optimization or aggressive tax advice;
- draft a final objection for submission or provide reserved legal services;
- conduct an audit/review engagement or issue an assurance opinion;
- predict CRA audit selection; or
- market itself as CRA-certified tax software.

Synthetic fixtures and generic workpaper demonstrations are permitted. They
must be labelled as non-production and must not embed unreviewed tax rules.

## 6. Domain Boundaries

### 6.1 Identity and tenancy

This module owns firms, memberships, user identities, roles, invitations,
sessions, and tenant-scoped security policy. It exposes authorization
decisions, not raw membership tables.

Every stored domain record carries an immutable tenant identifier. Client,
entity, and engagement scope further restricts access. Cross-tenant queries
are denied even when a caller guesses a valid record identifier.

Platform support personnel have no standing access to customer financial
content. Time-bound support access requires a documented purpose, customer or
authorized-firm approval, least-privilege scope, and an immutable audit event.

### 6.2 Client, entity, and engagement registry

This module owns:

- client identity and authorized contacts;
- Canadian entity classification and relationships;
- registrations and program accounts as sensitive references;
- engagement type, jurisdiction, period, scope, selected language, team, and
  responsible professional;
- engagement terms, consent, client representations, and authorizations; and
- lifecycle state and release policy.

One engagement is tied to one primary entity, one defined period or case, and
one service type. Related entities may be linked as evidence or dependencies,
but their records are not silently merged.

### 6.3 Ledger and ingestion

This module owns source connections, import cursors, raw import manifests,
normalized accounts, journals, dimensions, reconciliation results, and the
optional platform-native ledger.

Imports are idempotent. Each imported record retains the source-system
identifier, source version when available, connector version, acquisition
time, and content hash. Re-importing the same source version does not create a
second journal. A changed source record creates a new import version; it does
not overwrite history.

The platform-native ledger uses append-only posted journals. A correction uses
a reversal and replacement. Draft journals may be edited until posting.

All authoritative money values use fixed-decimal arithmetic with explicit
currency. Binary floating-point arithmetic is prohibited for authoritative
amounts.

### 6.4 Canonical accounting layer

The canonical model represents, at minimum:

- chart of accounts and account mapping;
- balanced journal headers and lines;
- posting and effective dates;
- reporting period;
- source, department, location, project, and tax dimensions where applicable;
- currency and documented exchange-rate inputs;
- imported, native, adjusting, reversing, and closing journal types; and
- evidence and provenance references.

It validates debit/credit equality, period boundaries, currency requirements,
duplicate source identifiers, and mapping completeness. Failed records enter
an exception queue and cannot enter a locked snapshot.

### 6.5 Evidence and documents

This module owns encrypted document objects, structured evidence nodes,
content hashes, versions, classifications, access policy, retention policy,
legal holds, and provenance relationships.

Evidence relationships are append-only and typed:

- `supports`;
- `derived_from`;
- `reconciles`;
- `adjusts` or `reverses`;
- `prepared_by`;
- `reviewed_by`; and
- `approved_by`.

A material output assertion must have an unbroken path to source evidence or a
clearly identified professional judgment. Missing evidence is represented as
missing; it is never converted into negative evidence or an inferred fact.

AI output is a proposal, not evidence. It may suggest classification, extract
facts, explain a result, or draft narrative. It must cite evidence nodes and
rule versions. Unsupported, conflicting, or low-confidence output becomes an
exception and cannot enter an approved workpaper or released package.

### 6.6 Workpapers

A workpaper contains its purpose, engagement, period, preparer, reviewer,
inputs, evidence links, rule versions, calculations, judgments, exceptions,
review notes, conclusions, and output assertions.

Its lifecycle is:

```text
DRAFT -> PREPARED -> IN_REVIEW -> APPROVED_LOCKED -> SUPERSEDED
                         |              ^
                         `-> RETURNED --'
```

Review notes must be resolved or explicitly accepted. An approved workpaper is
immutable. Reopening creates a successor version linked to the original and
requires new approval.

### 6.7 Engagement snapshots

The platform uses a hybrid ledger model:

- the daily bookkeeping system of record is selected per client/entity and may
  be external or platform-native;
- the calculation system of record for an engagement is always a locked
  platform snapshot; and
- the evidence, workpaper, approval, and release system of record is always the
  platform.

A snapshot contains:

- the exact imported/native ledger versions;
- normalized balances and journals;
- approved adjusting journals;
- reconciliation status;
- evidence graph version;
- applicable rule-pack versions;
- preparer, reviewer, and approval records; and
- a deterministic content hash.

The snapshot lifecycle is:

```text
BUILDING -> VALIDATING -> LOCKED -> RELEASED -> SUPERSEDED
                |
                `-> BLOCKED
```

Only a fully reconciled and policy-compliant snapshot may lock. A released
snapshot is never modified. A correction creates a successor snapshot and
shows all changed data, adjustments, rules, evidence, and approvals.

Approved adjustments may be exported or posted back to an external ledger.
The external source controls final acceptance. Posting back never changes the
already locked engagement snapshot.

### 6.8 Rule and source registry

Wave 0 implements the generic contract for future accounting, tax, payroll,
jurisdiction, and professional-policy packs. Each rule pack records:

- stable identifier and immutable version;
- jurisdiction and entity applicability;
- tax year, filing period, and effective dates;
- primary source URLs and source publication/review dates;
- structured inputs, outputs, assumptions, and unsupported states;
- golden and boundary-case fixtures;
- author, independent reviewer, qualified professional approval, and dates;
- release and retirement status; and
- next mandatory review or expiry date.

A stale, expired, inapplicable, or unsupported rule pack cannot be used to
finalize an engagement. The system returns `BLOCKED_UNSUPPORTED`; neither the
model nor an operator can substitute an estimate without creating and
approving a new rule version.

Rollback pins a new engagement run to a prior approved version. A published
rule version is never edited after use.

### 6.9 Authorization and professional policy

Authorization combines:

- scope: tenant, firm, client, entity, and engagement;
- service: bookkeeping, tax, payroll, indirect tax, disputes, or assurance;
- action: view, prepare, review, approve, represent, sign, release, or
  administer;
- data classification; and
- qualification: jurisdiction, licence/credential class, verification state,
  permitted services, and expiry.

Role families are firm administrator, engagement owner, preparer, reviewer,
qualified professional, specialist, client contact, and restricted platform
support. A person may hold several roles, but a gate may require different
people to preserve separation of duties.

Credential claims are not accepted solely because a user selected a role.
Verification evidence, jurisdiction, permitted service, and expiry are stored
and periodically revalidated. An expired or out-of-scope credential disables
the associated approval action.

The server computes required gates from engagement type, jurisdiction, risk,
firm policy, and current credentials. The plugin, workspace, portal, and API
must all request the same decision. Missing gates block release.

## 7. Responsibility and Release Matrix

| Work type | Who may prepare | Minimum release condition |
|---|---|---|
| Routine books, payroll workpaper, indirect-tax workpaper | Authorized staff | Firm policy; required review; client confirmation where applicable |
| Standard tax-return workpaper | Authorized tax preparer | Tax reviewer, client approval, current rules, and valid filing authority for any later filing action |
| Aggressive or materially uncertain tax position | Assigned specialist team | Appropriately qualified CPA or tax lawyer plus written facts, alternatives, risk analysis, and client risk acceptance |
| CRA review/audit/objection case | Assigned case team | Verified representative authorization; lawyer gate where legal representation or reserved legal work applies |
| Audit/review assurance engagement | Assigned assurance team | Acceptance/continuance, independence, quality-management gates, and a provincially authorized engagement partner |

The matrix is a minimum platform policy, not a declaration that one credential
has the same legal scope in every province. Each later jurisdiction/service
pack must encode and receive professional review for its applicable rules.

For the current unlicensed operator, the system permits preparation,
organization, routing, and non-restricted administration. Restricted sign,
represent, opinion, and release actions remain disabled until a verified
external professional with the applicable authority is assigned and approves.

## 8. End-to-End Data Flow

1. A firm administrator creates the firm, staff memberships, client, entity,
   and engagement. The engagement fixes service, period, jurisdictions,
   language, team, consent, and initial approval policy.
2. The client or firm provides documents and connects/imports the daily ledger,
   or uses the platform-native ledger.
3. Ingestion records a raw manifest, verifies content, deduplicates records,
   and normalizes accounts, journals, and dimensions.
4. Validation checks accounting invariants and creates owned exceptions for
   missing, conflicting, duplicate, unsupported, or unreconciled items.
5. Preparers resolve exceptions, attach evidence, and create append-only
   adjustments. AI may propose work but cannot confirm authoritative facts or
   amounts by itself.
6. The platform builds a candidate engagement snapshot from exact source and
   adjustment versions.
7. Deterministic validation confirms balances, evidence coverage, rule-pack
   applicability, credential validity, separation of duties, and required
   client/professional approvals.
8. The snapshot locks and workpapers enter review. Returned work produces a
   new version where necessary.
9. All required parties approve. The system generates a signed release package
   with content hashes, source/rule manifest, and an audit event.
10. Later corrections produce a successor snapshot and release package. Prior
    versions remain available subject to retention and legal-hold policy.

## 9. Bilingual Model

Core facts, amounts, codes, dates, rule results, evidence identifiers, and
workflow states are language-neutral structured data.

English and French labels, instructions, explanations, review notes, client
requests, and output narratives are separate localized representations. An
engagement stores a selected language; English is the default. A user may have
a personal display preference without changing the engagement's official
output language.

Changing language must not trigger a recalculation or produce different facts,
amounts, dates, risk classifications, gates, or citations. Material generated
narrative is reviewed in the language in which it will be released. Translation
of a professional conclusion does not inherit approval automatically unless
the reviewer approved both renderings or the approved workflow explicitly
covers a controlled translation.

## 10. Privacy, Security, and Canadian Data Residency

Production architecture must keep customer content and derived content in
Canada, including:

- relational and analytical stores;
- document/object storage;
- search and vector indexes;
- queues, caches, and temporary processing artifacts;
- application, access, security, and model-operation logs;
- backups and disaster-recovery replicas; and
- support and incident artifacts containing customer data.

Before a model or external processor receives customer data, the platform must
verify that the route, retention behavior, training setting, and subprocessors
meet the Canadian-residency and no-training policy. If they do not, the request
is denied. Redaction or synthetic data may be used only when it genuinely
removes customer content and re-identification risk.

Minimum controls are encryption in transit and at rest, tenant-scoped key and
access policy, least privilege, strong authentication, session revocation,
secret isolation, log redaction, auditable privileged access, data export,
retention by record class, legal hold, defensible deletion, incident response,
and tested Canadian backup restoration.

Financial, payroll, SIN, business-number, banking, ownership, and related-party
information is treated as sensitive. Collection and display are minimized to
the engagement purpose. Full identifiers are masked in routine views and
excluded from ordinary logs.

Customer data is not used for foundation-model or shared-model training.
Product analytics use de-identified operational metadata only when the
de-identification and purpose have been documented and approved.

## 11. Failure Handling and Recovery

### 11.1 Failure classes

- **Transient technical failure:** timeout, rate limit, or temporary
  dependency outage. Use bounded retries, idempotency keys, the transactional
  outbox, and a dead-letter/exception queue. Show freshness to the operator.
- **Accounting/data failure:** unbalanced journal, duplicate ambiguity,
  missing period, mapping gap, or failed reconciliation. Create an owned
  exception; the snapshot cannot lock.
- **Unsupported-rule failure:** missing entity, jurisdiction, service, year,
  or effective rule. Return `BLOCKED_UNSUPPORTED`; disable calculation and
  release.
- **Evidence/approval failure:** required support, review, client approval, or
  professional gate is missing. Block only the affected assertion or release
  stage, and route a task to the accountable role.
- **AI failure:** model unavailable, low confidence, conflicting extraction, or
  prompt-injection signal. Queue optional work or request human input. The
  deterministic core continues; no answer is invented.
- **Authorization/security/residency failure:** deny the action, revoke or
  contain access where appropriate, retain a forensic event, and stop affected
  processing.

### 11.2 User-visible exceptions

The practice workspace shows the cause, affected records/outputs, owner,
severity, blocking state, and required next action. The audit view additionally
shows attempts, state transitions, and resolution evidence. The client portal
shows a plain-language request without internal security details or unrelated
client information.

### 11.3 Recovery rules

Retries must be idempotent. Resuming an import uses the last confirmed cursor
and cannot duplicate a journal. A failed output does not partially release.
Completed deterministic calculations remain valid when optional AI services
are unavailable.

Locked or released records are repaired only by append-only correction,
reversal, or successor version. History is never rewritten.

## 12. Audit Log and Outbox

Security-sensitive and professionally material events are append-only and
tamper-evident. Events include actor, tenant, scope, request/channel,
timestamp, action, target, prior/new version identifiers, policy decision,
credential used, reason, and correlation identifier.

Events include at least imports, mapping changes, postings, reversals,
reconciliations, snapshot transitions, evidence links, review notes,
approvals, client confirmations, credential changes, access denials,
privileged support access, exports, releases, supersessions, retention/legal
hold actions, and security incidents.

The transactional outbox is committed with the domain change. Consumers may
receive an event more than once and therefore must be idempotent. An event is
never treated as proof that a remote integration accepted a request; remote
acceptance is recorded as a separate result.

## 13. Testing Strategy

### 13.1 Accounting and snapshot tests

- Unit and property tests enforce debit/credit equality, fixed-decimal money,
  period boundaries, currencies, reversal behavior, and immutable posted
  journals.
- Snapshot tests prove identical inputs and rule versions produce identical
  content hashes and outputs.
- Mutation tests prove locked/released records cannot change.
- Successor tests prove every difference is disclosed and linked.

### 13.2 Import and integration contract tests

- Idempotent import and deduplication fixtures.
- Cursor resume after timeouts and partial batches.
- Raw-to-canonical provenance checks.
- Connector schema-drift and malformed-input fixtures.
- Transactional outbox duplication and replay tests.
- Posting-back tests that distinguish request, remote acceptance, rejection,
  and retry.

### 13.3 Evidence and workpaper tests

- Every material output has a complete evidence/rule/judgment path.
- Hash and version mismatches are detected.
- Missing evidence remains missing and blocks the applicable state.
- Review-note resolution and returned-work loops behave deterministically.
- Approved workpapers are immutable and supersession retains prior approval.

### 13.4 Authorization and professional-gate tests

- Cross-tenant and cross-client access attempts are denied.
- Direct-object-reference and bulk-query isolation are tested.
- Separation-of-duties scenarios cannot self-approve.
- Expired, unverified, wrong-jurisdiction, and wrong-service credentials block
  restricted actions.
- Plugin, workspace, portal, and direct API calls receive the same policy
  decision.
- Unlicensed-operator fixtures cannot sign, represent, release an assurance
  opinion, or bypass a required professional gate.

### 13.5 Privacy, security, and resilience tests

- Data-flow tests prove production customer data and derivatives stay on
  approved Canadian routes.
- Logs, traces, support tools, and error messages are scanned for prohibited
  identifiers and secrets.
- Backup restoration, legal hold, export, deletion, incident response, and
  session/credential revocation are exercised.
- Prompt-injection content embedded in documents or imported fields cannot
  invoke tools, alter policy, or become authoritative instructions.

### 13.6 AI and bilingual evaluations

- Extraction is measured against human-confirmed fixtures.
- Every AI-supported assertion is checked for evidence and rule citations.
- Unsupported facts, rules, or jurisdictions must trigger refusal/exception
  behavior.
- English and French outputs must contain identical structured facts, amounts,
  dates, states, risk classifications, gates, and citations.
- Material narrative quality is reviewed by qualified English and French
  domain reviewers before production release.

### 13.7 Rule-pack release tests

Every future production rule pack requires primary sources, applicability and
effective dates, machine-testable normal/boundary/unsupported cases,
independent review, qualified professional approval, and an immutable
published version. Expiry and stale-source tests must prevent finalization.

## 14. Wave 0 Production Acceptance Criteria

Wave 0 is complete only when a controlled pilot can:

1. Create isolated firm, staff, client, entity, and engagement records with
   English/French preferences.
2. Import a representative external ledger or use the platform-native ledger.
3. Preserve raw provenance, normalize balanced journals, reconcile accounts,
   and expose unresolved exceptions.
4. Attach/version evidence and create append-only adjustments.
5. Build and lock a reproducible engagement snapshot.
6. Prepare, review, return, approve, release, and supersede a generic
   workpaper package.
7. Enforce client, reviewer, and qualified-professional gates derived from
   policy.
8. Prove tenant isolation, separation of duties, credential expiry,
   immutable/tamper-evident history, and fail-closed unsupported states.
9. Render English and French packages with identical structured content.
10. Prove Canada-only processing, logging, backup, and restoration for the
    production deployment.

Passing Wave 0 does not authorize production tax calculation, statutory
filing, representation, or an assurance opinion. Each such module requires a
separate approved design, implementation plan, professional validation set,
and release decision.

## 15. Operational Release Process

Wave 0 moves from development to synthetic testing, internal control testing,
and then a limited firm pilot. Pilot data is production data and therefore
uses the full Canadian-residency, privacy, security, retention, and access
controls.

Production changes require automated checks, reviewer approval for material
domain/policy changes, forward and rollback procedures, migration rehearsal,
and audit-log verification. A rollback never mutates a released snapshot or
published rule pack.

Operational monitoring covers import freshness, exception age, outbox lag,
failed authorization, privileged access, credential expiry, snapshot failures,
data-route violations, backup completion, and restore-test status. Alerts must
identify an accountable owner without exposing customer financial content.

## 16. Intentional Technology Boundary

This specification is normative for domain boundaries, control behavior,
states, data residency, responsibility, and acceptance tests. It intentionally
does not select a cloud vendor, web framework, database product, identity
provider, accounting connector vendor, or model provider.

The implementation plan must choose concrete components only after verifying
that they can satisfy Canada-only processing for all customer-derived data,
transactional consistency for the ledger/snapshot boundary, strong tenant
isolation, fixed-decimal calculations, immutable object/version retention,
auditable identity and credential controls, bilingual delivery, and tested
backup recovery. A component that cannot meet those requirements is ineligible
regardless of development convenience.

## 17. Source and Regulatory Notes

This is a product and system design, not legal, tax, accounting, or assurance
advice. Before production use, applicable workflows and release matrices need
review by Canadian privacy counsel and qualified professionals in the relevant
province and service area.

Primary-source context used for this design includes:

- CRA, [Electronic Record Keeping](https://www.canada.ca/en/revenue-agency/services/forms-publications/publications/ic05-1/electronic-record-keeping.html),
  supporting accessible electronic records, system documentation, and audit
  trail retention.
- CRA, [Corporation income tax return](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/corporations/corporation-income-tax-return.html)
  and [Using tax preparation software](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/corporations/corporation-income-tax-return/completing-your-corporation-income-tax-t2-return/using-tax-preparation-software.html),
  supporting the certified-software and electronic-filing context.
- CRA, [Authorize a representative](https://www.canada.ca/en/revenue-agency/services/tax/representative-authorization/overview.html),
  supporting explicit representative authorization.
- CRA, [Provincial and territorial corporation tax](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/corporations/provincial-territorial-corporation-tax.html),
  and Alberta, [Corporate income tax](https://www.alberta.ca/corporate-income-tax),
  supporting separate Quebec and Alberta corporate-administration tracks.
- Revenu Québec, [Guide for Employers: Source Deductions and
  Contributions](https://www.revenuquebec.ca/en/online-services/forms-and-publications/current-details/tp-1015-g-v/),
  supporting a dedicated Quebec payroll jurisdiction pack.
- Office of the Privacy Commissioner of Canada, [PIPEDA safeguards](https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/the-personal-information-protection-and-electronic-documents-act-pipeda/p_principle/principles/p_safeguards/)
  and [cloud-computing FAQ](https://www.priv.gc.ca/en/privacy-topics/technology/online-privacy-tracking-cookies/online-privacy/cloud-computing/02_05_d_51_cc_faq/),
  supporting sensitivity-based safeguards and accountability for processors.
- Ontario, [Public Accounting Act, 2004](https://www.ontario.ca/laws/statute/s04008),
  illustrating that assurance/public-accounting authority is regulated and
  must be evaluated by province rather than assumed nationally.

The broader source review and initial feasibility analysis are recorded in
`docs/research/2026-08-13-canadian-small-business-tax-skills-feasibility.md`.

## 18. Decision Record

The following design sections were explicitly approved during brainstorming:

1. Modular regulated platform and phased module boundaries.
2. Hybrid daily ledger with a locked platform engagement snapshot as the
   calculation system of record.
3. Append-only evidence graph and versioned workpaper lifecycle.
4. Server-enforced roles, credentials, and professional release gates.
5. Fail-closed exception handling and successor-version recovery.
6. Accounting, evidence, authorization, residency, AI, bilingual, and
   rule-pack test/release criteria.
