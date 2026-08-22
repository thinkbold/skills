"""Plan case retention actions; delete only when explicitly requested."""

import argparse
from dataclasses import asdict, dataclass
from datetime import date, timedelta
import json
from pathlib import Path

from scripts.shared import AssessmentError, load_json, parse_date


@dataclass(frozen=True)
class RetentionAction:
    relative_path: str
    reason: str


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(value.day, days[month - 1]))


def _case_end_date(decision: dict) -> date | None:
    status = decision.get("status")
    if status == "completed":
        value = decision.get("completed_at") or decision.get("decision_date")
    elif status == "withdrawn":
        value = decision.get("withdrawn_at")
    else:
        return None
    if not value:
        raise AssessmentError(f"Missing retention start date for {status} case")
    return parse_date(value, f"decision.{status}_at")


def _files_under(case_dir: Path, directory: str) -> list[Path]:
    root = case_dir / directory
    if not root.is_dir():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file())


def plan_retention(
    case_dir: Path, as_of: date | None = None
) -> tuple[RetentionAction, ...]:
    as_of = as_of or date.today()
    manifest = load_json(case_dir / "case-manifest.json")
    decision = manifest.get("decision", {})
    if decision.get("legal_hold") is True:
        return ()
    ended_at = _case_end_date(decision)
    if ended_at is None:
        return ()

    actions: dict[str, RetentionAction] = {}
    if as_of >= ended_at + timedelta(days=30):
        for directory in ("inputs", "work"):
            for path in _files_under(case_dir, directory):
                relative = path.relative_to(case_dir).as_posix()
                actions[relative] = RetentionAction(
                    relative, "raw_or_work_retention_expired_30_days"
                )
    if as_of >= add_months(ended_at, 13):
        for path in _files_under(case_dir, "outputs"):
            relative = path.relative_to(case_dir).as_posix()
            actions[relative] = RetentionAction(
                relative, "derived_artifact_retention_expired_13_months"
            )
    return tuple(actions[path] for path in sorted(actions))


def apply_retention(
    case_dir: Path,
    actions: tuple[RetentionAction, ...],
    *,
    apply: bool = False,
) -> None:
    if not apply:
        return
    case_root = case_dir.resolve()
    for action in actions:
        target = (case_root / action.relative_path).resolve()
        try:
            target.relative_to(case_root)
        except ValueError as exc:
            raise AssessmentError(
                f"Retention target escapes case directory: {action.relative_path}"
            ) from exc
        if target == case_root / "case-manifest.json":
            raise AssessmentError("Retention cannot delete case-manifest.json")
        target.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    actions = plan_retention(args.case_dir, args.as_of)
    print(json.dumps([asdict(action) for action in actions], indent=2))
    apply_retention(args.case_dir, actions, apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
