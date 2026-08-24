"""Canonical CSV statement normalization, overlap handling, and corrections."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Iterable
from uuid import uuid4

from .contracts import CANONICAL_TRANSACTION_FIELDS, AccountContext, ImportResult, Issue
from .storage import append_audit_event, atomic_write_csv, atomic_write_json, resolve_inside_ledger, sha256_file


_MONEY_FIELDS = frozenset({"inflow", "outflow", "running_balance"})
_PROVENANCE_FIELDS = frozenset({
    "transaction_id", "source_file", "source_page_or_row", "source_locations",
    "extraction_method", "extraction_confidence",
})
_EDITABLE_FIELDS = frozenset({
    "transaction_date", "posting_date", "inflow", "outflow", "running_balance",
    "reference", "normalized_merchant", "classification_status", "account_code",
    "account_name", "rule_id",
})
_MASKED_LABEL = re.compile(r"^\*+[^\d]*\d{4}$")


class _AmountError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CsvMapping:
    transaction_date: str
    description: str
    debit: str
    credit: str
    balance: str
    reference: str
    posting_date: str = ""
    date_formats: tuple[str, ...] = ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y")


@dataclass(frozen=True)
class StatementInventory:
    source_file: str
    institution: str
    masked_label: str
    currency: str
    confidence: str


@dataclass(frozen=True)
class AccountCandidate:
    institution: str
    masked_label: str
    currency: str
    source_files: tuple[str, ...]
    confidence: str
    issues: tuple[Issue, ...] = field(default_factory=tuple)


def parse_decimal(value: str) -> Decimal:
    """Parse a human CSV amount without using binary floating point."""
    text = str(value).strip().replace(",", "")
    if not text:
        return Decimal("0")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    text = re.sub(r"^[^0-9+\-.]+", "", text).replace(" ", "")
    try:
        parsed = Decimal(text)
    except InvalidOperation as error:
        raise ValueError(f"invalid decimal: {value}") from error
    return -parsed if negative else parsed


def serialize_decimal(value: Decimal) -> str:
    """Serialize a Decimal exactly, without exponent notation or float rounding."""
    return format(value, "f")


def _parse_date(value: str, formats: tuple[str, ...]) -> str:
    for date_format in formats:
        try:
            return datetime.strptime(value.strip(), date_format).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {value}")


def _account_issue(account: AccountContext) -> Issue | None:
    if not all((account.account_id, account.institution, account.masked_label, account.currency)):
        return Issue("ACCOUNT_UNCONFIRMED", "A confirmed account context is required.")
    if not _MASKED_LABEL.fullmatch(account.masked_label):
        return Issue("ACCOUNT_UNCONFIRMED", "Account labels must be explicitly masked before import.")
    return None


def _mapping_headers(mapping: CsvMapping) -> tuple[str, ...]:
    return tuple(value for value in (
        mapping.transaction_date, mapping.posting_date, mapping.description,
        mapping.debit, mapping.credit, mapping.balance, mapping.reference,
    ) if value)


def _canonical_row(
    source: Path,
    source_identity: str,
    source_hash: str,
    source_row: int,
    raw: dict[str, str],
    mapping: CsvMapping,
    account: AccountContext,
) -> dict[str, str]:
    transaction_date = _parse_date(raw[mapping.transaction_date], mapping.date_formats)
    posting_date = transaction_date
    if mapping.posting_date and raw.get(mapping.posting_date, "").strip():
        posting_date = _parse_date(raw[mapping.posting_date], mapping.date_formats)
    debit_text = raw.get(mapping.debit, "") if mapping.debit else ""
    credit_text = raw.get(mapping.credit, "") if mapping.credit else ""
    if not str(debit_text).strip() and not str(credit_text).strip():
        raise _AmountError("AMOUNT_MISSING", "A debit or credit amount is required.")
    try:
        debit = abs(parse_decimal(debit_text)) if str(debit_text).strip() else Decimal("0")
        credit = abs(parse_decimal(credit_text)) if str(credit_text).strip() else Decimal("0")
    except ValueError as error:
        raise _AmountError("AMOUNT_UNPARSEABLE", str(error)) from error
    if debit and credit:
        raise _AmountError("AMOUNT_DIRECTION_AMBIGUOUS", "simultaneous debit and credit")
    if not debit and not credit:
        raise _AmountError("AMOUNT_ZERO", "A transaction amount cannot be zero.")
    balance_text = raw.get(mapping.balance, "") if mapping.balance else ""
    if not str(balance_text).strip():
        raise _AmountError("AMOUNT_MISSING", "A running balance amount is required.")
    try:
        balance = parse_decimal(balance_text)
    except ValueError as error:
        raise _AmountError("AMOUNT_UNPARSEABLE", str(error)) from error
    transaction_id = hashlib.sha256(f"{source_identity}:{source_hash}:{source_row}".encode("utf-8")).hexdigest()
    location = f"{source_identity}:{source_row}"
    return {
        "transaction_id": transaction_id,
        "account_id": account.account_id,
        "currency": account.currency,
        "transaction_date": transaction_date,
        "posting_date": posting_date,
        "raw_description": raw[mapping.description],
        "normalized_merchant": "",
        "inflow": serialize_decimal(credit),
        "outflow": serialize_decimal(debit),
        "running_balance": serialize_decimal(balance),
        "reference": raw.get(mapping.reference, "") if mapping.reference else "",
        "source_file": source_identity,
        "source_page_or_row": str(source_row),
        "extraction_method": "csv",
        "extraction_confidence": "high",
        "classification_status": "unclassified",
        "account_code": "",
        "account_name": "",
        "rule_id": "",
        "review_note": "",
        "source_locations": location,
    }


def normalize_csv_statement(
    source: Path,
    mapping: CsvMapping,
    account: AccountContext,
    source_identity: str | None = None,
) -> ImportResult:
    """Return canonical rows or blocking issues without making format guesses."""
    source = Path(source)
    source_hash = sha256_file(source)
    logical_source = source_identity or source.name
    if not account.currency.strip():
        return ImportResult(
            issues=(Issue("CURRENCY_MISSING", "A currency is required for each import.", logical_source),),
            source_hashes={logical_source: source_hash},
        )
    account_issue = _account_issue(account)
    if account_issue is not None:
        return ImportResult(issues=(account_issue,), source_hashes={logical_source: source_hash})
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        missing = [header for header in _mapping_headers(mapping) if header not in fieldnames]
        if missing:
            return ImportResult(
                issues=(Issue("CSV_HEADER_MISSING", f"CSV header missing: {', '.join(missing)}", logical_source),),
                source_hashes={logical_source: source_hash},
            )
        rows: list[dict[str, str]] = []
        issues: list[Issue] = []
        for source_row, raw in enumerate(reader, start=2):
            try:
                rows.append(_canonical_row(source, logical_source, source_hash, source_row, raw, mapping, account))
            except _AmountError as error:
                issues.append(Issue(error.code, str(error), logical_source, str(source_row)))
            except ValueError as error:
                issues.append(Issue("DATE_UNPARSEABLE", str(error), logical_source, str(source_row)))
        if issues:
            return ImportResult(issues=tuple(issues), source_hashes={logical_source: source_hash})
    return ImportResult(transactions=tuple(rows), source_hashes={logical_source: source_hash})


def discover_account_candidates(inventories: tuple[StatementInventory, ...]) -> tuple[AccountCandidate, ...]:
    """Group exact masked account identities for explicit user confirmation."""
    grouped: dict[tuple[str, str, str], list[StatementInventory]] = {}
    for inventory in inventories:
        grouped.setdefault((inventory.institution, inventory.masked_label, inventory.currency), []).append(inventory)
    candidates: list[AccountCandidate] = []
    for identity, entries in sorted(grouped.items()):
        institution, masked_label, currency = identity
        issues: tuple[Issue, ...] = ()
        if not all(identity) or not _MASKED_LABEL.fullmatch(masked_label):
            issues = (Issue(
                "ACCOUNT_IDENTITY_AMBIGUOUS",
                "Institution, masked account label, and currency are required for confirmation.",
            ),)
        candidates.append(AccountCandidate(
            institution=institution,
            masked_label=masked_label,
            currency=currency,
            source_files=tuple(sorted(entry.source_file for entry in entries)),
            confidence="high" if not issues and all(entry.confidence == "high" for entry in entries) else "low",
            issues=issues,
        ))
    return tuple(candidates)


def transaction_signature(row: dict[str, str]) -> tuple[str, ...]:
    """Return the conservative account-scoped identity used for overlap matching."""
    return (
        row["account_id"], row["currency"], row["transaction_date"],
        row["posting_date"], row["inflow"], row["outflow"],
        " ".join(row["raw_description"].split()).upper(), row["reference"],
    )


def _locations(row: dict[str, str]) -> list[str]:
    return [value for value in row.get("source_locations", "").split("|") if value]


def deduplicate_overlaps(transactions: Iterable[dict[str, str]]) -> ImportResult:
    """Keep the maximum repeated count per source while retaining all locations."""
    grouped: dict[tuple[str, ...], list[dict[str, str]]] = {}
    order: list[tuple[str, ...]] = []
    for row in transactions:
        signature = transaction_signature(row)
        if signature not in grouped:
            grouped[signature] = []
            order.append(signature)
        grouped[signature].append(dict(row))

    kept: list[dict[str, str]] = []
    duplicates: list[dict[str, str]] = []
    for signature in order:
        signature_rows = grouped[signature]
        by_source: dict[str, list[dict[str, str]]] = {}
        source_order: list[str] = []
        for row in signature_rows:
            source = row["source_file"]
            if source not in by_source:
                by_source[source] = []
                source_order.append(source)
            by_source[source].append(row)
        maximum = max(len(rows) for rows in by_source.values())
        primary_source = next(source for source in source_order if len(by_source[source]) == maximum)
        primary = by_source[primary_source]
        for occurrence in range(maximum):
            chosen = dict(primary[occurrence])
            locations: list[str] = []
            for source in source_order:
                rows = by_source[source]
                if occurrence < len(rows):
                    for location in _locations(rows[occurrence]):
                        if location not in locations:
                            locations.append(location)
            chosen["source_locations"] = "|".join(locations)
            kept.append(chosen)
        if len(source_order) > 1:
            for source in source_order:
                if source == primary_source:
                    continue
                for row in by_source[source]:
                    duplicates.append({
                        "transaction_id": row["transaction_id"],
                        "source_file": source,
                        "source_page_or_row": row["source_page_or_row"],
                    })
    return ImportResult(transactions=tuple(kept), duplicate_sources=tuple(duplicates))


def _correction_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


_CANONICAL_RELATIVE_PATH = Path("work") / "normalized-transactions.csv"
_PENDING_CORRECTION_RELATIVE_PATH = Path("work") / "pending-correction.json"
_STAGED_CORRECTION_RELATIVE_PATH = Path("work") / "pending-correction.csv"


def _append_correction(ledger_root: Path, event: dict[str, str]) -> None:
    path = resolve_inside_ledger(ledger_root, Path("work") / "corrections.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _correction_recorded(ledger_root: Path, event_id: str) -> bool:
    path = resolve_inside_ledger(ledger_root, Path("work") / "corrections.jsonl")
    if not path.exists():
        return False
    with path.open("r", encoding="utf-8") as handle:
        return any(
            isinstance(record, dict) and record.get("event_id") == event_id
            for record in (json.loads(line) for line in handle if line.strip())
        )


def _validate_correction(field_name: str, corrected_value: str, row: dict[str, str]) -> str:
    if field_name == "raw_description":
        raise ValueError("raw_description is immutable")
    if field_name in _PROVENANCE_FIELDS:
        raise ValueError("provenance fields are immutable")
    if field_name not in _EDITABLE_FIELDS:
        raise ValueError(f"field is not manually correctable: {field_name}")
    if field_name in {"transaction_date", "posting_date"}:
        corrected_value = _parse_date(corrected_value, ("%Y-%m-%d",))
    elif field_name in _MONEY_FIELDS:
        corrected_value = serialize_decimal(parse_decimal(corrected_value))
        if field_name != "running_balance" and parse_decimal(corrected_value) < 0:
            raise ValueError("inflow and outflow must be non-negative")
    proposed = dict(row)
    proposed[field_name] = corrected_value
    if parse_decimal(proposed["inflow"]) and parse_decimal(proposed["outflow"]):
        raise ValueError("correction would create simultaneous inflow and outflow")
    return corrected_value


def _corrected_rows(
    transactions: tuple[dict[str, str], ...],
    transaction_id: str,
    field_name: str,
    corrected_value: str,
    event_id: str,
) -> tuple[dict[str, str], ...]:
    output: list[dict[str, str]] = []
    for row in transactions:
        revised = dict(row)
        if row.get("transaction_id") == transaction_id:
            revised[field_name] = corrected_value
            revised["review_note"] = event_id
        output.append(revised)
    return tuple(output)


def stage_manual_correction(
    ledger_root: Path,
    transactions: tuple[dict[str, str], ...],
    transaction_id: str,
    field_name: str,
    corrected_value: str,
    reason: str,
    actor: str,
) -> tuple[dict[str, str], ...]:
    """Stage one correction in a recoverable journal without changing canonical rows."""
    recover_pending_correction(ledger_root)
    if not reason.strip() or not actor.strip():
        raise ValueError("a correction reason and actor are required")
    matches = [row for row in transactions if row.get("transaction_id") == transaction_id]
    if len(matches) != 1:
        raise ValueError("transaction ID must identify exactly one row")
    original = matches[0]
    corrected = _validate_correction(field_name, corrected_value, original)
    event_id = uuid4().hex
    output = _corrected_rows(transactions, transaction_id, field_name, corrected, event_id)
    correction_record = {
        "actor": actor,
        "corrected_value": corrected,
        "event_id": event_id,
        "field_name": field_name,
        "original_value": original[field_name],
        "reason": reason,
        "timestamp": _correction_timestamp(),
        "transaction_id": transaction_id,
    }
    staged_path = resolve_inside_ledger(ledger_root, _STAGED_CORRECTION_RELATIVE_PATH)
    atomic_write_csv(staged_path, CANONICAL_TRANSACTION_FIELDS, output)
    journal = {
        "audit_payload": {
            "corrected_value_sha256": hashlib.sha256(corrected.encode("utf-8")).hexdigest(),
            "field_name": field_name,
            "original_value_sha256": hashlib.sha256(original[field_name].encode("utf-8")).hexdigest(),
            "reason_sha256": hashlib.sha256(reason.encode("utf-8")).hexdigest(),
            "transaction_id": transaction_id,
        },
        "canonical_relative_path": str(_CANONICAL_RELATIVE_PATH),
        "correction_record": correction_record,
        "event_id": event_id,
        "expected_canonical_sha256": sha256_file(staged_path),
        "staged_relative_path": str(_STAGED_CORRECTION_RELATIVE_PATH),
    }
    atomic_write_json(resolve_inside_ledger(ledger_root, _PENDING_CORRECTION_RELATIVE_PATH), journal)
    return output


def recover_pending_correction(ledger_root: Path) -> None:
    """Finish a journaled correction exactly once after a process interruption."""
    journal_path = resolve_inside_ledger(ledger_root, _PENDING_CORRECTION_RELATIVE_PATH)
    if not journal_path.exists():
        return
    with journal_path.open("r", encoding="utf-8") as handle:
        journal = json.load(handle)
    if not isinstance(journal, dict):
        raise ValueError("pending correction journal is invalid")
    required = {
        "audit_payload", "canonical_relative_path", "correction_record", "event_id",
        "expected_canonical_sha256", "staged_relative_path",
    }
    if set(journal) != required or not isinstance(journal["audit_payload"], dict) or not isinstance(journal["correction_record"], dict):
        raise ValueError("pending correction journal is invalid")
    canonical_path = resolve_inside_ledger(ledger_root, str(journal["canonical_relative_path"]))
    staged_path = resolve_inside_ledger(ledger_root, str(journal["staged_relative_path"]))
    expected_hash = str(journal["expected_canonical_sha256"])
    canonical_matches = canonical_path.exists() and sha256_file(canonical_path) == expected_hash
    if not canonical_matches:
        if not staged_path.exists() or sha256_file(staged_path) != expected_hash:
            raise ValueError("pending correction cannot safely recover canonical rows")
        os.replace(staged_path, canonical_path)
    event_id = append_audit_event(
        ledger_root,
        "manual_correction_recorded",
        dict(journal["audit_payload"]),
        actor=str(journal["correction_record"].get("actor", "user")),
        dedupe_key=f"manual-correction:{journal['event_id']}",
        event_id=str(journal["event_id"]),
    )
    if event_id != journal["event_id"]:
        raise ValueError("pending correction audit event does not match its journal")
    correction_record = {str(key): str(value) for key, value in journal["correction_record"].items()}
    if not _correction_recorded(ledger_root, event_id):
        _append_correction(ledger_root, correction_record)
    journal_path.unlink()


def apply_manual_correction(
    ledger_root: Path,
    transactions: tuple[dict[str, str], ...],
    transaction_id: str,
    field_name: str,
    corrected_value: str,
    reason: str,
    actor: str,
) -> tuple[dict[str, str], ...]:
    """Persist a correction through a pending journal and return its corrected rows."""
    output = stage_manual_correction(
        ledger_root, transactions, transaction_id, field_name, corrected_value, reason, actor,
    )
    recover_pending_correction(ledger_root)
    return output


def merge_import_results(results: Iterable[ImportResult]) -> ImportResult:
    """Merge normalized sources while preserving issues, hashes, and overlap audit data."""
    results = tuple(results)
    merged = deduplicate_overlaps(row for result in results for row in result.transactions)
    source_hashes: dict[str, str] = {}
    for result in results:
        source_hashes.update(result.source_hashes)
    return ImportResult(
        transactions=merged.transactions,
        issues=tuple(issue for result in results for issue in result.issues),
        source_hashes=source_hashes,
        duplicate_sources=merged.duplicate_sources,
        staged_files=tuple(path for result in results for path in result.staged_files),
    )
