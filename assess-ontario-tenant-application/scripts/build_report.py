"""Render an auditable assessment package with a hard-isolated web appendix."""

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from scripts.shared import ValidationResult, write_json
from scripts.validate_evidence import EvidenceResult


RECOMMENDATIONS = {
    "ready": "Evidence is sufficient for a human rental decision.",
    "verify": "Complete the listed verification before deciding.",
    "compliance": "Confirmed material facts require human and compliance review.",
    "insufficient": "Evidence is insufficient to assess the application.",
}
ALLOWED_REASON_CODES = [
    "chronological_first_meeting_uniform_criteria",
    "applicant_withdrew",
    "required_evidence_not_supplied_by_deadline",
    "confirmed_material_conflict",
    "other_requires_explanation",
]
ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets"


def recommendation_for(
    states: EvidenceResult, preflight: ValidationResult
) -> str:
    if (
        not preflight.can_finalize
        or states.payment_state == "unable_to_assess"
        or states.integrity_state == "insufficient_evidence"
    ):
        return RECOMMENDATIONS["insufficient"]
    if (
        states.requires_accommodation_review
        or states.integrity_state == "human_confirmed_material_conflict"
    ):
        return RECOMMENDATIONS["compliance"]
    if states.integrity_state == "clarification_pending" or states.payment_state in {
        "negative_payment_evidence_requires_human_review",
        "limited_evidence",
    }:
        return RECOMMENDATIONS["verify"]
    return RECOMMENDATIONS["ready"]


def _public_issue(code: str) -> bool:
    return code.startswith(("PUBLIC_", "SOCIAL_", "OPEN_WEB_"))


def _render_assessment(
    manifest: dict[str, Any],
    evidence: dict[str, Any],
    financials: dict[str, Any],
    states: EvidenceResult,
    preflight: ValidationResult,
    policy: dict[str, Any],
) -> str:
    housing = manifest.get("housing", {})
    lines = [
        "# Ontario Tenant Application Evidence Assessment",
        "",
        f"- Case ID: {manifest.get('case_id', '')}",
        f"- Property: {housing.get('address', '')}",
        f"- Monthly rent (CAD): {financials.get('monthly_rent_cad', '')}",
        f"- Policy version: {policy.get('version', '')}",
        "",
        "## Evidence States",
        "",
        f"- Application integrity: {states.integrity_state}",
        f"- Rent-payment evidence: {states.payment_state}",
        "",
        "## Confirmed Financial Facts",
        "",
    ]
    for applicant_id, facts in financials.get("applicants", {}).items():
        lines.extend(
            [
                f"### Applicant {applicant_id}",
                "",
                f"- Confirmed recurring monthly income (CAD): {facts.get('gross_monthly_income_cad', '0.00')}",
                f"- Reported monthly debt payments (CAD): {facts.get('reported_monthly_debt_cad', '0.00')}",
                f"- Accounts with unknown monthly payments: {facts.get('unknown_monthly_payment_accounts', 0)}",
                f"- Limited income history: {'yes' if facts.get('limited_income_history') else 'no'}",
                "",
            ]
        )
        for balance in facts.get("unknown_monthly_payment_balances", []):
            lines.append(
                f"- Unknown-payment account balance (CAD): {balance.get('balance_cad', '')}"
            )
        if facts.get("unknown_monthly_payment_balances"):
            lines.append("")

    household = financials.get("household", {})
    lines.extend(
        [
            "### Signing Applicants Combined",
            "",
            f"- Confirmed recurring monthly income (CAD): {household.get('gross_monthly_income_cad', '0.00')}",
            f"- Reported monthly debt payments (CAD): {household.get('reported_monthly_debt_cad', '0.00')}",
            f"- Accounts with unknown monthly payments: {household.get('unknown_monthly_payment_accounts', 0)}",
            f"- Rent coverage: {household.get('rent_coverage', 'insufficient_evidence')}",
            "",
        ]
    )

    credit_report = evidence.get("core", {}).get("credit_report")
    if credit_report:
        lines.extend(
            [
                "## Credit Evidence",
                "",
                f"- Acquisition: {credit_report.get('acquisition', '')}",
                f"- Generated at: {credit_report.get('generated_at', '')}",
            ]
        )
        if credit_report.get("score") is not None:
            lines.append(f"- Reported official score: {credit_report['score']}")
        for factor in credit_report.get("reported_factors", []):
            lines.append(f"- Reported factor: {factor}")
        lines.append("")

    limitations = [
        issue
        for issue in (*preflight.issues, *states.issues)
        if not _public_issue(issue.code)
    ]
    lines.extend(["## Confidence and Review Items", ""])
    if limitations:
        lines.extend(f"- {issue.code}: {issue.message}" for issue in limitations)
    else:
        lines.append("- No unresolved core validation item was recorded.")
    lines.extend(
        [
            "",
            "## Recommendation Summary",
            "",
            recommendation_for(states, preflight),
            "",
            "## Human Review Checklist",
            "",
            "- Confirm every critical value and source location.",
            "- Give the applicant an opportunity to address listed discrepancies.",
            "- Complete the separate human-decision record.",
            "- Run the retention tool in dry-run mode after the case is completed or withdrawn.",
            "",
        ]
    )
    return "\n".join(lines)


def _core_evidence(
    manifest: dict[str, Any],
    evidence: dict[str, Any],
    financials: dict[str, Any],
    states: EvidenceResult,
    preflight: ValidationResult,
    policy: dict[str, Any],
) -> dict[str, Any]:
    facts = []
    allowed_fact_fields = (
        "applicant_id",
        "fact_type",
        "normalized_value",
        "source_file",
        "location",
        "reporting_period",
        "currency",
        "gross_or_net",
        "confidence",
        "confirmed",
    )
    for fact in evidence.get("core_facts", []):
        facts.append({key: fact.get(key) for key in allowed_fact_fields if key in fact})
    return {
        "schema_version": "1.0",
        "case_id": manifest.get("case_id", ""),
        "policy_version": policy.get("version", ""),
        "can_finalize": preflight.can_finalize,
        "integrity_state": states.integrity_state,
        "payment_state": states.payment_state,
        "core_facts": facts,
        "financials": financials,
        "issues": [
            asdict(issue)
            for issue in (*preflight.issues, *states.issues)
            if not _public_issue(issue.code)
        ],
        "recommendation": recommendation_for(states, preflight),
    }


def _render_discrepancies(evidence: dict[str, Any]) -> str:
    lines = ["# Discrepancies", ""]
    discrepancies = evidence.get("discrepancies", [])
    if not discrepancies:
        lines.extend(["No discrepancy was recorded.", ""])
        return "\n".join(lines)
    for index, item in enumerate(discrepancies, start=1):
        lines.extend(
            [
                f"## Discrepancy {index}",
                "",
                f"- Classification: {item.get('classification', 'parsing_uncertainty')}",
                f"- Applicant: {item.get('applicant_id', '')}",
                f"- Fact: {item.get('fact_type', '')}",
                f"- Source A: {item.get('source_a', '')}",
                f"- Source B: {item.get('source_b', '')}",
                f"- Human-confirmed: {'yes' if item.get('human_confirmed') else 'no'}",
                f"- Disposition: {item.get('human_disposition', '')}",
                "",
            ]
        )
    return "\n".join(lines)


def _render_public_records(states: EvidenceResult) -> str:
    lines = [
        "# Public-Source Appendix",
        "",
        "Not an official criminal record check; not used in evidence states or recommendations.",
        "",
    ]
    if not states.accepted_public_records:
        lines.extend(["No identity-matched public record was accepted for display.", ""])
    for index, record in enumerate(states.accepted_public_records, start=1):
        lines.extend(
            [
                f"## Record {index}",
                "",
                f"- Source type: {record.get('source_type', '')}",
                f"- URL: {record.get('url', '')}",
                f"- Identity matches: {', '.join(record.get('identity_matches', []))}",
            ]
        )
        for key, label in (
            ("party_role", "Party role"),
            ("case_type", "Case type"),
            ("status", "Status"),
            ("result", "Result"),
            ("finding_against_applicant", "Finding against applicant"),
            ("source_name", "Source name"),
            ("retrieved_at", "Retrieved at"),
            ("excerpt", "Minimal excerpt"),
        ):
            if key in record:
                lines.append(f"- {label}: {record[key]}")
        if record.get("permitted_facts"):
            for key, value in record["permitted_facts"].items():
                lines.append(f"- Permitted fact {key}: {value}")
        lines.append("")
    public_issues = [issue for issue in states.issues if _public_issue(issue.code)]
    if public_issues:
        lines.extend(["## Excluded or Limited Results", ""])
        lines.extend(f"- {issue.code}: {issue.message}" for issue in public_issues)
        lines.append("")
    return "\n".join(lines)


def _write_audit(path: Path, case_id: str, artifacts: list[Path]) -> None:
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    events = [
        {
            "timestamp": timestamp,
            "event": "assessment_package_built",
            "case_id": case_id,
        },
        *(
            {
                "timestamp": timestamp,
                "event": "artifact_written",
                "case_id": case_id,
                "artifact": artifact.name,
            }
            for artifact in artifacts
        ),
    ]
    path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )


def build_package(
    case_dir: Path,
    manifest: dict[str, Any],
    evidence: dict[str, Any],
    financials: dict[str, Any],
    states: EvidenceResult,
    preflight: ValidationResult,
    policy: dict[str, Any],
) -> list[Path]:
    outputs = case_dir / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)

    assessment_path = outputs / "assessment.md"
    assessment_path.write_text(
        _render_assessment(manifest, evidence, financials, states, preflight, policy),
        encoding="utf-8",
    )
    evidence_path = outputs / "evidence.json"
    write_json(
        evidence_path,
        _core_evidence(manifest, evidence, financials, states, preflight, policy),
    )
    discrepancy_path = outputs / "discrepancies.md"
    discrepancy_path.write_text(_render_discrepancies(evidence), encoding="utf-8")
    public_path = outputs / "public-records.md"
    public_path.write_text(_render_public_records(states), encoding="utf-8")

    decision_path = outputs / "human-decision.json"
    write_json(
        decision_path,
        {
            "decided_by": "",
            "decided_at": "",
            "selected_reason_code": "",
            "other_explanation": "",
            "allowed_reason_codes": ALLOWED_REASON_CODES,
        },
    )

    outreach_dir = outputs / "outreach"
    outreach_dir.mkdir(exist_ok=True)
    outreach_paths = []
    for template in sorted((ASSET_ROOT / "outreach-templates").glob("*.md")):
        target = outreach_dir / template.name
        target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        outreach_paths.append(target)

    artifacts = [
        assessment_path,
        evidence_path,
        discrepancy_path,
        public_path,
        decision_path,
        *outreach_paths,
    ]
    audit_path = outputs / "audit.jsonl"
    _write_audit(audit_path, str(manifest.get("case_id", "")), artifacts)
    artifacts.append(audit_path)
    return artifacts
