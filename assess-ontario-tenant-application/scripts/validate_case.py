"""Validate the scope and privacy prerequisites for one assessment case."""

import argparse
from datetime import date
from pathlib import Path

from scripts.shared import (
    ValidationIssue,
    ValidationResult,
    load_json,
    parse_date,
    write_json,
)


ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".csv", ".txt", ".md"}
POLICY_PATH = Path(__file__).resolve().parents[1] / "references/policy-version.json"


def validate_case(case_dir: Path, today: date | None = None) -> ValidationResult:
    today = today or date.today()
    manifest = load_json(case_dir / "case-manifest.json")
    policy = load_json(POLICY_PATH)
    issues: list[ValidationIssue] = []

    jurisdiction = manifest.get("jurisdiction", {})
    housing = manifest.get("housing", {})
    if jurisdiction != {"country": "CA", "province": "ON"}:
        issues.append(
            ValidationIssue(
                "OUT_OF_SCOPE_JURISDICTION",
                "blocking",
                "Property must be in Ontario, Canada.",
            )
        )
    if housing.get("market_type") != "market":
        issues.append(
            ValidationIssue(
                "OUT_OF_SCOPE_MARKET_TYPE",
                "blocking",
                "Only ordinary market rentals are supported.",
            )
        )
    if housing.get("owner_shared_kitchen_or_bathroom") is not False:
        issues.append(
            ValidationIssue(
                "OUT_OF_SCOPE_SHARED_SPACE",
                "blocking",
                "Owner-shared kitchen or bathroom housing is excluded.",
            )
        )

    privacy = manifest.get("privacy", {})
    privacy_keys = (
        "responsible_person",
        "controlled_storage_confirmed",
        "access_correction_process_confirmed",
    )
    if not all(privacy.get(key) for key in privacy_keys):
        issues.append(
            ValidationIssue(
                "PRIVACY_PREFLIGHT_INCOMPLETE",
                "blocking",
                "Privacy preflight is incomplete.",
            )
        )

    general = manifest.get("authorizations", {}).get("general", {})
    if not all(
        (
            general.get("version"),
            general.get("signed_at"),
            general.get("open_web_disclosed") is True,
        )
    ):
        issues.append(
            ValidationIssue(
                "GENERAL_AUTHORIZATION_INCOMPLETE",
                "blocking",
                "General authorization is incomplete.",
            )
        )

    applicants = manifest.get("applicants", [])
    if not applicants or any(
        applicant.get("lease_signer") is not True for applicant in applicants
    ):
        issues.append(
            ValidationIssue(
                "INVALID_APPLICANT_SET",
                "blocking",
                "Every listed applicant must be a lease signer.",
            )
        )
    for applicant in applicants:
        for file_record in applicant.get("files", []):
            relative = Path(file_record.get("path", ""))
            if relative.suffix.lower() not in ALLOWED_EXTENSIONS:
                issues.append(
                    ValidationIssue(
                        "UNSUPPORTED_FILE_TYPE", "blocking", str(relative)
                    )
                )
            elif not (case_dir / relative).is_file():
                issues.append(
                    ValidationIssue("MISSING_CASE_FILE", "blocking", str(relative))
                )

    reviewed = parse_date(policy["last_reviewed"], "policy.last_reviewed")
    if (today - reviewed).days > int(policy["review_interval_days"]):
        issues.append(
            ValidationIssue(
                "POLICY_EXPIRED",
                "blocking_finalization",
                "Ontario policy review is older than 90 days.",
            )
        )

    blocking = any(issue.severity == "blocking" for issue in issues)
    finalization_block = blocking or any(
        issue.severity == "blocking_finalization" for issue in issues
    )
    return ValidationResult(not blocking, not finalization_block, tuple(issues))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path)
    args = parser.parse_args()

    result = validate_case(args.case_dir)
    write_json(args.case_dir / "outputs/preflight.json", result.to_dict())
    return 0 if result.can_extract else 2


if __name__ == "__main__":
    raise SystemExit(main())
