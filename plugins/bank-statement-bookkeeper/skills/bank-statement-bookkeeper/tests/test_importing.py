from decimal import Decimal
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from bookkeeper.contracts import AccountContext
from bookkeeper.ledger import initialize_ledger
from bookkeeper.storage import read_audit_events, read_csv_rows
from bookkeeper.importing import (
    CsvMapping,
    StatementInventory,
    deduplicate_overlaps,
    discover_account_candidates,
    normalize_csv_statement,
    parse_decimal,
    stage_manual_correction,
)


FIXTURES = Path(__file__).parent / "fixtures"
MAPPING = CsvMapping(
    transaction_date="Date", posting_date="Posted", description="Description",
    debit="Debit", credit="Credit", balance="Balance", reference="Reference",
    date_formats=("%Y-%m-%d",),
)
ACCOUNT = AccountContext("checking-001", "Synthetic Bank", "***1001", "CAD")


class ImportingTests(unittest.TestCase):
    def _configured_ledger(self, temporary_root: str) -> Path:
        ledger = Path(temporary_root) / "ledger"
        initialize_ledger(ledger, "test", "Test", "CAD")
        mapping = {
            "transaction_date": "Date", "posting_date": "Posted", "description": "Description",
            "debit": "Debit", "credit": "Credit", "balance": "Balance", "reference": "Reference",
            "date_formats": ["%Y-%m-%d"],
        }
        account = {"account_id": "checking-001", "institution": "Synthetic Bank", "masked_label": "***1001", "currency": "CAD"}
        (ledger / "work" / "checking-map.json").write_text(json.dumps(mapping), encoding="utf-8")
        (ledger / "work" / "checking-account.json").write_text(json.dumps(account), encoding="utf-8")
        return ledger

    def _csv_command(self, ledger: Path, source: str) -> list[str]:
        return [
            sys.executable, str(SKILL_ROOT / "scripts" / "import_statements.py"), "csv", str(ledger), source,
            "--mapping", "work/checking-map.json", "--account", "work/checking-account.json",
        ]

    def test_decimal_and_provenance(self) -> None:
        """Catches stripped thousands, parenthetical debit, or lost CSV row provenance."""
        self.assertEqual(Decimal("1234.50"), parse_decimal("1,234.50"))
        self.assertEqual(Decimal("-42.10"), parse_decimal("(42.10)"))
        result = normalize_csv_statement(FIXTURES / "checking-january.csv", MAPPING, ACCOUNT)
        first = result.transactions[0]
        self.assertEqual("checking-001", first["account_id"])
        self.assertEqual("CAD", first["currency"])
        self.assertEqual("checking-january.csv", first["source_file"])
        self.assertEqual("2", first["source_page_or_row"])

    def test_overlap_preserves_multiplicity(self) -> None:
        """Catches overlap removal collapsing two legitimate same-day coffee purchases."""
        first = normalize_csv_statement(FIXTURES / "checking-january.csv", MAPPING, ACCOUNT)
        second = normalize_csv_statement(FIXTURES / "checking-overlap.csv", MAPPING, ACCOUNT)
        result = deduplicate_overlaps(first.transactions + second.transactions)
        coffee = [row for row in result.transactions if row["raw_description"] == "COFFEE SHOP"]
        self.assertEqual(2, len(coffee))
        self.assertGreaterEqual(len(result.duplicate_sources), 1)

    def test_overlap_uses_a_source_with_the_maximum_multiplicity(self) -> None:
        """Catches retaining a repeated location when a later source has two real rows."""
        january = normalize_csv_statement(FIXTURES / "checking-january.csv", MAPPING, ACCOUNT)
        overlap = normalize_csv_statement(FIXTURES / "checking-overlap.csv", MAPPING, ACCOUNT)
        later_second = dict(overlap.transactions[0])
        later_second["transaction_id"] = "later-second-coffee"
        later_second["source_page_or_row"] = "3"
        later_second["source_locations"] = "checking-overlap.csv:3"
        result = deduplicate_overlaps((january.transactions[0], overlap.transactions[0], later_second))
        self.assertEqual(2, len(result.transactions))
        self.assertEqual(
            {overlap.transactions[0]["transaction_id"], "later-second-coffee"},
            {row["transaction_id"] for row in result.transactions},
        )

    def test_account_candidates_separate_currency_and_masked_label(self) -> None:
        """Catches grouping distinct currency or masked-account statements for one confirmation."""
        candidates = discover_account_candidates((
            StatementInventory("a.csv", "Synthetic Bank", "***1001", "CAD", "high"),
            StatementInventory("b.csv", "Synthetic Bank", "***1001", "CAD", "high"),
            StatementInventory("c.csv", "Synthetic Bank", "***2002", "USD", "high"),
        ))
        self.assertEqual(2, len(candidates))

    def test_normalization_reports_currency_missing_before_account_confirmation(self) -> None:
        """Catches a missing currency being hidden behind the generic confirmation failure."""
        result = normalize_csv_statement(
            FIXTURES / "checking-january.csv", MAPPING,
            AccountContext("checking-001", "Synthetic Bank", "***1001", ""),
        )
        self.assertEqual("CURRENCY_MISSING", result.issues[0].code)

    def test_csv_command_is_idempotent_and_correction_preserves_extraction(self) -> None:
        """Catches writing canonical rows outside work or correction replacing extracted provenance."""
        with TemporaryDirectory() as temp:
            ledger = self._configured_ledger(temp)
            source = ledger / "inputs" / "checking-january.csv"
            shutil.copyfile(FIXTURES / "checking-january.csv", source)
            command = self._csv_command(ledger, "inputs/checking-january.csv")
            first = subprocess.run(command, check=True, capture_output=True, text=True)
            second = subprocess.run(command, check=True, capture_output=True, text=True)
            rows = read_csv_rows(ledger / "work" / "normalized-transactions.csv")
            self.assertEqual(3, len(rows))
            self.assertFalse((ledger / "inputs" / "canonical-transactions.csv").exists())
            self.assertEqual(json.loads(first.stdout)["transaction_count"], json.loads(second.stdout)["transaction_count"])
            correction = subprocess.run(
                [
                    sys.executable, str(SKILL_ROOT / "scripts" / "import_statements.py"), "correct-row", str(ledger),
                    rows[0]["transaction_id"], "--field", "transaction_date", "--value", "2026-01-31",
                    "--reason", "Confirmed against page 2", "--actor", "user",
                ], check=True, capture_output=True, text=True,
            )
            corrected = read_csv_rows(ledger / "work" / "normalized-transactions.csv")[0]
            self.assertEqual("COFFEE SHOP", corrected["raw_description"])
            self.assertEqual("inputs/checking-january.csv", corrected["source_file"])
            self.assertEqual("2", corrected["source_page_or_row"])
            self.assertEqual("2026-01-31", corrected["transaction_date"])
            self.assertEqual(json.loads(correction.stdout)["audit_event_id"], corrected["review_note"])
            correction_record = json.loads((ledger / "work" / "corrections.jsonl").read_text(encoding="utf-8"))
            self.assertEqual("2026-01-03", correction_record["original_value"])
            self.assertEqual("2026-01-31", correction_record["corrected_value"])
            self.assertNotIn("raw_description", json.dumps(read_audit_events(ledger)))

    def test_csv_replaces_changed_logical_source_and_keeps_same_basenames_distinct(self) -> None:
        """Catches stale rows after a changed source or collisions between separate statement paths."""
        with TemporaryDirectory() as temp:
            ledger = self._configured_ledger(temp)
            january = ledger / "inputs" / "january" / "statement.csv"
            february = ledger / "inputs" / "february" / "statement.csv"
            january.parent.mkdir()
            february.parent.mkdir()
            january.write_text(
                "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
                "2026-01-03,2026-01-03,OLD COFFEE,4.50,,995.50,OLD-1\n", encoding="utf-8",
            )
            subprocess.run(self._csv_command(ledger, "inputs/january/statement.csv"), check=True, capture_output=True, text=True)
            january.write_text(
                "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
                "2026-01-03,2026-01-03,NEW COFFEE,5.00,,995.00,NEW-1\n", encoding="utf-8",
            )
            subprocess.run(self._csv_command(ledger, "inputs/january/statement.csv"), check=True, capture_output=True, text=True)
            february.write_text(
                "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
                "2026-02-03,2026-02-03,FEBRUARY COFFEE,6.00,,989.00,FEB-1\n", encoding="utf-8",
            )
            subprocess.run(self._csv_command(ledger, "inputs/february/statement.csv"), check=True, capture_output=True, text=True)
            rows = read_csv_rows(ledger / "work" / "normalized-transactions.csv")
            self.assertEqual(2, len(rows))
            self.assertEqual({"NEW COFFEE", "FEBRUARY COFFEE"}, {row["raw_description"] for row in rows})
            self.assertEqual(
                {"inputs/january/statement.csv", "inputs/february/statement.csv"},
                {row["source_file"] for row in rows},
            )

    def test_normalization_blocks_blank_invalid_and_zero_amounts(self) -> None:
        """Catches zero-value statements or malformed money being accepted or called a date failure."""
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            cases = {
                "blank": "2026-01-03,2026-01-03,COFFEE,,,995.50,R-1\n",
                "invalid": "2026-01-03,2026-01-03,COFFEE,not-money,,995.50,R-1\n",
                "zero": "2026-01-03,2026-01-03,COFFEE,0,0,995.50,R-1\n",
            }
            expected = {"blank": "AMOUNT_MISSING", "invalid": "AMOUNT_UNPARSEABLE", "zero": "AMOUNT_ZERO"}
            for name, row in cases.items():
                source = directory / f"{name}.csv"
                source.write_text("Date,Posted,Description,Debit,Credit,Balance,Reference\n" + row, encoding="utf-8")
                result = normalize_csv_statement(source, MAPPING, ACCOUNT)
                self.assertEqual(expected[name], result.issues[0].code)

    def test_pending_correction_recovers_canonical_audit_and_correction_record_together(self) -> None:
        """Catches an interruption leaving an updated row without its audit and correction record."""
        with TemporaryDirectory() as temp:
            ledger = self._configured_ledger(temp)
            source = ledger / "inputs" / "checking-january.csv"
            shutil.copyfile(FIXTURES / "checking-january.csv", source)
            subprocess.run(self._csv_command(ledger, "inputs/checking-january.csv"), check=True, capture_output=True, text=True)
            canonical = ledger / "work" / "normalized-transactions.csv"
            original = read_csv_rows(canonical)
            stage_manual_correction(
                ledger, tuple(original), original[0]["transaction_id"], "transaction_date", "2026-01-31",
                "Confirmed against page 2", "user",
            )
            self.assertEqual("2026-01-03", read_csv_rows(canonical)[0]["transaction_date"])
            self.assertTrue((ledger / "work" / "pending-correction.json").is_file())
            rerun = [
                sys.executable, str(SKILL_ROOT / "scripts" / "import_statements.py"), "inventory", str(ledger),
                "inputs/checking-january.csv",
            ]
            subprocess.run(rerun, check=True, capture_output=True, text=True)
            self.assertEqual("2026-01-31", read_csv_rows(canonical)[0]["transaction_date"])
            self.assertFalse((ledger / "work" / "pending-correction.json").exists())
            self.assertEqual(1, len([event for event in read_audit_events(ledger) if event["event_type"] == "manual_correction_recorded"]))
            self.assertEqual(1, len((ledger / "work" / "corrections.jsonl").read_text(encoding="utf-8").splitlines()))
            subprocess.run(rerun, check=True, capture_output=True, text=True)
            self.assertEqual(1, len((ledger / "work" / "corrections.jsonl").read_text(encoding="utf-8").splitlines()))


if __name__ == "__main__":
    unittest.main()
