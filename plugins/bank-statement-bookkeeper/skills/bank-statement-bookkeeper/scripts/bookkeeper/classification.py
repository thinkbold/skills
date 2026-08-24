"""Ledger-local merchant classification, exact rules, and auditable rule lifecycle."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from difflib import SequenceMatcher
import hashlib
from pathlib import Path
import re
import unicodedata
from uuid import uuid4

from .contracts import CANONICAL_TRANSACTION_FIELDS, Issue, MERCHANT_RULE_FIELDS
from .storage import append_audit_event, atomic_write_csv, read_csv_rows, resolve_inside_ledger


_CHART_FIELDS = ("account_code", "account_name", "active")
_CANONICAL_PATH = Path("work") / "normalized-transactions.csv"
_RULES_PATH = Path("merchant-rules.csv")
_DATE_PATTERN = re.compile(r"\b(?:19|20)\d{2}[/-](?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])\b")
_TERMINAL_REFERENCE = re.compile(r"^(?=.*[A-Z])(?=.*\d)[A-Z0-9]{5,}$")


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


def normalize_merchant(value: str) -> str:
    """Conservatively normalize a description without stripping merchant words."""
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").upper()
    text = _DATE_PATTERN.sub(" ", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    tokens = [token for token in text.split() if token]
    while tokens and _TERMINAL_REFERENCE.fullmatch(tokens[-1]):
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
    return tuple(rows)


def save_transactions(ledger_root: Path, transactions: tuple[dict[str, str], ...]) -> None:
    atomic_write_csv(resolve_inside_ledger(ledger_root, _CANONICAL_PATH), CANONICAL_TRANSACTION_FIELDS, transactions)


def build_pending_groups(transactions: tuple[dict[str, str], ...]) -> tuple[MerchantGroup, ...]:
    """Build review questions by normalized merchant and direction, never by currency total."""
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


def confirm_group(ledger_root: Path, transactions: tuple[dict[str, str], ...], normalized_merchant: str, direction: str, account_code: str, account_name: str, apply_future: bool, actor: str) -> ClassificationResult:
    """Confirm current rows and optionally retain one ledger-local exact rule."""
    code, name = _validate_category(ledger_root, account_code, account_name)
    merchant = normalize_merchant(normalized_merchant)
    selected_ids = tuple(sorted(row.get("transaction_id", "") for row in transactions if row.get("classification_status", "unclassified") == "unclassified" and _normalized(row) == merchant and _direction(row) == direction))
    if not selected_ids:
        raise ValueError("group has no unclassified transactions")
    event_id = append_audit_event(ledger_root, "merchant_group_confirmed", {"transaction_ids": list(selected_ids), "normalized_merchant_sha256": hashlib.sha256(merchant.encode()).hexdigest(), "direction": direction, "account_code": code, "apply_future": apply_future}, actor=actor, dedupe_key=f"merchant-confirm:{','.join(selected_ids)}:{code}:{name}:{apply_future}")
    existing = load_rules(ledger_root)
    created: tuple[dict[str, str], ...] = ()
    rule: dict[str, str] | None = None
    if apply_future:
        matches = [item for item in existing if item.get("status") == "active" and item.get("normalized_merchant") == merchant and item.get("direction") == direction and item.get("account_code") == code and item.get("account_name") == name and not item.get("account_scope") and item.get("match_type") == "exact_normalized"]
        if matches:
            rule = matches[0]
        else:
            rule = _new_rule(merchant, direction, code, name, event_id)
            existing.append(rule)
            _write_rules(ledger_root, existing)
            created = (rule,)
    output: list[dict[str, str]] = []
    for source in transactions:
        item = dict(source)
        if item.get("transaction_id") in selected_ids:
            item.update({"normalized_merchant": merchant, "classification_status": "classified", "account_code": code, "account_name": name, "rule_id": rule["rule_id"] if rule else "", "review_note": ""})
        output.append(item)
    return ClassificationResult(tuple(output), created_rules=created, audit_event_ids=(event_id,))


def correct_transactions(ledger_root: Path, transactions: tuple[dict[str, str], ...], transaction_ids: tuple[str, ...], account_code: str, account_name: str, scope: str, actor: str) -> ClassificationResult:
    """Correct selected rows or replace a future exact rule without altering audit history."""
    if scope not in {"selected", "future_rule"}:
        raise ValueError("scope must be selected or future_rule")
    code, name = _validate_category(ledger_root, account_code, account_name)
    selected = [row for row in transactions if row.get("transaction_id") in set(transaction_ids)]
    if len(selected) != len(set(transaction_ids)):
        raise ValueError("transaction ID must identify exactly one row")
    if not selected:
        raise ValueError("at least one transaction is required")
    event_id = append_audit_event(
        ledger_root,
        "merchant_rule_replaced" if scope == "future_rule" else "merchant_classification_corrected",
        {"transaction_ids": sorted(transaction_ids), "account_code": code, "scope": scope},
        actor=actor,
        dedupe_key=f"merchant-correct:{','.join(sorted(transaction_ids))}:{code}:{name}:{scope}",
    )
    rule_id = ""
    created: tuple[dict[str, str], ...] = ()
    if scope == "future_rule":
        accounts = {row.get("account_id", "") for row in selected}
        merchants = {_normalized(row) for row in selected}
        directions = {_direction(row) for row in selected}
        if len(accounts) != 1 or len(merchants) != 1 or len(directions) != 1:
            raise ValueError("future_rule correction requires one merchant, direction, and account")
        rules = load_rules(ledger_root)
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
            next(iter(merchants)), next(iter(directions)), code, name, event_id,
            next(iter(accounts)) if confirmed_conflict else "",
        )
        rules.append(replacement)
        _write_rules(ledger_root, rules)
        rule_id, created = replacement["rule_id"], (replacement,)
    output: list[dict[str, str]] = []
    for source in transactions:
        item = dict(source)
        if item.get("transaction_id") in transaction_ids:
            item.update({"normalized_merchant": _normalized(item), "classification_status": "classified", "account_code": code, "account_name": name, "rule_id": rule_id if scope == "future_rule" else item.get("rule_id", ""), "review_note": ""})
        output.append(item)
    return ClassificationResult(tuple(output), created_rules=created, audit_event_ids=(event_id,))


def export_rules(ledger_root: Path, destination: str | Path) -> Path:
    """Export only the selected ledger's rule metadata to a ledger-contained CSV."""
    target = resolve_inside_ledger(ledger_root, destination)
    atomic_write_csv(target, MERCHANT_RULE_FIELDS, load_rules(ledger_root))
    return target


def deactivate_rule(ledger_root: Path, rule_id: str, actor: str) -> str:
    """Mark one active rule inactive and append an auditable lifecycle event."""
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
    rules = load_rules(ledger_root)
    kept = [rule for rule in rules if rule.get("rule_id") != rule_id]
    if len(kept) == len(rules):
        raise ValueError("rule ID must identify exactly one rule")
    event_id = append_audit_event(ledger_root, "merchant_rule_deleted", {"rule_id": rule_id}, actor=actor, dedupe_key=f"merchant-rule-delete:{rule_id}")
    _write_rules(ledger_root, kept)
    return event_id
