"""Run the deterministic post-extraction assessment pipeline for one case."""

import argparse
from dataclasses import asdict
from datetime import date
from pathlib import Path

from scripts.build_report import build_package
from scripts.calculate_financials import calculate_financials
from scripts.redact_sensitive_data import sanitize_value
from scripts.shared import load_json, write_json
from scripts.validate_case import POLICY_PATH, validate_case
from scripts.validate_evidence import validate_and_classify


def run_pipeline(case_dir: Path, today: date | None = None) -> list[Path]:
    assessment_date = today or date.today()
    preflight = validate_case(case_dir, today=assessment_date)
    preflight_path = case_dir / "outputs/preflight.json"
    write_json(preflight_path, preflight.to_dict())
    if not preflight.can_extract:
        return [preflight_path]

    manifest = load_json(case_dir / "case-manifest.json")
    extracted = load_json(case_dir / "work/extracted-evidence.json")
    sanitization = sanitize_value(extracted)
    sanitized_path = case_dir / "work/sanitized-evidence.json"
    findings_path = case_dir / "work/redaction-findings.json"
    write_json(sanitized_path, sanitization.value)
    write_json(
        findings_path,
        {"findings": [asdict(finding) for finding in sanitization.findings]},
    )

    financials = calculate_financials(sanitization.value["financial_input"])
    financials_path = case_dir / "work/financials.json"
    write_json(financials_path, financials)

    states = validate_and_classify(
        sanitization.value, manifest, today=assessment_date
    )
    states_path = case_dir / "work/evidence-states.json"
    write_json(states_path, states.to_dict())

    policy = load_json(POLICY_PATH)
    package_paths = build_package(
        case_dir,
        manifest,
        sanitization.value,
        financials,
        states,
        preflight,
        policy,
    )
    return [
        preflight_path,
        sanitized_path,
        findings_path,
        financials_path,
        states_path,
        *package_paths,
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path)
    args = parser.parse_args()
    run_pipeline(args.case_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
