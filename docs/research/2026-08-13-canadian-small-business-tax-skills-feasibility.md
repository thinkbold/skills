# Feasibility of a Canadian small-business bookkeeping / tax / audit-readiness Codex skill or plugin

Date: 2026-08-13

> **Decision update:** The narrow Ontario/sole-proprietor MVP discussed in
> this research was the initial lowest-risk recommendation, not the final
> approved product scope. Subsequent product decisions require Canada-wide
> coverage for the confirmed entity and jurisdiction set, delivered through
> phased modules with mandatory qualified-professional gates. The current
> design is recorded in
> `docs/superpowers/specs/2026-08-13-canadian-practice-platform-wave-0-design.md`.

## Bottom line

My assessment: a Canadian-market Codex offering is feasible if the MVP is framed as an educational, workflow, and document-preparation copilot, not as an autonomous tax filer or legal/tax advisor.

Fact from sources:

- CRA has clear official guidance and forms for the core small-business flows: self-employed T1/T2125 reporting, GST/HST registration and filing, payroll deductions/remittances, T2 corporate filing, record retention, audits, and objections ([T2125](https://www.canada.ca/en/revenue-agency/services/forms-publications/forms/t2125.html); [Business or professional income](https://www.canada.ca/en/services/taxes/income-tax/business-or-professional-income.html); [When to register for and start charging the GST/HST](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/gst-hst-businesses/when-register-charge.html); [Reporting requirements and deadlines - File your GST/HST return](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/gst-hst-businesses/file-gst-hst-return/reporting-requirements-deadlines.html); [Employers’ Guide – Payroll Deductions and Remittances](https://www.canada.ca/en/revenue-agency/services/forms-publications/publications/t4001/employers-guide-payroll-deductions-remittances.html); [Corporation income tax return](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/corporations/corporation-income-tax-return.html); [Keeping records](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/keeping-records.html); [Business audits](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/changes-your-business/business-audits.html); [Resolving disputes](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/corporations/after-you-file-your-corporation-income-tax-return/resolving-disputes.html)).
- CRA’s official filing/authorization surface is portal- and certified-software-centric: NETFILE/EFILE for T1, Corporation Internet Filing / My Business Account / Represent a Client for T2, and CRA account channels for GST/HST; authorized access is controlled through CRA authorization flows ([Digital services for individuals](https://www.canada.ca/en/revenue-agency/services/e-services/digital-services-individuals.html); [EFILE for electronic filers](https://www.canada.ca/en/revenue-agency/services/e-services/digital-services-individuals/efile-electronic-filers.html); [Using tax preparation software](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/corporations/corporation-income-tax-return/completing-your-corporation-income-tax-t2-return/using-tax-preparation-software.html); [Digital services for businesses](https://www.canada.ca/en/revenue-agency/services/e-services/digital-services-businesses.html); [In your CRA account - File your GST/HST return](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/gst-hst-businesses/file-gst-hst-return/how-file/in-your-cra-account.html); [Authorize a representative: Overview](https://www.canada.ca/en/revenue-agency/services/tax/representative-authorization/overview.html)).

Inference:

- The easiest credible MVP is a skill-only or plugin-packaged copilot that produces categorized books, GST/HST workpapers, payroll checklists, T2125/T2 preparation packs, review-response packages, and objection drafts with source links.
- A filing-capable product is materially harder because the reviewed official sources emphasize certified software, CRA portals, and explicit authorization, not a simple public API surface.

## 1) What the reference repository actually is

The target repository is small and mostly documentation/prompt assets, not a software system with automation depth.

Fact from source:

- The repo presents itself as “Tax Skills for Claude Code,” with 5 skills and 25 Markdown files under `skills/`, and post-2025 law guidance, under MIT license. The tree contains 5 `SKILL.md` files and 20 files under `references/`; the README's phrase “25 reference files” appears to count both groups together ([repo README](https://github.com/davidjelinekk/tax-skills-claude-code); [skills tree](https://github.com/davidjelinekk/tax-skills-claude-code/tree/main/skills)).
- Visible root structure: `.claude/`, `2025/`, `2026/`, `skills/`, `templates/`, `.gitignore`, `CLAUDE.md`, `LICENSE`, `README.md`, `install.sh` ([repo README/tree](https://github.com/davidjelinekk/tax-skills-claude-code)).
- Visible skills: `tax`, `tax-bookkeeping`, `tax-optimize`, `tax-prep`, `tax-audit-risk` ([skills tree](https://github.com/davidjelinekk/tax-skills-claude-code/tree/main/skills)).
- The root `CLAUDE.md` defines a multi-year workspace layout with year folders, entity folders, shared materials, and tracking, so the repo is also a workspace template, not just a skill pack ([CLAUDE.md](https://github.com/davidjelinekk/tax-skills-claude-code/blob/main/CLAUDE.md)).
- The template layer includes at least `templates/entity-workspace.md`, which captures entity metadata, required returns, elections, document checklists, and key calculations ([entity-workspace.md](https://github.com/davidjelinekk/tax-skills-claude-code/blob/main/templates/entity-workspace.md)).
- The visible repository signals are sparse: 2 commits total, 3 stars, 0 forks, 0 issues, 0 pull requests, and no visible test/eval assets in the root tree ([repo README/tree](https://github.com/davidjelinekk/tax-skills-claude-code)).

Fact from accessible skill files:

- `tax` is an orchestrator skill that routes into bookkeeping, optimization, preparation, and audit-risk flows, gathers taxpayer context first, and declares “quality gates” like always including a disclaimer and citing IRC sections ([tax/SKILL.md](https://raw.githubusercontent.com/davidjelinekk/tax-skills-claude-code/main/skills/tax/SKILL.md)).
- `tax-bookkeeping` is a procedural bookkeeping skill that maps transactions to IRS lines, flags ambiguity, tracks 1099 candidates, and uses recordkeeping checklists and quarterly review steps ([tax-bookkeeping/SKILL.md](https://raw.githubusercontent.com/davidjelinekk/tax-skills-claude-code/main/skills/tax-bookkeeping/SKILL.md)).
- `tax-prep` focuses on filing workflows, deadlines, form selection, and document gathering for 1040 / Schedule C / 1065 / 1120-S / Illinois equivalents ([tax-prep/SKILL.md](https://github.com/davidjelinekk/tax-skills-claude-code/blob/main/skills/tax-prep/SKILL.md)).
- `tax-audit-risk` defines a weighted audit-risk model and explicitly admits that the actual IRS DIF algorithm is classified, so the score is directional rather than authoritative ([tax-audit-risk/SKILL.md](https://github.com/davidjelinekk/tax-skills-claude-code/blob/main/skills/tax-audit-risk/SKILL.md)).

Inference:

- The reference repo is a strong pattern for packaging knowledge and workflows, but not yet a strong pattern for regulated production use. It appears optimized for “expert prompt bundle + templates” rather than traceable calculations, refresh automation, or compliance-grade testing.

## 2) What Canada’s official source-of-truth landscape supports

### Sole proprietors / self-employed individuals

Fact from sources:

- CRA expects self-employed business or professional income to be reported on T1 using Form T2125, and recommends T2125 for reporting business or professional income and expenses ([T2125](https://www.canada.ca/en/revenue-agency/services/forms-publications/forms/t2125.html); [Report business income and expenses](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/sole-proprietorships-partnerships/report-business-income-expenses.html)).
- For the 2025 return, self-employed individuals generally file by June 15, 2026, but must pay balances by April 30, 2026 ([Filing due dates for the 2025 tax return](https://www.canada.ca/en/revenue-agency/services/tax/individuals/topics/important-dates-individuals/filing-dates-tax-return.html)).
- Individuals file electronically through NETFILE or through a professional using EFILE; My Account is useful after filing, but it is not the filing channel itself ([Digital services for individuals](https://www.canada.ca/en/revenue-agency/services/e-services/digital-services-individuals.html); [Using My Account – Learn about your taxes](https://www.canada.ca/en/revenue-agency/services/tax/individuals/educational-programs/using-my-account.html)).

Inference:

- A Canadian sole-proprietor MVP is substantially easier than a corporation-first MVP. The form model is simpler, the annual tax year is standardized, and the official sources are relatively centralized.

### Corporations

Fact from sources:

- All resident corporations, including inactive and tax-exempt corporations (with listed exceptions), must file a T2 every tax year even if no tax is payable ([Corporation income tax return](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/corporations/corporation-income-tax-return.html)).
- For tax years starting after 2023, most corporations must file T2 electronically; non-compliance can trigger a $1,000 penalty ([Corporation income tax return](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/corporations/corporation-income-tax-return.html)).
- A T2 is due within six months after the end of the corporation’s tax year ([When to file your corporation income tax return](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/corporations/corporation-income-tax-return/when-file-your-corporation-income-tax-return.html)).
- CRA’s federal corporate rate structure and the small-business deduction are official and current, with federal net rates of 15% general and 9% for eligible CCPC small-business income, plus province/territory rates and business limits ([Corporation tax rates](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/corporations/corporation-tax-rates.html)).

Inference:

- A corporation-capable MVP is still feasible, but only if it treats T2 support as preparation and review assistance, not autonomous filing advice. Even “simple” corporations add fiscal-year variance, GIFI/software constraints, instalments, and province-specific overlays.

### GST/HST

Fact from sources:

- Small suppliers generally do not have to register until they exceed the $30,000 threshold; if they exceed it in a single calendar quarter, GST/HST can attach immediately to the supply that pushes them over the threshold ([When to register for and start charging the GST/HST](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/gst-hst-businesses/when-register-charge.html)).
- Registrants must file a GST/HST return for every reporting period, including nil returns ([Reporting requirements and deadlines - File your GST/HST return](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/gst-hst-businesses/file-gst-hst-return/reporting-requirements-deadlines.html)).
- CRA generally assigns reporting periods based on revenue: annual up to $1.5M, quarterly above $1.5M up to $6M, monthly above $6M, with optional more-frequent elections in some bands ([General Information for GST/HST Registrants](https://www.canada.ca/en/revenue-agency/services/forms-publications/publications/rc4022/general-information-gst-hst-registrants.html)).
- GST/HST rates vary by province, and place-of-supply rules matter; Quebec is a non-participating province for GST/HST purposes and also has separate QST outside special cases ([GST/HST calculator (and rates)](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/gst-hst-businesses/charge-collect-which-rate/calculator.html); [GST/HST rates and place-of-supply rules](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/gst-hst-businesses/charge-collect-place-supply.html); [Place of Supply in a Province – Overview](https://www.canada.ca/en/revenue-agency/services/forms-publications/publications/3-3-2/place-supply-province-overview.html)).
- CRA supports filing GST/HST returns in My Business Account or Represent a Client ([In your CRA account - File your GST/HST return](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/gst-hst-businesses/file-gst-hst-return/how-file/in-your-cra-account.html)).

Inference:

- GST/HST is good MVP territory for a copilot because the official rules are structured and form-based, but it is also one of the highest hallucination-risk areas because thresholds, filing frequency, place-of-supply, and province rates interact.

### Payroll

Fact from sources:

- Employers must register a payroll program account if they pay salaries, wages, bonuses, vacation pay, taxable benefits, or other remuneration requiring deductions/remittances ([Employers’ Guide – Payroll Deductions and Remittances](https://www.canada.ca/en/revenue-agency/services/forms-publications/publications/t4001/employers-guide-payroll-deductions-remittances.html)).
- Employers are responsible for obtaining SIN/TD1 data, withholding income tax/CPP/EI, remitting on time, filing T4/T4A information returns, issuing ROEs when required, and keeping records ([Employers’ Guide – Payroll Deductions and Remittances](https://www.canada.ca/en/revenue-agency/services/forms-publications/publications/t4001/employers-guide-payroll-deductions-remittances.html)).
- Remittance frequency depends on remitter type and average monthly withholding amount; regular remitters generally pay by the 15th of the next month, while some small employers can remit quarterly ([When to remit (pay)](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/payroll/remitting-source-deductions/how-when-remit-due-dates.html)).
- Quebec payroll is materially different: Revenu Québec requires source deductions/contributions in Quebec-specific categories such as Quebec income tax, QPP, QPIP, employer contributions, and separate registration flows ([Employers: Are You Required to Make Source Deductions and Pay Contributions?](https://www.revenuquebec.ca/en/businesses/source-deductions-and-employer-contributions/conditions-for-making-source-deductions-and-paying-contributions/employers-are-you-required-to-make-source-deductions-and-pay-contributions/); [Guide for Employers: Source Deductions and Contributions](https://www.revenuquebec.ca/en/online-services/forms-and-publications/current-details/tp-1015-g-v/); [Registering for Source Deductions](https://www.revenuquebec.ca/en/businesses/source-deductions-and-employer-contributions/registering-for-source-deductions/)).

Inference:

- Payroll should probably be “checklist / calculation-assist / exception-detection” in MVP, not “full payroll engine.”
- Quebec payroll should be excluded or clearly flagged as phase 2 unless there is dedicated Quebec rule maintenance.

## 3) Record retention, audits, reviews, objections

Fact from sources:

- CRA requires businesses to keep organized records; the records required vary by business type, GST/HST status, and payroll status ([Keeping records](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/keeping-records.html)).
- GST/HST registrants generally keep records for 6 years from the end of the year to which they relate ([GST/HST records to keep](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/gst-hst-businesses/calculate-prepare-report/gst-hst-records-keep.html)).
- CRA’s audit and compliance materials say taxpayers generally keep books and records for six years; for corporate taxpayers, certain records must be kept until two years after dissolution ([Income Tax Audit Manual Chapter 10](https://www.canada.ca/en/revenue-agency/services/tax/technical-information/income-tax-audit-manual-domestic-compliance-programs-branch-dcpb-10.html); [Obtaining Information During Compliance Activities](https://www.canada.ca/en/revenue-agency/services/tax/technical-information/compliance-manuals-policies/obtaining-information-during-compliance-activities.html)).
- For electronic records, retained files must be accessible and useable, business system documentation must be maintained, and relevant audit-trail information must be retained ([Electronic Record Keeping](https://www.canada.ca/en/revenue-agency/services/forms-publications/publications/ic05-1/electronic-record-keeping.html)).
- During a business audit, CRA may inspect business records, owners’ personal records, and related-party records; it may request electronic books and records and can use indirect verification methods such as net worth analysis ([Business audits](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/changes-your-business/business-audits.html)).
- CRA supports electronic submission of documents for pre-assessment review / processing review / verification programs, including by authorized representatives with level 2 authorization ([Submitting documents online – Pre-assessment Review, Processing Review, Request Verification and Matching Programs](https://www.canada.ca/en/revenue-agency/services/tax/individuals/topics/about-your-tax-return/review-your-tax-return-cra/submitting-documents-electronically.html)).
- For corporate disputes, objections can be filed online in Represent a Client or My Business Account, or by mail, generally within 90 days of the notice of assessment or reassessment ([Resolving disputes](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/corporations/after-you-file-your-corporation-income-tax-return/resolving-disputes.html); [Important dates for corporations](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/important-dates-businesses/important-dates-corporations.html)).

Inference:

- “Audit readiness” is a realistic product lane. There is enough official structure to build checklists, evidence manifests, document request packets, reconciliation workpapers, and objection-draft workflows with citations.
- “Audit risk scoring” is much riskier. The reference repo can do it for the IRS because it openly frames the score as directional, but a Canadian build should be careful not to imply CRA endorsement or predictive precision.

## 4) Province complexity: where MVP boundaries should be drawn

Fact from sources:

- CRA administers provincial/territorial corporation income tax for most jurisdictions, but not Quebec and Alberta ([Provincial and territorial corporation tax](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/corporations/provincial-territorial-corporation-tax.html); [Income Tax Audit Manual Chapter 12](https://www.canada.ca/en/revenue-agency/services/tax/technical-information/income-tax-audit-manual-domestic-compliance-programs-branch-dcpb-12.html)).
- CRA’s partnership material states Quebec administers its own personal and corporate tax systems and also administers GST on behalf of CRA in the province; Alberta administers its own corporate income tax regime ([Partnerships and stakeholders](https://www.canada.ca/en/revenue-agency/corporate/about-canada-revenue-agency-cra/ministerial-transition-2021/organization/partnerships.html)).
- Alberta separately requires an AT1 for corporations with a permanent establishment in Alberta ([Corporate income tax | Alberta.ca](https://www.alberta.ca/corporate-income-tax)).
- Quebec has a separate payroll regime through Revenu Québec ([Guide for Employers: Source Deductions and Contributions](https://www.revenuquebec.ca/en/online-services/forms-and-publications/current-details/tp-1015-g-v/)).

Inference:

- The cleanest MVP boundary is:
  - include: sole proprietors nationwide for T1/T2125 education, GST/HST, generic recordkeeping, CRA review/audit prep;
  - include cautiously: straightforward CCPC T2 support in CRA-administered corporate jurisdictions;
  - exclude or clearly gate for phase 2: Quebec payroll, Quebec personal/corporate tax, Alberta corporate returns, advanced multi-jurisdiction allocation.

## 5) Filing interfaces and authorization constraints

Fact from sources:

- T1 electronic filing runs through NETFILE for self-filers and EFILE for preparers ([Digital services for individuals](https://www.canada.ca/en/revenue-agency/services/e-services/digital-services-individuals.html); [Overview - EFILE](https://www.canada.ca/en/revenue-agency/services/e-services/digital-services-individuals/efile-electronic-filers/overview.html)).
- As of July 15, 2025, EFILE’s Authorize a Representative service for individual clients is no longer available there; representatives use Represent a Client for online access requests ([EFILE for electronic filers](https://www.canada.ca/en/revenue-agency/services/e-services/digital-services-individuals/efile-electronic-filers.html)).
- T2 electronic filing relies on CRA-certified software and Corporation Internet Filing / My Business Account / Represent a Client ([Using tax preparation software](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/corporations/corporation-income-tax-return/completing-your-corporation-income-tax-t2-return/using-tax-preparation-software.html); [Corporation Internet Filing](https://www.canada.ca/en/revenue-agency/services/e-services/digital-services-businesses/business-account/corporation-internet-filing.html)).
- Businesses and representatives obtain access through My Business Account / Represent a Client, with level-based authorizations; level 2 permits substantive changes and filings ([Authorize a representative: Overview](https://www.canada.ca/en/revenue-agency/services/tax/representative-authorization/overview.html); [How do individuals and businesses authorize me?](https://www.canada.ca/en/revenue-agency/services/e-services/represent-a-client/individuals-businesses-authorize.html); [Confirm my representative's authorization request](https://www.canada.ca/en/revenue-agency/services/tax/representative-authorization/confirm-representative.html)).

Inference:

- I did not find, in the reviewed official sources, a public CRA developer API suitable for a third-party agent to directly submit T1/T2/GST/HST filings on a user’s behalf. The official pattern surfaced here is “certified software + portal + explicit authorization.”
- That makes a service-backed plugin possible, but likely with human-in-the-loop handoff into certified software / portal workflows unless there is later-discovered CRA integration authority.

## 6) Licensing, freshness, hallucination, privacy, and maintenance

### Licensing / reuse risk

Fact from sources:

- The reference repository is MIT-licensed ([repo README](https://github.com/davidjelinekk/tax-skills-claude-code)).
- OpenAI’s current plugin examples repo says a plugin can include a required `.codex-plugin/plugin.json` plus optional `skills/`, `.app.json`, `.mcp.json`, plugin-level `agents/`, `commands/`, `hooks.json`, and assets; OpenAI’s older `openai/skills` repository states it is deprecated in favor of the plugins repo ([OpenAI plugins README](https://github.com/openai/plugins/blob/main/README.md); [openai/skills repo page](https://github.com/openai/skills)).

Inference:

- You can reuse the repo’s high-level structural ideas under MIT, but should be conservative about copying domain prose wholesale. A safer path is to author Canada-specific content from first-party sources and store source links + effective dates alongside each rule.
- A Canadian build should avoid inheriting U.S.-specific logic or prompts by adaptation alone; it should be source-recomposed.

### Freshness / versioning risk

Fact from sources:

- Multiple reviewed pages have recent, mutable dates and operational changes: e.g. CRA corporation rates page updated 2025-05-30, GST/HST records page updated 2026-03-05, EFILE 2026 transmission window published, and representative authorization pages changed in 2025-2026 ([Corporation tax rates](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/corporations/corporation-tax-rates.html); [GST/HST and payroll records](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/keeping-records/gst-hst-payroll-records.html); [EFILE for electronic filers](https://www.canada.ca/en/revenue-agency/services/e-services/digital-services-individuals/efile-electronic-filers.html); [Authorize a representative: Overview](https://www.canada.ca/en/revenue-agency/services/tax/representative-authorization/overview.html)).

Inference:

- This product needs tax-year versioning, dated rule packs, and refresh workflows. “Current guidance” without an effective date is not safe enough.

### Hallucination / compliance risk

Inference:

- Highest-risk topics for wrong answers are GST/HST place-of-supply, provincial corporate exceptions, payroll remittance class, worker classification side effects, and objection deadlines.
- The safest posture is to require every substantive output to carry:
  - tax year / filing period;
  - jurisdiction;
  - source links;
  - “facts supplied by user” vs “facts inferred/assumed”;
  - “needs accountant/lawyer review” triggers.

### Privacy / security

Fact from sources:

- CRA representatives are expected to protect confidentiality and security when accessing taxpayer information ([Responsibilities of authorized representatives](https://www.canada.ca/en/revenue-agency/services/e-services/represent-a-client/responsibilities-authorized-representatives.html)).
- CRA audit materials show that highly sensitive records can be in scope, including personal financial records of owners and related parties ([Business audits](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/changes-your-business/business-audits.html)).
- The Office of the Privacy Commissioner of Canada treats financial information as sensitive and says safeguards must be appropriate to sensitivity. PIPEDA also requires limiting collection, use, disclosure, and retention, and an organization remains accountable when personal information is transferred to a cloud provider for processing ([PIPEDA safeguards](https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/the-personal-information-protection-and-electronic-documents-act-pipeda/p_principle/principles/p_safeguards/); [PIPEDA fair information principles](https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/the-personal-information-protection-and-electronic-documents-act-pipeda/p_principle/); [cloud computing FAQ](https://www.priv.gc.ca/en/privacy-topics/technology/online-privacy-tracking-cookies/online-privacy/cloud-computing/02_05_d_51_cc_faq/)).

Inference:

- Even an MVP that avoids filing still touches SINs, BN/program account details, payroll records, invoices, bank statements, and spouse/household financial data in audit contexts. That argues for strict data minimization, explicit consent boundaries, encryption at rest/in transit, per-workspace access controls, and structured deletion/retention policies.
- A local-first MVP is preferable to a cloud-backed MVP until the product has a privacy impact assessment, processor contracts, access logging, retention controls, and an incident-response process.

### Maintenance burden

Inference:

- The maintenance burden is moderate for bookkeeping templates, high for GST/HST and payroll, and very high for province-specific corporate content. Quebec alone can justify a separate track.

## 7) Product-shape comparison

### A. Skill-only

Best for:

- source-backed checklists;
- bookkeeping categorization guidance;
- T2125/T2 prep packets;
- audit-readiness and objection drafting.

Pros:

- fastest to build;
- lowest infrastructure and privacy burden;
- easiest to distribute and iterate;
- good fit for the reference repo pattern.

Cons:

- weakest freshness enforcement;
- highest prompt-level hallucination risk unless heavily source-disciplined;
- limited audit trail;
- no authenticated CRA/accounting-system integration.

My view:

- Good for an internal prototype or a narrow educational MVP.

### B. Installable Codex plugin (skills + optional MCP/app surface)

Fact from source:

- OpenAI’s examples repo supports exactly this mixed shape: a plugin bundle can include skills plus optional MCP/app/commands/hooks surfaces ([OpenAI plugins README](https://github.com/openai/plugins/blob/main/README.md)).

Pros:

- still relatively lightweight;
- can package skill routing, local tools, calculators, templates, and validation scripts together;
- better UX than loose skills;
- can create clearer boundaries between “knowledge,” “workpapers,” and “live actions.”

Cons:

- still not enough by itself for compliant filing flows unless paired with authoritative services or certified software/human steps;
- more packaging and maintenance overhead than skill-only.

My view:

- This is the best default shape for MVP if the goal is a reusable Canadian tax/bookkeeping assistant for Codex users.

### C. Service-backed plugin

Best for:

- secure workpaper storage;
- ledger ingestion;
- deterministic calculations;
- jurisdiction packs and versioned rules;
- audit logs;
- human-review queues;
- possible accounting-software integrations.

Pros:

- strongest control over freshness, security, traceability, and evaluations;
- best long-term foundation if this becomes a real product.

Cons:

- highest cost and operational burden;
- requires privacy/compliance engineering;
- still constrained by CRA authorization/certified-software realities for filing.

My view:

- This is the right end-state if you want something commercially serious. It is probably overkill for v1 unless live integrations are core to the thesis.

## 8) Recommended MVP

Recommended MVP scope:

1. Sole proprietor first, plus optional “simple CCPC” preparation support.
2. Outside Quebec payroll and outside Quebec/Alberta corporate filing for the first release.
3. No autonomous filing.
4. Outputs:
   - tax-year intake questionnaire;
   - bookkeeping categorization and chart-of-accounts templates;
   - GST/HST threshold checker, filing calendar, and return workpaper;
   - payroll onboarding/remittance checklist;
   - T2125 preparation pack;
   - T2 preparation checklist for simple corporations;
   - CRA review/audit document request organizer;
   - objection-draft helper with cited facts and timelines.
5. Every answer must cite official sources and mark assumptions.

Recommended packaging:

- installable Codex plugin with:
  - a router skill;
  - dedicated skills for bookkeeping, GST/HST, payroll, T1/T2125, T2 prep, and audit-readiness;
  - optional local validation scripts for dates/rates/thresholds;
  - optional MCP/service layer only when you need storage, ingestion, or versioned rule updates.

## 9) Test and evaluation requirements before shipping

Inference:

- You should not ship this without a standing eval suite. Minimum useful eval set:
  - sole prop vs corporation classification;
  - GST/HST registration threshold edge cases;
  - annual/quarterly/monthly GST/HST reporting-period assignments;
  - self-employed filing/payment dates;
  - T2 six-month filing date calculations;
  - payroll remitter-type scenarios;
  - Quebec exclusion/gating behavior;
  - source citation presence and recency;
  - “I don’t know / seek professional advice” behavior for ambiguous or high-stakes cases.
- Each rule should have: source URL, page date, effective date, jurisdiction, tax year, and a machine-testable expected output.

## 10) Overall conclusion

Feasible: yes.

Feasible as a pure “Canadian tax filing agent”: not from the reviewed sources.

Best path:

- Start with a Codex plugin package centered on source-backed skills and workpaper generation.
- Keep the MVP narrow: sole proprietors, GST/HST, payroll basics, audit-readiness, and simple T2 prep.
- Add a service layer only when you need versioned rules, secure storage, or integration.
- Treat Quebec and Alberta as explicit scope boundaries unless you invest in dedicated maintenance.

## 11) Recommended product boundary and phased plan

### Naming and regulated-service boundary

Fact from source:

- In Ontario, an assurance engagement, including an audit or review engagement concerning financial statements and intended for third-party reliance, is part of regulated public accounting ([Ontario Public Accounting Act, 2004, section 2](https://www.ontario.ca/laws/statute/s04008); [CPA Ontario public accounting licence guidance](https://www.cpaontario.ca/members/regulations-guidance/public-accounting-licence)). Other provinces have their own professional regimes.

Inference:

- The product should use **CRA review/audit readiness**, **evidence readiness**, or **books health check** in its name. It should not claim to perform an assurance audit, issue an audit/review opinion, predict CRA selection, or replace a licensed public accountant.

### Recommended first release

The narrowest commercially useful first release is an installable plugin containing source-backed skills and local deterministic scripts, with no MCP server and no cloud storage:

1. `canada-small-business-tax` — intake and routing; fixes tax year, entity type, province, GST/HST status, accounting basis, and supported-scope decision before work starts.
2. `close-canadian-small-business-books` — imports user-provided CSVs, maps a small chart of accounts, reconciles bank/credit-card totals, separates personal/owner items, tracks source documents, and produces an exception queue instead of guessing.
3. `prepare-ontario-sole-proprietor-tax-pack` — prepares an Ontario sole-proprietor T2125 workpaper and GST/HST workpaper; it does not calculate or submit a complete T1 return.
4. `prepare-cra-review-package` — builds an evidence index, source-to-ledger-to-workpaper trail, revenue reconciliation, missing-document list, and draft response outline for human review.

The first release should explicitly exclude corporations/T2, payroll calculations, Quebec, Alberta corporate tax, other provincial sales taxes, cross-border tax, trusts, partnerships, actual filing, tax optimization strategies, objections, and assurance opinions. These are expansion tracks, not hidden fallbacks.

### Proposed internal architecture

- **Versioned rule packs:** every rule carries source URL, jurisdiction, tax year/period, effective date, last-reviewed date, and an expiry/review date.
- **Case manifest:** one business, one period, declared entity/province/accounting basis, file inventory, consent, and human reviewer.
- **Canonical transaction schema:** immutable source reference, normalized amount/date/payee, tax treatment candidates, classification confidence, human confirmation, and change history.
- **Deterministic scripts:** decimal arithmetic, date/deadline calculations, GST/HST threshold logic, reconciliation, totals, invariant checks, and report generation. The model may classify or explain; it must not perform authoritative arithmetic in prose.
- **Evidence graph and audit log:** source document → transaction → ledger account → tax workpaper line, with append-only corrections showing who changed what, when, and why. This matches CRA's emphasis on electronically readable records and source-to-account audit trails ([Electronic Record Keeping](https://www.canada.ca/en/revenue-agency/services/forms-publications/publications/ic05-1/electronic-record-keeping.html)).
- **Hard stops:** unsupported jurisdiction/entity, stale rule pack, unreconciled account, missing critical source, ambiguous tax treatment, or absent human confirmation prevents finalization.

### Delivery phases and rough effort

These estimates assume one experienced builder with part-time review by a Canadian CPA/bookkeeper and privacy counsel where indicated.

| Phase | Scope | Rough effort | Exit criterion |
|---|---|---:|---|
| 0. Domain design | Ontario sole-proprietor scenarios, output contracts, source registry, professional/privacy review | 1–2 weeks | Written boundaries and 30–50 representative cases approved |
| 1. Bookkeeping core | Plugin shell, router, case/transaction schemas, CSV ingest, reconciliation, evidence trail, close report | 3–5 weeks | Golden ledgers reconcile; no silent classification of ambiguous items |
| 2. Tax-prep MVP | T2125 and GST/HST workpapers, deadline/threshold calculators, CRA review package | 3–5 weeks | CPA-reviewed golden cases and policy-expiry tests pass |
| 3. Pilot hardening | 5–10 controlled pilot businesses, privacy controls, bilingual UX if required, failure-mode/eval expansion | 3–4 weeks | All material discrepancies are traceable and human-resolved |
| 4. Expansion | Simple CCPC/T2 preparation, payroll checklist, then selected provinces | 6–10 weeks per major track | Separate reviewed jurisdiction/entity packs and regression suites |
| 5. Integrations | Read-only accounting-platform MCP; write-back only after a separate authorization/security review | 6–10+ weeks | Least-privilege OAuth, idempotency, audit logs, deletion/export controls |

Direct CRA submission should be treated as a separate product program. It should proceed only through CRA-certified software or a qualified partner and the applicable representative/authorization process.

### Release gates

Do not ship the MVP until it has:

- double-entry and reconciliation invariants;
- unit tests for every deterministic threshold, date, and formula;
- golden cases for normal, ambiguous, missing-record, mixed personal/business, and GST/HST edge cases;
- activation and non-activation evaluations for each skill;
- adversarial-document tests, including instructions embedded in receipts or CSV cells;
- citation, jurisdiction, tax-year, and rule-expiry checks on every finalized workpaper;
- human sign-off captured separately from model output;
- documented retention, deletion, export, access-control, and incident-response behavior.
