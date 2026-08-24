"""Exact account/currency statement reconciliation and safe report writing."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
from typing import Iterable, Mapping

from .contracts import BALANCE_FIELDS, Issue
from .storage import atomic_write_csv, resolve_inside_ledger


RECONCILIATION_FIELDS = (
    "account_label", "currency", "period_start", "period_end", "opening_source_type",
    "opening_source_date", "opening_balance", "inflows", "outflows", "expected_closing",
    "reported_closing", "difference", "tolerance", "reconciled", "issue_codes",
)
ACCOUNT_SUMMARY_FIELDS = ("account_label", "currency", "period_count", "reconciled_period_count", "state")
OPENING_SOURCE_TYPES = frozenset({
    "user_provided", "statement_opening", "prior_year_end_statement",
})


@dataclass(frozen=True)
class OpeningEvidence:
    amount: Decimal | None
    source_type: str
    source_date: str
    issues: tuple[Issue, ...] = ()


@dataclass(frozen=True)
class ReconciliationRow:
    account_id: str
    currency: str
    period_start: str
    period_end: str
    opening_balance: Decimal | None
    opening_source_type: str
    opening_source_date: str
    inflows: Decimal
    outflows: Decimal
    expected_closing: Decimal | None
    reported_closing: Decimal | None
    difference: Decimal | None
    tolerance: Decimal | None
    reconciled: bool
    issues: tuple[Issue, ...] = ()


def _decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        parsed = value
    else:
        parsed = Decimal(str(value).strip())
    if not parsed.is_finite():
        raise InvalidOperation
    return parsed


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _pending(code: str, message: str) -> Issue:
    return Issue(code, message, blocking=False)


def _blocking(code: str, message: str) -> Issue:
    return Issue(code, message, blocking=True)


def _masked_account(account_id: str, labels: Mapping[str, str] | None) -> str:
    if labels and account_id in labels:
        return labels[account_id]
    return f"account-{hashlib.sha256(account_id.encode('utf-8')).hexdigest()[:12]}"


def derive_opening_from_prior_statement(
    *,
    account_id: str,
    currency: str,
    prior_period_end: str,
    prior_closing_balance: Decimal | None,
    current_period_start: str,
    confirmed: bool,
    prior_account_id: str | None = None,
    prior_currency: str | None = None,
) -> OpeningEvidence:
    """Accept only confirmed, adjacent same-account/currency prior statement evidence."""
    if prior_account_id is not None and prior_account_id != account_id:
        return OpeningEvidence(None, "", "", (_pending("OPENING_BALANCE_MISSING", "Prior statement belongs to another account."),))
    if prior_currency is not None and prior_currency != currency:
        return OpeningEvidence(None, "", "", (_pending("OPENING_BALANCE_MISSING", "Prior statement uses another currency."),))
    if not confirmed:
        return OpeningEvidence(None, "", "", (_pending("BALANCE_UNCONFIRMED", "Prior closing balance is not confirmed."),))
    if prior_closing_balance is None:
        return OpeningEvidence(None, "", "", (_pending("OPENING_BALANCE_MISSING", "Prior closing balance is missing."),))
    try:
        if _date(prior_period_end) + timedelta(days=1) != _date(current_period_start):
            return OpeningEvidence(None, "", "", (_pending("STATEMENT_COVERAGE_GAP", "Prior statement does not end the day before this period."),))
        amount = _decimal(prior_closing_balance)
    except (ValueError, InvalidOperation):
        return OpeningEvidence(None, "", "", (_blocking("BALANCE_EVIDENCE_INVALID", "Prior closing balance or date is invalid."),))
    return OpeningEvidence(amount, "prior_year_end_statement", prior_period_end)


def reconcile_account_period(
    account_id: str,
    currency: str,
    opening_balance: Decimal | None,
    inflows: Iterable[Decimal],
    outflows: Iterable[Decimal],
    reported_closing_balance: Decimal | None,
    period_start: str,
    period_end: str,
    opening_source_type: str,
    opening_source_date: str,
    *,
    tolerance: Decimal | None = None,
    issues: Iterable[Issue] = (),
) -> ReconciliationRow:
    """Reconcile one account/currency/period using exact Decimal arithmetic."""
    row_issues = list(issues)
    source_type = opening_source_type.strip() if isinstance(opening_source_type, str) else ""
    source_type_valid = bool(source_type)
    if source_type and source_type not in OPENING_SOURCE_TYPES:
        row_issues.append(_blocking("BALANCE_EVIDENCE_INVALID", "Opening balance source type is unsupported."))
        source_type_valid = False
    elif not source_type and opening_balance is not None:
        row_issues.append(_pending("OPENING_BALANCE_MISSING", "Opening balance source type is required."))
    try:
        _date(period_start)
        _date(period_end)
        if _date(period_end) < _date(period_start):
            raise ValueError
    except ValueError:
        row_issues.append(_blocking("BALANCE_EVIDENCE_INVALID", "Statement period is invalid."))
    opening: Decimal | None = None
    closing: Decimal | None = None
    if opening_balance is None:
        row_issues.append(_pending("OPENING_BALANCE_MISSING", "Opening balance evidence is required."))
    else:
        try:
            opening = _decimal(opening_balance)
        except (InvalidOperation, ValueError):
            row_issues.append(_blocking("BALANCE_EVIDENCE_INVALID", "Opening balance is invalid."))
    if reported_closing_balance is None:
        row_issues.append(_pending("CLOSING_BALANCE_MISSING", "Closing balance evidence is required."))
    else:
        try:
            closing = _decimal(reported_closing_balance)
        except (InvalidOperation, ValueError):
            row_issues.append(_blocking("BALANCE_EVIDENCE_INVALID", "Closing balance is invalid."))
    try:
        inflow_total = sum((_decimal(value) for value in inflows), Decimal("0"))
        outflow_total = sum((_decimal(value) for value in outflows), Decimal("0"))
    except (InvalidOperation, ValueError):
        inflow_total = Decimal("0")
        outflow_total = Decimal("0")
        row_issues.append(_blocking("BALANCE_EVIDENCE_INVALID", "Transaction amount is invalid."))
    parsed_tolerance: Decimal | None = None
    if tolerance is not None:
        try:
            parsed_tolerance = _decimal(tolerance)
            if parsed_tolerance < 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            row_issues.append(_blocking("BALANCE_EVIDENCE_INVALID", "Configured tolerance is invalid."))
            parsed_tolerance = None
    expected = opening + inflow_total - outflow_total if opening is not None else None
    difference = closing - expected if closing is not None and expected is not None else None
    reconciled = difference is not None and (
        difference == Decimal("0") or (parsed_tolerance is not None and abs(difference) <= parsed_tolerance)
    )
    if difference is not None and not reconciled:
        row_issues.append(_blocking("RECONCILIATION_DIFFERENCE", "Reported closing balance differs from calculated closing balance."))
    if source_type == "prior_year_end_statement":
        try:
            adjacent = _date(opening_source_date) + timedelta(days=1) == _date(period_start)
        except ValueError:
            adjacent = False
        if not adjacent:
            row_issues.append(_blocking("STATEMENT_COVERAGE_GAP", "Prior-year opening evidence is not continuous with this period."))
            reconciled = False
    return ReconciliationRow(
        account_id, currency, period_start, period_end, opening, source_type,
        opening_source_date, inflow_total, outflow_total, expected, closing, difference,
        parsed_tolerance,
        reconciled and source_type_valid and not any(issue.blocking for issue in row_issues),
        tuple(row_issues),
    )


def validate_period_continuity(balance_rows: Iterable[Mapping[str, str]]) -> tuple[Issue, ...]:
    """Return coverage gaps and overlaps without comparing different account currencies."""
    grouped: dict[tuple[str, str], list[Mapping[str, str]]] = {}
    for row in balance_rows:
        account_id, currency = row.get("account_id", "").strip(), row.get("currency", "").strip()
        if account_id and currency:
            grouped.setdefault((account_id, currency), []).append(row)
    issues: list[Issue] = []
    for unit, rows in sorted(grouped.items()):
        periods: list[tuple[date, date]] = []
        for row in rows:
            try:
                start, end = _date(row.get("period_start", "")), _date(row.get("period_end", ""))
                if end < start:
                    raise ValueError
            except ValueError:
                issues.append(_blocking("BALANCE_EVIDENCE_INVALID", f"Statement period is invalid for {unit[0]}/{unit[1]}."))
                continue
            periods.append((start, end))
        previous_end: date | None = None
        for start, end in sorted(periods):
            if previous_end is not None:
                if start <= previous_end:
                    issues.append(_blocking("STATEMENT_COVERAGE_OVERLAP", f"Statement periods overlap for {unit[0]}/{unit[1]}."))
                elif start > previous_end + timedelta(days=1):
                    issues.append(_blocking("STATEMENT_COVERAGE_GAP", f"Statement periods have a gap for {unit[0]}/{unit[1]}."))
            previous_end = max(previous_end, end) if previous_end else end
    return tuple(issues)


def _balance_value(row: Mapping[str, str], field: str) -> Decimal | None:
    value = row.get(field, "")
    value = value.strip() if isinstance(value, str) else ""
    return _decimal(value) if value else None


def _confirmed(value: str) -> bool | None:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    if normalized in {"true", "yes", "1"}:
        return True
    if normalized in {"false", "no", "0", ""}:
        return False
    return None


def reconcile_all(
    transactions: Iterable[Mapping[str, str]],
    balance_rows: Iterable[Mapping[str, str]],
    *,
    tolerance: Decimal | None = None,
) -> tuple[ReconciliationRow, ...]:
    """Reconcile each balance period and every otherwise-uncovered imported unit."""
    transactions_by_unit: dict[tuple[str, str], list[Mapping[str, str]]] = {}
    for transaction in transactions:
        account_id, currency = transaction.get("account_id", "").strip(), transaction.get("currency", "").strip()
        if account_id and currency:
            transactions_by_unit.setdefault((account_id, currency), []).append(transaction)
    source_rows = tuple(balance_rows)
    balances_by_key: dict[tuple[str, str, str, str], list[Mapping[str, str]]] = {}
    for row in source_rows:
        key = tuple(row.get(field, "").strip() for field in ("account_id", "currency", "period_start", "period_end"))
        balances_by_key.setdefault(key, []).append(row)
    continuity = validate_period_continuity(source_rows)
    output: list[ReconciliationRow] = []
    verified_predecessors: dict[tuple[str, str, str], ReconciliationRow] = {}
    covered_units: set[tuple[str, str]] = set()
    for key in sorted(balances_by_key):
        account_id, currency, period_start, period_end = key
        entries = balances_by_key[key]
        covered_units.add((account_id, currency))
        local_issues: list[Issue] = []
        if not account_id or not currency or not period_start or not period_end:
            local_issues.append(_blocking("BALANCE_EVIDENCE_INVALID", "Balance evidence is missing account, currency, or period."))
        if len(entries) != 1:
            local_issues.append(_blocking("BALANCE_EVIDENCE_DUPLICATE", "Exactly one balance row is required for each account/currency/period."))
        evidence = entries[0]
        if set(evidence) != set(BALANCE_FIELDS):
            local_issues.append(_blocking("BALANCE_SCHEMA_INVALID", "Balance evidence has unsupported columns."))
        confirmed = _confirmed(evidence.get("confirmed", ""))
        if confirmed is None:
            local_issues.append(_blocking("BALANCE_EVIDENCE_INVALID", "Balance confirmation must be true or false."))
        elif not confirmed:
            local_issues.append(_pending("BALANCE_UNCONFIRMED", "Balance evidence is not confirmed."))
        raw_source_type = evidence.get("opening_source_type", "")
        source_type = raw_source_type.strip() if isinstance(raw_source_type, str) else ""
        opening_missing = confirmed is False or any(not isinstance(evidence.get(field, ""), str) or not evidence.get(field, "").strip() for field in (
            "opening_balance", "opening_source_type", "opening_source_file", "opening_source_location",
        ))
        closing_missing = confirmed is False or any(not isinstance(evidence.get(field, ""), str) or not evidence.get(field, "").strip() for field in (
            "closing_balance", "closing_source_file", "closing_source_location",
        ))
        derived_opening: Decimal | None = None
        if source_type == "prior_year_end_statement" and confirmed is True:
            try:
                prior_end = _date(period_start) - timedelta(days=1)
                predecessor = verified_predecessors.get((account_id, currency, prior_end.isoformat()))
                if predecessor is None or not predecessor.reconciled or predecessor.reported_closing is None:
                    raise ValueError
                derived_opening = predecessor.reported_closing
                claimed = _balance_value(evidence, "opening_balance")
                if claimed is not None and claimed != derived_opening:
                    local_issues.append(_blocking("BALANCE_EVIDENCE_INVALID", "Claimed opening balance contradicts confirmed predecessor closing."))
                opening_missing = False
            except (ValueError, InvalidOperation):
                opening_missing = True
        if opening_missing:
            local_issues.append(_pending("OPENING_BALANCE_MISSING", "Opening balance and source provenance are required."))
        if closing_missing:
            local_issues.append(_pending("CLOSING_BALANCE_MISSING", "Closing balance and source provenance are required."))
        try:
            opening = derived_opening if derived_opening is not None else (None if opening_missing else _balance_value(evidence, "opening_balance"))
            closing = None if closing_missing else _balance_value(evidence, "closing_balance")
        except (InvalidOperation, ValueError):
            opening = closing = None
            local_issues.append(_blocking("BALANCE_EVIDENCE_INVALID", "Balance amount is not a finite Decimal."))
        unit_transactions = transactions_by_unit.get((account_id, currency), [])
        selected: list[Mapping[str, str]] = []
        try:
            selected = [row for row in unit_transactions if _date(period_start) <= _date(row.get("transaction_date", "")) <= _date(period_end)]
        except ValueError:
            local_issues.append(_blocking("BALANCE_EVIDENCE_INVALID", "Transaction date is invalid for statement coverage."))
        local_issues.extend(issue for issue in continuity if f"{account_id}/{currency}" in issue.message)
        reconciled_row = reconcile_account_period(
            account_id, currency, opening, (row.get("inflow", "0") for row in selected),
            (row.get("outflow", "0") for row in selected), closing, period_start, period_end,
            source_type, evidence.get("opening_source_location", "") if source_type == "prior_year_end_statement" else period_start,
            tolerance=tolerance, issues=local_issues,
        )
        output.append(reconciled_row)
        verified_predecessors[(account_id, currency, period_end)] = reconciled_row
    for (account_id, currency), unit_transactions in sorted(transactions_by_unit.items()):
        if (account_id, currency) in covered_units:
            ranges: list[tuple[date, date]] = []
            for (balance_account, balance_currency, period_start, period_end) in balances_by_key:
                if (balance_account, balance_currency) != (account_id, currency):
                    continue
                try:
                    ranges.append((_date(period_start), _date(period_end)))
                except ValueError:
                    continue
            uncovered: list[Mapping[str, str]] = []
            for transaction in unit_transactions:
                try:
                    transaction_day = _date(transaction.get("transaction_date", ""))
                except ValueError:
                    continue
                if not any(start <= transaction_day <= end for start, end in ranges):
                    uncovered.append(transaction)
            if uncovered:
                dates = sorted(row.get("transaction_date", "") for row in uncovered)
                output.append(reconcile_account_period(
                    account_id, currency, None, (row.get("inflow", "0") for row in uncovered),
                    (row.get("outflow", "0") for row in uncovered), None, dates[0], dates[-1], "", "",
                    issues=(_blocking("STATEMENT_COVERAGE_GAP", "Imported activity is outside supplied statement coverage."),),
                ))
            continue
        dates = sorted(row.get("transaction_date", "") for row in unit_transactions)
        period_start, period_end = (dates[0], dates[-1]) if dates else ("", "")
        output.append(reconcile_account_period(
            account_id, currency, None, (row.get("inflow", "0") for row in unit_transactions),
            (row.get("outflow", "0") for row in unit_transactions), None, period_start, period_end,
            "", "", issues=(_pending("OPENING_BALANCE_MISSING", "No balance evidence was supplied."),),
        ))
    return tuple(sorted(output, key=lambda row: (row.account_id, row.currency, row.period_start, row.period_end)))


def load_balance_rows(ledger_root: Path) -> tuple[tuple[dict[str, str], ...], tuple[Issue, ...]]:
    """Read only a complete account-balances CSV schema from the selected ledger."""
    path = resolve_inside_ledger(ledger_root, Path("inputs") / "account-balances.csv")
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != BALANCE_FIELDS:
                return (), (_blocking("BALANCE_SCHEMA_INVALID", "Account balance CSV has unsupported columns."),)
            rows = []
            for raw in reader:
                if None in raw or any(raw.get(field) is None for field in BALANCE_FIELDS):
                    return (), (_blocking("BALANCE_SCHEMA_INVALID", "Account balance CSV has malformed rows."),)
                rows.append({field: str(raw[field]) for field in BALANCE_FIELDS})
            rows = tuple(rows)
    except (OSError, csv.Error, UnicodeError):
        return (), (_blocking("BALANCE_SCHEMA_INVALID", "Account balance CSV cannot be read."),)
    if any(set(row) != set(BALANCE_FIELDS) for row in rows):
        return (), (_blocking("BALANCE_SCHEMA_INVALID", "Account balance CSV has malformed rows."),)
    return rows, ()


def write_reconciliation_outputs(
    ledger_root: Path,
    rows: Iterable[ReconciliationRow],
    run_state: object,
    account_labels: Mapping[str, str] | None = None,
) -> None:
    """Write masked, currency-separated reconciliation summaries and report."""
    ordered = tuple(sorted(rows, key=lambda row: (row.account_id, row.currency, row.period_start, row.period_end)))
    csv_rows = []
    for row in ordered:
        csv_rows.append({
            "account_label": _masked_account(row.account_id, account_labels), "currency": row.currency,
            "period_start": row.period_start, "period_end": row.period_end,
            "opening_source_type": row.opening_source_type, "opening_source_date": row.opening_source_date,
            "opening_balance": _money(row.opening_balance), "inflows": _money(row.inflows), "outflows": _money(row.outflows),
            "expected_closing": _money(row.expected_closing), "reported_closing": _money(row.reported_closing),
            "difference": _money(row.difference), "tolerance": _money(row.tolerance), "reconciled": str(row.reconciled).lower(),
            "issue_codes": "|".join(sorted({issue.code for issue in row.issues})),
        })
    outputs = resolve_inside_ledger(ledger_root, "outputs")
    atomic_write_csv(outputs / "reconciliation.csv", RECONCILIATION_FIELDS, csv_rows)
    summary: dict[tuple[str, str], list[ReconciliationRow]] = {}
    for row in ordered:
        summary.setdefault((row.account_id, row.currency), []).append(row)
    atomic_write_csv(outputs / "account-summary.csv", ACCOUNT_SUMMARY_FIELDS, ({
        "account_label": _masked_account(account_id, account_labels), "currency": currency,
        "period_count": str(len(unit_rows)), "reconciled_period_count": str(sum(row.reconciled for row in unit_rows)),
        "state": str(getattr(run_state, "value", run_state)),
    } for (account_id, currency), unit_rows in sorted(summary.items())))
    lines = [f"Run state: {getattr(run_state, 'value', run_state)}", ""]
    for item in csv_rows:
        lines.extend((
            f"## Account: {item['account_label']} | Currency: {item['currency']} | Period: {item['period_start']} to {item['period_end']}",
            f"Opening source: {item['opening_source_type']} ({item['opening_source_date']})",
            f"Inflows: {item['inflows']} {item['currency']}", f"Outflows: {item['outflows']} {item['currency']}",
            f"Expected closing: {item['expected_closing']} {item['currency']}", f"Reported closing: {item['reported_closing']} {item['currency']}",
            f"Difference: {item['difference']} {item['currency']}", f"Tolerance: {item['tolerance'] or 'none'}",
            f"Coverage: {item['period_start']} to {item['period_end']}", f"Issues: {item['issue_codes'] or 'none'}", "",
        ))
    (outputs / "reconciliation-report.md").parent.mkdir(parents=True, exist_ok=True)
    (outputs / "reconciliation-report.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _money(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")
