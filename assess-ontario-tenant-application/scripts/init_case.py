"""Create a case manifest from validated operator intake answers."""

import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys
from typing import Any

from scripts.shared import AssessmentError, load_json, parse_date, parse_decimal
from scripts.validate_case import ALLOWED_EXTENSIONS


CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
SOCIAL_PLATFORMS = ("facebook", "linkedin")
SOCIAL_STATUSES = {"not_requested", "granted", "refused", "withdrawn"}


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssessmentError(f"Expected an object for {field}.")
    return value


def _list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise AssessmentError(f"Expected a list for {field}.")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AssessmentError(f"A non-empty value is required for {field}.")
    return value.strip()


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise AssessmentError(f"Answer true or false for {field}.")
    return value


def _money(value: object, field: str) -> str:
    amount = parse_decimal(value, field)
    if not amount.is_finite() or amount <= 0:
        raise AssessmentError(f"{field} must be a positive finite amount.")
    try:
        normalized = amount.quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise AssessmentError(f"Invalid currency amount for {field}: {value!r}") from exc
    if amount != normalized:
        raise AssessmentError(f"{field} must have no more than two decimal places.")
    return format(normalized, "f")


def _case_file(case_dir: Path, file_record: object, field: str) -> dict[str, str]:
    record = _object(file_record, field)
    relative_text = _text(record.get("path"), f"{field}.path")
    relative = Path(relative_text)
    if relative.is_absolute():
        raise AssessmentError(f"{field}.path must stay inside the case directory.")

    case_root = case_dir.resolve()
    candidate = (case_root / relative).resolve()
    try:
        candidate.relative_to(case_root)
    except ValueError as exc:
        raise AssessmentError(
            f"{field}.path must stay inside the case directory."
        ) from exc

    if relative.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise AssessmentError(f"Unsupported file type for {field}.path: {relative_text}")
    if not candidate.is_file():
        raise AssessmentError(f"Case file does not exist: {relative_text}")
    return {
        "path": candidate.relative_to(case_root).as_posix(),
        "kind": _text(record.get("kind"), f"{field}.kind"),
    }


def _applicants(case_dir: Path, value: object) -> list[dict[str, Any]]:
    intake_applicants = _list(value, "applicants")
    if not intake_applicants:
        raise AssessmentError("At least one lease-signing applicant is required.")

    applicants: list[dict[str, Any]] = []
    applicant_ids: set[str] = set()
    file_paths: set[str] = set()
    for applicant_index, applicant_value in enumerate(intake_applicants):
        field = f"applicants[{applicant_index}]"
        applicant = _object(applicant_value, field)
        applicant_id = _text(applicant.get("applicant_id"), f"{field}.applicant_id")
        if not CASE_ID_PATTERN.fullmatch(applicant_id):
            raise AssessmentError(
                f"{field}.applicant_id must be a non-name stable identifier using "
                "letters, numbers, '.', '_', or '-'."
            )
        if applicant_id in applicant_ids:
            raise AssessmentError(f"Duplicate applicant_id: {applicant_id}")
        applicant_ids.add(applicant_id)

        intake_files = _list(applicant.get("files"), f"{field}.files")
        if not intake_files:
            raise AssessmentError(f"At least one case file is required for {applicant_id}.")
        files = [
            _case_file(case_dir, file_value, f"{field}.files[{file_index}]")
            for file_index, file_value in enumerate(intake_files)
        ]
        for file_record in files:
            path = file_record["path"]
            if path in file_paths:
                raise AssessmentError(f"A case file may be listed only once: {path}")
            file_paths.add(path)

        applicants.append(
            {
                "applicant_id": applicant_id,
                "lease_signer": True,
                "files": files,
            }
        )
    return applicants


def _general_authorization(value: object) -> dict[str, Any]:
    authorization = _object(value, "general_authorization")
    available = _boolean(
        authorization.get("available"), "general_authorization.available"
    )
    if not available:
        return {"version": "", "signed_at": "", "open_web_disclosed": False}

    version = _text(authorization.get("version"), "general_authorization.version")
    signed_at = _text(
        authorization.get("signed_at"), "general_authorization.signed_at"
    )
    parse_date(signed_at, "general_authorization.signed_at")
    open_web_disclosed = _boolean(
        authorization.get("open_web_disclosed"),
        "general_authorization.open_web_disclosed",
    )
    return {
        "version": version,
        "signed_at": signed_at,
        "open_web_disclosed": open_web_disclosed,
    }


def _social_consent(value: object) -> dict[str, Any]:
    consent = _object(value, "social_consent")
    platform_statuses: dict[str, str] = {}
    for platform in SOCIAL_PLATFORMS:
        status = _text(consent.get(platform), f"social_consent.{platform}")
        if status not in SOCIAL_STATUSES:
            allowed = ", ".join(sorted(SOCIAL_STATUSES))
            raise AssessmentError(
                f"social_consent.{platform} must be one of: {allowed}."
            )
        platform_statuses[platform] = status

    granted_platforms = [
        platform
        for platform in SOCIAL_PLATFORMS
        if platform_statuses[platform] == "granted"
    ]
    if granted_platforms:
        aggregate_status = "granted"
    elif "withdrawn" in platform_statuses.values():
        aggregate_status = "withdrawn"
    elif "refused" in platform_statuses.values():
        aggregate_status = "refused"
    else:
        aggregate_status = "not_requested"
    return {
        "status": aggregate_status,
        "platforms": granted_platforms,
        "platform_statuses": platform_statuses,
    }


def build_manifest(case_dir: Path, intake: dict[str, Any]) -> dict[str, Any]:
    scope = _object(intake.get("scope"), "scope")
    ordinary_market = _boolean(
        scope.get("ordinary_ontario_market_rental"),
        "scope.ordinary_ontario_market_rental",
    )
    owner_shared = _boolean(
        scope.get("owner_shared_kitchen_or_bathroom"),
        "scope.owner_shared_kitchen_or_bathroom",
    )
    if not ordinary_market or owner_shared:
        raise AssessmentError(
            "This case is outside this skill: it must be an ordinary Ontario "
            "market rental with no kitchen or bathroom shared with the owner "
            "or the owner's family."
        )

    case_id = _text(intake.get("case_id"), "case_id")
    if not CASE_ID_PATTERN.fullmatch(case_id):
        raise AssessmentError(
            "case_id must be 1-100 characters using letters, numbers, '.', '_', "
            "or '-', and must start with a letter or number."
        )

    housing = _object(intake.get("housing"), "housing")
    expected_start_date = _text(
        housing.get("expected_start_date"), "housing.expected_start_date"
    )
    parse_date(expected_start_date, "housing.expected_start_date")
    term_months = housing.get("term_months")
    if (
        not isinstance(term_months, int)
        or isinstance(term_months, bool)
        or term_months <= 0
    ):
        raise AssessmentError("housing.term_months must be a positive integer.")

    privacy = _object(intake.get("privacy"), "privacy")
    responsible_person = _text(
        privacy.get("responsible_person"), "privacy.responsible_person"
    )
    controlled_storage = _boolean(
        privacy.get("controlled_storage_confirmed"),
        "privacy.controlled_storage_confirmed",
    )
    access_correction = _boolean(
        privacy.get("access_correction_process_confirmed"),
        "privacy.access_correction_process_confirmed",
    )
    if not controlled_storage or not access_correction:
        raise AssessmentError(
            "The privacy preflight must confirm controlled storage and an "
            "access/correction process before creating the manifest."
        )

    legal_hold = _boolean(intake.get("legal_hold"), "legal_hold")
    return {
        "schema_version": "1.0",
        "case_id": case_id,
        "jurisdiction": {"country": "CA", "province": "ON"},
        "housing": {
            "market_type": "market",
            "owner_shared_kitchen_or_bathroom": False,
            "address": _text(housing.get("address"), "housing.address"),
            "monthly_rent_cad": _money(
                housing.get("monthly_rent_cad"), "housing.monthly_rent_cad"
            ),
            "expected_start_date": expected_start_date,
            "term_months": term_months,
        },
        "applicants": _applicants(case_dir, intake.get("applicants")),
        "privacy": {
            "responsible_person": responsible_person,
            "controlled_storage_confirmed": True,
            "access_correction_process_confirmed": True,
        },
        "authorizations": {
            "general": _general_authorization(
                intake.get("general_authorization")
            ),
            "social": _social_consent(intake.get("social_consent")),
        },
        "decision": {"status": "pending", "legal_hold": legal_hold},
    }


def _write_manifest_exclusively(path: Path, manifest: dict[str, Any]) -> None:
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise AssessmentError(
            f"case-manifest.json already exists and will not be overwritten: {path}"
        ) from exc


def initialize_case(case_dir: Path, answers_path: Path) -> Path:
    if not case_dir.is_dir():
        raise AssessmentError(f"Case directory does not exist: {case_dir}")
    manifest_path = case_dir / "case-manifest.json"
    if manifest_path.exists():
        raise AssessmentError(
            f"case-manifest.json already exists and will not be overwritten: "
            f"{manifest_path}"
        )

    intake = load_json(answers_path)
    manifest = build_manifest(case_dir, intake)
    for directory in ("inputs", "work", "outputs"):
        (case_dir / directory).mkdir(parents=True, exist_ok=True)
    _write_manifest_exclusively(manifest_path, manifest)
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path)
    parser.add_argument(
        "--answers",
        required=True,
        type=Path,
        help="JSON file containing the operator's intake answers",
    )
    args = parser.parse_args()
    try:
        manifest_path = initialize_case(args.case_dir, args.answers)
    except (AssessmentError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"created": str(manifest_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
