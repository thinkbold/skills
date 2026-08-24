"""Ledger-local merchant classification, exact rules, and auditable rule lifecycle."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from difflib import SequenceMatcher
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata
from uuid import uuid4

from .contracts import CANONICAL_TRANSACTION_FIELDS, Issue, MERCHANT_RULE_FIELDS
from .storage import append_audit_event, atomic_write_csv, atomic_write_json, read_audit_events, resolve_inside_ledger, sha256_file


_CHART_FIELDS = ("account_code", "account_name", "active")
_CANONICAL_PATH = Path("work") / "normalized-transactions.csv"
_RULES_PATH = Path("merchant-rules.csv")
_PENDING_OPERATION_PATH = Path("work") / "pending-classification-operation.json"
_STAGED_TRANSACTIONS_PATH = Path("work") / "pending-classification-transactions.csv"
_STAGED_RULES_PATH = Path("work") / "pending-classification-rules.csv"
_DATE_PATTERN = re.compile(r"\b(?:19|20)\d{2}[/-](?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])\b")


@dataclass(frozen=True)
class ChartEntry:
    account_code: str
    account_name: str
    active: bool


@dataclass(frozen=True)
class MerchantGroup:
    group_id: str
    normalized_merchant: str
    direction: str
    currencies: tuple[str, ...]
    account_ids: tuple[str, ...]
    transaction_ids: tuple[str, ...]
    sample_descriptions: tuple[str, ...]
    transaction_count: int
    totals_by_currency: tuple[tuple[str, str], ...]
    date_start: str
    date_end: str
    confidence: str


@dataclass(frozen=True)
class ClassificationResult:
    transactions: tuple[dict[str, str], ...]
    created_rules: tuple[dict[str, str], ...] = ()
    issues: tuple[Issue, ...] = ()
    audit_event_ids: tuple[str, ...] = ()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_transaction_ids(transactions: tuple[dict[str, str], ...]) -> None:
    ids = [row.get("transaction_id", "").strip() for row in transactions]
    if any(not transaction_id for transaction_id in ids) or len(set(ids)) != len(ids):
        raise ValueError("normalized transactions require unique non-empty transaction_id values")


def normalize_merchant(value: str) -> str:
    """Conservatively normalize a description without stripping merchant words."""
    text = unicodedata.normalize("NFKC", value).upper()
    text = _DATE_PATTERN.sub(" ", text)
    text = "".join(character if character.isalnum() else " " for character in text)
    tokens = [token for token in text.split() if token]
    while tokens and len(tokens[-1]) >= 5 and all(character.isalnum() for character in tokens[-1]) and any(character.isalpha() for character in tokens[-1]) and any(character.isdigit() for character in tokens[-1]):
        tokens.pop()
    return " ".join(tokens)


def _direction(row: dict[str, str]) -> str:
    if Decimal(row.get("outflow", "0") or "0") > 0:
        return "outflow"
    if Decimal(row.get("inflow", "0") or "0") > 0:
        return "inflow"
    return ""


def _normalized(row: dict[str, str]) -> str:
    return row.get("normalized_merchant", "").strip() or normalize_merchant(row.get("raw_description", ""))


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in re.split(r"[\s,]+", value.strip().upper()) if token)


def load_chart(ledger_root: Path) -> tuple[ChartEntry, ...]:
    """Load the selected ledger chart, if the user supplied one."""
    path = resolve_inside_ledger(ledger_root, "chart-of-accounts.csv")
    if not path.exists():
        return ()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not set(_CHART_FIELDS).issubset(reader.fieldnames):
            raise ValueError("chart must contain account_code, account_name, and active")
        entries: list[ChartEntry] = []
        for raw in reader:
            active_text = raw.get("active", "").strip().lower()
            if active_text not in {"true", "false"}:
                raise ValueError("chart active must be true or false")
            code = raw.get("account_code", "").strip()
            name = raw.get("account_name", "").strip()
            if not code or not name:
                raise ValueError("chart account_code and account_name are required")
            entries.append(ChartEntry(code, name, active_text == "true"))
    if len({entry.account_code for entry in entries}) != len(entries):
        raise ValueError("chart account codes must be unique")
    return tuple(entries)


def load_rules(ledger_root: Path) -> list[dict[str, str]]:
    """Read only the selected ledger's merchant rule memory."""
    path = resolve_inside_ledger(ledger_root, _RULES_PATH)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(MERCHANT_RULE_FIELDS):
            raise ValueError("merchant rules have unsupported columns")
        rows = list(reader)
    if any(set(row) != set(MERCHANT_RULE_FIELDS) for row in rows):
        raise ValueError("merchant rules have unsupported columns")
    return rows


def _write_rules(ledger_root: Path, rules: list[dict[str, str]]) -> None:
    atomic_write_csv(resolve_inside_ledger(ledger_root, _RULES_PATH), MERCHANT_RULE_FIELDS, rules)


def load_transactions(ledger_root: Path) -> tuple[dict[str, str], ...]:
    path = resolve_inside_ledger(ledger_root, _CANONICAL_PATH)
    if not path.exists():
        return ()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(CANONICAL_TRANSACTION_FIELDS):
            raise ValueError("normalized transactions have unsupported columns")
        rows = list(reader)
    if any(set(row) != set(CANONICAL_TRANSACTION_FIELDS) for row in rows):
        raise ValueError("normalized transactions have unsupported columns")
    transactions = tuple(rows)
    _validate_transaction_ids(transactions)
    return transactions


def save_transactions(ledger_root: Path, transactions: tuple[dict[str, str], ...]) -> None:
    atomic_write_csv(resolve_inside_ledger(ledger_root, _CANONICAL_PATH), CANONICAL_TRANSACTION_FIELDS, transactions)


def build_pending_groups(transactions: tuple[dict[str, str], ...]) -> tuple[MerchantGroup, ...]:
    """Build review questions by normalized merchant and direction, never by currency total."""
    _validate_transaction_ids(transactions)
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in transactions:
        if row.get("classification_status", "unclassified") != "unclassified":
            continue
        merchant, direction = _normalized(row), _direction(row)
        if merchant and direction:
            grouped.setdefault((merchant, direction), []).append(row)
    groups: list[MerchantGroup] = []
    for (merchant, direction), rows in sorted(grouped.items()):
        ordered = sorted(rows, key=lambda item: (item.get("transaction_date", ""), item.get("transaction_id", "")))
        totals: dict[str, Decimal] = {}
        for item in ordered:
            currency = item.get("currency", "")
            amount = Decimal(item.get("outflow" if direction == "outflow" else "inflow", "0") or "0")
            totals[currency] = totals.get(currency, Decimal("0")) + amount
        ids = tuple(item.get("transaction_id", "") for item in ordered)
        digest = hashlib.sha256((merchant + "\0" + direction + "\0" + "\0".join(ids)).encode("utf-8")).hexdigest()[:16]
        groups.append(MerchantGroup(
            group_id=f"merchant-{digest}", normalized_merchant=merchant, direction=direction,
            currencies=tuple(sorted(totals)), account_ids=tuple(sorted({item.get("account_id", "") for item in ordered})),
            transaction_ids=ids, sample_descriptions=tuple(item.get("raw_description", "") for item in ordered[:3]),
            transaction_count=len(ordered), totals_by_currency=tuple((currency, format(totals[currency], ".2f")) for currency in sorted(totals)),
            date_start=min(item.get("transaction_date", "") for item in ordered), date_end=max(item.get("transaction_date", "") for item in ordered),
            confidence="review_required",
        ))
    return tuple(groups)


def _matching_rules(row: dict[str, str], rules: list[dict[str, str]]) -> list[dict[str, str]]:
    merchant, direction = _normalized(row), _direction(row)
    words = set(merchant.split())
    matching: list[dict[str, str]] = []
    for rule in rules:
        if rule.get("status") != "active" or rule.get("match_type") != "exact_normalized":
            continue
        if rule.get("normalized_merchant") != merchant or rule.get("direction") != direction:
            continue
        if rule.get("account_scope") and rule["account_scope"] != row.get("account_id", ""):
            continue
        if not set(_tokens(rule.get("required_tokens", ""))).issubset(words):
            continue
        if set(_tokens(rule.get("excluded_tokens", ""))) & words:
            continue
        matching.append(rule)
    if not matching:
        return []
    # Account-scoped and token-constrained rules are more specific than a broad exact rule.
    score = lambda rule: (bool(rule.get("account_scope")), len(_tokens(rule.get("required_tokens", ""))) + len(_tokens(rule.get("excluded_tokens", ""))))
    best = max(score(rule) for rule in matching)
    return [rule for rule in matching if score(rule) == best]


def apply_exact_rules(transactions: tuple[dict[str, str], ...], rules: list[dict[str, str]]) -> ClassificationResult:
    """Apply a single unambiguous active exact rule; fuzzy matching is deliberately absent."""
    _validate_transaction_ids(transactions)
    output: list[dict[str, str]] = []
    issues: list[Issue] = []
    for source in transactions:
        row = dict(source)
        if row.get("classification_status", "unclassified") != "unclassified":
            output.append(row)
            continue
        row["normalized_merchant"] = _normalized(row)
        winners = _matching_rules(row, rules)
        if len(winners) == 1:
            rule = winners[0]
            row.update({"classification_status": "classified", "account_code": rule["account_code"], "account_name": rule["account_name"], "rule_id": rule["rule_id"], "review_note": ""})
        elif len(winners) > 1:
            row["review_note"] = "MERCHANT_RULE_CONFLICT"
            issues.append(Issue("MERCHANT_RULE_CONFLICT", "Multiple active exact merchant rules require review.", False, row.get("source_file", ""), row.get("source_page_or_row", "")))
        output.append(row)
    return ClassificationResult(tuple(output), issues=tuple(issues))


def suggest_fuzzy_rules(normalized_merchant: str, rules: list[dict[str, str]], limit: int = 3) -> tuple[dict[str, str], ...]:
    """Rank candidate rules for a human; this function never receives or changes transactions."""
    needle = normalize_merchant(normalized_merchant)
    scored = [
        (SequenceMatcher(None, needle, rule.get("normalized_merchant", "")).ratio(), rule)
        for rule in rules if rule.get("status") == "active" and rule.get("match_type") == "exact_normalized"
    ]
    return tuple(dict(rule, similarity=f"{score:.3f}") for score, rule in sorted(scored, key=lambda item: (-item[0], item[1].get("rule_id", "")))[:limit] if score > 0)


def _validate_category(ledger_root: Path, account_code: str, account_name: str) -> tuple[str, str]:
    chart = load_chart(ledger_root)
    code, name = account_code.strip(), account_name.strip()
    if chart:
        active = {entry.account_code: entry for entry in chart if entry.active}
        if not code or code not in active:
            raise ValueError("account code is not active")
        return code, name or active[code].account_name
    if code:
        raise ValueError("account code must be blank when no chart exists")
    if not name:
        raise ValueError("account name is required when no chart exists")
    return "", name


def _new_rule(merchant: str, direction: str, account_code: str, account_name: str, audit_event_id: str, account_scope: str = "") -> dict[str, str]:
    now = _timestamp()
    return {
        "rule_id": f"rule-{uuid4().hex}", "normalized_merchant": merchant, "direction": direction,
        "required_tokens": "", "excluded_tokens": "", "account_scope": account_scope,
        "account_code": account_code, "account_name": account_name, "match_type": "exact_normalized",
        "status": "active", "created_at": now, "updated_at": now, "audit_event_id": audit_event_id,
    }


def _operation_key(kind: str, values: dict[str, object]) -> str:
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"classification:{kind}:{hashlib.sha256(encoded).hexdigest()}"


def _completed_operation(ledger_root: Path, operation_key: str) -> str | None:
    for event in read_audit_events(ledger_root):
        if event.get("dedupe_key") == operation_key:
            return str(event["event_id"])
    return None


def _install_staged_file(ledger_root: Path, staged_relative: Path, target_relative: Path, expected_hash: str) -> None:
    staged = resolve_inside_ledger(ledger_root, staged_relative)
    target = resolve_inside_ledger(ledger_root, target_relative)
    if target.exists() and sha256_file(target) == expected_hash:
        return
    if not staged.exists() or sha256_file(staged) != expected_hash:
        raise ValueError("pending classification operation cannot safely recover")
    os.replace(staged, target)
    if sha256_file(target) != expected_hash:
        raise ValueError("pending classification operation wrote an unexpected target")


def recover_pending_operation(ledger_root: Path) -> str | None:
    """Complete a previously staged classification mutation exactly once."""
    journal_path = resolve_inside_ledger(ledger_root, _PENDING_OPERATION_PATH)
    if not journal_path.exists():
        return None
    with journal_path.open("r", encoding="utf-8") as handle:
        journal = json.load(handle)
    required = {
        "actor", "audit_event_id", "event_payload", "event_type", "operation_key",
        "rules_sha256", "transactions_sha256",
    }
    if not isinstance(journal, dict) or set(journal) != required or not isinstance(journal["event_payload"], dict):
        raise ValueError("pending classification operation is invalid")
    _install_staged_file(ledger_root, _STAGED_TRANSACTIONS_PATH, _CANONICAL_PATH, str(journal["transactions_sha256"]))
    _install_staged_file(ledger_root, _STAGED_RULES_PATH, _RULES_PATH, str(journal["rules_sha256"]))
    event_id = append_audit_event(
        ledger_root, str(journal["event_type"]), dict(journal["event_payload"]),
        actor=str(journal["actor"]), dedupe_key=str(journal["operation_key"]), event_id=str(journal["audit_event_id"]),
    )
    if event_id != journal["audit_event_id"]:
        raise ValueError("pending classification operation audit event does not match its journal")
    journal_path.unlink()
    resolve_inside_ledger(ledger_root, _STAGED_TRANSACTIONS_PATH).unlink(missing_ok=True)
    resolve_inside_ledger(ledger_root, _STAGED_RULES_PATH).unlink(missing_ok=True)
    return event_id


def _completed_result(ledger_root: Path, event_id: str) -> ClassificationResult:
    return ClassificationResult(load_transactions(ledger_root), audit_event_ids=(event_id,))


def confirm_group(
    ledger_root: Path,
    transactions: tuple[dict[str, str], ...],
    normalized_merchant: str,
    direction: str,
    account_code: str,
    account_name: str,
    apply_future: bool,
    actor: str,
    transaction_ids: tuple[str, ...] | None = None,
) -> ClassificationResult:
    """Confirm current rows and optionally retain one ledger-local exact rule."""
    recover_pending_operation(ledger_root)
    _validate_transaction_ids(transactions)
    code, name = _validate_category(ledger_root, account_code, account_name)
    merchant = normalize_merchant(normalized_merchant)
    if transaction_ids is not None:
        selected_ids = tuple(transaction_ids)
    else:
        selected_ids = tuple(row["transaction_id"] for row in sorted(
            (row for row in transactions if row.get("classification_status", "unclassified") == "unclassified"
             and _normalized(row) == merchant and _direction(row) == direction),
            key=lambda row: (row.get("transaction_date", ""), row["transaction_id"]),
        ))
    if not selected_ids:
        raise ValueError("group has no unclassified transactions")
    by_id = {row["transaction_id"]: row for row in transactions}
    if len(selected_ids) != len(set(selected_ids)) or any(transaction_id not in by_id for transaction_id in selected_ids):
        raise ValueError("group no longer matches its selected transactions")
    selected = [by_id[transaction_id] for transaction_id in selected_ids]
    if any(row.get("classification_status", "unclassified") != "unclassified" or _normalized(row) != merchant or _direction(row) != direction for row in selected):
        raise ValueError("group no longer matches its selected transactions")
    group_id = "merchant-" + hashlib.sha256((merchant + "\0" + direction + "\0" + "\0".join(selected_ids)).encode("utf-8")).hexdigest()[:16]
    operation_key = _operation_key("confirm", {
        "account_code": code, "account_name": name, "apply_future": apply_future,
        "direction": direction, "merchant": merchant, "transaction_ids": tuple(sorted(selected_ids)),
    })
    completed = _completed_operation(ledger_root, operation_key)
    if completed is not None:
        return _completed_result(ledger_root, completed)
    existing = load_rules(ledger_root)
    created: tuple[dict[str, str], ...] = ()
    rule: dict[str, str] | None = None
    if apply_future:
        matches = [item for item in existing if item.get("status") == "active" and item.get("normalized_merchant") == merchant and item.get("direction") == direction and item.get("account_code") == code and item.get("account_name") == name and not item.get("account_scope") and item.get("match_type") == "exact_normalized"]
        if matches:
            rule = matches[0]
        else:
            rule = _new_rule(merchant, direction, code, name, "PENDING")
            existing.append(rule)
            created = (rule,)
    output: list[dict[str, str]] = []
    for source in transactions:
        item = dict(source)
        if item.get("transaction_id") in selected_ids:
            item.update({"normalized_merchant": merchant, "classification_status": "classified", "account_code": code, "account_name": name, "rule_id": rule["rule_id"] if rule else "", "review_note": ""})
        output.append(item)
    event_payload = {
        "transaction_ids": list(selected_ids), "normalized_merchant_sha256": hashlib.sha256(merchant.encode()).hexdigest(),
        "direction": direction, "account_code": code, "account_name_sha256": hashlib.sha256(name.encode()).hexdigest(),
        "apply_future": apply_future, "group_id": group_id,
    }
    event_id = uuid4().hex
    if rule is not None and rule["audit_event_id"] == "PENDING":
        rule["audit_event_id"] = event_id
    # Stage with the preallocated audit ID so the rule and audit record are permanently linked.
    transactions_path = resolve_inside_ledger(ledger_root, _STAGED_TRANSACTIONS_PATH)
    rules_path = resolve_inside_ledger(ledger_root, _STAGED_RULES_PATH)
    atomic_write_csv(transactions_path, CANONICAL_TRANSACTION_FIELDS, tuple(output))
    atomic_write_csv(rules_path, MERCHANT_RULE_FIELDS, existing)
    atomic_write_json(resolve_inside_ledger(ledger_root, _PENDING_OPERATION_PATH), {
        "actor": actor, "audit_event_id": event_id, "event_payload": event_payload,
        "event_type": "merchant_group_confirmed", "operation_key": operation_key,
        "rules_sha256": sha256_file(rules_path), "transactions_sha256": sha256_file(transactions_path),
    })
    recovered = recover_pending_operation(ledger_root)
    if recovered != event_id:
        raise ValueError("classification operation did not recover its audit event")
    return ClassificationResult(tuple(output), created_rules=created, audit_event_ids=(event_id,))


def correct_transactions(ledger_root: Path, transactions: tuple[dict[str, str], ...], transaction_ids: tuple[str, ...], account_code: str, account_name: str, scope: str, actor: str) -> ClassificationResult:
    """Correct selected rows or replace a future exact rule without altering audit history."""
    recover_pending_operation(ledger_root)
    _validate_transaction_ids(transactions)
    if scope not in {"selected", "future_rule"}:
        raise ValueError("scope must be selected or future_rule")
    code, name = _validate_category(ledger_root, account_code, account_name)
    requested_ids = tuple(sorted(transaction_ids))
    if not requested_ids or len(requested_ids) != len(set(requested_ids)):
        raise ValueError("transaction ID must identify exactly one row")
    selected = [row for row in transactions if row.get("transaction_id") in set(requested_ids)]
    if len(selected) != len(requested_ids):
        raise ValueError("transaction ID must identify exactly one row")
    operation_key = _operation_key("correct", {
        "account_code": code, "account_name": name, "scope": scope, "transaction_ids": requested_ids,
    })
    completed = _completed_operation(ledger_root, operation_key)
    if completed is not None:
        return _completed_result(ledger_root, completed)
    rule_id = ""
    created: tuple[dict[str, str], ...] = ()
    rules = load_rules(ledger_root)
    audit_event_id = uuid4().hex
    if scope == "future_rule":
        accounts = {row.get("account_id", "") for row in selected}
        merchants = {_normalized(row) for row in selected}
        directions = {_direction(row) for row in selected}
        if len(accounts) != 1 or len(merchants) != 1 or len(directions) != 1:
            raise ValueError("future_rule correction requires one merchant, direction, and account")
        old_ids = {row.get("rule_id", "") for row in selected if row.get("rule_id")}
        candidates = [rule for rule in rules if rule.get("rule_id") in old_ids and rule.get("status") == "active"]
        if not candidates:
            candidates = [rule for rule in _matching_rules(selected[0], rules) if rule.get("account_code") == code and rule.get("account_name") == name]
        if len(candidates) != 1:
            raise ValueError("future_rule correction requires one matching active rule")
        old = candidates[0]
        confirmed_conflict = any(len(_matching_rules(row, rules)) > 1 for row in selected)
        old["status"] = "inactive"
        old["updated_at"] = _timestamp()
        replacement = _new_rule(
            next(iter(merchants)), next(iter(directions)), code, name, audit_event_id,
            next(iter(accounts)) if confirmed_conflict else "",
        )
        rules.append(replacement)
        rule_id, created = replacement["rule_id"], (replacement,)
    output: list[dict[str, str]] = []
    for source in transactions:
        item = dict(source)
        if item.get("transaction_id") in requested_ids:
            item.update({"normalized_merchant": _normalized(item), "classification_status": "classified", "account_code": code, "account_name": name, "rule_id": rule_id if scope == "future_rule" else item.get("rule_id", ""), "review_note": ""})
        output.append(item)
    event_payload = {"transaction_ids": list(requested_ids), "account_code": code, "scope": scope}
    transactions_path = resolve_inside_ledger(ledger_root, _STAGED_TRANSACTIONS_PATH)
    rules_path = resolve_inside_ledger(ledger_root, _STAGED_RULES_PATH)
    atomic_write_csv(transactions_path, CANONICAL_TRANSACTION_FIELDS, tuple(output))
    atomic_write_csv(rules_path, MERCHANT_RULE_FIELDS, rules)
    atomic_write_json(resolve_inside_ledger(ledger_root, _PENDING_OPERATION_PATH), {
        "actor": actor, "audit_event_id": audit_event_id, "event_payload": event_payload,
        "event_type": "merchant_rule_replaced" if scope == "future_rule" else "merchant_classification_corrected",
        "operation_key": operation_key, "rules_sha256": sha256_file(rules_path),
        "transactions_sha256": sha256_file(transactions_path),
    })
    recovered = recover_pending_operation(ledger_root)
    if recovered != audit_event_id:
        raise ValueError("classification operation did not recover its audit event")
    return ClassificationResult(tuple(output), created_rules=created, audit_event_ids=(audit_event_id,))


def export_rules(ledger_root: Path, destination: str | Path) -> Path:
    """Export only the selected ledger's rule metadata to a ledger-contained CSV."""
    recover_pending_operation(ledger_root)
    target = resolve_inside_ledger(ledger_root, destination)
    atomic_write_csv(target, MERCHANT_RULE_FIELDS, load_rules(ledger_root))
    return target


def deactivate_rule(ledger_root: Path, rule_id: str, actor: str) -> str:
    """Mark one active rule inactive and append an auditable lifecycle event."""
    recover_pending_operation(ledger_root)
    rules = load_rules(ledger_root)
    matches = [rule for rule in rules if rule.get("rule_id") == rule_id]
    if len(matches) != 1:
        raise ValueError("rule ID must identify exactly one rule")
    event_id = append_audit_event(ledger_root, "merchant_rule_deactivated", {"rule_id": rule_id}, actor=actor, dedupe_key=f"merchant-rule-deactivate:{rule_id}")
    matches[0]["status"] = "inactive"
    matches[0]["updated_at"] = _timestamp()
    _write_rules(ledger_root, rules)
    return event_id


def delete_rule(ledger_root: Path, rule_id: str, actor: str) -> str:
    """Remove the current rule row while retaining an append-only audit record."""
    recover_pending_operation(ledger_root)
    rules = load_rules(ledger_root)
    kept = [rule for rule in rules if rule.get("rule_id") != rule_id]
    if len(kept) == len(rules):
        raise ValueError("rule ID must identify exactly one rule")
    event_id = append_audit_event(ledger_root, "merchant_rule_deleted", {"rule_id": rule_id}, actor=actor, dedupe_key=f"merchant-rule-delete:{rule_id}")
    _write_rules(ledger_root, kept)
    return event_id
