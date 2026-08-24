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

from bookkeeper.contracts import CANONICAL_TRANSACTION_FIELDS, MERCHANT_RULE_FIELDS, AccountContext
from bookkeeper.ledger import initialize_ledger
from bookkeeper.storage import atomic_write_csv, read_audit_events, read_csv_rows
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

    def _classification_command(self, *arguments: str) -> list[str]:
        return [sys.executable, str(SKILL_ROOT / "scripts" / "classify_transactions.py"), *arguments]

    def _ledger_bytes(self, ledger: Path) -> dict[str, bytes]:
        return {
            path.relative_to(ledger).as_posix(): path.read_bytes()
            for path in sorted(ledger.rglob("*"))
            if path.is_file()
        }

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

    def test_unrelated_import_preserves_a_durable_manual_correction_and_review_note(self) -> None:
        """Catches contribution rebuilds reverting an audit-backed correct-row decision."""
        with TemporaryDirectory() as temp:
            ledger = self._configured_ledger(temp)
            first = ledger / "inputs" / "first.csv"
            second = ledger / "inputs" / "second.csv"
            first.write_text(
                "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
                "2026-01-05,2026-01-05,FIRST MERCHANT,10.00,,990.00,FIRST-1\n",
                encoding="utf-8",
            )
            subprocess.run(self._csv_command(ledger, "inputs/first.csv"), check=True, capture_output=True, text=True)
            transaction_id = read_csv_rows(ledger / "work" / "normalized-transactions.csv")[0]["transaction_id"]
            corrected = subprocess.run([
                sys.executable, str(SKILL_ROOT / "scripts" / "import_statements.py"), "correct-row", str(ledger),
                transaction_id, "--field", "posting_date", "--value", "2026-01-07",
                "--reason", "Confirmed posting date", "--actor", "user",
            ], check=True, capture_output=True, text=True)
            correction_event_id = json.loads(corrected.stdout)["audit_event_id"]
            second.write_text(
                "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
                "2026-02-05,2026-02-05,SECOND MERCHANT,12.00,,978.00,SECOND-1\n",
                encoding="utf-8",
            )

            subprocess.run(self._csv_command(ledger, "inputs/second.csv"), check=True, capture_output=True, text=True)

            row_after_rebuild = next(
                row for row in read_csv_rows(ledger / "work" / "normalized-transactions.csv")
                if row["transaction_id"] == transaction_id
            )
            self.assertEqual("2026-01-07", row_after_rebuild["posting_date"])
            self.assertEqual(correction_event_id, row_after_rebuild["review_note"])

    def test_signature_correction_preserves_one_overlap_row_and_all_source_locations(self) -> None:
        """Catches replaying a signature correction before overlap removal and splitting one transaction."""
        with TemporaryDirectory() as temp:
            ledger = self._configured_ledger(temp)
            header = "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
            overlap = "2026-01-05,2026-01-05,OVERLAP MERCHANT,10.00,,990.00,OVERLAP-1\n"
            for name in ("a.csv", "b.csv"):
                (ledger / "inputs" / name).write_text(header + overlap, encoding="utf-8")
                subprocess.run(self._csv_command(ledger, f"inputs/{name}"), check=True, capture_output=True, text=True)
            before = read_csv_rows(ledger / "work" / "normalized-transactions.csv")
            self.assertEqual(1, len(before))
            transaction_id = before[0]["transaction_id"]
            correction = subprocess.run([
                sys.executable, str(SKILL_ROOT / "scripts" / "import_statements.py"), "correct-row", str(ledger),
                transaction_id, "--field", "posting_date", "--value", "2026-01-07",
                "--reason", "Confirmed corrected posting date", "--actor", "user",
            ], check=True, capture_output=True, text=True)
            (ledger / "inputs" / "c.csv").write_text(
                header + "2026-02-05,2026-02-05,UNRELATED MERCHANT,12.00,,978.00,C-1\n",
                encoding="utf-8",
            )

            subprocess.run(self._csv_command(ledger, "inputs/c.csv"), check=True, capture_output=True, text=True)

            overlap_rows = [
                row for row in read_csv_rows(ledger / "work" / "normalized-transactions.csv")
                if row["raw_description"] == "OVERLAP MERCHANT"
            ]
            self.assertEqual(1, len(overlap_rows))
            self.assertEqual(transaction_id, overlap_rows[0]["transaction_id"])
            self.assertEqual("2026-01-07", overlap_rows[0]["posting_date"])
            self.assertEqual(json.loads(correction.stdout)["audit_event_id"], overlap_rows[0]["review_note"])
            self.assertEqual(
                {"inputs/a.csv:2", "inputs/b.csv:2"},
                set(overlap_rows[0]["source_locations"].split("|")),
            )

    def test_apply_future_confirmation_preserves_historical_rule_link_after_rebuild(self) -> None:
        """Catches an unrelated import blanking the rule created by an apply-future confirmation."""
        with TemporaryDirectory() as temp:
            ledger = self._configured_ledger(temp)
            header = "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
            (ledger / "inputs" / "a.csv").write_text(
                header + "2026-01-05,2026-01-05,FUTURE MERCHANT,10.00,,990.00,A-1\n",
                encoding="utf-8",
            )
            subprocess.run(self._csv_command(ledger, "inputs/a.csv"), check=True, capture_output=True, text=True)
            pending = subprocess.run(
                self._classification_command("pending", str(ledger)), check=True, capture_output=True, text=True,
            )
            group_id = json.loads(pending.stdout)["groups"][0]["group_id"]
            subprocess.run(self._classification_command(
                "confirm", str(ledger), group_id, "--account-code", "", "--account-name", "Durable Future",
                "--apply-future", "--actor", "user",
            ), check=True, capture_output=True, text=True)
            historical = read_csv_rows(ledger / "work" / "normalized-transactions.csv")[0]
            historical_rule_id = historical["rule_id"]
            subprocess.run(self._classification_command(
                "deactivate-rule", str(ledger), historical_rule_id, "--actor", "user",
            ), check=True, capture_output=True, text=True)
            (ledger / "inputs" / "b.csv").write_text(
                header + "2026-02-05,2026-02-05,UNRELATED MERCHANT,12.00,,978.00,B-1\n",
                encoding="utf-8",
            )

            subprocess.run(self._csv_command(ledger, "inputs/b.csv"), check=True, capture_output=True, text=True)

            rebuilt = next(
                row for row in read_csv_rows(ledger / "work" / "normalized-transactions.csv")
                if row["transaction_id"] == historical["transaction_id"]
            )
            self.assertEqual(("classified", "Durable Future", historical_rule_id), (
                rebuilt["classification_status"], rebuilt["account_name"], rebuilt["rule_id"],
            ))

    def test_future_rule_correction_preserves_deleted_historical_rule_link_after_rebuild(self) -> None:
        """Catches replay losing the audit-bound replacement rule after that rule is deliberately deleted."""
        with TemporaryDirectory() as temp:
            ledger = self._configured_ledger(temp)
            header = "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
            (ledger / "inputs" / "a.csv").write_text(
                header + "2026-01-05,2026-01-05,REPLACED MERCHANT,10.00,,990.00,A-1\n",
                encoding="utf-8",
            )
            subprocess.run(self._csv_command(ledger, "inputs/a.csv"), check=True, capture_output=True, text=True)
            pending = subprocess.run(
                self._classification_command("pending", str(ledger)), check=True, capture_output=True, text=True,
            )
            group_id = json.loads(pending.stdout)["groups"][0]["group_id"]
            subprocess.run(self._classification_command(
                "confirm", str(ledger), group_id, "--account-code", "", "--account-name", "Initial",
                "--apply-future", "--actor", "user",
            ), check=True, capture_output=True, text=True)
            selected = read_csv_rows(ledger / "work" / "normalized-transactions.csv")[0]
            subprocess.run(self._classification_command(
                "correct", str(ledger), "--transaction-id", selected["transaction_id"],
                "--account-code", "", "--account-name", "Durable Replacement",
                "--scope", "future_rule", "--actor", "user",
            ), check=True, capture_output=True, text=True)
            historical = read_csv_rows(ledger / "work" / "normalized-transactions.csv")[0]
            historical_rule_id = historical["rule_id"]
            subprocess.run(self._classification_command(
                "delete-rule", str(ledger), historical_rule_id, "--actor", "user",
            ), check=True, capture_output=True, text=True)
            self.assertNotIn(
                historical_rule_id,
                {rule["rule_id"] for rule in read_csv_rows(ledger / "merchant-rules.csv")},
            )
            (ledger / "inputs" / "b.csv").write_text(
                header + "2026-02-05,2026-02-05,UNRELATED MERCHANT,12.00,,978.00,B-1\n",
                encoding="utf-8",
            )

            subprocess.run(self._csv_command(ledger, "inputs/b.csv"), check=True, capture_output=True, text=True)

            rebuilt = next(
                row for row in read_csv_rows(ledger / "work" / "normalized-transactions.csv")
                if row["transaction_id"] == historical["transaction_id"]
            )
            self.assertEqual(("classified", "Durable Replacement", historical_rule_id), (
                rebuilt["classification_status"], rebuilt["account_name"], rebuilt["rule_id"],
            ))

    def test_selected_correction_deliberately_clears_an_existing_rule_link(self) -> None:
        """Catches selected-only correction retaining a rule that authorizes future classifications."""
        with TemporaryDirectory() as temp:
            ledger = self._configured_ledger(temp)
            (ledger / "inputs" / "a.csv").write_text(
                "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
                "2026-01-05,2026-01-05,SELECTED MERCHANT,10.00,,990.00,A-1\n",
                encoding="utf-8",
            )
            subprocess.run(self._csv_command(ledger, "inputs/a.csv"), check=True, capture_output=True, text=True)
            pending = subprocess.run(
                self._classification_command("pending", str(ledger)), check=True, capture_output=True, text=True,
            )
            group_id = json.loads(pending.stdout)["groups"][0]["group_id"]
            subprocess.run(self._classification_command(
                "confirm", str(ledger), group_id, "--account-code", "", "--account-name", "Initial",
                "--apply-future", "--actor", "user",
            ), check=True, capture_output=True, text=True)
            selected = read_csv_rows(ledger / "work" / "normalized-transactions.csv")[0]
            self.assertNotEqual("", selected["rule_id"])

            subprocess.run(self._classification_command(
                "correct", str(ledger), "--transaction-id", selected["transaction_id"],
                "--account-code", "", "--account-name", "One Time Override",
                "--scope", "selected", "--actor", "user",
            ), check=True, capture_output=True, text=True)

            corrected = read_csv_rows(ledger / "work" / "normalized-transactions.csv")[0]
            self.assertEqual(("classified", "One Time Override", ""), (
                corrected["classification_status"], corrected["account_name"], corrected["rule_id"],
            ))

    def test_unrelated_import_preserves_a_selected_only_classification_correction(self) -> None:
        """Catches rebuilding a selected classification from rules when the user chose no future rule."""
        with TemporaryDirectory() as temp:
            ledger = self._configured_ledger(temp)
            first = ledger / "inputs" / "first.csv"
            second = ledger / "inputs" / "second.csv"
            first.write_text(
                "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
                "2026-01-05,2026-01-05,ONE TIME MERCHANT,10.00,,990.00,FIRST-1\n",
                encoding="utf-8",
            )
            subprocess.run(self._csv_command(ledger, "inputs/first.csv"), check=True, capture_output=True, text=True)
            classify = str(SKILL_ROOT / "scripts" / "classify_transactions.py")
            pending = subprocess.run(
                [sys.executable, classify, "pending", str(ledger)],
                check=True, capture_output=True, text=True,
            )
            group_id = json.loads(pending.stdout)["groups"][0]["group_id"]
            subprocess.run([
                sys.executable, classify, "confirm", str(ledger), group_id,
                "--account-code", "", "--account-name", "Initial Category", "--actor", "user",
            ], check=True, capture_output=True, text=True)
            selected = read_csv_rows(ledger / "work" / "normalized-transactions.csv")[0]
            transaction_id = selected["transaction_id"]
            subprocess.run([
                sys.executable, classify, "correct", str(ledger), "--transaction-id", transaction_id,
                "--account-code", "", "--account-name", "Durable Category",
                "--scope", "selected", "--actor", "user",
            ], check=True, capture_output=True, text=True)
            self.assertEqual([], read_csv_rows(ledger / "merchant-rules.csv"))
            second.write_text(
                "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
                "2026-02-05,2026-02-05,SECOND MERCHANT,12.00,,978.00,SECOND-1\n",
                encoding="utf-8",
            )

            subprocess.run(self._csv_command(ledger, "inputs/second.csv"), check=True, capture_output=True, text=True)

            row_after_rebuild = next(
                row for row in read_csv_rows(ledger / "work" / "normalized-transactions.csv")
                if row["transaction_id"] == transaction_id
            )
            self.assertEqual("classified", row_after_rebuild["classification_status"])
            self.assertEqual("ONE TIME MERCHANT", row_after_rebuild["normalized_merchant"])
            self.assertEqual("Durable Category", row_after_rebuild["account_name"])
            self.assertEqual(("", ""), (row_after_rebuild["account_code"], row_after_rebuild["rule_id"]))
            self.assertEqual([], read_csv_rows(ledger / "merchant-rules.csv"))

    def test_changed_source_transaction_ids_do_not_inherit_old_user_decisions(self) -> None:
        """Catches correction or classification overlays leaking from obsolete IDs to replacement rows."""
        with TemporaryDirectory() as temp:
            ledger = self._configured_ledger(temp)
            source = ledger / "inputs" / "changing.csv"
            source.write_text(
                "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
                "2026-01-05,2026-01-05,CORRECTED MERCHANT,10.00,,990.00,CORRECT-1\n"
                "2026-01-06,2026-01-06,SELECTED MERCHANT,11.00,,979.00,SELECT-1\n",
                encoding="utf-8",
            )
            subprocess.run(self._csv_command(ledger, "inputs/changing.csv"), check=True, capture_output=True, text=True)
            original = read_csv_rows(ledger / "work" / "normalized-transactions.csv")
            corrected_id = next(row["transaction_id"] for row in original if row["raw_description"] == "CORRECTED MERCHANT")
            selected_id = next(row["transaction_id"] for row in original if row["raw_description"] == "SELECTED MERCHANT")
            subprocess.run([
                sys.executable, str(SKILL_ROOT / "scripts" / "import_statements.py"), "correct-row", str(ledger),
                corrected_id, "--field", "posting_date", "--value", "2026-01-09",
                "--reason", "Confirmed posting date", "--actor", "user",
            ], check=True, capture_output=True, text=True)
            classify = str(SKILL_ROOT / "scripts" / "classify_transactions.py")
            pending = subprocess.run(
                [sys.executable, classify, "pending", str(ledger)],
                check=True, capture_output=True, text=True,
            )
            group = next(
                item for item in json.loads(pending.stdout)["groups"]
                if item["normalized_merchant"] == "SELECTED MERCHANT"
            )
            subprocess.run([
                sys.executable, classify, "confirm", str(ledger), group["group_id"],
                "--account-code", "", "--account-name", "Selected Category", "--actor", "user",
            ], check=True, capture_output=True, text=True)
            source.write_text(
                "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
                "2026-01-05,2026-01-05,CORRECTED MERCHANT,10.00,,990.00,CORRECT-2\n"
                "2026-01-06,2026-01-06,SELECTED MERCHANT,11.00,,979.00,SELECT-2\n",
                encoding="utf-8",
            )

            subprocess.run(self._csv_command(ledger, "inputs/changing.csv"), check=True, capture_output=True, text=True)

            replacement = read_csv_rows(ledger / "work" / "normalized-transactions.csv")
            self.assertTrue({corrected_id, selected_id}.isdisjoint(row["transaction_id"] for row in replacement))
            corrected = next(row for row in replacement if row["raw_description"] == "CORRECTED MERCHANT")
            selected = next(row for row in replacement if row["raw_description"] == "SELECTED MERCHANT")
            self.assertEqual(("2026-01-05", ""), (corrected["posting_date"], corrected["review_note"]))
            self.assertEqual("unclassified", selected["classification_status"])
            self.assertEqual(("", "", ""), (selected["account_code"], selected["account_name"], selected["rule_id"]))

    def test_unrelated_import_fails_closed_on_a_tampered_correction_record(self) -> None:
        """Catches replaying a correction value that no longer matches its privacy-safe audit hashes."""
        with TemporaryDirectory() as temp:
            ledger = self._configured_ledger(temp)
            first = ledger / "inputs" / "first.csv"
            second = ledger / "inputs" / "second.csv"
            first.write_text(
                "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
                "2026-01-05,2026-01-05,FIRST MERCHANT,10.00,,990.00,FIRST-1\n",
                encoding="utf-8",
            )
            subprocess.run(self._csv_command(ledger, "inputs/first.csv"), check=True, capture_output=True, text=True)
            transaction_id = read_csv_rows(ledger / "work" / "normalized-transactions.csv")[0]["transaction_id"]
            subprocess.run([
                sys.executable, str(SKILL_ROOT / "scripts" / "import_statements.py"), "correct-row", str(ledger),
                transaction_id, "--field", "posting_date", "--value", "2026-01-07",
                "--reason", "Confirmed posting date", "--actor", "user",
            ], check=True, capture_output=True, text=True)
            corrections = ledger / "work" / "corrections.jsonl"
            record = json.loads(corrections.read_text(encoding="utf-8"))
            record["corrected_value"] = "2026-01-08"
            corrections.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
            second.write_text(
                "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
                "2026-02-05,2026-02-05,SECOND MERCHANT,12.00,,978.00,SECOND-1\n",
                encoding="utf-8",
            )
            expected = self._ledger_bytes(ledger)

            rejected = subprocess.run(
                self._csv_command(ledger, "inputs/second.csv"), capture_output=True, text=True,
            )

            self.assertEqual(3, rejected.returncode)
            self.assertEqual("LEDGER_SCHEMA_INVALID", json.loads(rejected.stdout)["error"])
            self.assertEqual(expected, self._ledger_bytes(ledger))

    def test_unrelated_import_fails_closed_on_a_tampered_selected_classification(self) -> None:
        """Catches trusting canonical category fields that do not match their selection audit hashes."""
        with TemporaryDirectory() as temp:
            ledger = self._configured_ledger(temp)
            first = ledger / "inputs" / "first.csv"
            second = ledger / "inputs" / "second.csv"
            first.write_text(
                "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
                "2026-01-05,2026-01-05,ONE TIME MERCHANT,10.00,,990.00,FIRST-1\n",
                encoding="utf-8",
            )
            subprocess.run(self._csv_command(ledger, "inputs/first.csv"), check=True, capture_output=True, text=True)
            classify = str(SKILL_ROOT / "scripts" / "classify_transactions.py")
            pending = subprocess.run(
                [sys.executable, classify, "pending", str(ledger)],
                check=True, capture_output=True, text=True,
            )
            group_id = json.loads(pending.stdout)["groups"][0]["group_id"]
            subprocess.run([
                sys.executable, classify, "confirm", str(ledger), group_id,
                "--account-code", "", "--account-name", "Selected Category", "--actor", "user",
            ], check=True, capture_output=True, text=True)
            canonical = ledger / "work" / "normalized-transactions.csv"
            row = read_csv_rows(canonical)[0]
            row["account_name"] = "Forged Category"
            atomic_write_csv(canonical, CANONICAL_TRANSACTION_FIELDS, (row,))
            second.write_text(
                "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
                "2026-02-05,2026-02-05,SECOND MERCHANT,12.00,,978.00,SECOND-1\n",
                encoding="utf-8",
            )
            expected = self._ledger_bytes(ledger)

            rejected = subprocess.run(
                self._csv_command(ledger, "inputs/second.csv"), capture_output=True, text=True,
            )

            self.assertEqual(3, rejected.returncode)
            self.assertEqual("LEDGER_SCHEMA_INVALID", json.loads(rejected.stdout)["error"])
            self.assertEqual(expected, self._ledger_bytes(ledger))

    def test_unrelated_import_fails_closed_on_a_rule_linked_to_an_unrelated_audit_event(self) -> None:
        """Catches accepting a rule whose audit ID exists but did not authorize that rule."""
        with TemporaryDirectory() as temp:
            ledger = self._configured_ledger(temp)
            header = "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
            (ledger / "inputs" / "a.csv").write_text(
                header + "2026-01-05,2026-01-05,LINKED MERCHANT,10.00,,990.00,A-1\n",
                encoding="utf-8",
            )
            subprocess.run(self._csv_command(ledger, "inputs/a.csv"), check=True, capture_output=True, text=True)
            pending = subprocess.run(
                self._classification_command("pending", str(ledger)), check=True, capture_output=True, text=True,
            )
            group_id = json.loads(pending.stdout)["groups"][0]["group_id"]
            subprocess.run(self._classification_command(
                "confirm", str(ledger), group_id, "--account-code", "", "--account-name", "Linked Category",
                "--apply-future", "--actor", "user",
            ), check=True, capture_output=True, text=True)
            rules_path = ledger / "merchant-rules.csv"
            rule = read_csv_rows(rules_path)[0]
            rule["audit_event_id"] = next(
                event["event_id"] for event in read_audit_events(ledger)
                if event["event_type"] == "ledger_initialized"
            )
            atomic_write_csv(rules_path, MERCHANT_RULE_FIELDS, (rule,))
            (ledger / "inputs" / "b.csv").write_text(
                header + "2026-02-05,2026-02-05,UNRELATED MERCHANT,12.00,,978.00,B-1\n",
                encoding="utf-8",
            )
            expected = self._ledger_bytes(ledger)

            rejected = subprocess.run(
                self._csv_command(ledger, "inputs/b.csv"), capture_output=True, text=True,
            )

            self.assertEqual(3, rejected.returncode)
            self.assertEqual("LEDGER_SCHEMA_INVALID", json.loads(rejected.stdout)["error"])
            self.assertEqual(expected, self._ledger_bytes(ledger))

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
