"""Classify normalized transactions with ledger-local exact merchant rules."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from bookkeeper.classification import (
    apply_exact_rules,
    build_pending_groups,
    ClassificationResult,
    confirm_group,
    correct_transactions,
    deactivate_rule,
    delete_rule,
    export_rules,
    load_rules,
    load_transactions,
    recover_pending_operation,
    save_transactions,
)
from bookkeeper.storage import read_audit_events
from bookkeeper.storage import replace_active_issues
from bookkeeper.ledger import load_ledger
from bookkeeper.validation import publish_derived_outputs, recover_ledger_workflow


class _UsageError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError(message)


def _json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _current(ledger: Path):
    rows = load_transactions(ledger)
    result = apply_exact_rules(rows, load_rules(ledger))
    replace_active_issues(ledger, "classification", {"view": "current"}, result.issues)
    save_transactions(ledger, result.transactions)
    return result


def main() -> int:
    parser = _Parser()
    commands = parser.add_subparsers(dest="command", required=True)
    pending = commands.add_parser("pending")
    pending.add_argument("ledger")
    confirm = commands.add_parser("confirm")
    confirm.add_argument("ledger")
    confirm.add_argument("group_id")
    confirm.add_argument("--account-code", required=True)
    confirm.add_argument("--account-name", required=True)
    confirm.add_argument("--apply-future", action="store_true")
    confirm.add_argument("--actor", required=True)
    correct = commands.add_parser("correct")
    correct.add_argument("ledger")
    correct.add_argument("--transaction-id", action="append", required=True)
    correct.add_argument("--account-code", required=True)
    correct.add_argument("--account-name", required=True)
    correct.add_argument("--scope", choices=("selected", "future_rule"), required=True)
    correct.add_argument("--actor", required=True)
    rules = commands.add_parser("rules")
    rules.add_argument("ledger")
    exported = commands.add_parser("export-rules")
    exported.add_argument("ledger")
    exported.add_argument("destination")
    deactivated = commands.add_parser("deactivate-rule")
    deactivated.add_argument("ledger")
    deactivated.add_argument("rule_id")
    deactivated.add_argument("--actor", required=True)
    deleted = commands.add_parser("delete-rule")
    deleted.add_argument("ledger")
    deleted.add_argument("rule_id")
    deleted.add_argument("--actor", required=True)
    args = parser.parse_args()
    ledger = Path(args.ledger)
    load_ledger(ledger)
    recover_ledger_workflow(ledger)
    if args.command == "pending":
        current = _current(ledger)
        groups = build_pending_groups(current.transactions)
        output = {"group_count": len(groups), "groups": [asdict(group) for group in groups], "issue_count": len(current.issues)}
    elif args.command == "confirm":
        current = _current(ledger)
        group = next((item for item in build_pending_groups(current.transactions) if item.group_id == args.group_id), None)
        if group is None:
            name_hash = hashlib.sha256(args.account_name.encode("utf-8")).hexdigest()
            event = next((item for item in read_audit_events(ledger) if item.get("event_type") == "merchant_group_confirmed" and item.get("payload", {}).get("group_id") == args.group_id and item.get("payload", {}).get("account_code") == args.account_code and item.get("payload", {}).get("account_name_sha256") == name_hash and item.get("payload", {}).get("apply_future") == args.apply_future), None)
            if event is None:
                raise ValueError("pending group does not exist")
            result = ClassificationResult(current.transactions, audit_event_ids=(str(event["event_id"]),))
        else:
            result = confirm_group(ledger, current.transactions, group.normalized_merchant, group.direction, args.account_code, args.account_name, args.apply_future, args.actor, group.transaction_ids)
        save_transactions(ledger, result.transactions)
        output = {"classified_count": sum(row["classification_status"] == "classified" for row in result.transactions), "created_rule_ids": [rule["rule_id"] for rule in result.created_rules], "audit_event_ids": list(result.audit_event_ids)}
    elif args.command == "correct":
        current = _current(ledger)
        result = correct_transactions(ledger, current.transactions, tuple(args.transaction_id), args.account_code, args.account_name, args.scope, args.actor)
        save_transactions(ledger, result.transactions)
        output = {"corrected_count": len(args.transaction_id), "created_rule_ids": [rule["rule_id"] for rule in result.created_rules], "audit_event_ids": list(result.audit_event_ids)}
    elif args.command == "rules":
        records = load_rules(ledger)
        output = {"rule_count": len(records), "rules": records}
    elif args.command == "export-rules":
        output = export_rules(ledger, args.destination)
        output = {"exported_rule_count": len(load_rules(ledger)), "destination": str(output)}
    elif args.command == "deactivate-rule":
        output = {"rule_id": args.rule_id, "audit_event_id": deactivate_rule(ledger, args.rule_id, args.actor)}
    else:
        output = {"rule_id": args.rule_id, "audit_event_id": delete_rule(ledger, args.rule_id, args.actor)}
    publish_derived_outputs(ledger)
    _json(output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except _UsageError:
        _json({"error": "USAGE"})
        raise SystemExit(2)
    except ValueError:
        _json({"error": "LEDGER_SCHEMA_INVALID"})
        raise SystemExit(3)
    except Exception:
        _json({"error": "CLASSIFICATION_UNEXPECTED"})
        raise SystemExit(4)
