"""Run-state precedence, exception collection, and safe final status output."""

from __future__ import annotations

import hashlib
import io
import json
import csv
import os
import re
import shutil
import stat
from pathlib import Path
from typing import Iterable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation

from .contracts import Issue, RunState
from .contracts import CANONICAL_TRANSACTION_FIELDS
from .reconciliation import ACCOUNT_SUMMARY_FIELDS, RECONCILIATION_FIELDS, ReconciliationRow, load_balance_rows, reconcile_all
from .storage import append_audit_event, atomic_write_csv, atomic_write_json, load_active_issues, resolve_inside_ledger, sha256_file
from .ledger import lexical_ledger_root


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
_PENDING_GROUP_FIELDS = ("group_id", "normalized_merchant", "direction", "currencies", "account_ids", "transaction_count", "totals_by_currency", "date_start", "date_end", "confidence")
_OUTPUT_BUNDLE_JOURNAL = Path("work") / "pending-derived-output.json"
_OUTPUT_BUNDLE_STAGE = Path("work") / "pending-derived-output-stage"
_OUTPUT_BUNDLE_BACKUP = Path("work") / "pending-derived-output-backup"
_OUTPUT_TARGETS = frozenset({
    "outputs/normalized-transactions.csv", "outputs/classified-transactions.csv",
    "outputs/account-summary.csv", "outputs/reconciliation.csv",
    "outputs/reconciliation-report.md", "outputs/exceptions.csv", "outputs/status.json",
    "work/pending-merchant-groups.csv",
})
_MANDATORY_OUTPUT_TARGETS = frozenset({
    "outputs/normalized-transactions.csv", "outputs/classified-transactions.csv",
    "outputs/account-summary.csv", "outputs/reconciliation.csv",
    "outputs/reconciliation-report.md", "outputs/exceptions.csv", "outputs/status.json",
})
_GENERATION_INPUTS = (
    "work/normalized-transactions.csv", "merchant-rules.csv", "work/active-issues.json",
    "inputs/account-balances.csv", "ledger.json", "work/import-manifest.json", "audit/audit.jsonl",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def validate_canonical_transactions(transactions: Iterable[Mapping[str, object]]) -> tuple[Issue, ...]:
    """Block malformed canonical rows before grouping or reconciliation can omit them."""
    issues: list[Issue] = []
    rows = tuple(transactions)
    identifiers = [str(row.get("transaction_id") or "").strip() for row in rows]
    duplicates = {value for value in identifiers if value and identifiers.count(value) > 1}
    for index, row in enumerate(rows, start=1):
        if set(row) != set(CANONICAL_TRANSACTION_FIELDS) or len(row) != len(CANONICAL_TRANSACTION_FIELDS):
            issues.append(Issue("CANONICAL_SCHEMA_INVALID", "Canonical transaction schema is invalid.", True, source_location=str(index)))
            continue
        transaction_id = str(row.get("transaction_id") or "").strip()
        if not transaction_id or transaction_id in duplicates:
            issues.append(Issue("CANONICAL_SCHEMA_INVALID", "Canonical transaction identity is invalid.", True, source_location=str(index)))
        account_id, currency = str(row.get("account_id") or "").strip(), str(row.get("currency") or "").strip()
        if not account_id:
            issues.append(Issue("ACCOUNT_UNCONFIRMED", "Canonical transaction account is missing.", True, source_location=str(index)))
        if not currency:
            issues.append(Issue("CURRENCY_MISSING", "Canonical transaction currency is missing.", True, source_location=str(index)))
        if not all(str(row.get(field) or "").strip() for field in ("raw_description", "source_file", "source_page_or_row", "source_locations", "extraction_method", "extraction_confidence")):
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


def admit_canonical_transactions(transactions: Iterable[Mapping[str, object]]) -> tuple[tuple[dict[str, str], ...], tuple[Issue, ...]]:
    """Return only rows valid both locally and as part of this canonical batch."""
    rows = tuple(transactions)
    batch_issues = validate_canonical_transactions(rows)
    duplicate_ids = {str(row.get("transaction_id") or "").strip() for row in rows if str(row.get("transaction_id") or "").strip() and sum(str(item.get("transaction_id") or "").strip() == str(row.get("transaction_id") or "").strip() for item in rows) > 1}
    admitted = tuple(row for row in rows if str(row.get("transaction_id") or "").strip() not in duplicate_ids and not validate_canonical_transactions((row,)))
    return admitted, batch_issues


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
    sensitive_values = {
        value
        for account_id, label in account_labels.items()
        for value in (account_id, label)
        if value
    }
    if not sensitive_values:
        return message
    ordered_values = sorted(sensitive_values, key=lambda value: (-len(value), value))
    pattern = re.compile("|".join(re.escape(value) for value in ordered_values))
    return pattern.sub(
        lambda match: f"account-{hashlib.sha256(match.group().encode('utf-8')).hexdigest()[:12]}",
        message,
    )


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


def _csv_bytes(fieldnames: tuple[str, ...], rows: Iterable[Mapping[str, object]]) -> bytes:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return handle.getvalue().encode("utf-8")


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _ordered_transactions(rows: Iterable[Mapping[str, str]]) -> tuple[dict[str, str], ...]:
    return tuple(sorted((dict(row) for row in rows), key=lambda row: (
        row.get("account_id", ""), row.get("currency", ""), row.get("transaction_date", ""),
        row.get("posting_date", ""), row.get("transaction_id", ""),
    )))


def _pending_group_rows(rows: tuple[dict[str, str], ...]) -> tuple[dict[str, str], ...]:
    from .classification import build_pending_groups

    return tuple({
        "group_id": group.group_id,
        "normalized_merchant": group.normalized_merchant,
        "direction": group.direction,
        "currencies": "|".join(group.currencies),
        "account_ids": "|".join(group.account_ids),
        "transaction_count": str(group.transaction_count),
        "totals_by_currency": "|".join(
            f"{currency}:{amount}" for currency, amount in group.totals_by_currency
        ),
        "date_start": group.date_start,
        "date_end": group.date_end,
        "confidence": group.confidence,
    } for group in build_pending_groups(rows))


def _parsed_reconciliation_rows(rows: Iterable[Mapping[str, str]]) -> tuple[ReconciliationRow, ...]:
    def optional_money(value: str) -> Decimal | None:
        return Decimal(value) if value else None

    parsed: list[ReconciliationRow] = []
    for row in rows:
        issues = tuple(
            Issue(code, f"Issue: {code}", code in _BLOCKING_CODES)
            for code in row["issue_codes"].split("|")
            if code
        )
        parsed.append(ReconciliationRow(
            account_id=row["account_label"],
            currency=row["currency"],
            period_start=row["period_start"],
            period_end=row["period_end"],
            opening_balance=optional_money(row["opening_balance"]),
            opening_source_type=row["opening_source_type"],
            opening_source_date=row["opening_source_date"],
            inflows=Decimal(row["inflows"]),
            outflows=Decimal(row["outflows"]),
            expected_closing=optional_money(row["expected_closing"]),
            reported_closing=optional_money(row["reported_closing"]),
            difference=optional_money(row["difference"]),
            tolerance=optional_money(row["tolerance"]),
            reconciled=row["reconciled"] == "true",
            issues=issues,
        ))
    return tuple(parsed)


def _reconciliation_artifacts(rows: tuple[ReconciliationRow, ...], state: RunState) -> dict[str, bytes]:
    ordered = tuple(sorted(rows, key=lambda row: (row.account_id, row.currency, row.period_start, row.period_end)))
    reconciliation = []
    for row in ordered:
        reconciliation.append({
            "account_label": f"account-{hashlib.sha256(row.account_id.encode('utf-8')).hexdigest()[:12]}", "currency": row.currency,
            "period_start": row.period_start, "period_end": row.period_end,
            "opening_source_type": row.opening_source_type, "opening_source_date": row.opening_source_date,
            "opening_balance": _money(row.opening_balance), "inflows": _money(row.inflows), "outflows": _money(row.outflows),
            "expected_closing": _money(row.expected_closing), "reported_closing": _money(row.reported_closing),
            "difference": _money(row.difference), "tolerance": _money(row.tolerance), "reconciled": str(row.reconciled).lower(),
            "issue_codes": "|".join(sorted({issue.code for issue in row.issues})),
        })
    summary: dict[tuple[str, str], list[ReconciliationRow]] = {}
    for row in ordered:
        summary.setdefault((row.account_id, row.currency), []).append(row)
    summary_rows = ({
        "account_label": f"account-{hashlib.sha256(account_id.encode('utf-8')).hexdigest()[:12]}", "currency": currency,
        "period_count": str(len(unit_rows)), "reconciled_period_count": str(sum(row.reconciled for row in unit_rows)), "state": state.value,
    } for (account_id, currency), unit_rows in sorted(summary.items()))
    report = [f"Run state: {state.value}", ""]
    for item in reconciliation:
        report.extend((
            f"## Account: {item['account_label']} | Currency: {item['currency']} | Period: {item['period_start']} to {item['period_end']}",
            f"Opening source: {item['opening_source_type']} ({item['opening_source_date']})",
            f"Inflows: {item['inflows']} {item['currency']}", f"Outflows: {item['outflows']} {item['currency']}",
            f"Expected closing: {item['expected_closing']} {item['currency']}", f"Reported closing: {item['reported_closing']} {item['currency']}",
            f"Difference: {item['difference']} {item['currency']}", f"Tolerance: {item['tolerance'] or 'none'}",
            f"Coverage: {item['period_start']} to {item['period_end']}", f"Issues: {item['issue_codes'] or 'none'}", "",
        ))
    return {
        "outputs/account-summary.csv": _csv_bytes(ACCOUNT_SUMMARY_FIELDS, summary_rows),
        "outputs/reconciliation.csv": _csv_bytes(RECONCILIATION_FIELDS, reconciliation),
        "outputs/reconciliation-report.md": ("\n".join(report).rstrip() + "\n").encode("utf-8"),
    }


def _money(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")


def recover_ledger_workflow(ledger_root: Path) -> None:
    """Preflight every pending protocol before recovering them in dependency order."""
    from .classification import recover_pending_operation, validate_pending_operation
    from .importing import recover_pending_correction, validate_pending_correction

    validate_pending_correction(ledger_root)
    validate_pending_operation(ledger_root)
    validate_pending_output_bundle(ledger_root)
    recover_pending_correction(ledger_root)
    recover_pending_operation(ledger_root)
    recover_pending_output_bundle(ledger_root)


def _lexical_protocol_path(ledger_root: Path, relative: Path, *, directory: bool = False) -> Path:
    """Return a protocol path only through real ledger/work directories, never symlinks."""
    root = lexical_ledger_root(ledger_root)
    for ancestor in (root, root / "work"):
        try:
            mode = os.lstat(ancestor).st_mode
        except FileNotFoundError as error:
            raise ValueError("derived output protocol root is missing") from error
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise ValueError("derived output protocol root is unsafe")
    candidate = root / relative
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("derived output protocol path is unsafe") from error
    parent = root
    for part in relative.parts[:-1]:
        parent = parent / part
        if parent.exists():
            mode = os.lstat(parent).st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise ValueError("derived output protocol ancestor is unsafe")
    if candidate.exists() or candidate.is_symlink():
        mode = os.lstat(candidate).st_mode
        if stat.S_ISLNK(mode) or (directory and not stat.S_ISDIR(mode)):
            raise ValueError("derived output protocol path is unsafe")
    return candidate


def _authoritative_generation(ledger_root: Path) -> dict[str, str]:
    """Hash every input which can make a derived output generation stale."""
    root = lexical_ledger_root(ledger_root)
    generation: dict[str, str] = {}
    for relative in _GENERATION_INPUTS:
        path = _lexical_protocol_path(root, Path(relative))
        if not path.exists():
            generation[relative] = "absent"
        elif path.is_symlink() or not path.is_file():
            raise ValueError("authoritative ledger input is unsafe")
        else:
            generation[relative] = sha256_file(path)
    return generation


def _marker_path(ledger_root: Path) -> Path:
    return _lexical_protocol_path(ledger_root, _OUTPUT_BUNDLE_STAGE / ".protocol-marker")


def _validate_staged_artifact(relative: str, path: Path, expected: str) -> None:
    """Validate one complete public artifact, not just its file header."""
    if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
        raise ValueError("pending derived output cannot safely recover")
    if relative.endswith(".csv"):
        expected_headers = {
            "outputs/normalized-transactions.csv": CANONICAL_TRANSACTION_FIELDS,
            "outputs/classified-transactions.csv": CANONICAL_TRANSACTION_FIELDS,
            "outputs/account-summary.csv": ACCOUNT_SUMMARY_FIELDS,
            "outputs/reconciliation.csv": RECONCILIATION_FIELDS,
            "outputs/exceptions.csv": _EXCEPTION_FIELDS,
            "work/pending-merchant-groups.csv": _PENDING_GROUP_FIELDS,
        }[relative]
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            if tuple(reader.fieldnames or ()) != expected_headers or any(None in row or set(row) != set(expected_headers) for row in rows):
                raise ValueError("pending derived output is malformed")
        if relative in {"outputs/normalized-transactions.csv", "outputs/classified-transactions.csv"}:
            admitted, issues = admit_canonical_transactions(rows)
            if issues or len(admitted) != len(rows) or tuple(rows) != _ordered_transactions(rows):
                raise ValueError("pending derived output is malformed")
        elif relative == "outputs/account-summary.csv":
            seen = set()
            for row in rows:
                try:
                    unit = (row["account_label"], row["currency"])
                    periods, reconciled = int(row["period_count"]), int(row["reconciled_period_count"])
                    if not row["account_label"].startswith("account-") or not row["currency"] or periods < 0 or reconciled < 0 or reconciled > periods or row["state"] not in {state.value for state in RunState} or unit in seen:
                        raise ValueError
                    seen.add(unit)
                except (KeyError, ValueError):
                    raise ValueError("pending derived output is malformed")
        if relative == "outputs/reconciliation.csv":
            seen = set()
            for row in rows:
                try:
                    start, end = date.fromisoformat(str(row["period_start"])), date.fromisoformat(str(row["period_end"]))
                    unit = (row["account_label"], row["currency"], row["period_start"], row["period_end"])
                    if not row["account_label"].startswith("account-") or not row["currency"] or end < start or unit in seen or row["reconciled"] not in {"true", "false"}:
                        raise ValueError
                    seen.add(unit)
                    for field in ("opening_balance", "inflows", "outflows", "expected_closing", "reported_closing", "difference", "tolerance"):
                        if str(row[field]).strip():
                            value = Decimal(str(row[field]))
                            if not value.is_finite() or (field == "tolerance" and value < 0):
                                raise ValueError
                    if row["issue_codes"] and any(not re.fullmatch(r"[A-Z0-9_]+", code) for code in row["issue_codes"].split("|")):
                        raise ValueError
                except (KeyError, ValueError, InvalidOperation):
                    raise ValueError("pending derived output is malformed")
        elif relative == "outputs/exceptions.csv":
            for row in rows:
                if not re.fullmatch(r"[A-Z0-9_]+", row["code"]) or row["blocking"] not in {"true", "false"} or row["message"] != f"Issue: {row['code']}" or any(value and not value.startswith("source-") for value in (row["source_file"], row["source_location"])):
                    raise ValueError("pending derived output is malformed")
            if tuple(rows) != tuple(sorted(rows, key=lambda row: (row["code"], row["source_file"], row["source_location"], row["message"]))):
                raise ValueError("pending derived output is malformed")
        elif relative == "work/pending-merchant-groups.csv":
            seen = set()
            for row in rows:
                try:
                    if not row["group_id"] or row["group_id"] in seen or row["direction"] not in {"inflow", "outflow"} or int(row["transaction_count"]) <= 0:
                        raise ValueError
                    seen.add(row["group_id"]); date.fromisoformat(row["date_start"]); date.fromisoformat(row["date_end"])
                    currencies = row["currencies"].split("|") if row["currencies"] else []
                    totals = row["totals_by_currency"].split("|") if row["totals_by_currency"] else []
                    if not currencies or len(currencies) != len(totals) or any(":" not in item or item.split(":", 1)[0] not in currencies or not Decimal(item.split(":", 1)[1]).is_finite() for item in totals):
                        raise ValueError
                except (ValueError, InvalidOperation):
                    raise ValueError("pending derived output is malformed")
    elif relative == "outputs/status.json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        required = {"blocking_issue_count", "has_transactions", "output_hashes", "pending_group_count", "reconciled_unit_count", "state", "unit_count"}
        if set(payload) != required or not isinstance(payload.get("output_hashes"), dict) or payload.get("state") not in {state.value for state in RunState} or not isinstance(payload["has_transactions"], bool) or any(not isinstance(payload[field], int) or isinstance(payload[field], bool) or payload[field] < 0 for field in ("blocking_issue_count", "pending_group_count", "reconciled_unit_count", "unit_count")):
            raise ValueError("pending derived status is malformed")
        if any(not isinstance(value, str) or not _SHA256.fullmatch(value) for value in payload["output_hashes"].values()):
            raise ValueError("pending derived status is malformed")
    elif not path.read_bytes().endswith(b"\n"):
        raise ValueError("pending derived report is malformed")


def validate_pending_output_bundle(ledger_root: Path) -> None:
    """Validate an output journal and all staged bytes before any recovery mutation."""
    journal_path = _lexical_protocol_path(ledger_root, _OUTPUT_BUNDLE_JOURNAL)
    if not journal_path.exists():
        return
    with journal_path.open("r", encoding="utf-8") as handle:
        journal = json.load(handle)
    if not isinstance(journal, dict) or set(journal) != {"generation", "marker", "targets", "version"} or journal["version"] != 3 or not isinstance(journal["marker"], str) or not _SHA256.fullmatch(journal["marker"]) or not isinstance(journal["targets"], list) or journal.get("generation") != _authoritative_generation(ledger_root):
        raise ValueError("pending derived output journal is invalid")
    stage_root = _lexical_protocol_path(ledger_root, _OUTPUT_BUNDLE_STAGE, directory=True)
    marker = _marker_path(ledger_root)
    if not marker.is_file() or marker.is_symlink() or marker.read_text(encoding="ascii") != journal["marker"] + "\n":
        raise ValueError("pending derived output journal is invalid")
    targets = journal["targets"]
    if len(targets) != len({str(item.get("relative", "")) for item in targets if isinstance(item, dict)}):
        raise ValueError("pending derived output journal is invalid")
    ordered = []
    for item in targets:
        if not isinstance(item, dict) or set(item) != {"relative", "sha256"}:
            raise ValueError("pending derived output journal is invalid")
        relative, expected = item["relative"], item["sha256"]
        if not isinstance(relative, str) or relative not in _OUTPUT_TARGETS or not isinstance(expected, str) or not _SHA256.fullmatch(expected):
            raise ValueError("pending derived output journal is invalid")
        staged = _lexical_protocol_path(ledger_root, _OUTPUT_BUNDLE_STAGE / relative)
        target = _lexical_protocol_path(ledger_root, Path(relative))
        # A replacement may have completed before interruption.  It is safe to
        # resume without a staged copy only when the installed bytes validate.
        if staged.exists():
            _validate_staged_artifact(relative, staged, expected)
        else:
            _validate_staged_artifact(relative, target, expected)
        ordered.append(relative)
    if not _MANDATORY_OUTPUT_TARGETS.issubset(ordered) or set(ordered) != _OUTPUT_TARGETS or ordered[-1] != "outputs/status.json":
        raise ValueError("pending derived output journal is invalid")
    status_path = _lexical_protocol_path(ledger_root, _OUTPUT_BUNDLE_STAGE / "outputs/status.json")
    if not status_path.exists():
        status_path = _lexical_protocol_path(ledger_root, Path("outputs/status.json"))
    status = json.loads(status_path.read_text(encoding="utf-8"))
    expected_hashes = {str(item["relative"]): str(item["sha256"]) for item in targets if item["relative"] != "outputs/status.json"}
    for relative in ("work/import-manifest.json", "audit/audit.jsonl"):
        path = _lexical_protocol_path(ledger_root, Path(relative))
        if path.exists():
            expected_hashes[relative] = sha256_file(path)
    if status.get("output_hashes") != expected_hashes:
        raise ValueError("pending derived status is malformed")
    def artifact_path(relative: str) -> Path:
        candidate = _lexical_protocol_path(ledger_root, _OUTPUT_BUNDLE_STAGE / relative)
        if not candidate.exists():
            candidate = _lexical_protocol_path(ledger_root, Path(relative))
        return candidate

    def artifact_rows(relative: str) -> list[dict[str, str]]:
        with artifact_path(relative).open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    normalized = artifact_rows("outputs/normalized-transactions.csv")
    classified = artifact_rows("outputs/classified-transactions.csv")
    groups, reconciliation, summary, exceptions = (
        artifact_rows(relative)
        for relative in (
            "work/pending-merchant-groups.csv",
            "outputs/reconciliation.csv",
            "outputs/account-summary.csv",
            "outputs/exceptions.csv",
        )
    )

    normalized_by_id = {row["transaction_id"]: row for row in normalized}
    classified_by_id = {row["transaction_id"]: row for row in classified}
    if set(normalized_by_id) != set(classified_by_id) or len(normalized) != len(classified):
        raise ValueError("pending derived output cross-artifact validation failed")
    classification_fields = {
        "normalized_merchant", "classification_status", "account_code",
        "account_name", "rule_id", "review_note",
    }
    immutable_fields = set(CANONICAL_TRANSACTION_FIELDS) - classification_fields
    if any(
        any(normalized_by_id[transaction_id][field] != classified_by_id[transaction_id][field] for field in immutable_fields)
        for transaction_id in normalized_by_id
    ):
        raise ValueError("pending derived output cross-artifact validation failed")

    from .classification import apply_exact_rules, load_rules
    expected_classified = _ordered_transactions(
        apply_exact_rules(tuple(normalized), load_rules(ledger_root)).transactions
    )
    if tuple(classified) != expected_classified:
        raise ValueError("pending derived output cross-artifact validation failed")

    authoritative_transactions, canonical_load_issues = load_canonical_for_validation(ledger_root)
    authoritative_valid, canonical_issues = admit_canonical_transactions(authoritative_transactions)
    authoritative_by_id = {
        row["transaction_id"]: row for row in authoritative_valid
    }
    if set(normalized_by_id) != set(authoritative_by_id) or any(
        any(normalized_by_id[transaction_id][field] != authoritative_by_id[transaction_id][field] for field in immutable_fields)
        for transaction_id in normalized_by_id
    ):
        raise ValueError("pending derived output cross-artifact validation failed")

    authoritative_classification = apply_exact_rules(
        authoritative_valid,
        load_rules(ledger_root),
    )
    authoritative_classified = _ordered_transactions(authoritative_classification.transactions)
    if tuple(classified) != authoritative_classified:
        raise ValueError("pending derived output cross-artifact validation failed")
    expected_groups = _pending_group_rows(tuple(classified))
    if tuple(groups) != expected_groups:
        raise ValueError("pending derived output cross-artifact validation failed")

    pending_count = count_pending_classifications(classified)
    grouped_count = sum(int(row["transaction_count"]) for row in groups)
    if grouped_count > pending_count:
        raise ValueError("pending derived output cross-artifact validation failed")
    balance_rows, balance_issues = load_balance_rows(ledger_root)
    authoritative_reconciliation = reconcile_all(authoritative_classified, balance_rows)
    authoritative_issues = collect_ledger_issues(
        (
            *load_active_issues(ledger_root),
            *canonical_load_issues,
            *canonical_issues,
            *authoritative_classification.issues,
            *balance_issues,
        ),
        authoritative_reconciliation,
        pending_count,
    )
    authoritative_state = determine_run_state(
        bool(authoritative_transactions),
        pending_count,
        authoritative_reconciliation,
        authoritative_issues,
    )
    authoritative_all_issues = collect_ledger_issues(
        authoritative_issues,
        authoritative_reconciliation,
        pending_count,
    )
    expected_exceptions = tuple({
        "code": issue.code,
        "blocking": str(issue.blocking).lower(),
        "message": f"Issue: {issue.code}",
        "source_file": _opaque_source(issue.source_file),
        "source_location": _opaque_source(issue.source_location),
    } for issue in authoritative_all_issues)
    if tuple(exceptions) != expected_exceptions:
        raise ValueError("pending derived output cross-artifact validation failed")
    expected_reconciliation_artifacts = _reconciliation_artifacts(
        authoritative_reconciliation,
        authoritative_state,
    )
    if any(
        artifact_path(relative).read_bytes() != payload
        for relative, payload in expected_reconciliation_artifacts.items()
    ):
        raise ValueError("pending derived output cross-artifact validation failed")

    parsed_reconciliation = _parsed_reconciliation_rows(reconciliation)
    exception_issues = tuple(
        Issue(row["code"], row["message"], row["blocking"] == "true")
        for row in exceptions
    )
    exception_codes = {issue.code for issue in exception_issues}
    blocking_exception_codes = {issue.code for issue in exception_issues if issue.blocking}
    reconciliation_issue_codes = {
        issue.code for row in parsed_reconciliation for issue in row.issues
    }
    if not reconciliation_issue_codes.issubset(exception_codes) or any(
        code in _BLOCKING_CODES and code not in blocking_exception_codes
        for code in reconciliation_issue_codes
    ):
        raise ValueError("pending derived output cross-artifact validation failed")

    recomputed_state = determine_run_state(
        bool(normalized), pending_count, parsed_reconciliation, exception_issues
    )
    if recomputed_state != authoritative_state:
        raise ValueError("pending derived output cross-artifact validation failed")
    expected_status_facts = {
        "blocking_issue_count": sum(issue.blocking for issue in exception_issues),
        "has_transactions": bool(normalized),
        "pending_group_count": pending_count,
        "reconciled_unit_count": sum(row.reconciled for row in parsed_reconciliation),
        "state": recomputed_state.value,
        "unit_count": len(parsed_reconciliation),
    }
    if any(status[field] != value for field, value in expected_status_facts.items()):
        raise ValueError("pending derived output cross-artifact validation failed")

    actual_summary = {
        (row["account_label"], row["currency"]): (
            int(row["period_count"]), int(row["reconciled_period_count"])
        )
        for row in summary
    }
    reconciliation_units = {
        (row["account_label"], row["currency"]) for row in reconciliation
    }
    expected_summary = {
        key: (
            sum((row["account_label"], row["currency"]) == key for row in reconciliation),
            sum(
                (row["account_label"], row["currency"]) == key
                and row["reconciled"] == "true"
                for row in reconciliation
            ),
        )
        for key in reconciliation_units
    }
    if actual_summary != expected_summary or any(
        row["state"] != recomputed_state.value for row in summary
    ):
        raise ValueError("pending derived output cross-artifact validation failed")
    report_path = artifact_path("outputs/reconciliation-report.md")
    if not report_path.read_text(encoding="utf-8").startswith(f"Run state: {recomputed_state.value}\n"):
        raise ValueError("pending derived report is malformed")


def _remove_protocol_dir(ledger_root: Path, relative: Path, marker: str) -> None:
    directory = _lexical_protocol_path(ledger_root, relative, directory=True)
    marker_path = _lexical_protocol_path(ledger_root, relative / ".protocol-marker")
    if not marker_path.is_file() or marker_path.is_symlink() or marker_path.read_text(encoding="ascii") != marker + "\n":
        raise ValueError("derived output cleanup is unsafe")
    for current, dirs, files in os.walk(directory, followlinks=False):
        if any(Path(current, entry).is_symlink() for entry in (*dirs, *files)):
            raise ValueError("derived output cleanup is unsafe")
    shutil.rmtree(directory)


def recover_pending_output_bundle(ledger_root: Path) -> None:
    """Finish an interrupted derived-output installation before exposing a new generation."""
    journal_path = _lexical_protocol_path(ledger_root, _OUTPUT_BUNDLE_JOURNAL)
    if not journal_path.exists():
        return
    validate_pending_output_bundle(ledger_root)
    with journal_path.open("r", encoding="utf-8") as handle:
        journal = json.load(handle)
    stage_root = _lexical_protocol_path(ledger_root, _OUTPUT_BUNDLE_STAGE, directory=True)
    marker = str(journal["marker"])
    backup_root = _lexical_protocol_path(ledger_root, _OUTPUT_BUNDLE_BACKUP, directory=True) if _lexical_protocol_path(ledger_root, _OUTPUT_BUNDLE_BACKUP).exists() else None
    for item in journal["targets"]:
        relative, expected = str(item["relative"]), str(item["sha256"])
        target = _lexical_protocol_path(ledger_root, Path(relative))
        staged = _lexical_protocol_path(ledger_root, _OUTPUT_BUNDLE_STAGE / relative)
        backup = _lexical_protocol_path(ledger_root, _OUTPUT_BUNDLE_BACKUP / relative)
        if target.exists() and sha256_file(target) == expected:
            continue
        if not staged.exists() or sha256_file(staged) != expected:
            raise ValueError("pending derived output cannot safely recover")
        target.parent.mkdir(parents=True, exist_ok=True)
        _lexical_protocol_path(ledger_root, Path(relative).parent, directory=True)
        if target.exists() and not backup.exists():
            if backup_root is None:
                backup_root = _lexical_protocol_path(ledger_root, _OUTPUT_BUNDLE_BACKUP)
                backup_root.mkdir()
                (backup_root / ".protocol-marker").write_text(marker + "\n", encoding="ascii")
            backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, backup)
        os.replace(staged, target)
        if sha256_file(target) != expected:
            raise ValueError("pending derived output installed an unexpected file")
    journal_path.unlink()
    _remove_protocol_dir(ledger_root, _OUTPUT_BUNDLE_STAGE, marker)
    if backup_root is not None:
        _remove_protocol_dir(ledger_root, _OUTPUT_BUNDLE_BACKUP, marker)


def _install_output_bundle(ledger_root: Path, artifacts: Mapping[str, bytes]) -> None:
    recover_pending_output_bundle(ledger_root)
    stage_root = _lexical_protocol_path(ledger_root, _OUTPUT_BUNDLE_STAGE)
    backup_root = _lexical_protocol_path(ledger_root, _OUTPUT_BUNDLE_BACKUP)
    if stage_root.exists() or backup_root.exists():
        raise ValueError("derived output protocol is not clean")
    stage_root.mkdir(parents=True)
    marker = hashlib.sha256(os.urandom(32)).hexdigest()
    (stage_root / ".protocol-marker").write_text(marker + "\n", encoding="ascii")
    targets = []
    try:
        for relative, payload in sorted(artifacts.items()):
            staged = _lexical_protocol_path(ledger_root, _OUTPUT_BUNDLE_STAGE / relative)
            staged.parent.mkdir(parents=True, exist_ok=True)
            with staged.open("wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if sha256_file(staged) != hashlib.sha256(payload).hexdigest():
                raise ValueError("derived output staging hash mismatch")
            if relative.endswith(".csv"):
                with staged.open("r", encoding="utf-8", newline="") as handle:
                    if csv.DictReader(handle).fieldnames is None:
                        raise ValueError("derived output CSV is invalid")
            elif relative.endswith(".json"):
                json.loads(staged.read_text(encoding="utf-8"))
            elif not payload.endswith(b"\n"):
                raise ValueError("derived output text must end with a newline")
            targets.append({"relative": relative, "sha256": sha256_file(staged)})
        # Status is deliberately sorted last: it is the generation commit marker.
        targets.sort(key=lambda item: (item["relative"].endswith("outputs/status.json"), item["relative"]))
        atomic_write_json(
            _lexical_protocol_path(ledger_root, _OUTPUT_BUNDLE_JOURNAL),
            {"generation": _authoritative_generation(ledger_root), "marker": marker, "targets": targets, "version": 3},
        )
        recover_pending_output_bundle(ledger_root)
    except Exception:
        # A journal means recovery must preserve the target generation; without one staging is disposable.
        if not _lexical_protocol_path(ledger_root, _OUTPUT_BUNDLE_JOURNAL).exists():
            _remove_protocol_dir(ledger_root, _OUTPUT_BUNDLE_STAGE, marker)
        raise


def publish_derived_outputs(
    ledger_root: Path,
    *,
    record_validation: bool = False,
    update_canonical: bool = True,
) -> dict[str, object]:
    """Publish one complete deterministic ledger-local view, recovering an old view first."""
    recover_pending_output_bundle(ledger_root)
    from .classification import apply_exact_rules, load_rules

    transactions, canonical_load_issues = load_canonical_for_validation(ledger_root)
    valid_transactions, canonical_issues = admit_canonical_transactions(transactions)
    classified = apply_exact_rules(valid_transactions, load_rules(ledger_root))
    classified_rows = _ordered_transactions(classified.transactions)
    if update_canonical and not canonical_load_issues and not canonical_issues and len(classified_rows) == len(transactions):
        atomic_write_csv(resolve_inside_ledger(ledger_root, Path("work") / "normalized-transactions.csv"), CANONICAL_TRANSACTION_FIELDS, classified.transactions)
    from .storage import replace_active_issues
    replace_active_issues(ledger_root, "classification", {"view": "current"}, classified.issues)
    balance_rows, balance_issues = load_balance_rows(ledger_root)
    rows = reconcile_all(classified_rows, balance_rows)
    pending_group_count = count_pending_classifications(classified_rows)
    issues = collect_ledger_issues((*load_active_issues(ledger_root), *canonical_load_issues, *canonical_issues, *classified.issues, *balance_issues), rows, pending_group_count)
    state = determine_run_state(bool(transactions), pending_group_count, rows, issues)
    all_issues = collect_ledger_issues(issues, rows, pending_group_count)
    exceptions = ({
        "code": issue.code, "blocking": str(issue.blocking).lower(), "message": f"Issue: {issue.code}",
        "source_file": _opaque_source(issue.source_file), "source_location": _opaque_source(issue.source_location),
    } for issue in all_issues)
    artifacts: dict[str, bytes] = {
        "outputs/normalized-transactions.csv": _csv_bytes(CANONICAL_TRANSACTION_FIELDS, _ordered_transactions(valid_transactions)),
        "outputs/classified-transactions.csv": _csv_bytes(CANONICAL_TRANSACTION_FIELDS, classified_rows),
        "outputs/exceptions.csv": _csv_bytes(_EXCEPTION_FIELDS, exceptions),
    }
    artifacts.update(_reconciliation_artifacts(rows, state))
    artifacts["work/pending-merchant-groups.csv"] = _csv_bytes(
        _PENDING_GROUP_FIELDS,
        _pending_group_rows(classified_rows),
    )
    hashes = {relative: hashlib.sha256(payload).hexdigest() for relative, payload in sorted(artifacts.items())}
    manifest = resolve_inside_ledger(ledger_root, Path("work") / "import-manifest.json")
    if manifest.exists():
        hashes["work/import-manifest.json"] = sha256_file(manifest)
    if record_validation:
        input_hash = hashlib.sha256(json.dumps({
            "balances": sha256_file(resolve_inside_ledger(ledger_root, Path("inputs") / "account-balances.csv")),
            "rules": sha256_file(resolve_inside_ledger(ledger_root, "merchant-rules.csv")),
            "transactions": sha256_file(resolve_inside_ledger(ledger_root, Path("work") / "normalized-transactions.csv")) if resolve_inside_ledger(ledger_root, Path("work") / "normalized-transactions.csv").exists() else "",
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        append_audit_event(ledger_root, "validation_completed", {"input_sha256": input_hash, "output_hashes": hashes, "state": state.value}, dedupe_key=f"validation_completed:{input_hash}:{hashlib.sha256(json.dumps(hashes, sort_keys=True).encode('utf-8')).hexdigest()}")
    audit = resolve_inside_ledger(ledger_root, Path("audit") / "audit.jsonl")
    if audit.exists():
        hashes["audit/audit.jsonl"] = sha256_file(audit)
    status = {
        "blocking_issue_count": sum(issue.blocking for issue in all_issues), "has_transactions": bool(valid_transactions),
        "output_hashes": hashes, "pending_group_count": pending_group_count,
        "reconciled_unit_count": sum(row.reconciled for row in rows), "state": state.value, "unit_count": len(rows),
    }
    artifacts["outputs/status.json"] = _json_bytes(status)
    _install_output_bundle(ledger_root, artifacts)
    return status
