# Assessment Rules

## Application Integrity

- `no_confirmed_issue`: core evidence exists and no pending or human-confirmed material conflict remains.
- `clarification_pending`: at least one fact needs clarification.
- `human_confirmed_material_conflict`: a human confirmed materiality after authoritative verification.
- `insufficient_evidence`: core evidence cannot support classification.

Display every discrepancy. Never call an applicant fraudulent. Only an issuing or authoritative source can confirm a document is false, and a human decides materiality.

## Payment Evidence

- `no_current_negative_payment_evidence_found`
- `negative_payment_evidence_requires_human_review`
- `limited_evidence`
- `unable_to_assess`

Only verified, current, core-surface delinquencies, collections, charge-offs, rent arrears, repeated late-rent records, or applicant-acknowledged unresolved payment facts can trigger human review. Missing credit or rental history, unanswered references, public records, total debt, utilization alone, and expired credit information are never negative evidence.

A manager-authorized credit report is current for 30 days. An applicant-supplied report remains unverified. Show an official score and its reported factors when present, but apply no cutoff and never let a score alone change a state.

## Financial Facts

Use Decimal script output only.

- Fixed annual gross employment income: annual amount divided by 12.
- Biweekly gross income: amount multiplied by 26 and divided by 12.
- Weekly gross income: amount multiplied by 52 and divided by 12.
- Variable income: confirmed total divided by actual covered months, up to 12; do not annualize a shorter history.
- Self-employment: net business income after business expenses and before personal tax.
- Exclude one-time or unconfirmed income from recurring totals and list it separately.

Sum only explicit confirmed monthly debt payments. Show confirmed balances with unknown monthly payments separately. Never estimate a payment from balance, interest, or account type. A negative debt amount is invalid.

The only rent-coverage rule is confirmed recurring monthly income greater than or equal to monthly rent. Report `covers`, `does_not_cover`, or `insufficient_evidence`.

Do not calculate debt-to-income, rent-to-income, income multiples, residual income, post-rent living expenses, or an affordability score. Keep income and debt as separate facts.

## Recommendations

Use exactly one:

- `Evidence is sufficient for a human rental decision.`
- `Complete the listed verification before deciding.`
- `Confirmed material facts require human and compliance review.`
- `Evidence is insufficient to assess the application.`

These summarize evidence readiness. They do not choose the tenancy outcome.

## Accommodation

When disability, domestic violence, family status, or another protected circumstance may explain an issue, isolate the details and stop automated classification for that issue. Route it for individualized accommodation and compliance review.
