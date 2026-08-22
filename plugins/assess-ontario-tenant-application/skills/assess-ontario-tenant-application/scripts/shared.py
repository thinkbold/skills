"""Shared helpers for the Ontario tenant application assessment pipeline."""

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Any


class AssessmentError(ValueError):
    """Raised when assessment input violates a hard contract."""


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    can_extract: bool
    can_finalize: bool
    issues: tuple[ValidationIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "can_extract": self.can_extract,
            "can_finalize": self.can_finalize,
            "issues": [asdict(issue) for issue in self.issues],
        }


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise AssessmentError(f"Expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def parse_decimal(value: object, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise AssessmentError(f"Invalid decimal for {field}: {value!r}") from exc


def parse_date(value: object, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise AssessmentError(f"Invalid ISO date for {field}: {value!r}") from exc
