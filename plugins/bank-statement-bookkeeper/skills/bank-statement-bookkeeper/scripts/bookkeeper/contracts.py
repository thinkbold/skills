"""Stable public contracts for the bank-statement bookkeeping workflow."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


SCHEMA_VERSION = "1.0"

CANONICAL_TRANSACTION_FIELDS = (
    "transaction_id", "account_id", "currency", "transaction_date",
    "posting_date", "raw_description", "normalized_merchant", "inflow",
    "outflow", "running_balance", "reference", "source_file",
    "source_page_or_row", "extraction_method", "extraction_confidence",
    "classification_status", "account_code", "account_name", "rule_id",
    "review_note", "source_locations",
)

MERCHANT_RULE_FIELDS = (
    "rule_id", "normalized_merchant", "direction", "required_tokens",
    "excluded_tokens", "account_scope", "account_code", "account_name",
    "match_type", "status", "created_at", "updated_at", "audit_event_id",
)

BALANCE_FIELDS = (
    "account_id", "currency", "period_start", "period_end",
    "opening_balance", "closing_balance", "opening_source_type",
    "opening_source_file", "opening_source_location", "closing_source_file",
    "closing_source_location", "confirmed",
)


class RunState(str, Enum):
    EXTRACTED = "extracted"
    CLASSIFICATION_PENDING = "classification_pending"
    RECONCILIATION_PENDING = "reconciliation_pending"
    BLOCKED = "blocked"
    COMPLETE = "complete"


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    blocking: bool = True
    source_file: str = ""
    source_location: str = ""


@dataclass(frozen=True)
class AccountContext:
    account_id: str
    institution: str
    masked_label: str
    currency: str


@dataclass(frozen=True)
class ImportResult:
    transactions: tuple[dict[str, str], ...] = ()
    issues: tuple[Issue, ...] = ()
    source_hashes: dict[str, str] = field(default_factory=dict)
    duplicate_sources: tuple[dict[str, str], ...] = ()
    staged_files: tuple[Path, ...] = ()
