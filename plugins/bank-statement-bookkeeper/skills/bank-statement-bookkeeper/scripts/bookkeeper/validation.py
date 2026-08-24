"""Run-state precedence, exception collection, and safe final status output."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping

from .contracts import Issue, RunState
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
        return message
    masked = message
    for account_id, label in account_labels.items():
        masked = masked.replace(account_id, label)
    return masked


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
    all_issues = collect_ledger_issues(issues, reconciliation_rows, pending_group_count)
    state = determine_run_state(has_transactions, pending_group_count, reconciliation_rows, all_issues)
    exceptions = [{
        "code": issue.code, "blocking": str(issue.blocking).lower(),
        "message": _masked_message(issue.message, account_labels), "source_file": issue.source_file,
        "source_location": issue.source_location,
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
