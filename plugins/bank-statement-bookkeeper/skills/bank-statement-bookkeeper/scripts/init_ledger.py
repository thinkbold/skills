"""Create or verify an isolated bank-statement bookkeeping ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bookkeeper.ledger import initialize_ledger, lexical_ledger_root, load_ledger
from bookkeeper.validation import publish_derived_outputs, recover_ledger_workflow


class _UsageError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError(message)


def main() -> int:
    """Parse initialization options and print a compact JSON result."""
    parser = _Parser(description=__doc__)
    parser.add_argument("ledger_dir", type=Path)
    parser.add_argument("--ledger-id", required=True)
    parser.add_argument("--company-name", required=True)
    parser.add_argument("--base-currency", required=True)
    parser.add_argument("--fiscal-year-end")
    try:
        arguments = parser.parse_args()
    except _UsageError:
        print(json.dumps({"error": "USAGE"}, sort_keys=True))
        return 2
    try:
        config = initialize_ledger(
            arguments.ledger_dir, arguments.ledger_id, arguments.company_name,
            arguments.base_currency, arguments.fiscal_year_end,
        )
        ledger_root = lexical_ledger_root(arguments.ledger_dir)
        # Existing and fresh initialization both pass through the same ledger
        # gate and publish a complete, committed derived view.
        load_ledger(ledger_root)
        ledger_root = ledger_root.resolve()
        recover_ledger_workflow(ledger_root)
        status = publish_derived_outputs(ledger_root)
    except (OSError, ValueError):
        print(json.dumps({"error": "LEDGER_SCHEMA_INVALID"}, sort_keys=True))
        return 3
    except Exception:
        print(json.dumps({"error": "INITIALIZATION_UNEXPECTED"}, sort_keys=True))
        return 4
    print(json.dumps({
        "ledger_directory": str(lexical_ledger_root(arguments.ledger_dir).resolve()),
        "ledger_id": config["ledger_id"],
        "schema_version": config["schema_version"],
        "status": "initialized",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
