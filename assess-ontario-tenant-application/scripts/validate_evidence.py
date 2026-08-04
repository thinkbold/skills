"""Derive bounded evidence states and isolate public-source records."""

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from scripts.redact_sensitive_data import PROTECTED_KEYS, normalize_field_name
from scripts.shared import ValidationIssue, parse_date


ALLOWED_PUBLIC_SOURCES = {
    "government",
    "court",
    "tribunal",
    "canlii",
    "ltb",
    "corporate_registry",
    "professional_registry",
    "official_site",
    "news",
    "facebook",
    "linkedin",
}
SOCIAL_SOURCES = {"facebook", "linkedin"}
ALLOWED_NEGATIVE_PAYMENT_FACTS = {
    "current_delinquency",
    "current_collection",
    "current_charge_off",
    "verified_rent_arrears",
    "confirmed_repeated_late_rent",
    "acknowledged_unresolved_payment",
}
SOCIAL_RECORD_KEYS = {
    "source_type",
    "url",
    "source_id",
    "source_name",
    "retrieved_at",
    "identity_matches",
    "permitted_facts",
}
SOCIAL_FACT_KEYS = {
    "identity_exists",
    "profile_name_matches",
    "declared_employer_matches",
    "declared_role_matches",
    "declared_education_matches",
}
FULL_PAGE_KEYS = {"full_page_content", "raw_html", "screenshot", "page_dump"}
PUBLIC_SEARCH_OUTCOME_KEYS = {"source_type", "status", "searched_at"}
PUBLIC_SEARCH_OUTCOME_STATES = {"no_match", "private", "no_displayable_match"}


@dataclass(frozen=True)
class EvidenceResult:
    integrity_state: str
    payment_state: str
    accepted_public_records: tuple[dict[str, Any], ...]
    issues: tuple[ValidationIssue, ...]
    requires_accommodation_review: bool
    public_search_outcomes: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "integrity_state": self.integrity_state,
            "payment_state": self.payment_state,
            "accepted_public_records": list(self.accepted_public_records),
            "issues": [asdict(issue) for issue in self.issues],
            "requires_accommodation_review": self.requires_accommodation_review,
            "public_search_outcomes": list(self.public_search_outcomes),
        }


def _contains_key(value: Any, keys: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            normalize_field_name(key) in keys or _contains_key(item, keys)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_key(item, keys) for item in value)
    return False


def _core_references_public(core: Any, public_ids: set[str]) -> bool:
    if isinstance(core, dict):
        if core.get("source_surface") == "public":
            return True
        if str(core.get("source_id", "")) in public_ids:
            return True
        return any(_core_references_public(item, public_ids) for item in core.values())
    if isinstance(core, list):
        return any(_core_references_public(item, public_ids) for item in core)
    return False


def _public_records(
    evidence: dict[str, Any], manifest: dict[str, Any]
) -> tuple[tuple[dict[str, Any], ...], list[ValidationIssue]]:
    records = evidence.get("public_records", [])
    issues: list[ValidationIssue] = []
    accepted: list[dict[str, Any]] = []
    general = manifest.get("authorizations", {}).get("general", {})
    social = manifest.get("authorizations", {}).get("social", {})
    granted_platforms = set(social.get("platforms", []))

    public_ids = {
        str(record["source_id"])
        for record in records
        if record.get("source_id") is not None
    }
    if _core_references_public(evidence.get("core", {}), public_ids):
        issues.append(
            ValidationIssue(
                "PUBLIC_RECORD_REFERENCED_BY_CORE",
                "blocking_finalization",
                "Public-source records must not feed core evidence.",
            )
        )
        return (), issues

    for record in records:
        source_type = record.get("source_type")
        if general.get("open_web_disclosed") is not True:
            issues.append(
                ValidationIssue(
                    "OPEN_WEB_DISCLOSURE_REQUIRED",
                    "excluded",
                    "General authorization does not disclose open-web checks.",
                )
            )
            continue
        if source_type not in ALLOWED_PUBLIC_SOURCES:
            issues.append(
                ValidationIssue(
                    "PUBLIC_SOURCE_NOT_ALLOWED",
                    "excluded",
                    str(source_type),
                )
            )
            continue
        identity_matches = record.get("identity_matches", [])
        if (
            not isinstance(identity_matches, list)
            or not all(isinstance(item, str) for item in identity_matches)
            or len(set(identity_matches)) < 2
        ):
            issues.append(
                ValidationIssue(
                    "PUBLIC_IDENTITY_MATCH_INSUFFICIENT",
                    "excluded",
                    str(record.get("url", "")),
                )
            )
            continue
        if _contains_key(record, PROTECTED_KEYS):
            issues.append(
                ValidationIssue(
                    "PUBLIC_RECORD_PROTECTED_DATA",
                    "excluded",
                    str(record.get("url", "")),
                )
            )
            continue
        if _contains_key(record, FULL_PAGE_KEYS):
            issues.append(
                ValidationIssue(
                    "PUBLIC_FULL_PAGE_CONTENT_NOT_ALLOWED",
                    "excluded",
                    str(record.get("url", "")),
                )
            )
            continue
        if source_type in SOCIAL_SOURCES:
            if social.get("status") != "granted" or source_type not in granted_platforms:
                issues.append(
                    ValidationIssue(
                        "SOCIAL_CONSENT_REQUIRED",
                        "excluded",
                        str(source_type),
                    )
                )
                continue
            facts = record.get("permitted_facts", {})
            if (
                set(record) - SOCIAL_RECORD_KEYS
                or not isinstance(facts, dict)
                or set(facts) - SOCIAL_FACT_KEYS
            ):
                issues.append(
                    ValidationIssue(
                        "SOCIAL_FIELD_NOT_ALLOWED",
                        "excluded",
                        str(record.get("url", "")),
                    )
                )
                continue
        accepted.append(record)
    return tuple(accepted), issues


def _public_search_outcomes(
    evidence: dict[str, Any], manifest: dict[str, Any]
) -> tuple[tuple[dict[str, Any], ...], list[ValidationIssue]]:
    outcomes = evidence.get("public_search_outcomes", [])
    issues: list[ValidationIssue] = []
    accepted: list[dict[str, Any]] = []
    authorizations = manifest.get("authorizations", {})
    general = authorizations.get("general", {})
    social = authorizations.get("social", {})
    granted_platforms = set(social.get("platforms", []))

    for outcome in outcomes:
        source_type = outcome.get("source_type")
        if general.get("open_web_disclosed") is not True:
            continue
        if source_type not in ALLOWED_PUBLIC_SOURCES:
            issues.append(
                ValidationIssue(
                    "PUBLIC_SEARCH_OUTCOME_SOURCE_NOT_ALLOWED",
                    "excluded",
                    str(source_type),
                )
            )
            continue
        if set(outcome) - PUBLIC_SEARCH_OUTCOME_KEYS:
            issues.append(
                ValidationIssue(
                    "PUBLIC_SEARCH_OUTCOME_FIELD_NOT_ALLOWED",
                    "excluded",
                    str(source_type),
                )
            )
            continue
        if outcome.get("status") not in PUBLIC_SEARCH_OUTCOME_STATES:
            continue
        if source_type in SOCIAL_SOURCES and (
            social.get("status") != "granted" or source_type not in granted_platforms
        ):
            continue
        accepted.append(
            {
                "source_type": source_type,
                "status": outcome["status"],
                "searched_at": outcome.get("searched_at", ""),
            }
        )
    return tuple(accepted), issues


def validate_and_classify(
    evidence: dict[str, Any],
    manifest: dict[str, Any],
    today: date | None = None,
) -> EvidenceResult:
    today = today or date.today()
    issues: list[ValidationIssue] = []

    if evidence.get("accommodation_review_required") is True:
        issues.append(
            ValidationIssue(
                "ACCOMMODATION_REVIEW_REQUIRED",
                "blocking_finalization",
                "Automated classification stopped for individualized review.",
            )
        )
        return EvidenceResult(
            "insufficient_evidence", "unable_to_assess", (), tuple(issues), True
        )

    core = evidence.get("core", {})
    discrepancies = evidence.get("discrepancies", [])
    financial_input = evidence.get("financial_input", {})
    critical_value_unconfirmed = any(
        fact.get("critical") is True and fact.get("confirmed") is not True
        for fact in evidence.get("core_facts", [])
    ) or any(
        record.get("recurring") is True and record.get("confirmed") is not True
        for record in financial_input.get("incomes", [])
    ) or any(
        record.get("monthly_payment") is not None
        and record.get("confirmed") is not True
        for record in financial_input.get("debts", [])
    )
    if critical_value_unconfirmed:
        issues.append(
            ValidationIssue(
                "CRITICAL_VALUE_UNCONFIRMED",
                "blocking_finalization",
                "A critical value requires human or validated structured confirmation.",
            )
        )
    if core.get("evidence_available") is not True:
        integrity_state = "insufficient_evidence"
    elif any(
        item.get("classification") == "confirmed_material_conflict"
        and item.get("human_confirmed") is True
        for item in discrepancies
    ):
        integrity_state = "human_confirmed_material_conflict"
    elif critical_value_unconfirmed or any(
        not item.get("human_disposition")
        or item.get("classification")
        in {"needs_clarification", "clarification_pending"}
        for item in discrepancies
    ):
        integrity_state = "clarification_pending"
    else:
        integrity_state = "no_confirmed_issue"

    credit_report = core.get("credit_report")
    credit_report_usable = True
    if credit_report:
        if credit_report.get("acquisition") != "manager_authorized":
            credit_report_usable = False
            issues.append(
                ValidationIssue(
                    "CREDIT_REPORT_UNVERIFIED",
                    "limitation",
                    "Applicant-supplied credit information is not independently verified.",
                )
            )
        else:
            generated_at = parse_date(
                credit_report.get("generated_at"), "core.credit_report.generated_at"
            )
            report_age = (today - generated_at).days
            if report_age < 0:
                credit_report_usable = False
                issues.append(
                    ValidationIssue(
                        "CREDIT_REPORT_FUTURE_DATE",
                        "limitation",
                        "Credit report generation date is after the assessment date.",
                    )
                )
            elif report_age > 30:
                credit_report_usable = False
                issues.append(
                    ValidationIssue(
                        "CREDIT_REPORT_STALE",
                        "limitation",
                        "Credit report is more than 30 days old.",
                    )
                )

    has_negative_fact = False
    for fact in evidence.get("payment_facts", []):
        if (
            fact.get("kind") not in ALLOWED_NEGATIVE_PAYMENT_FACTS
            or fact.get("verified") is not True
            or fact.get("current") is not True
            or fact.get("source_surface") != "core"
        ):
            continue
        if fact.get("source_id") == "credit-report" and not credit_report_usable:
            continue
        has_negative_fact = True
        break

    if core.get("evidence_available") is not True:
        payment_state = "unable_to_assess"
    elif has_negative_fact:
        payment_state = "negative_payment_evidence_requires_human_review"
    elif (
        core.get("credit_history_available") is False
        or core.get("rental_history_available") is False
    ):
        payment_state = "limited_evidence"
    else:
        payment_state = "no_current_negative_payment_evidence_found"

    accepted_public_records, public_issues = _public_records(evidence, manifest)
    issues.extend(public_issues)
    public_search_outcomes, outcome_issues = _public_search_outcomes(
        evidence, manifest
    )
    issues.extend(outcome_issues)
    return EvidenceResult(
        integrity_state,
        payment_state,
        accepted_public_records,
        tuple(issues),
        False,
        public_search_outcomes,
    )
