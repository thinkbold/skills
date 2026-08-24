"""Create or verify an isolated bank-statement bookkeeping ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bookkeeper.ledger import initialize_ledger


def main() -> int:
    """Parse initialization options and print a compact JSON result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger_dir", type=Path)
    parser.add_argument("--ledger-id", required=True)
    parser.add_argument("--company-name", required=True)
    parser.add_argument("--base-currency", required=True)
    parser.add_argument("--fiscal-year-end")
    arguments = parser.parse_args()
    config = initialize_ledger(
        arguments.ledger_dir,
        arguments.ledger_id,
        arguments.company_name,
        arguments.base_currency,
        arguments.fiscal_year_end,
    )
    print(json.dumps({
        "ledger_directory": str(arguments.ledger_dir.resolve()),
        "ledger_id": config["ledger_id"],
        "schema_version": config["schema_version"],
        "status": "initialized",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
