from decimal import Decimal
import json
from pathlib import Path
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
)


FIXTURES = Path(__file__).parent / "fixtures"
MAPPING = CsvMapping(
    transaction_date="Date", posting_date="Posted", description="Description",
    debit="Debit", credit="Credit", balance="Balance", reference="Reference",
    date_formats=("%Y-%m-%d",),
)
ACCOUNT = AccountContext("checking-001", "Synthetic Bank", "***1001", "CAD")


class ImportingTests(unittest.TestCase):
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
        """Catches re-import growth or a correction replacing the original description/provenance."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            initialize_ledger(ledger, "test", "Test", "CAD")
            mapping = {
                "transaction_date": "Date", "posting_date": "Posted", "description": "Description",
                "debit": "Debit", "credit": "Credit", "balance": "Balance", "reference": "Reference",
                "date_formats": ["%Y-%m-%d"],
            }
            account = {"account_id": "checking-001", "institution": "Synthetic Bank", "masked_label": "***1001", "currency": "CAD"}
            (ledger / "work" / "checking-map.json").write_text(json.dumps(mapping), encoding="utf-8")
            (ledger / "work" / "checking-account.json").write_text(json.dumps(account), encoding="utf-8")
            command = [
                sys.executable, str(SKILL_ROOT / "scripts" / "import_statements.py"), "csv", str(ledger),
                str(FIXTURES / "checking-january.csv"), "--mapping", "work/checking-map.json",
                "--account", "work/checking-account.json",
            ]
            first = subprocess.run(command, check=True, capture_output=True, text=True)
            second = subprocess.run(command, check=True, capture_output=True, text=True)
            rows = read_csv_rows(ledger / "inputs" / "canonical-transactions.csv")
            self.assertEqual(3, len(rows))
            self.assertEqual(json.loads(first.stdout)["transaction_count"], json.loads(second.stdout)["transaction_count"])
            correction = subprocess.run(
                [
                    sys.executable, str(SKILL_ROOT / "scripts" / "import_statements.py"), "correct-row", str(ledger),
                    rows[0]["transaction_id"], "--field", "transaction_date", "--value", "2026-01-31",
                    "--reason", "Confirmed against page 2", "--actor", "user",
                ], check=True, capture_output=True, text=True,
            )
            corrected = read_csv_rows(ledger / "inputs" / "canonical-transactions.csv")[0]
            self.assertEqual("COFFEE SHOP", corrected["raw_description"])
            self.assertEqual("checking-january.csv", corrected["source_file"])
            self.assertEqual("2", corrected["source_page_or_row"])
            self.assertEqual("2026-01-31", corrected["transaction_date"])
            self.assertEqual(json.loads(correction.stdout)["audit_event_id"], corrected["review_note"])
            correction_record = json.loads((ledger / "work" / "corrections.jsonl").read_text(encoding="utf-8"))
            self.assertEqual("2026-01-03", correction_record["original_value"])
            self.assertEqual("2026-01-31", correction_record["corrected_value"])
            self.assertNotIn("raw_description", json.dumps(read_audit_events(ledger)))


if __name__ == "__main__":
    unittest.main()
