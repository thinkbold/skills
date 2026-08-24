"""Run-state precedence, exception collection, and safe final status output."""

from __future__ import annotations

import hashlib
import io
import json
import csv
import os
import re
import shutil
from pathlib import Path
from typing import Iterable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation

from .contracts import Issue, RunState
from .contracts import CANONICAL_TRANSACTION_FIELDS
from .reconciliation import ACCOUNT_SUMMARY_FIELDS, RECONCILIATION_FIELDS, ReconciliationRow, load_balance_rows, reconcile_all
from .storage import append_audit_event, atomic_write_csv, atomic_write_json, load_active_issues, resolve_inside_ledger, sha256_file


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


def recover_pending_output_bundle(ledger_root: Path) -> None:
    """Finish an interrupted derived-output installation before exposing a new generation."""
    journal_path = resolve_inside_ledger(ledger_root, _OUTPUT_BUNDLE_JOURNAL)
    if not journal_path.exists():
        return
    with journal_path.open("r", encoding="utf-8") as handle:
        journal = json.load(handle)
    if not isinstance(journal, dict) or set(journal) != {"targets", "version"} or journal["version"] != 1 or not isinstance(journal["targets"], list):
        raise ValueError("pending derived output journal is invalid")
    stage_root = resolve_inside_ledger(ledger_root, _OUTPUT_BUNDLE_STAGE)
    backup_root = resolve_inside_ledger(ledger_root, _OUTPUT_BUNDLE_BACKUP)
    for item in journal["targets"]:
        if not isinstance(item, dict) or set(item) != {"relative", "sha256"}:
            raise ValueError("pending derived output journal is invalid")
        relative, expected = str(item["relative"]), str(item["sha256"])
        target = resolve_inside_ledger(ledger_root, relative)
        staged = resolve_inside_ledger(ledger_root, _OUTPUT_BUNDLE_STAGE / relative)
        backup = resolve_inside_ledger(ledger_root, _OUTPUT_BUNDLE_BACKUP / relative)
        if target.exists() and sha256_file(target) == expected:
            continue
        if not staged.exists() or sha256_file(staged) != expected:
            raise ValueError("pending derived output cannot safely recover")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, backup)
        os.replace(staged, target)
        if sha256_file(target) != expected:
            raise ValueError("pending derived output installed an unexpected file")
    journal_path.unlink()
    shutil.rmtree(stage_root, ignore_errors=True)
    shutil.rmtree(backup_root, ignore_errors=True)


def _install_output_bundle(ledger_root: Path, artifacts: Mapping[str, bytes]) -> None:
    recover_pending_output_bundle(ledger_root)
    stage_root = resolve_inside_ledger(ledger_root, _OUTPUT_BUNDLE_STAGE)
    backup_root = resolve_inside_ledger(ledger_root, _OUTPUT_BUNDLE_BACKUP)
    shutil.rmtree(stage_root, ignore_errors=True)
    shutil.rmtree(backup_root, ignore_errors=True)
    stage_root.mkdir(parents=True)
    targets = []
    try:
        for relative, payload in sorted(artifacts.items()):
            staged = resolve_inside_ledger(ledger_root, _OUTPUT_BUNDLE_STAGE / relative)
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
        atomic_write_json(resolve_inside_ledger(ledger_root, _OUTPUT_BUNDLE_JOURNAL), {"targets": targets, "version": 1})
        recover_pending_output_bundle(ledger_root)
    except Exception:
        # A journal means recovery must preserve the target generation; without one staging is disposable.
        if not resolve_inside_ledger(ledger_root, _OUTPUT_BUNDLE_JOURNAL).exists():
            shutil.rmtree(stage_root, ignore_errors=True)
            shutil.rmtree(backup_root, ignore_errors=True)
        raise


def publish_derived_outputs(ledger_root: Path, *, record_validation: bool = False) -> dict[str, object]:
    """Publish one complete deterministic ledger-local view, recovering an old view first."""
    recover_pending_output_bundle(ledger_root)
    from .classification import apply_exact_rules, build_pending_groups, load_rules

    transactions, canonical_load_issues = load_canonical_for_validation(ledger_root)
    valid_transactions, canonical_issues = admit_canonical_transactions(transactions)
    classified = apply_exact_rules(valid_transactions, load_rules(ledger_root))
    classified_rows = _ordered_transactions(classified.transactions)
    if not canonical_load_issues and not canonical_issues and len(classified_rows) == len(transactions):
        atomic_write_csv(resolve_inside_ledger(ledger_root, Path("work") / "normalized-transactions.csv"), CANONICAL_TRANSACTION_FIELDS, classified_rows)
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
        "outputs/normalized-transactions.csv": _csv_bytes(CANONICAL_TRANSACTION_FIELDS, _ordered_transactions(transactions)),
        "outputs/classified-transactions.csv": _csv_bytes(CANONICAL_TRANSACTION_FIELDS, classified_rows),
        "outputs/exceptions.csv": _csv_bytes(_EXCEPTION_FIELDS, exceptions),
    }
    artifacts.update(_reconciliation_artifacts(rows, state))
    groups = build_pending_groups(classified_rows)
    artifacts["work/pending-merchant-groups.csv"] = _csv_bytes(_PENDING_GROUP_FIELDS, ({
            "group_id": group.group_id, "normalized_merchant": group.normalized_merchant, "direction": group.direction,
            "currencies": "|".join(group.currencies), "account_ids": "|".join(group.account_ids),
            "transaction_count": str(group.transaction_count), "totals_by_currency": "|".join(f"{currency}:{amount}" for currency, amount in group.totals_by_currency),
            "date_start": group.date_start, "date_end": group.date_end, "confidence": group.confidence,
        } for group in groups))
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
        "blocking_issue_count": sum(issue.blocking for issue in all_issues), "has_transactions": bool(transactions),
        "output_hashes": hashes, "pending_group_count": pending_group_count,
        "reconciled_unit_count": sum(row.reconciled for row in rows), "state": state.value, "unit_count": len(rows),
    }
    artifacts["outputs/status.json"] = _json_bytes(status)
    _install_output_bundle(ledger_root, artifacts)
    return status
