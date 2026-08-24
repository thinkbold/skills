"""Ledger-local storage and privacy-preserving audit helpers."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Iterable, Mapping, Sequence
from uuid import uuid4


_SENSITIVE_AUDIT_KEYS = frozenset({
    "full_account_number",
    "account_number",
    "routing_number",
    "password",
    "secret",
    "api_key",
    "access_token",
    "raw_description",
    "description",
})
_NON_DEDUPLICABLE_AUDIT_PREFIXES = ("external_processing_consent_",)


def resolve_inside_ledger(root: Path, relative: str | Path) -> Path:
    """Resolve a path and reject any path outside the selected ledger."""
    resolved_root = Path(root).resolve()
    candidate = (resolved_root / relative).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise ValueError(f"path is outside ledger: {relative}")
    return candidate


def _atomic_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    return Path(temporary_name)


def atomic_write_json(path: Path, value: object) -> None:
    """Atomically write JSON using a sibling file that is flushed to disk."""
    destination = Path(path)
    temporary = _atomic_path(destination)
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_csv(
    path: Path,
    fieldnames: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> None:
    """Atomically write a CSV with its required header."""
    destination = Path(path)
    temporary = _atomic_path(destination)
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read CSV records as string-valued dictionaries."""
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a file without loading it all into memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mask_account_label(value: str) -> str:
    """Mask all but the last four digits of an account label."""
    digits = "".join(character for character in value if character.isdigit())
    suffix = digits[-4:]
    return f"{'*' * max(3, len(digits) - len(suffix))}{suffix}"


def _find_sensitive_key(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key).casefold()
            if key_text in _SENSITIVE_AUDIT_KEYS:
                return str(key)
            nested_key = _find_sensitive_key(nested)
            if nested_key is not None:
                return nested_key
    elif isinstance(value, (list, tuple)):
        for item in value:
            nested_key = _find_sensitive_key(item)
            if nested_key is not None:
                return nested_key
    return None


def _utc_timestamp(now: datetime | None) -> str:
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def read_audit_events(ledger_root: Path) -> list[dict[str, object]]:
    """Read the selected ledger's audit events in append order."""
    audit_path = resolve_inside_ledger(ledger_root, Path("audit") / "audit.jsonl")
    if not audit_path.exists():
        return []
    with audit_path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def append_audit_event(
    ledger_root: Path,
    event_type: str,
    payload: dict[str, object],
    actor: str = "user",
    now: datetime | None = None,
    dedupe_key: str | None = None,
) -> str:
    """Append one fsynced privacy-safe JSON line and return its event ID."""
    sensitive_key = _find_sensitive_key(payload)
    if sensitive_key is not None:
        raise ValueError(f"sensitive audit key: {sensitive_key}")
    if dedupe_key is not None and event_type.startswith(_NON_DEDUPLICABLE_AUDIT_PREFIXES):
        raise ValueError("dedupe_key is not permitted for external processing consent events")

    existing_events = read_audit_events(ledger_root)
    if dedupe_key is not None:
        for event in existing_events:
            if event.get("dedupe_key") == dedupe_key:
                return str(event["event_id"])

    event_id = uuid4().hex
    event: dict[str, object] = {
        "event_id": event_id,
        "timestamp": _utc_timestamp(now),
        "event_type": event_type,
        "actor": actor,
        "payload": payload,
    }
    if dedupe_key is not None:
        event["dedupe_key"] = dedupe_key
    encoded = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    audit_path = resolve_inside_ledger(ledger_root, Path("audit") / "audit.jsonl")
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(f"{encoded}\n")
        handle.flush()
        os.fsync(handle.fileno())
    return event_id
