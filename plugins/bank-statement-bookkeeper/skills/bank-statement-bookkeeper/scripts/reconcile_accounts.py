"""Reconcile every selected-ledger account/currency statement period."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bookkeeper.classification import apply_exact_rules, build_pending_groups, load_rules, load_transactions
from bookkeeper.ledger import load_ledger
from bookkeeper.reconciliation import load_balance_rows, reconcile_all, write_reconciliation_outputs
from bookkeeper.validation import collect_ledger_issues, determine_run_state


def _run(ledger: Path) -> dict[str, object]:
    load_ledger(ledger)
    transactions = load_transactions(ledger)
    classified = apply_exact_rules(transactions, load_rules(ledger))
    balance_rows, balance_issues = load_balance_rows(ledger)
    rows = reconcile_all(classified.transactions, balance_rows)
    pending_group_count = len(build_pending_groups(classified.transactions)) if transactions else 0
    issues = collect_ledger_issues((*classified.issues, *balance_issues), rows, pending_group_count)
    state = determine_run_state(bool(transactions), pending_group_count, rows, issues)
    write_reconciliation_outputs(ledger, rows, state)
    return {
        "blocking_issue_count": sum(issue.blocking for issue in issues),
        "pending_group_count": pending_group_count,
        "reconciled_unit_count": sum(row.reconciled for row in rows),
        "state": state.value,
        "unit_count": len(rows),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(_run(Path(args.ledger)), sort_keys=True))
        return 0
    except ValueError as error:
        print(json.dumps({"error": "LEDGER_SCHEMA_INVALID", "message": str(error)}, sort_keys=True))
        return 3
    except Exception:
        print(json.dumps({"error": "RECONCILIATION_UNEXPECTED"}, sort_keys=True))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
