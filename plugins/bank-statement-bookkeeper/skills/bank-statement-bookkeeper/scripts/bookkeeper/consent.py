"""Operation-specific consent gates for locally returned extraction results.

This module deliberately has no provider client or upload capability.  It only
records a user's decision in the selected ledger and verifies a local file
returned by a separately performed operation.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping
from uuid import uuid4

from .contracts import CANONICAL_TRANSACTION_FIELDS, ImportResult, Issue
from .storage import append_audit_event, read_audit_events


_DECISION_EVENT_TYPE = "external_processing_consent_decision"
_HASH = re.compile(r"^[0-9a-f]{64}$")
_NONCE = re.compile(r"^[0-9a-f]{32}$")
_PAGE_LOCATION = re.compile(r"^page:([1-9][0-9]*)/row:([1-9][0-9]*)$")
_FIELD_REQUIREMENTS = {
    "date": ("transaction_date", "posting_date"),
    "description": ("raw_description",),
    "amount": ("inflow", "outflow"),
}
_REQUIRED_RESULT_FIELDS = frozenset({
    "transaction_id", "account_id", "currency", "transaction_date", "posting_date",
    "raw_description", "inflow", "outflow", "running_balance", "source_file",
    "source_page_or_row", "extraction_method", "extraction_confidence",
    "classification_status", "source_locations",
})
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


@dataclass(frozen=True)
class ExternalProcessingProposal:
    operation_id: str
    nonce: str
    provider: str
    source_hash: str
    pages: tuple[int, ...]
    fields: tuple[str, ...]
    sensitive_data: tuple[str, ...]
    retention_risk: str
    training_risk: str
    regional_risk: str
    redactions: tuple[str, ...]
    manual_alternative: str


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"proposal {name} is required")
    return value.strip()


def _text_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"proposal {name} is required")
    values = tuple(_required_text(item, name) for item in value)
    if len(set(values)) != len(values):
        raise ValueError(f"proposal {name} must not repeat values")
    return tuple(sorted(values))


def _pages(value: object) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("proposal pages are required")
    if any(not isinstance(page, int) or isinstance(page, bool) or page < 1 for page in value):
        raise ValueError("proposal pages must be positive integers")
    pages = tuple(sorted(value))
    if len(set(pages)) != len(pages):
        raise ValueError("proposal pages must not repeat values")
    return pages


def _operation_id(provider: str, source_hash: str, pages: tuple[int, ...], fields: tuple[str, ...], nonce: str) -> str:
    basis = json.dumps({
        "provider": provider, "source_hash": source_hash, "pages": pages,
        "fields": fields, "nonce": nonce,
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _normalized_proposal(
    *,
    provider: object,
    source_hash: object,
    pages: object,
    fields: object,
    sensitive_data: object,
    retention_risk: object,
    training_risk: object,
    regional_risk: object,
    redactions: object,
    manual_alternative: object,
    nonce: object,
    operation_id: object | None = None,
) -> ExternalProcessingProposal:
    provider_text = _required_text(provider, "provider")
    hash_text = _required_text(source_hash, "source_hash").lower()
    if not _HASH.fullmatch(hash_text):
        raise ValueError("proposal source_hash must be a SHA-256 digest")
    nonce_text = _required_text(nonce, "nonce").lower()
    if not _NONCE.fullmatch(nonce_text):
        raise ValueError("proposal nonce is invalid")
    normalized_pages = _pages(pages)
    normalized_fields = _text_tuple(fields, "fields")
    if set(normalized_fields).difference(_FIELD_REQUIREMENTS):
        raise ValueError("proposal fields are not supported")
    expected_operation_id = _operation_id(provider_text, hash_text, normalized_pages, normalized_fields, nonce_text)
    if operation_id is not None and _required_text(operation_id, "operation_id").lower() != expected_operation_id:
        raise ValueError("proposal operation_id does not match its disclosed scope")
    return ExternalProcessingProposal(
        operation_id=expected_operation_id,
        nonce=nonce_text,
        provider=provider_text,
        source_hash=hash_text,
        pages=normalized_pages,
        fields=normalized_fields,
        sensitive_data=_text_tuple(sensitive_data, "sensitive_data"),
        retention_risk=_required_text(retention_risk, "retention_risk"),
        training_risk=_required_text(training_risk, "training_risk"),
        regional_risk=_required_text(regional_risk, "regional_risk"),
        redactions=_text_tuple(redactions, "redactions"),
        manual_alternative=_required_text(manual_alternative, "manual_alternative"),
    )


def create_external_proposal(
    *,
    provider: str,
    source_hash: str,
    pages: tuple[int, ...] | list[int],
    fields: tuple[str, ...] | list[str],
    sensitive_data: tuple[str, ...] | list[str],
    retention_risk: str,
    training_risk: str,
    regional_risk: str,
    redactions: tuple[str, ...] | list[str],
    manual_alternative: str,
) -> ExternalProcessingProposal:
    """Create one non-reusable disclosure for one proposed external operation."""
    return _normalized_proposal(
        provider=provider, source_hash=source_hash, pages=pages, fields=fields,
        sensitive_data=sensitive_data, retention_risk=retention_risk, training_risk=training_risk,
        regional_risk=regional_risk, redactions=redactions, manual_alternative=manual_alternative,
        nonce=uuid4().hex,
    )


def proposal_to_dict(proposal: ExternalProcessingProposal) -> dict[str, object]:
    """Return the complete disclosure suitable for a local proposal JSON file."""
    return asdict(proposal)


def proposal_from_dict(payload: Mapping[str, object]) -> ExternalProcessingProposal:
    """Validate a locally saved disclosure without generating a new operation ID."""
    operation_id = payload.get("operation_id")
    nonce = payload.get("nonce")
    if operation_id is None and nonce is None:
        return create_external_proposal(
            provider=payload.get("provider", ""), source_hash=payload.get("source_hash", ""),
            pages=payload.get("pages", ()), fields=payload.get("fields", ()),
            sensitive_data=payload.get("sensitive_data", ()), retention_risk=payload.get("retention_risk", ""),
            training_risk=payload.get("training_risk", ""), regional_risk=payload.get("regional_risk", ""),
            redactions=payload.get("redactions", ()), manual_alternative=payload.get("manual_alternative", ""),
        )
    if operation_id is None or nonce is None:
        raise ValueError("proposal operation_id and nonce must both be present")
    return _normalized_proposal(
        provider=payload.get("provider", ""), source_hash=payload.get("source_hash", ""),
        pages=payload.get("pages", ()), fields=payload.get("fields", ()),
        sensitive_data=payload.get("sensitive_data", ()), retention_risk=payload.get("retention_risk", ""),
        training_risk=payload.get("training_risk", ""), regional_risk=payload.get("regional_risk", ""),
        redactions=payload.get("redactions", ()), manual_alternative=payload.get("manual_alternative", ""),
        nonce=nonce, operation_id=operation_id,
    )


def _scope_payload(proposal: ExternalProcessingProposal) -> dict[str, object]:
    """Return the non-sensitive exact scope retained in append-only audit."""
    disclosure = proposal_to_dict(proposal)
    disclosure.pop("operation_id")
    disclosure_digest = hashlib.sha256(
        json.dumps(disclosure, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "operation_id": proposal.operation_id,
        "provider": proposal.provider,
        "source_hash": proposal.source_hash,
        "pages": list(proposal.pages),
        "fields": list(proposal.fields),
        "disclosure_digest": disclosure_digest,
    }


def _decision_payload(proposal: ExternalProcessingProposal, authorized: bool) -> dict[str, object]:
    return {**_scope_payload(proposal), "authorized": authorized}


def record_external_decision(
    ledger_root: Path,
    proposal: ExternalProcessingProposal,
    authorized: bool,
    actor: str,
    now: datetime | None = None,
) -> str:
    """Append the user's current answer for exactly one disclosed operation."""
    if not isinstance(authorized, bool):
        raise ValueError("authorization decision must be boolean")
    proposal = proposal_from_dict(proposal_to_dict(proposal))
    return append_audit_event(
        ledger_root, _DECISION_EVENT_TYPE, _decision_payload(proposal, authorized), actor=actor, now=now,
    )


def _proposal_matches_payload(proposal: ExternalProcessingProposal, payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    return all(payload.get(key) == value for key, value in _scope_payload(proposal).items())


def _decision_for_id(ledger_root: Path, consent_id: str) -> dict[str, object] | None:
    for event in read_audit_events(ledger_root):
        if event.get("event_id") == consent_id and event.get("event_type") == _DECISION_EVENT_TYPE:
            return event
    return None


def find_valid_authorization(
    ledger_root: Path,
    consent_id: str,
    proposal: ExternalProcessingProposal,
) -> bool:
    """Return whether this event is the current authorization for this exact operation."""
    selected = _decision_for_id(ledger_root, consent_id)
    if selected is None or not _proposal_matches_payload(proposal, selected.get("payload")):
        return False
    events = [
        event for event in read_audit_events(ledger_root)
        if event.get("event_type") == _DECISION_EVENT_TYPE
        and isinstance(event.get("payload"), dict)
        and event["payload"].get("operation_id") == proposal.operation_id
    ]
    if not events:
        return False
    current = events[-1]
    return current.get("event_id") == consent_id and current.get("payload", {}).get("authorized") is True


def _issue(code: str, message: str) -> ImportResult:
    return ImportResult(issues=(Issue(code, message),))


@dataclass(frozen=True)
class _AuthorizedScope:
    operation_id: str
    provider: str
    source_hash: str
    pages: tuple[int, ...]
    fields: tuple[str, ...]


def _authorized_scope(ledger_root: Path, consent_id: str) -> _AuthorizedScope | None:
    event = _decision_for_id(ledger_root, consent_id)
    if event is None or not isinstance(event.get("payload"), dict):
        return None
    payload = event["payload"]
    try:
        operation_id = _required_text(payload.get("operation_id", ""), "operation_id")
        provider = _required_text(payload.get("provider", ""), "provider")
        source_hash = _required_text(payload.get("source_hash", ""), "source_hash").lower()
        if not _HASH.fullmatch(operation_id) or not _HASH.fullmatch(source_hash):
            return None
        scope = _AuthorizedScope(operation_id, provider, source_hash, _pages(payload.get("pages", ())), _text_tuple(payload.get("fields", ()), "fields"))
    except ValueError:
        return None
    # Compare the selected and current decision by stored exact scope, without
    # copying the human-facing disclosure text into audit storage.
    events = [
        item for item in read_audit_events(ledger_root)
        if item.get("event_type") == _DECISION_EVENT_TYPE
        and isinstance(item.get("payload"), dict)
        and item["payload"].get("operation_id") == scope.operation_id
    ]
    if not events or events[-1].get("event_id") != consent_id or payload.get("authorized") is not True:
        return None
    return scope


def _canonical_rows(result_path: Path) -> tuple[tuple[dict[str, str], ...], ImportResult | None]:
    try:
        with Path(result_path).open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != CANONICAL_TRANSACTION_FIELDS:
                return (), _issue("EXTERNAL_RESULT_INVALID", "Returned result does not use the canonical transaction fields.")
            rows = tuple(dict(row) for row in reader)
    except (OSError, csv.Error, UnicodeError):
        return (), _issue("EXTERNAL_RESULT_INVALID", "Returned result cannot be read as a local canonical CSV.")
    if not rows:
        return (), _issue("EXTERNAL_RESULT_INVALID", "Returned result has no transaction rows.")
    if any(not _valid_canonical_row(row) for row in rows):
        return (), _issue("EXTERNAL_RESULT_INVALID", "Returned result has malformed canonical transaction values.")
    return rows, None


def _valid_iso_date(value: str) -> bool:
    if not _ISO_DATE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _finite_decimal(value: str) -> Decimal | None:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def _valid_canonical_row(row: Mapping[object, object]) -> bool:
    """Validate a complete canonical result row before scope/provenance checks."""
    if set(row) != set(CANONICAL_TRANSACTION_FIELDS) or len(row) != len(CANONICAL_TRANSACTION_FIELDS):
        return False
    if any(not isinstance(row[field], str) for field in CANONICAL_TRANSACTION_FIELDS):
        return False
    if any(not row[field].strip() for field in _REQUIRED_RESULT_FIELDS):
        return False
    if not _valid_iso_date(str(row["transaction_date"])) or not _valid_iso_date(str(row["posting_date"])):
        return False
    inflow = _finite_decimal(str(row["inflow"]))
    outflow = _finite_decimal(str(row["outflow"]))
    balance = _finite_decimal(str(row["running_balance"]))
    if inflow is None or outflow is None or balance is None:
        return False
    return (inflow > 0 and outflow == 0) or (outflow > 0 and inflow == 0)


def _has_requested_fields(row: Mapping[str, str], fields: tuple[str, ...]) -> bool:
    for field in fields:
        required = _FIELD_REQUIREMENTS[field]
        if field == "amount":
            try:
                inflow, outflow = Decimal(row["inflow"]), Decimal(row["outflow"])
            except (InvalidOperation, KeyError):
                return False
            if (inflow == 0) == (outflow == 0):
                return False
        elif any(not row.get(name, "").strip() for name in required):
            return False
    return True


def _result_scope_issue(rows: tuple[dict[str, str], ...], proposal: _AuthorizedScope) -> ImportResult | None:
    expected_method = f"third_party:{proposal.provider}"
    if any(row.get("extraction_method") != expected_method for row in rows):
        return _issue("EXTERNAL_RESULT_PROVIDER_MISMATCH", "Returned result does not identify the authorized provider.")
    pages: set[int] = set()
    for row in rows:
        location = _PAGE_LOCATION.fullmatch(row.get("source_page_or_row", ""))
        if location is None:
            return _issue("EXTERNAL_RESULT_INVALID", "Returned result is missing page and row provenance.")
        pages.add(int(location.group(1)))
        if not row.get("source_file", "").strip() or not row.get("source_locations", "").strip():
            return _issue("EXTERNAL_RESULT_INVALID", "Returned result is missing source provenance.")
        if not _has_requested_fields(row, proposal.fields):
            return _issue("EXTERNAL_SCOPE_MISMATCH", "Returned result does not match the authorized field set.")
    if tuple(sorted(pages)) != proposal.pages:
        return _issue("EXTERNAL_SCOPE_MISMATCH", "Returned result does not match the authorized page set.")
    return None


def admit_external_result(
    ledger_root: Path,
    consent_id: str,
    provider: str,
    source_hash: str,
    result_path: Path,
) -> ImportResult:
    """Validate a local returned CSV; this function never uploads or calls a provider."""
    # Authorization must be evaluated before opening result_path.
    proposal = _authorized_scope(ledger_root, consent_id)
    if proposal is None:
        return _issue("EXTERNAL_NOT_AUTHORIZED", "The selected ledger has no current authorization for this operation.")
    if provider != proposal.provider or source_hash.lower() != proposal.source_hash:
        return _issue("EXTERNAL_SCOPE_MISMATCH", "Provider or source does not match the authorized operation.")
    rows, invalid = _canonical_rows(result_path)
    if invalid is not None:
        return invalid
    scope_issue = _result_scope_issue(rows, proposal)
    if scope_issue is not None:
        return scope_issue
    return ImportResult(transactions=rows, source_hashes={f"external:{proposal.operation_id}": proposal.source_hash})
