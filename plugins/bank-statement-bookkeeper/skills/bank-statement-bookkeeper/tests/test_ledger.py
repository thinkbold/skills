from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import sys
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from bookkeeper.ledger import initialize_ledger, load_ledger, validate_ledger_config
from bookkeeper.storage import (
    append_audit_event,
    atomic_write_csv,
    atomic_write_json,
    mask_account_label,
    read_audit_events,
    read_csv_rows,
    resolve_inside_ledger,
    sha256_file,
)


class LedgerTests(unittest.TestCase):
    def test_initialize_is_ledger_local(self) -> None:
        """Catches initialization creating shared or unsupported ledger files."""
        with TemporaryDirectory() as temp:
            root = Path(temp) / "acme"
            config = initialize_ledger(
                root, "acme-2026", "Acme Synthetic Inc.", "CAD", "12-31",
                datetime(2026, 8, 24, tzinfo=timezone.utc),
            )
            self.assertEqual(config, load_ledger(root))
            self.assertEqual(
                {"audit", "inputs", "ledger.json", "merchant-rules.csv", "outputs", "work"},
                {path.name for path in root.iterdir()},
            )
            self.assertTrue((root / "inputs" / "account-balances.csv").is_file())
            self.assertTrue((root / "merchant-rules.csv").is_file())
            self.assertEqual([], read_csv_rows(root / "inputs" / "account-balances.csv"))
            self.assertEqual([], read_csv_rows(root / "merchant-rules.csv"))
            self.assertFalse((root / "chart-of-accounts.csv").exists())

    def test_escape_masking_and_audit_rejection(self) -> None:
        """Catches path escape, account disclosure, and sensitive audit storage."""
        with TemporaryDirectory() as temp:
            root = Path(temp) / "ledger"
            initialize_ledger(root, "acme", "Acme", "CAD", None)
            with self.assertRaisesRegex(ValueError, "outside ledger"):
                resolve_inside_ledger(root, "../other/merchant-rules.csv")
            self.assertEqual("********9012", mask_account_label("123456789012"))
            with self.assertRaisesRegex(ValueError, "sensitive audit key"):
                append_audit_event(root, "account_confirmed", {"full_account_number": "1"})

    def test_storage_round_trip_and_hash(self) -> None:
        """Catches partial writes or CSV values that cannot be read back."""
        with TemporaryDirectory() as temp:
            root = Path(temp) / "ledger"
            root.mkdir()
            json_path = root / "work" / "state.json"
            csv_path = root / "inputs" / "rows.csv"
            atomic_write_json(json_path, {"state": "ready"})
            atomic_write_csv(csv_path, ("account_id", "currency"), ({"account_id": "A-1", "currency": "CAD"},))

            self.assertEqual('{\n  "state": "ready"\n}\n', json_path.read_text(encoding="utf-8"))
            self.assertEqual([{"account_id": "A-1", "currency": "CAD"}], read_csv_rows(csv_path))
            self.assertEqual(
                "1c5ba079896272f398d82c16ec8f42401fbfb6ebc069a23b8ede12a4ee2cd2a8",
                sha256_file(json_path),
            )

    def test_idempotent_initialization_keeps_one_audit_event(self) -> None:
        """Catches a repeated initialization appending a duplicate audit event."""
        with TemporaryDirectory() as temp:
            root = Path(temp) / "ledger"
            first = initialize_ledger(root, "acme", "Acme", "CAD", None)
            second = initialize_ledger(root, "acme", "Other Name", "USD", "06-30")

            self.assertEqual(first, second)
            events = read_audit_events(root)
            self.assertEqual(1, len(events))
            self.assertEqual("ledger_initialized", events[0]["event_type"])

    def test_audit_deduplication_is_only_used_when_requested(self) -> None:
        """Catches audit events being deduplicated without an explicit key."""
        with TemporaryDirectory() as temp:
            root = Path(temp) / "ledger"
            initialize_ledger(root, "acme", "Acme", "CAD")
            first = append_audit_event(root, "rule_saved", {"rule_id": "R-1"})
            second = append_audit_event(root, "rule_saved", {"rule_id": "R-1"})
            deduped = append_audit_event(root, "rule_saved", {"rule_id": "R-2"}, dedupe_key="rule-r2")
            repeated = append_audit_event(root, "rule_saved", {"rule_id": "R-2"}, dedupe_key="rule-r2")

            self.assertNotEqual(first, second)
            self.assertEqual(deduped, repeated)
            self.assertEqual(4, len(read_audit_events(root)))

    def test_nested_sensitive_audit_key_and_other_ledger_are_rejected(self) -> None:
        """Catches nested private data and accidental reuse of another ledger root."""
        with TemporaryDirectory() as temp:
            root = Path(temp) / "ledger"
            initialize_ledger(root, "acme", "Acme", "CAD")
            with self.assertRaisesRegex(ValueError, "sensitive audit key"):
                append_audit_event(root, "imported", {"source": {"access_token": "nope"}})
            with self.assertRaisesRegex(ValueError, "ledger ID"):
                initialize_ledger(root, "other", "Other", "CAD")

    def test_validates_required_ledger_configuration(self) -> None:
        """Catches accepting a config that cannot identify or interpret a ledger."""
        config = {
            "ledger_id": "acme",
            "company_name": "Acme",
            "base_currency": "CAD",
            "fiscal_year_end": None,
            "schema_version": "1.0",
            "created_at": "2026-08-24T00:00:00Z",
        }
        self.assertEqual(config, validate_ledger_config(config))
        with self.assertRaisesRegex(ValueError, "ledger_id"):
            validate_ledger_config({**config, "ledger_id": ""})

    def test_cli_prints_initialized_ledger_summary(self) -> None:
        """Catches the command omitting the initialized ledger's public summary."""
        with TemporaryDirectory() as temp:
            root = Path(temp) / "ledger"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SKILL_ROOT / "scripts" / "init_ledger.py"),
                    str(root),
                    "--ledger-id", "acme",
                    "--company-name", "Acme",
                    "--base-currency", "CAD",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual({
                "ledger_directory": str(root.resolve()),
                "ledger_id": "acme",
                "schema_version": "1.0",
                "status": "initialized",
            }, json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()
