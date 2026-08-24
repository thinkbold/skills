from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from bookkeeper.contracts import Issue, RunState
from bookkeeper.ledger import initialize_ledger
from bookkeeper.classification import save_transactions
from bookkeeper.contracts import CANONICAL_TRANSACTION_FIELDS, BALANCE_FIELDS
from bookkeeper.storage import atomic_write_csv
from bookkeeper.reconciliation import reconcile_account_period
from bookkeeper.validation import collect_ledger_issues, determine_run_state, finalize_outputs


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reconciled = reconcile_account_period(
            "checking", "CAD", Decimal("1.00"), (), (), Decimal("1.00"),
            "2026-01-01", "2026-01-31", "user_provided", "2026-01-01",
        )

    def test_state_precedence_blocks_before_classification_and_reconciliation(self) -> None:
        """Catches a pending merchant hiding a critical parsing failure."""
        state = determine_run_state(True, 1, (), (Issue("PDF_PAGE_EMPTY", "page 2", True),))
        self.assertEqual(RunState.BLOCKED, state)

    def test_unknown_merchants_are_pending_not_blocking(self) -> None:
        """Catches unknown merchants being promoted to blocking validation issues."""
        issues = collect_ledger_issues((), (), pending_group_count=2)
        self.assertEqual((), issues)
        self.assertEqual(RunState.CLASSIFICATION_PENDING, determine_run_state(True, 2, (self.reconciled,), issues))

    def test_unreconciled_units_are_pending_when_evidence_is_missing(self) -> None:
        """Catches missing unconfirmed balance evidence becoming a blocking issue."""
        pending = reconcile_account_period(
            "checking", "CAD", None, (), (), Decimal("1.00"),
            "2026-01-01", "2026-01-31", "", "",
        )
        self.assertFalse(any(issue.blocking for issue in pending.issues))
        self.assertEqual(RunState.RECONCILIATION_PENDING, determine_run_state(True, 0, (pending,), pending.issues))

    def test_collect_ledger_issues_promotes_critical_categories_and_nonzero_difference(self) -> None:
        """Catches consent, conflicts, coverage, and failed balancing not blocking completion."""
        unbalanced = reconcile_account_period(
            "checking", "CAD", Decimal("1.00"), (), (), Decimal("2.00"),
            "2026-01-01", "2026-01-31", "user_provided", "2026-01-01",
        )
        issues = collect_ledger_issues(
            (Issue("MERCHANT_RULE_CONFLICT", "conflict", False), Issue("EXTERNAL_NOT_AUTHORIZED", "no", True)),
            (unbalanced,),
        )
        self.assertTrue(all(issue.blocking for issue in issues))
        self.assertEqual(RunState.BLOCKED, determine_run_state(True, 0, (unbalanced,), issues))

    def test_finalize_outputs_writes_masked_exceptions_and_status(self) -> None:
        """Catches final status omitting the state or leaking an account identifier in exception output."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
            result = finalize_outputs(
                ledger, has_transactions=True, pending_group_count=0,
                reconciliation_rows=(self.reconciled,),
                issues=(Issue("ACCOUNT_IDENTITY_AMBIGUOUS", "checking-001 requires review", True),),
                account_labels={"checking-001": "********9012"},
            )
            status = json.loads((ledger / "outputs" / "status.json").read_text(encoding="utf-8"))
            exceptions = (ledger / "outputs" / "exceptions.csv").read_text(encoding="utf-8")
            self.assertEqual("blocked", result["state"])
            self.assertEqual("blocked", status["state"])
            self.assertNotIn("checking-001", exceptions)
            self.assertIn("********9012", exceptions)

    def test_empty_run_is_reconciliation_pending_and_complete_requires_transactions(self) -> None:
        """Catches an empty ledger being announced as complete without reconciliation units."""
        self.assertEqual(RunState.RECONCILIATION_PENDING, determine_run_state(False, 0, (), ()))
        self.assertEqual(RunState.COMPLETE, determine_run_state(True, 0, (self.reconciled,), ()))

    def test_public_clis_write_currency_separated_outputs_and_one_json_status(self) -> None:
        """Catches the reconciliation commands failing to materialize safe ledger outputs."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
            row = {field: "" for field in CANONICAL_TRANSACTION_FIELDS}
            row.update({
                "transaction_id": "synthetic-cad-1", "account_id": "checking-001", "currency": "CAD",
                "transaction_date": "2026-01-03", "posting_date": "2026-01-03",
                "raw_description": "Synthetic private description", "inflow": "10.00", "outflow": "0",
                "running_balance": "110.00", "source_file": "synthetic.csv", "source_page_or_row": "2",
                "extraction_method": "csv", "extraction_confidence": "high", "classification_status": "classified",
                "account_name": "Synthetic category", "source_locations": "synthetic.csv:2",
            })
            save_transactions(ledger, (row,))
            balance = {field: "" for field in BALANCE_FIELDS}
            balance.update({
                "account_id": "checking-001", "currency": "CAD", "period_start": "2026-01-01",
                "period_end": "2026-01-31", "opening_balance": "100.00", "closing_balance": "110.00",
                "opening_source_type": "user_provided", "opening_source_file": "synthetic-balance.txt",
                "opening_source_location": "1", "closing_source_file": "synthetic.csv",
                "closing_source_location": "3", "confirmed": "true",
            })
            atomic_write_csv(ledger / "inputs" / "account-balances.csv", BALANCE_FIELDS, (balance,))
            reconcile = subprocess.run([sys.executable, str(SKILL_ROOT / "scripts" / "reconcile_accounts.py"), str(ledger)], capture_output=True, text=True)
            validate = subprocess.run([sys.executable, str(SKILL_ROOT / "scripts" / "validate_ledger.py"), str(ledger)], capture_output=True, text=True)
            self.assertEqual(0, reconcile.returncode, reconcile.stderr)
            self.assertEqual(0, validate.returncode, validate.stderr)
            self.assertEqual("complete", json.loads(validate.stdout)["state"])
            report = (ledger / "outputs" / "reconciliation-report.md").read_text(encoding="utf-8")
            self.assertIn("Currency: CAD", report)
            self.assertNotIn("Synthetic private description", report)

    def test_public_clis_reject_a_directory_without_a_selected_ledger(self) -> None:
        """Catches reconciliation writing derived files outside a validated ledger boundary."""
        with TemporaryDirectory() as temp:
            outside = Path(temp) / "not-a-ledger"
            outside.mkdir()
            for script in ("reconcile_accounts.py", "validate_ledger.py"):
                with self.subTest(script=script):
                    result = subprocess.run(
                        [sys.executable, str(SKILL_ROOT / "scripts" / script), str(outside)],
                        capture_output=True, text=True,
                    )
                    self.assertEqual(3, result.returncode)
                    self.assertFalse((outside / "outputs").exists())

    def test_invalid_canonical_rows_block_and_orphaned_unclassified_rows_stay_pending(self) -> None:
        """Catches malformed rows disappearing or blank descriptions bypassing classification pending."""
        malformed = {field: "" for field in CANONICAL_TRANSACTION_FIELDS}
        malformed.update({
            "transaction_id": "bad", "account_id": "checking", "currency": "", "transaction_date": "2026-01-03",
            "posting_date": "2026-01-03", "inflow": "10", "outflow": "0", "running_balance": "10",
            "classification_status": "unclassified", "source_file": "synthetic.csv", "source_page_or_row": "2",
        })
        orphaned = {**malformed, "transaction_id": "orphaned", "currency": "CAD", "raw_description": "!!!", "inflow": "10"}
        from bookkeeper.validation import count_pending_classifications, validate_canonical_transactions
        self.assertIn("CURRENCY_MISSING", {issue.code for issue in validate_canonical_transactions((malformed,))})
        self.assertEqual(1, count_pending_classifications((orphaned,)))

    def test_full_canonical_contract_rejects_structure_status_and_provenance(self) -> None:
        """Catches malformed schema/status/provenance rows bypassing final validation."""
        from bookkeeper.validation import validate_canonical_transactions
        complete = {field: "x" for field in CANONICAL_TRANSACTION_FIELDS}
        complete.update({"transaction_id": "row-1", "account_id": "checking", "currency": "CAD", "transaction_date": "2026-01-03", "posting_date": "2026-01-03", "raw_description": "Synthetic", "inflow": "10", "outflow": "0", "running_balance": "10", "source_file": "synthetic.csv", "source_page_or_row": "2", "classification_status": "bogus", "account_name": ""})
        malformed = {key: value for key, value in complete.items() if key != "source_page_or_row"}
        self.assertIn("CANONICAL_STATUS_INVALID", {issue.code for issue in validate_canonical_transactions((complete,))})
        self.assertIn("CANONICAL_SCHEMA_INVALID", {issue.code for issue in validate_canonical_transactions((malformed,))})

    def test_final_cli_blocks_bogus_status_and_nan_without_unexpected_error(self) -> None:
        """Catches exact-rule Decimal parsing occurring before canonical validation."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
            for status, inflow in (("bogus", "10"), ("unclassified", "NaN")):
                row = {field: "" for field in CANONICAL_TRANSACTION_FIELDS}
                row.update({"transaction_id": f"row-{status}", "account_id": "checking", "currency": "CAD", "transaction_date": "2026-01-03", "posting_date": "2026-01-03", "raw_description": "Synthetic", "inflow": inflow, "outflow": "0", "running_balance": "10", "source_file": "synthetic.csv", "source_page_or_row": "2", "classification_status": status, "source_locations": "synthetic.csv:2"})
                atomic_write_csv(ledger / "work" / "normalized-transactions.csv", CANONICAL_TRANSACTION_FIELDS, (row,))
                result = subprocess.run([sys.executable, str(SKILL_ROOT / "scripts" / "validate_ledger.py"), str(ledger)], capture_output=True, text=True)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("blocked", json.loads(result.stdout)["state"])

    def test_exception_sources_are_opaque(self) -> None:
        """Catches caller supplied account, filename, or location text escaping exceptions.csv."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
            finalize_outputs(ledger, has_transactions=False, pending_group_count=0, reconciliation_rows=(), issues=(Issue("PDF_PAGE_EMPTY", "checking-001 123456", True, "statement-123456.pdf", "checking-001:page 2"),))
            text = (ledger / "outputs" / "exceptions.csv").read_text(encoding="utf-8")
            for secret in ("checking-001", "123456", "statement-123456.pdf", "page 2"):
                self.assertNotIn(secret, text)

    def test_active_import_issue_blocks_final_status_until_the_same_source_succeeds(self) -> None:
        """Catches an import failure being forgotten before final ledger validation."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
            (ledger / "work" / "mapping.json").write_text(json.dumps({
                "transaction_date": "Date", "description": "Description", "debit": "Debit", "credit": "Credit", "balance": "Balance", "reference": "Reference",
            }), encoding="utf-8")
            (ledger / "work" / "account.json").write_text(json.dumps({
                "account_id": "checking", "institution": "Synthetic", "masked_label": "********9012", "currency": "CAD",
            }), encoding="utf-8")
            statement = ledger / "inputs" / "statement.csv"
            statement.write_text("Date,Description,Debit,Balance,Reference\n2026-01-03,Synthetic,0,110,ref\n", encoding="utf-8")
            failed = subprocess.run([sys.executable, str(SKILL_ROOT / "scripts" / "import_statements.py"), "csv", str(ledger), "inputs/statement.csv", "--mapping", "work/mapping.json", "--account", "work/account.json"], capture_output=True, text=True)
            blocked = subprocess.run([sys.executable, str(SKILL_ROOT / "scripts" / "validate_ledger.py"), str(ledger)], capture_output=True, text=True)
            statement.write_text("Date,Description,Debit,Credit,Balance,Reference\n2026-01-03,Synthetic,0,10,110,ref\n", encoding="utf-8")
            succeeded = subprocess.run([sys.executable, str(SKILL_ROOT / "scripts" / "import_statements.py"), "csv", str(ledger), "inputs/statement.csv", "--mapping", "work/mapping.json", "--account", "work/account.json"], capture_output=True, text=True)
            cleared = subprocess.run([sys.executable, str(SKILL_ROOT / "scripts" / "validate_ledger.py"), str(ledger)], capture_output=True, text=True)
            self.assertEqual(2, failed.returncode)
            self.assertEqual("blocked", json.loads(blocked.stdout)["state"])
            self.assertEqual(0, succeeded.returncode, succeeded.stderr)
            self.assertNotEqual("blocked", json.loads(cleared.stdout)["state"])


if __name__ == "__main__":
    unittest.main()
