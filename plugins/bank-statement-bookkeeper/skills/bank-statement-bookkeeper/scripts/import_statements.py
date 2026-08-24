"""Import CSV statements into a selected ledger without exposing statement text."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

from bookkeeper.contracts import CANONICAL_TRANSACTION_FIELDS, AccountContext, ImportResult
from bookkeeper.classification import apply_exact_rules, load_rules
from bookkeeper.consent import (
    admit_external_result,
    proposal_from_dict,
    proposal_to_dict,
    record_external_decision,
)
from bookkeeper.importing import (
    AccountCandidate,
    CsvMapping,
    StatementInventory,
    apply_manual_correction,
    discover_account_candidates,
    merge_import_results,
    normalize_csv_statement,
    recover_pending_correction,
)
from bookkeeper.ledger import load_ledger
from bookkeeper.pdf_local import detect_pdf_capabilities, extract_pdf_pages, map_pdf_tables
from bookkeeper.storage import (
    append_audit_event,
    atomic_write_csv,
    atomic_write_json,
    mask_account_label,
    read_csv_rows,
    resolve_inside_ledger,
    replace_active_issues,
    sha256_file,
)
from bookkeeper.validation import publish_derived_outputs


class _UsageError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError(message)


def _read_ledger_json(ledger_root: Path, relative: str) -> dict[str, object]:
    path = resolve_inside_ledger(ledger_root, relative)
    if not path.is_file():
        raise ValueError(f"ledger-local configuration does not exist: {relative}")
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"ledger-local configuration must be an object: {relative}")
    return payload


def _mapping(payload: dict[str, object]) -> CsvMapping:
    fields = ("transaction_date", "description", "debit", "credit", "balance", "reference")
    missing = [field for field in fields if field not in payload or not isinstance(payload[field], str)]
    if missing:
        raise ValueError(f"CSV mapping missing fields: {', '.join(missing)}")
    date_formats = payload.get("date_formats", CsvMapping.__dataclass_fields__["date_formats"].default)
    if not isinstance(date_formats, list | tuple) or not all(isinstance(value, str) for value in date_formats):
        raise ValueError("CSV mapping date_formats must be a list of formats")
    return CsvMapping(
        transaction_date=str(payload["transaction_date"]), description=str(payload["description"]),
        debit=str(payload["debit"]), credit=str(payload["credit"]), balance=str(payload["balance"]),
        reference=str(payload["reference"]), posting_date=str(payload.get("posting_date", "")),
        date_formats=tuple(date_formats),
    )


def _account(payload: dict[str, object]) -> AccountContext:
    fields = ("account_id", "institution", "masked_label", "currency")
    missing = [field for field in fields if field not in payload or not isinstance(payload[field], str)]
    if missing:
        raise ValueError(f"account confirmation missing fields: {', '.join(missing)}")
    return AccountContext(**{field: str(payload[field]) for field in fields})


def _manifest(ledger_root: Path) -> dict[str, object]:
    path = resolve_inside_ledger(ledger_root, Path("work") / "import-manifest.json")
    if not path.exists():
        return {"source_hashes": {}, "transaction_count": 0}
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict) or not isinstance(loaded.get("source_hashes", {}), dict):
        raise ValueError("import manifest is invalid")
    return loaded


def _ledger_input(ledger_root: Path, requested: Path) -> tuple[Path, str]:
    source = resolve_inside_ledger(ledger_root, requested)
    inputs_root = resolve_inside_ledger(ledger_root, "inputs")
    if not source.is_file() or not source.is_relative_to(inputs_root):
        raise ValueError("statement files must be ledger-relative paths inside inputs/")
    return source, source.relative_to(ledger_root).as_posix()


def _candidate_from_csv(source: Path, source_identity: str) -> StatementInventory:
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        first = next(csv.DictReader(handle), {})
    institution = str(first.get("Institution") or first.get("Bank") or "")
    account = str(first.get("Masked Account") or first.get("Account") or "")
    currency = str(first.get("Currency") or "")
    masked = account if "*" in account else (mask_account_label(account) if account else "")
    confidence = "high" if all((institution, masked, currency)) else "low"
    return StatementInventory(source_identity, institution, masked, currency, confidence)


def _candidate_summary(candidate: AccountCandidate) -> dict[str, object]:
    return {
        "institution": candidate.institution,
        "masked_label": candidate.masked_label,
        "currency": candidate.currency,
        "source_files": list(candidate.source_files),
        "confidence": candidate.confidence,
        "issues": [issue.code for issue in candidate.issues],
    }


def _record_import(
    ledger_root: Path,
    source_identity: str,
    result: ImportResult,
    event_type: str,
) -> dict[str, object]:
    replace_active_issues(ledger_root, "import", {"source": source_identity}, result.issues)
    if result.issues:
        return {"status": "blocked", "issues": [issue.code for issue in result.issues]}
    manifest = _manifest(ledger_root)
    previous_hashes = dict(manifest.get("source_hashes", {}))
    source_hash = result.source_hashes[source_identity]
    canonical_path = resolve_inside_ledger(ledger_root, Path("work") / "normalized-transactions.csv")
    existing = tuple(read_csv_rows(canonical_path)) if canonical_path.exists() else ()
    if previous_hashes.get(source_identity) == source_hash:
        merged = ImportResult(transactions=existing, source_hashes=previous_hashes)
    else:
        retained = tuple(row for row in existing if row["source_file"] != source_identity)
        merged = merge_import_results((ImportResult(transactions=retained, source_hashes=previous_hashes), result))
    classified = apply_exact_rules(merged.transactions, load_rules(ledger_root))
    ordered = tuple(sorted(classified.transactions, key=lambda row: (
        row["account_id"], row["currency"], row["transaction_date"], row["posting_date"], row["transaction_id"],
    )))
    atomic_write_csv(canonical_path, CANONICAL_TRANSACTION_FIELDS, ordered)
    hashes = {**previous_hashes, **result.source_hashes}
    atomic_write_json(resolve_inside_ledger(ledger_root, Path("work") / "import-manifest.json"), {
        "source_hashes": hashes,
        "transaction_count": len(merged.transactions),
    })
    event_id = append_audit_event(
        ledger_root,
        event_type,
        {"source_hashes": hashes, "transaction_count": len(merged.transactions), "overlap_count": len(merged.duplicate_sources)},
        dedupe_key=f"{event_type}:{source_hash}",
    )
    publish_derived_outputs(ledger_root)
    return {"status": "imported", "transaction_count": len(merged.transactions), "audit_event_id": event_id}


def _write_import(
    ledger_root: Path,
    source: Path,
    source_identity: str,
    mapping: CsvMapping,
    account: AccountContext,
) -> dict[str, object]:
    return _record_import(
        ledger_root, source_identity, normalize_csv_statement(source, mapping, account, source_identity), "csv_import_recorded",
    )


def _write_pdf_import(
    ledger_root: Path,
    source: Path,
    source_identity: str,
    mapping: CsvMapping,
    account: AccountContext,
) -> dict[str, object]:
    source_hash = sha256_file(source)
    extraction = extract_pdf_pages(
        source, resolve_inside_ledger(ledger_root, "work"), detect_pdf_capabilities(),
    )
    mapped = map_pdf_tables(extraction, mapping, account, source_file=source_identity, source_hash=source_hash)
    result = ImportResult(
        transactions=mapped.transactions,
        issues=mapped.issues,
        source_hashes={source_identity: source_hash},
        staged_files=(extraction.staged_pdf,) if extraction.staged_pdf else (),
    )
    return _record_import(ledger_root, source_identity, result, "pdf_import_recorded")


def _correct_row(ledger_root: Path, args: argparse.Namespace) -> dict[str, object]:
    recover_pending_correction(ledger_root)
    canonical_path = resolve_inside_ledger(ledger_root, Path("work") / "normalized-transactions.csv")
    if not canonical_path.is_file():
        raise ValueError("canonical transaction CSV does not exist")
    corrected = apply_manual_correction(
        ledger_root, tuple(read_csv_rows(canonical_path)), args.transaction_id, args.field,
        args.value, args.reason, args.actor,
    )
    corrected_row = next(row for row in corrected if row["transaction_id"] == args.transaction_id)
    return {"status": "corrected", "transaction_id": args.transaction_id, "audit_event_id": corrected_row["review_note"]}


def _proposal_path(ledger_root: Path, requested: str) -> Path:
    path = resolve_inside_ledger(ledger_root, requested)
    if not path.is_file():
        raise ValueError("proposal JSON must be a ledger-local file")
    return path


def _read_proposal(ledger_root: Path, requested: str):
    path = _proposal_path(ledger_root, requested)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("proposal JSON must be an object")
    return path, proposal_from_dict(payload)


def _propose_external(ledger_root: Path, proposal_file: str) -> dict[str, object]:
    path, proposal = _read_proposal(ledger_root, proposal_file)
    atomic_write_json(path, proposal_to_dict(proposal))
    return proposal_to_dict(proposal)


def _record_consent(ledger_root: Path, args: argparse.Namespace) -> dict[str, object]:
    _, proposal = _read_proposal(ledger_root, args.proposal)
    consent_id = record_external_decision(ledger_root, proposal, args.decision == "authorized", args.actor)
    return {
        "consent_id": consent_id, "disclosure": proposal_to_dict(proposal),
        "status": "authorized" if args.decision == "authorized" else "declined",
    }


def _external_result(ledger_root: Path, args: argparse.Namespace) -> dict[str, object]:
    result = admit_external_result(ledger_root, args.consent_id, args.provider, args.source_hash, args.result)
    replace_active_issues(ledger_root, "external_result", {"provider": args.provider, "source_hash": args.source_hash}, result.issues)
    if result.issues:
        return {"status": "blocked", "issues": [issue.code for issue in result.issues]}
    return {"status": "admitted", "transaction_count": len(result.transactions)}


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("inventory")
    inventory.add_argument("ledger_dir", type=Path)
    inventory.add_argument("inputs", type=Path, nargs="+")
    csv_import = commands.add_parser("csv")
    csv_import.add_argument("ledger_dir", type=Path)
    csv_import.add_argument("statement", type=Path)
    csv_import.add_argument("--mapping", required=True)
    csv_import.add_argument("--account", required=True)
    pdf_import = commands.add_parser("pdf")
    pdf_import.add_argument("ledger_dir", type=Path)
    pdf_import.add_argument("statement", type=Path)
    pdf_import.add_argument("--mapping", required=True)
    pdf_import.add_argument("--account", required=True)
    correction = commands.add_parser("correct-row")
    correction.add_argument("ledger_dir", type=Path)
    correction.add_argument("transaction_id")
    correction.add_argument("--field", required=True)
    correction.add_argument("--value", required=True)
    correction.add_argument("--reason", required=True)
    correction.add_argument("--actor", required=True)
    proposal = commands.add_parser("propose-external")
    proposal.add_argument("ledger_dir", type=Path)
    proposal.add_argument("proposal")
    consent = commands.add_parser("record-consent")
    consent.add_argument("ledger_dir", type=Path)
    consent.add_argument("proposal")
    consent.add_argument("--decision", required=True, choices=("authorized", "declined"))
    consent.add_argument("--actor", required=True)
    external_result = commands.add_parser("external-result")
    external_result.add_argument("ledger_dir", type=Path)
    external_result.add_argument("result", type=Path)
    external_result.add_argument("--consent-id", required=True)
    external_result.add_argument("--provider", required=True)
    external_result.add_argument("--source-hash", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        ledger_root = args.ledger_dir.resolve()
        load_ledger(ledger_root)
        recover_pending_correction(ledger_root)
        if args.command == "inventory":
            inputs = tuple(_ledger_input(ledger_root, path) for path in args.inputs)
            candidates = discover_account_candidates(tuple(
                _candidate_from_csv(source, identity) for source, identity in inputs
            ))
            replace_active_issues(
                ledger_root, "inventory", {"sources": tuple(sorted(identity for _, identity in inputs))},
                tuple(issue for candidate in candidates for issue in candidate.issues),
            )
            output: dict[str, object] = {
                "candidate_count": len(candidates),
                "candidates": [_candidate_summary(candidate) for candidate in candidates],
                "status": "confirmation_required",
            }
        elif args.command == "csv":
            source, source_identity = _ledger_input(ledger_root, args.statement)
            output = _write_import(
                ledger_root, source, source_identity, _mapping(_read_ledger_json(ledger_root, args.mapping)),
                _account(_read_ledger_json(ledger_root, args.account)),
            )
        elif args.command == "pdf":
            source, source_identity = _ledger_input(ledger_root, args.statement)
            output = _write_pdf_import(
                ledger_root, source, source_identity, _mapping(_read_ledger_json(ledger_root, args.mapping)),
                _account(_read_ledger_json(ledger_root, args.account)),
            )
        elif args.command == "propose-external":
            output = _propose_external(ledger_root, args.proposal)
        elif args.command == "record-consent":
            output = _record_consent(ledger_root, args)
        elif args.command == "external-result":
            output = _external_result(ledger_root, args)
        else:
            output = _correct_row(ledger_root, args)
    except (OSError, ValueError, json.JSONDecodeError):
        print(json.dumps({"error": "LEDGER_SCHEMA_INVALID"}, sort_keys=True))
        return 3
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except _UsageError:
        print(json.dumps({"error": "USAGE"}, sort_keys=True))
        sys.exit(2)
    except Exception:
        print(json.dumps({"error": "IMPORT_UNEXPECTED"}, sort_keys=True))
        sys.exit(4)
