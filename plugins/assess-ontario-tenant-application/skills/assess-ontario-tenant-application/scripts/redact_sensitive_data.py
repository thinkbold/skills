"""Redact SIN values and isolate protected fields before assessment."""

import argparse
from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any

from scripts.shared import load_json, write_json


SIN_PATTERN = re.compile(r"(?<!\d)(\d{3})[- ]?(\d{3})[- ]?(\d{3})(?!\d)")
PROTECTED_KEYS = {
    "race",
    "ancestry",
    "place_of_origin",
    "colour",
    "ethnic_origin",
    "citizenship",
    "creed",
    "religion",
    "sex",
    "sexual_orientation",
    "gender_identity",
    "gender_expression",
    "age",
    "marital_status",
    "family_status",
    "disability",
    "public_assistance",
}


def normalize_field_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


@dataclass(frozen=True)
class RedactionFinding:
    kind: str
    field: str
    path: str


@dataclass(frozen=True)
class SanitizationResult:
    value: Any
    findings: tuple[RedactionFinding, ...]


def sanitize_value(value: Any, path: str = "$") -> SanitizationResult:
    findings: list[RedactionFinding] = []

    def redact_text(text: str, current: str) -> str:
        def replace(_: re.Match[str]) -> str:
            findings.append(RedactionFinding("sin", "sin", current))
            return "[REDACTED SIN]"

        return SIN_PATTERN.sub(replace, text)

    def visit(node: Any, current: str) -> Any:
        if isinstance(node, str):
            return redact_text(node, current)
        if isinstance(node, list):
            return [
                visit(item, f"{current}[{index}]")
                for index, item in enumerate(node)
            ]
        if isinstance(node, dict):
            clean: dict[str, Any] = {}
            for key, item in node.items():
                child = f"{current}.{key}"
                normalized_key = normalize_field_name(key)
                if normalized_key in PROTECTED_KEYS:
                    findings.append(RedactionFinding("protected_field", key, child))
                    continue
                if normalized_key == "birth_date":
                    findings.append(RedactionFinding("identity_field", key, child))
                    clean["identity_birth_date_match"] = "not_confirmed"
                    continue
                clean[key] = visit(item, child)
            return clean
        return node

    return SanitizationResult(visit(value, path), tuple(findings))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path)
    args = parser.parse_args()

    work_dir = args.case_dir / "work"
    result = sanitize_value(load_json(work_dir / "extracted-evidence.json"))
    write_json(work_dir / "sanitized-evidence.json", result.value)
    write_json(
        work_dir / "redaction-findings.json",
        {"findings": [asdict(finding) for finding in result.findings]},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
