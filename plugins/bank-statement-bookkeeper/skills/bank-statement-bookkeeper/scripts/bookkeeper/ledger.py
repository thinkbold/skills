"""Initialization and configuration for one isolated bookkeeping ledger."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Mapping

from .contracts import BALANCE_FIELDS, MERCHANT_RULE_FIELDS, SCHEMA_VERSION
from .storage import append_audit_event, atomic_write_csv, atomic_write_json, resolve_inside_ledger


_CONFIG_FIELDS = (
    "ledger_id",
    "company_name",
    "base_currency",
    "fiscal_year_end",
    "schema_version",
    "created_at",
)
_FISCAL_YEAR_END_PATTERN = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")


def _utc_timestamp(now: datetime | None) -> str:
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_ledger_config(config: Mapping[str, object]) -> dict[str, object]:
    """Validate and return the portable configuration for a single ledger."""
    validated = dict(config)
    for field in _CONFIG_FIELDS:
        if field not in validated:
            raise ValueError(f"ledger config missing {field}")
    for field in ("ledger_id", "company_name", "base_currency", "schema_version", "created_at"):
        if not isinstance(validated[field], str) or not validated[field]:
            raise ValueError(f"ledger config has invalid {field}")
    fiscal_year_end = validated["fiscal_year_end"]
    if fiscal_year_end is not None and (
        not isinstance(fiscal_year_end, str) or not _FISCAL_YEAR_END_PATTERN.fullmatch(fiscal_year_end)
    ):
        raise ValueError("ledger config has invalid fiscal_year_end")
    if validated["schema_version"] != SCHEMA_VERSION:
        raise ValueError("ledger config has unsupported schema_version")
    return validated


def load_ledger(root: Path) -> dict[str, object]:
    """Load and validate the selected ledger's configuration."""
    config_path = resolve_inside_ledger(root, "ledger.json")
    if not config_path.is_file():
        raise ValueError(f"ledger config does not exist: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ValueError("ledger config must be a JSON object")
    return validate_ledger_config(config)


def initialize_ledger(
    root: Path,
    ledger_id: str,
    company_name: str,
    base_currency: str,
    fiscal_year_end: str | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Create or verify one isolated ledger and return its configuration."""
    ledger_root = Path(root)
    if ledger_root.exists() and not ledger_root.is_dir():
        raise ValueError(f"ledger root is not a directory: {ledger_root}")
    if ledger_root.exists() and any(ledger_root.iterdir()):
        config = load_ledger(ledger_root)
        if config["ledger_id"] != ledger_id:
            raise ValueError("existing ledger ID does not match requested ledger ID")
        return config

    ledger_root.mkdir(parents=True, exist_ok=True)
    config = validate_ledger_config({
        "ledger_id": ledger_id,
        "company_name": company_name,
        "base_currency": base_currency,
        "fiscal_year_end": fiscal_year_end,
        "schema_version": SCHEMA_VERSION,
        "created_at": _utc_timestamp(now),
    })
    for directory in ("inputs", "work", "outputs", "audit"):
        resolve_inside_ledger(ledger_root, directory).mkdir(exist_ok=True)
    atomic_write_json(resolve_inside_ledger(ledger_root, "ledger.json"), config)
    atomic_write_csv(
        resolve_inside_ledger(ledger_root, "merchant-rules.csv"),
        MERCHANT_RULE_FIELDS,
        (),
    )
    atomic_write_csv(
        resolve_inside_ledger(ledger_root, Path("inputs") / "account-balances.csv"),
        BALANCE_FIELDS,
        (),
    )
    append_audit_event(
        ledger_root,
        "ledger_initialized",
        {"ledger_id": ledger_id, "schema_version": SCHEMA_VERSION},
        now=now,
    )
    return config
