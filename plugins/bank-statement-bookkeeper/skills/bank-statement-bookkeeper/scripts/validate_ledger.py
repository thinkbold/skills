"""Validate current ledger evidence and write safe exception/status outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bookkeeper.ledger import load_ledger
from bookkeeper.validation import publish_derived_outputs, recover_ledger_workflow


class _UsageError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError(message)


def _run(ledger: Path) -> dict[str, object]:
    load_ledger(ledger)
    recover_ledger_workflow(ledger)
    return publish_derived_outputs(ledger, record_validation=True)


def main(argv: list[str] | None = None) -> int:
    parser = _Parser()
    parser.add_argument("ledger")
    try:
        args = parser.parse_args(argv)
        print(json.dumps(_run(Path(args.ledger)), sort_keys=True))
        return 0
    except _UsageError:
        print(json.dumps({"error": "USAGE"}, sort_keys=True))
        return 2
    except ValueError as error:
        del error
        print(json.dumps({"error": "LEDGER_SCHEMA_INVALID"}, sort_keys=True))
        return 3
    except Exception:
        print(json.dumps({"error": "VALIDATION_UNEXPECTED"}, sort_keys=True))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
