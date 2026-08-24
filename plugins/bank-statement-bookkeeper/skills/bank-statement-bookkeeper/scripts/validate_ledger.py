"""Validate current ledger evidence and write safe exception/status outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bookkeeper.classification import apply_exact_rules, load_rules
from bookkeeper.ledger import load_ledger
from bookkeeper.storage import load_active_issues, replace_active_issues
from bookkeeper.validation import count_pending_classifications, admit_canonical_transactions, load_canonical_for_validation
from bookkeeper.reconciliation import load_balance_rows, reconcile_all
from bookkeeper.validation import collect_ledger_issues, finalize_outputs


def _run(ledger: Path) -> dict[str, object]:
    load_ledger(ledger)
    transactions, canonical_load_issues = load_canonical_for_validation(ledger)
    valid_transactions, canonical_issues = admit_canonical_transactions(transactions)
    classified = apply_exact_rules(valid_transactions, load_rules(ledger))
    replace_active_issues(ledger, "classification", {"view": "current"}, classified.issues)
    balances, balance_issues = load_balance_rows(ledger)
    rows = reconcile_all(classified.transactions, balances)
    pending_group_count = count_pending_classifications(classified.transactions)
    issues = collect_ledger_issues((*load_active_issues(ledger), *canonical_load_issues, *canonical_issues, *classified.issues, *balance_issues), rows, pending_group_count)
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
