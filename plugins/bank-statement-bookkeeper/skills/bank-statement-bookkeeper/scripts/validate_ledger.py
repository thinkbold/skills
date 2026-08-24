"""Validate current ledger evidence and write safe exception/status outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bookkeeper.classification import apply_exact_rules, build_pending_groups, load_rules, load_transactions
from bookkeeper.ledger import load_ledger
from bookkeeper.storage import load_active_issues, replace_active_issues
from bookkeeper.validation import count_pending_classifications, validate_canonical_transactions
from bookkeeper.reconciliation import load_balance_rows, reconcile_all
from bookkeeper.validation import collect_ledger_issues, finalize_outputs


def _run(ledger: Path) -> dict[str, object]:
    load_ledger(ledger)
    transactions = load_transactions(ledger)
    classified = apply_exact_rules(transactions, load_rules(ledger))
    replace_active_issues(ledger, "classification", {"view": "current"}, classified.issues)
    balances, balance_issues = load_balance_rows(ledger)
    rows = reconcile_all(classified.transactions, balances)
    pending_group_count = count_pending_classifications(classified.transactions)
    issues = collect_ledger_issues((*load_active_issues(ledger), *validate_canonical_transactions(classified.transactions), *classified.issues, *balance_issues), rows, pending_group_count)
    return finalize_outputs(
        ledger, has_transactions=bool(transactions), pending_group_count=pending_group_count,
        reconciliation_rows=rows, issues=issues,
    )


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
        print(json.dumps({"error": "VALIDATION_UNEXPECTED"}, sort_keys=True))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
