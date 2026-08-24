"""Run-state precedence, exception collection, and safe final status output."""

from __future__ import annotations

import hashlib
import json
import csv
from pathlib import Path
from typing import Iterable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation

from .contracts import Issue, RunState
from .contracts import CANONICAL_TRANSACTION_FIELDS
from .reconciliation import ReconciliationRow
from .storage import atomic_write_csv, atomic_write_json, resolve_inside_ledger


_BLOCKING_CODES = frozenset({
    "ACCOUNT_IDENTITY_AMBIGUOUS", "ACCOUNT_UNCONFIRMED", "AMOUNT_DIRECTION_AMBIGUOUS",
    "BALANCE_EVIDENCE_DUPLICATE", "BALANCE_EVIDENCE_INVALID", "BALANCE_SCHEMA_INVALID",
    "CURRENCY_MISSING", "CSV_HEADER_MISSING", "DATE_UNPARSEABLE", "EXTERNAL_NOT_AUTHORIZED",
    "EXTERNAL_RESULT_INVALID", "EXTERNAL_RESULT_PROVIDER_MISMATCH", "EXTERNAL_SCOPE_MISMATCH",
    "LOW_CONFIDENCE_CRITICAL", "MERCHANT_RULE_CONFLICT", "PDF_PAGE_EMPTY", "PDF_PAGE_MISSING",
    "RECONCILIATION_DIFFERENCE", "STATEMENT_COVERAGE_GAP", "STATEMENT_COVERAGE_OVERLAP",
    "UNRESOLVED_DUPLICATE_CANDIDATE", "CHART_REFERENCE_INVALID",
})
_EXCEPTION_FIELDS = ("code", "blocking", "message", "source_file", "source_location")


def validate_canonical_transactions(transactions: Iterable[Mapping[str, object]]) -> tuple[Issue, ...]:
    """Block malformed canonical rows before grouping or reconciliation can omit them."""
    issues: list[Issue] = []
    seen: set[str] = set()
    for index, row in enumerate(transactions, start=1):
        if set(row) != set(CANONICAL_TRANSACTION_FIELDS) or len(row) != len(CANONICAL_TRANSACTION_FIELDS):
            issues.append(Issue("CANONICAL_SCHEMA_INVALID", "Canonical transaction schema is invalid.", True, source_location=str(index)))
            continue
        transaction_id = str(row.get("transaction_id") or "").strip()
        if not transaction_id or transaction_id in seen:
            issues.append(Issue("CANONICAL_SCHEMA_INVALID", "Canonical transaction identity is invalid.", True, source_location=str(index)))
        seen.add(transaction_id)
        account_id, currency = str(row.get("account_id") or "").strip(), str(row.get("currency") or "").strip()
        if not account_id:
            issues.append(Issue("ACCOUNT_UNCONFIRMED", "Canonical transaction account is missing.", True, source_location=str(index)))
        if not currency:
            issues.append(Issue("CURRENCY_MISSING", "Canonical transaction currency is missing.", True, source_location=str(index)))
        if not str(row.get("raw_description") or "").strip() or not str(row.get("source_file") or "").strip() or not str(row.get("source_page_or_row") or "").strip():
            issues.append(Issue("CANONICAL_PROVENANCE_INVALID", "Canonical transaction evidence is missing.", True, source_location=str(index)))
        status = str(row.get("classification_status") or "")
        if status not in {"unclassified", "classified"} or (status == "classified" and not str(row.get("account_name") or "").strip()):
            issues.append(Issue("CANONICAL_STATUS_INVALID", "Canonical transaction classification is invalid.", True, source_location=str(index)))
        try:
            date.fromisoformat(str(row.get("transaction_date") or "")); date.fromisoformat(str(row.get("posting_date") or ""))
        except ValueError:
            issues.append(Issue("DATE_UNPARSEABLE", "Canonical transaction date is invalid.", True, source_location=str(index)))
        try:
            inflow, outflow, balance = (Decimal(str(row.get(field) or "")) for field in ("inflow", "outflow", "running_balance"))
            if not all(value.is_finite() for value in (inflow, outflow, balance)) or not ((inflow > 0 and outflow == 0) or (outflow > 0 and inflow == 0)):
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            issues.append(Issue("AMOUNT_DIRECTION_AMBIGUOUS", "Canonical transaction amount direction is invalid.", True, source_location=str(index)))
    return tuple(issues)


def count_pending_classifications(transactions: Iterable[Mapping[str, object]]) -> int:
    """Count every otherwise valid unclassified row, even if it cannot form a merchant group."""
    total = 0
    for row in transactions:
        if str(row.get("classification_status") or "") != "unclassified":
            continue
        if not validate_canonical_transactions((row,)):
            total += 1
    return total


def load_canonical_for_validation(ledger_root: Path) -> tuple[tuple[dict[str, str], ...], tuple[Issue, ...]]:
    """Load canonical CSV without throwing malformed rows into later parsing stages."""
    path = resolve_inside_ledger(ledger_root, Path("work") / "normalized-transactions.csv")
    if not path.exists():
        return (), ()
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != CANONICAL_TRANSACTION_FIELDS:
                return (), (Issue("CANONICAL_SCHEMA_INVALID", "Canonical transaction schema is invalid.", True),)
            rows = []
            for raw in reader:
                if None in raw or any(raw.get(field) is None for field in CANONICAL_TRANSACTION_FIELDS):
                    return (), (Issue("CANONICAL_SCHEMA_INVALID", "Canonical transaction schema is invalid.", True),)
                rows.append({field: str(raw[field]) for field in CANONICAL_TRANSACTION_FIELDS})
    except (OSError, csv.Error, UnicodeError):
        return (), (Issue("CANONICAL_SCHEMA_INVALID", "Canonical transaction schema is invalid.", True),)
    return tuple(rows), ()


def determine_run_state(
    has_transactions: bool,
    pending_group_count: int,
    reconciliation_rows: tuple[ReconciliationRow, ...],
    issues: tuple[Issue, ...],
) -> RunState:
    """Apply stable blocking → classification → reconciliation → completion precedence."""
    if any(issue.blocking for issue in issues):
        return RunState.BLOCKED
    if pending_group_count:
        return RunState.CLASSIFICATION_PENDING
    if not reconciliation_rows or not all(row.reconciled for row in reconciliation_rows):
        return RunState.RECONCILIATION_PENDING
    if has_transactions:
        return RunState.COMPLETE
    return RunState.EXTRACTED


def collect_ledger_issues(
    source_issues: Iterable[Issue],
    reconciliation_rows: Iterable[ReconciliationRow],
    pending_group_count: int = 0,
) -> tuple[Issue, ...]:
    """Promote critical imported/rule/consent failures; merchants remain a separate pending count."""
    del pending_group_count  # Unknown merchants are intentionally never an exception.
    collected: list[Issue] = []
    for issue in source_issues:
        collected.append(Issue(issue.code, issue.message, issue.blocking or issue.code in _BLOCKING_CODES, issue.source_file, issue.source_location))
    for row in reconciliation_rows:
        for issue in row.issues:
            collected.append(Issue(issue.code, issue.message, issue.blocking or issue.code in _BLOCKING_CODES, issue.source_file, issue.source_location))
    unique: dict[tuple[str, str, str, str, bool], Issue] = {}
    for issue in collected:
        unique[(issue.code, issue.message, issue.source_file, issue.source_location, issue.blocking)] = issue
    return tuple(sorted(unique.values(), key=lambda issue: (issue.code, issue.source_file, issue.source_location, issue.message)))


def _masked_message(message: str, account_labels: Mapping[str, str] | None) -> str:
    if not account_labels:
        return ""
    masked = message
    for account_id, label in sorted(account_labels.items(), key=lambda item: -len(item[0])):
        masked = masked.replace(account_id, label)
    return masked


def _opaque_source(value: str) -> str:
    return "" if not value else f"source-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}"


def finalize_outputs(
    ledger_root: Path,
    *,
    has_transactions: bool,
    pending_group_count: int,
    reconciliation_rows: tuple[ReconciliationRow, ...],
    issues: tuple[Issue, ...],
    account_labels: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Write stable masked exceptions and status after deterministic state selection."""
    generated_labels = {row.account_id: f"account-{hashlib.sha256(row.account_id.encode('utf-8')).hexdigest()[:12]}" for row in reconciliation_rows}
    labels = {**generated_labels, **(dict(account_labels) if account_labels else {})}
    all_issues = collect_ledger_issues(issues, reconciliation_rows, pending_group_count)
    state = determine_run_state(has_transactions, pending_group_count, reconciliation_rows, all_issues)
    exceptions = [{
        "code": issue.code, "blocking": str(issue.blocking).lower(),
        "message": _masked_message(issue.message, labels) or f"Issue: {issue.code}",
        "source_file": _opaque_source(issue.source_file),
        "source_location": _opaque_source(issue.source_location),
    } for issue in all_issues]
    outputs = resolve_inside_ledger(ledger_root, "outputs")
    atomic_write_csv(outputs / "exceptions.csv", _EXCEPTION_FIELDS, exceptions)
    status = {
        "blocking_issue_count": sum(issue.blocking for issue in all_issues),
        "has_transactions": has_transactions,
        "pending_group_count": pending_group_count,
        "reconciled_unit_count": sum(row.reconciled for row in reconciliation_rows),
        "state": state.value,
        "unit_count": len(reconciliation_rows),
    }
    atomic_write_json(outputs / "status.json", status)
    return status
