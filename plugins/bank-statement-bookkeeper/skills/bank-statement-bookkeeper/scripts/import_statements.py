"""Import CSV statements into a selected ledger without exposing statement text."""

from __future__ import annotations

import argparse
import csv
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import stat
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
from bookkeeper.validation import publish_derived_outputs, recover_ledger_workflow


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
        return {"source_contributions": {}, "source_hashes": {}, "source_order": [], "transaction_count": 0}
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict) or not isinstance(loaded.get("source_hashes", {}), dict):
        raise ValueError("import manifest is invalid")
    return loaded


_CONTRIBUTION_DIRECTORY = Path("work") / "import-contributions"
_UNCLASSIFIED_BLANK_FIELDS = (
    "normalized_merchant", "account_code", "account_name", "rule_id", "review_note",
)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _contribution_relative_path(source_identity: str, source_hash: str) -> Path:
    identity_hash = hashlib.sha256(source_identity.encode("utf-8")).hexdigest()
    return _CONTRIBUTION_DIRECTORY / f"{identity_hash}-{source_hash}.csv"


def _validate_contribution_rows(source_identity: str, rows: tuple[dict[str, str], ...]) -> None:
    for row in rows:
        if set(row) != set(CANONICAL_TRANSACTION_FIELDS):
            raise ValueError("import contribution row has invalid fields")
        if row["source_file"] != source_identity:
            raise ValueError("import contribution source identity is invalid")
        locations = [location for location in row["source_locations"].split("|") if location]
        if not locations or not all(location.startswith(f"{source_identity}:") for location in locations):
            raise ValueError("import contribution provenance is invalid")
        if row["classification_status"] != "unclassified" or any(row[field] for field in _UNCLASSIFIED_BLANK_FIELDS):
            raise ValueError("import contribution must be unclassified")


def _existing_contribution_path(ledger_root: Path, relative: Path) -> Path:
    if relative.parent != _CONTRIBUTION_DIRECTORY or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("import contribution path is invalid")
    current = ledger_root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError as error:
            raise ValueError("import contribution snapshot is missing") from error
        if stat.S_ISLNK(mode):
            raise ValueError("import contribution path contains a symlink")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(mode):
            raise ValueError("import contribution ancestor is invalid")
        if index == len(relative.parts) - 1 and not stat.S_ISREG(mode):
            raise ValueError("import contribution snapshot is invalid")
    return current


def _read_contribution_rows(path: Path, source_identity: str) -> tuple[dict[str, str], ...]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CANONICAL_TRANSACTION_FIELDS:
            raise ValueError("import contribution header is invalid")
        rows = tuple(dict(row) for row in reader)
    if any(any(value is None for value in row.values()) for row in rows):
        raise ValueError("import contribution row is invalid")
    _validate_contribution_rows(source_identity, rows)
    return rows


def _current_contributions(
    ledger_root: Path,
    manifest: dict[str, object],
) -> tuple[list[str], dict[str, ImportResult], dict[str, dict[str, str]]]:
    hashes = manifest.get("source_hashes", {})
    if not isinstance(hashes, dict) or not all(isinstance(source, str) and _is_sha256(value) for source, value in hashes.items()):
        raise ValueError("import manifest source hashes are invalid")
    entries = manifest.get("source_contributions", {})
    order = manifest.get("source_order", [])
    if not hashes:
        if entries not in ({}, None) or order not in ([], None):
            raise ValueError("import manifest contributions are invalid")
        return [], {}, {}
    if not isinstance(entries, dict) or not isinstance(order, list):
        raise ValueError("import manifest lacks trustworthy contribution snapshots")
    if not all(isinstance(source, str) for source in order) or len(order) != len(set(order)):
        raise ValueError("import manifest source order is invalid")
    if set(order) != set(hashes) or set(entries) != set(hashes):
        raise ValueError("import manifest contribution sources are inconsistent")
    results: dict[str, ImportResult] = {}
    validated_entries: dict[str, dict[str, str]] = {}
    for source_identity in order:
        source_hash = str(hashes[source_identity])
        entry = entries[source_identity]
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise ValueError("import manifest contribution entry is invalid")
        relative = _contribution_relative_path(source_identity, source_hash)
        if entry.get("path") != relative.as_posix() or not _is_sha256(entry.get("sha256")):
            raise ValueError("import manifest contribution binding is invalid")
        path = _existing_contribution_path(ledger_root, relative)
        if sha256_file(path) != entry["sha256"]:
            raise ValueError("import contribution snapshot hash mismatch")
        rows = _read_contribution_rows(path, source_identity)
        results[source_identity] = ImportResult(transactions=rows, source_hashes={source_identity: source_hash})
        validated_entries[source_identity] = {"path": relative.as_posix(), "sha256": str(entry["sha256"])}
    return list(order), results, validated_entries


def _snapshot_bytes(rows: tuple[dict[str, str], ...]) -> bytes:
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CANONICAL_TRANSACTION_FIELDS, extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _write_contribution_snapshot(
    ledger_root: Path,
    source_identity: str,
    source_hash: str,
    rows: tuple[dict[str, str], ...],
) -> dict[str, str]:
    _validate_contribution_rows(source_identity, rows)
    expected_hash = hashlib.sha256(_snapshot_bytes(rows)).hexdigest()
    directory = ledger_root / _CONTRIBUTION_DIRECTORY
    try:
        mode = os.lstat(directory).st_mode
    except FileNotFoundError:
        directory.mkdir()
    else:
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise ValueError("import contribution directory is invalid")
    relative = _contribution_relative_path(source_identity, source_hash)
    path = ledger_root / relative
    if path.exists():
        existing = _existing_contribution_path(ledger_root, relative)
        if sha256_file(existing) != expected_hash:
            raise ValueError("existing import contribution snapshot conflicts with normalized rows")
    else:
        atomic_write_csv(path, CANONICAL_TRANSACTION_FIELDS, rows)
        if sha256_file(path) != expected_hash:
            raise ValueError("import contribution snapshot write failed")
    return {"path": relative.as_posix(), "sha256": expected_hash}


def _prune_unreferenced_contributions(
    ledger_root: Path,
    contribution_entries: dict[str, dict[str, str]],
) -> None:
    directory = ledger_root / _CONTRIBUTION_DIRECTORY
    if not directory.exists():
        return
    mode = os.lstat(directory).st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise ValueError("import contribution directory is invalid")
    referenced = {Path(entry["path"]).name for entry in contribution_entries.values()}
    for path in directory.iterdir():
        parts = path.stem.split("-")
        managed_snapshot = (
            path.suffix == ".csv" and len(parts) == 2
            and all(_is_sha256(part) for part in parts)
        )
        if managed_snapshot and path.name not in referenced:
            path.unlink()


def _ledger_input(ledger_root: Path, requested: Path) -> tuple[Path, str]:
    source = resolve_inside_ledger(ledger_root, requested)
    inputs_root = resolve_inside_ledger(ledger_root, "inputs")
    if not source.is_file() or not source.is_relative_to(inputs_root):
        raise ValueError("statement files must be ledger-relative paths inside inputs/")
    return source, source.relative_to(ledger_root).as_posix()


def _ledger_external_result(ledger_root: Path, selected_root: Path, requested: Path) -> Path:
    """Return a real ledger-local result path without following any symlink component."""
    if selected_root.resolve(strict=True) != ledger_root:
        raise ValueError("selected ledger root does not match its canonical path")
    candidate = selected_root / requested
    relative = None
    walk_root = None
    for candidate_root in (selected_root, ledger_root):
        try:
            relative = candidate.relative_to(candidate_root)
            walk_root = candidate_root
            break
        except ValueError:
            continue
    if relative is None or walk_root is None:
        raise ValueError("external result is outside the selected ledger")
    if not relative.parts or ".." in relative.parts:
        raise ValueError("external result must identify a file")
    current = walk_root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError as error:
            raise ValueError("external result does not exist") from error
        if stat.S_ISLNK(mode):
            raise ValueError("external result path contains a symlink")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(mode):
            raise ValueError("external result ancestor is not a directory")
        if index == len(relative.parts) - 1 and not stat.S_ISREG(mode):
            raise ValueError("external result is not a regular file")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(ledger_root) or not resolved.is_file():
        raise ValueError("external result is not a real file inside the selected ledger")
    return resolved


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
    manifest = _manifest(ledger_root)
    source_order, contributions, contribution_entries = _current_contributions(ledger_root, manifest)
    replace_active_issues(ledger_root, "import", {"source": source_identity}, result.issues)
    if result.issues:
        return {"status": "blocked", "issues": [issue.code for issue in result.issues]}
    previous_hashes = dict(manifest.get("source_hashes", {}))
    if set(result.source_hashes) != {source_identity}:
        raise ValueError("import result did not bind exactly one logical source")
    source_hash = result.source_hashes[source_identity]
    if not _is_sha256(source_hash):
        raise ValueError("import result source hash is invalid")
    canonical_path = resolve_inside_ledger(ledger_root, Path("work") / "normalized-transactions.csv")
    existing = tuple(read_csv_rows(canonical_path)) if canonical_path.exists() else ()
    if previous_hashes.get(source_identity) == source_hash:
        merged = ImportResult(transactions=existing, source_hashes=previous_hashes)
        hashes = previous_hashes
    else:
        rows = tuple(dict(row) for row in result.transactions)
        contribution_entries[source_identity] = _write_contribution_snapshot(
            ledger_root, source_identity, source_hash, rows,
        )
        contributions[source_identity] = ImportResult(
            transactions=rows, source_hashes={source_identity: source_hash},
        )
        if source_identity not in source_order:
            source_order.append(source_identity)
        merged = merge_import_results(contributions[source] for source in source_order)
        hashes = {**previous_hashes, **result.source_hashes}
    classified = apply_exact_rules(merged.transactions, load_rules(ledger_root))
    atomic_write_csv(canonical_path, CANONICAL_TRANSACTION_FIELDS, classified.transactions)
    atomic_write_json(resolve_inside_ledger(ledger_root, Path("work") / "import-manifest.json"), {
        "source_contributions": contribution_entries,
        "source_hashes": hashes,
        "source_order": source_order,
        "transaction_count": len(merged.transactions),
    })
    _prune_unreferenced_contributions(ledger_root, contribution_entries)
    event_id = append_audit_event(
        ledger_root,
        event_type,
        {"source_hashes": hashes, "transaction_count": len(merged.transactions), "overlap_count": len(merged.duplicate_sources)},
        dedupe_key=f"{event_type}:{source_identity}:{source_hash}",
    )
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
    selected_root = Path(os.path.abspath(os.fspath(args.ledger_dir)))
    result_path = _ledger_external_result(ledger_root, selected_root, args.result)
    result = admit_external_result(ledger_root, args.consent_id, args.provider, args.source_hash, result_path)
    if result.issues:
        _current_contributions(ledger_root, _manifest(ledger_root))
        replace_active_issues(ledger_root, "external_result", {"provider": args.provider, "source_hash": args.source_hash}, result.issues)
        return {"status": "blocked", "issues": [issue.code for issue in result.issues]}
    if len(result.source_hashes) != 1:
        raise ValueError("external result did not identify one logical source")
    source_identity = next(iter(result.source_hashes))
    output = _record_import(
        ledger_root, source_identity, result, "external_result_import_recorded",
    )
    replace_active_issues(ledger_root, "external_result", {"provider": args.provider, "source_hash": args.source_hash}, ())
    return output


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
        # Do not resolve the caller selected root before the ledger gate can
        # reject a symlinked ledger path.
        ledger_root = args.ledger_dir
        load_ledger(ledger_root)
        # The selected lexical path has now been checked; use one canonical
        # spelling for containment comparisons inside the command.
        ledger_root = ledger_root.resolve()
        recover_ledger_workflow(ledger_root)
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
        publish_derived_outputs(ledger_root)
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
