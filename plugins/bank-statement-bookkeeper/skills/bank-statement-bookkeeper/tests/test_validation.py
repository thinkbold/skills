from __future__ import annotations

from collections.abc import Callable
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
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
from bookkeeper.storage import atomic_write_csv, replace_active_issues
from bookkeeper.reconciliation import reconcile_account_period
from bookkeeper.validation import _masked_message, collect_ledger_issues, determine_run_state, finalize_outputs, publish_derived_outputs


_DERIVED_TARGETS = (
    "outputs/account-summary.csv",
    "outputs/classified-transactions.csv",
    "outputs/exceptions.csv",
    "outputs/normalized-transactions.csv",
    "outputs/reconciliation-report.md",
    "outputs/reconciliation.csv",
    "work/pending-merchant-groups.csv",
    "outputs/status.json",
)
_GENERATION_INPUTS = (
    "work/normalized-transactions.csv",
    "merchant-rules.csv",
    "work/active-issues.json",
    "inputs/account-balances.csv",
    "ledger.json",
    "work/import-manifest.json",
    "audit/audit.jsonl",
)


def _valid_transaction(
    *,
    transaction_id: str = "synthetic-1",
    raw_description: str = "Synthetic merchant",
) -> dict[str, str]:
    row = {field: "" for field in CANONICAL_TRANSACTION_FIELDS}
    row.update({
        "transaction_id": transaction_id,
        "account_id": "checking-001",
        "currency": "CAD",
        "transaction_date": "2026-01-03",
        "posting_date": "2026-01-03",
        "raw_description": raw_description,
        "inflow": "10.00",
        "outflow": "0",
        "running_balance": "110.00",
        "reference": "synthetic-reference",
        "source_file": "inputs/synthetic.csv",
        "source_page_or_row": "2",
        "extraction_method": "csv",
        "extraction_confidence": "high",
        "classification_status": "unclassified",
        "source_locations": "inputs/synthetic.csv:2",
    })
    return row


def _valid_balance() -> dict[str, str]:
    row = {field: "" for field in BALANCE_FIELDS}
    row.update({
        "account_id": "checking-001",
        "currency": "CAD",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "opening_balance": "100.00",
        "closing_balance": "110.00",
        "opening_source_type": "user_provided",
        "opening_source_file": "inputs/synthetic-balance.txt",
        "opening_source_location": "1",
        "closing_source_file": "inputs/synthetic.csv",
        "closing_source_location": "3",
        "confirmed": "true",
    })
    return row


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _stage_current_generation(ledger: Path, mutate: Callable[[Path], None]) -> None:
    stage = ledger / "work" / "pending-derived-output-stage"
    stage.mkdir()
    marker = "a" * 64
    (stage / ".protocol-marker").write_text(marker + "\n", encoding="ascii")
    for relative in _DERIVED_TARGETS:
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ledger / relative, target)
    mutate(stage)

    status_path = stage / "outputs" / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["output_hashes"] = {
        relative: _sha256(stage / relative)
        for relative in _DERIVED_TARGETS
        if relative != "outputs/status.json"
    }
    for relative in ("work/import-manifest.json", "audit/audit.jsonl"):
        path = ledger / relative
        if path.exists():
            status["output_hashes"][relative] = _sha256(path)
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    generation = {
        relative: _sha256(ledger / relative) if (ledger / relative).exists() else "absent"
        for relative in _GENERATION_INPUTS
    }
    targets = [
        {"relative": relative, "sha256": _sha256(stage / relative)}
        for relative in _DERIVED_TARGETS
    ]
    (ledger / "work" / "pending-derived-output.json").write_text(
        json.dumps({"generation": generation, "marker": marker, "targets": targets, "version": 3}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
            self.assertNotIn("********9012", exceptions)
            self.assertIn("account-", exceptions)

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
        orphaned = {**malformed, "transaction_id": "orphaned", "currency": "CAD", "raw_description": "!!!", "inflow": "10", "source_locations": "synthetic.csv:2", "extraction_method": "csv", "extraction_confidence": "high"}
        from bookkeeper.validation import count_pending_classifications, validate_canonical_transactions
        self.assertIn("CURRENCY_MISSING", {issue.code for issue in validate_canonical_transactions((malformed,))})
        self.assertEqual(1, count_pending_classifications((orphaned,)))

    def test_public_validation_keeps_ungroupable_unclassified_row_pending(self) -> None:
        """Catches a valid unclassified row being rejected because punctuation yields no merchant group."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
            save_transactions(ledger, (_valid_transaction(raw_description="!!!"),))

            result = subprocess.run(
                [sys.executable, str(SKILL_ROOT / "scripts" / "validate_ledger.py"), str(ledger)],
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            status = json.loads(result.stdout)
            self.assertEqual("classification_pending", status["state"])
            self.assertEqual(1, status["pending_group_count"])
            self.assertEqual([], _read_csv(ledger / "work" / "pending-merchant-groups.csv"))

    def test_current_generation_cannot_claim_an_empty_ledger_is_complete(self) -> None:
        """Catches recovery trusting a self-consistent status/report instead of recomputing run state."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
            publish_derived_outputs(ledger)

            def claim_complete(stage: Path) -> None:
                status_path = stage / "outputs" / "status.json"
                status = json.loads(status_path.read_text(encoding="utf-8"))
                status["state"] = "complete"
                status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                (stage / "outputs" / "reconciliation-report.md").write_text(
                    "Run state: complete\n",
                    encoding="utf-8",
                )

            _stage_current_generation(ledger, claim_complete)
            result = subprocess.run(
                [sys.executable, str(SKILL_ROOT / "scripts" / "validate_ledger.py"), str(ledger)],
                capture_output=True,
                text=True,
            )

            self.assertEqual(3, result.returncode)
            self.assertEqual({"error": "LEDGER_SCHEMA_INVALID"}, json.loads(result.stdout))

    def test_current_generation_binds_classified_rows_to_normalized_evidence(self) -> None:
        """Catches a classified view changing immutable provenance while retaining the same ID."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
            save_transactions(ledger, (_valid_transaction(),))
            publish_derived_outputs(ledger)

            def substitute_provenance(stage: Path) -> None:
                path = stage / "outputs" / "classified-transactions.csv"
                row = _read_csv(path)[0]
                row["source_locations"] = "inputs/substituted.csv:99"
                atomic_write_csv(path, CANONICAL_TRANSACTION_FIELDS, (row,))

            _stage_current_generation(ledger, substitute_provenance)
            result = subprocess.run(
                [sys.executable, str(SKILL_ROOT / "scripts" / "validate_ledger.py"), str(ledger)],
                capture_output=True,
                text=True,
            )

            self.assertEqual(3, result.returncode)
            self.assertEqual({"error": "LEDGER_SCHEMA_INVALID"}, json.loads(result.stdout))

    def test_current_generation_binds_both_transaction_views_to_authoritative_provenance(self) -> None:
        """Catches synchronized provenance substitution across normalized and classified artifacts."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
            save_transactions(ledger, (_valid_transaction(),))
            publish_derived_outputs(ledger)

            def substitute_both_views(stage: Path) -> None:
                for relative in (
                    "outputs/normalized-transactions.csv",
                    "outputs/classified-transactions.csv",
                ):
                    path = stage / relative
                    row = _read_csv(path)[0]
                    row["source_locations"] = "inputs/substituted.csv:99"
                    atomic_write_csv(path, CANONICAL_TRANSACTION_FIELDS, (row,))

            _stage_current_generation(ledger, substitute_both_views)
            result = subprocess.run(
                [sys.executable, str(SKILL_ROOT / "scripts" / "validate_ledger.py"), str(ledger)],
                capture_output=True,
                text=True,
            )

            self.assertEqual(3, result.returncode)
            self.assertEqual({"error": "LEDGER_SCHEMA_INVALID"}, json.loads(result.stdout))

    def test_current_generation_cannot_fabricate_reconciled_complete_artifacts(self) -> None:
        """Catches internally consistent reconciliation artifacts replacing missing balance evidence."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
            row = _valid_transaction()
            row.update({
                "classification_status": "classified",
                "normalized_merchant": "SYNTHETIC MERCHANT",
                "account_name": "Synthetic category",
            })
            save_transactions(ledger, (row,))
            publish_derived_outputs(ledger)

            def fabricate_complete(stage: Path) -> None:
                reconciliation_path = stage / "outputs" / "reconciliation.csv"
                reconciliation = _read_csv(reconciliation_path)[0]
                reconciliation.update({
                    "opening_source_type": "user_provided",
                    "opening_source_date": "2026-01-01",
                    "opening_balance": "100.00",
                    "inflows": "10.00",
                    "outflows": "0",
                    "expected_closing": "110.00",
                    "reported_closing": "110.00",
                    "difference": "0.00",
                    "tolerance": "",
                    "reconciled": "true",
                    "issue_codes": "",
                })
                atomic_write_csv(reconciliation_path, tuple(reconciliation), (reconciliation,))
                summary_path = stage / "outputs" / "account-summary.csv"
                summary = _read_csv(summary_path)[0]
                summary.update({"reconciled_period_count": "1", "state": "complete"})
                atomic_write_csv(summary_path, tuple(summary), (summary,))
                atomic_write_csv(
                    stage / "outputs" / "exceptions.csv",
                    ("code", "blocking", "message", "source_file", "source_location"),
                    (),
                )
                (stage / "outputs" / "reconciliation-report.md").write_text(
                    "Run state: complete\n",
                    encoding="utf-8",
                )
                status_path = stage / "outputs" / "status.json"
                status = json.loads(status_path.read_text(encoding="utf-8"))
                status.update({
                    "blocking_issue_count": 0,
                    "reconciled_unit_count": 1,
                    "state": "complete",
                    "unit_count": 1,
                })
                status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            _stage_current_generation(ledger, fabricate_complete)
            result = subprocess.run(
                [sys.executable, str(SKILL_ROOT / "scripts" / "validate_ledger.py"), str(ledger)],
                capture_output=True,
                text=True,
            )

            self.assertEqual(3, result.returncode)
            self.assertEqual({"error": "LEDGER_SCHEMA_INVALID"}, json.loads(result.stdout))

    def test_current_generation_cannot_demote_an_authoritative_blocking_issue(self) -> None:
        """Catches a staged exception changing a production blocking issue to nonblocking."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
            row = _valid_transaction()
            row.update({
                "classification_status": "classified",
                "normalized_merchant": "SYNTHETIC MERCHANT",
                "account_name": "Synthetic category",
            })
            save_transactions(ledger, (row,))
            atomic_write_csv(
                ledger / "inputs" / "account-balances.csv",
                BALANCE_FIELDS,
                (_valid_balance(),),
            )
            replace_active_issues(
                ledger,
                "import",
                {"source": "synthetic"},
                (Issue("CURRENCY_MISSING", "Synthetic currency is missing.", True),),
            )
            publish_derived_outputs(ledger)

            def demote_blocker(stage: Path) -> None:
                exceptions_path = stage / "outputs" / "exceptions.csv"
                exceptions = _read_csv(exceptions_path)
                for exception in exceptions:
                    if exception["code"] == "CURRENCY_MISSING":
                        exception["blocking"] = "false"
                atomic_write_csv(exceptions_path, tuple(exceptions[0]), exceptions)
                summary_path = stage / "outputs" / "account-summary.csv"
                summary = _read_csv(summary_path)[0]
                summary["state"] = "complete"
                atomic_write_csv(summary_path, tuple(summary), (summary,))
                (stage / "outputs" / "reconciliation-report.md").write_text(
                    "Run state: complete\n",
                    encoding="utf-8",
                )
                status_path = stage / "outputs" / "status.json"
                status = json.loads(status_path.read_text(encoding="utf-8"))
                status.update({"blocking_issue_count": 0, "state": "complete"})
                status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            _stage_current_generation(ledger, demote_blocker)
            result = subprocess.run(
                [sys.executable, str(SKILL_ROOT / "scripts" / "validate_ledger.py"), str(ledger)],
                capture_output=True,
                text=True,
            )

            self.assertEqual(3, result.returncode)
            self.assertEqual({"error": "LEDGER_SCHEMA_INVALID"}, json.loads(result.stdout))

    def test_current_generation_rejects_duplicate_group_currency(self) -> None:
        """Catches a group repeating a currency while preserving superficial counts and finite totals."""
        self._assert_malicious_group_rejected(
            currencies="CAD|CAD",
            totals_by_currency="CAD:10.00|CAD:10.00",
        )

    def test_current_generation_rejects_group_total_not_derived_from_transactions(self) -> None:
        """Catches a group claiming a finite but incorrect currency total."""
        self._assert_malicious_group_rejected(
            currencies="CAD",
            totals_by_currency="CAD:999.00",
        )

    def _assert_malicious_group_rejected(self, *, currencies: str, totals_by_currency: str) -> None:
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
            save_transactions(ledger, (_valid_transaction(),))
            publish_derived_outputs(ledger)

            def mutate_group(stage: Path) -> None:
                path = stage / "work" / "pending-merchant-groups.csv"
                row = _read_csv(path)[0]
                row["currencies"] = currencies
                row["totals_by_currency"] = totals_by_currency
                atomic_write_csv(path, tuple(row), (row,))

            _stage_current_generation(ledger, mutate_group)
            result = subprocess.run(
                [sys.executable, str(SKILL_ROOT / "scripts" / "validate_ledger.py"), str(ledger)],
                capture_output=True,
                text=True,
            )

            self.assertEqual(3, result.returncode)
            self.assertEqual({"error": "LEDGER_SCHEMA_INVALID"}, json.loads(result.stdout))

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

    def test_final_cli_blocks_blank_provenance_and_duplicate_ids_without_schema_shortcut(self) -> None:
        """Catches invalid rows reaching exact rules or bypassing blocked status output."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
            base = {field: "" for field in CANONICAL_TRANSACTION_FIELDS}
            base.update({"transaction_id": "duplicate", "account_id": "checking", "currency": "CAD", "transaction_date": "2026-01-03", "posting_date": "2026-01-03", "raw_description": "Synthetic", "inflow": "10", "outflow": "0", "running_balance": "10", "source_file": "synthetic.csv", "source_page_or_row": "2", "source_locations": "synthetic.csv:2", "extraction_method": "csv", "extraction_confidence": "high", "classification_status": "unclassified"})
            blank = {**base, "transaction_id": "blank-provenance", "source_locations": "", "extraction_method": "", "extraction_confidence": ""}
            atomic_write_csv(ledger / "work" / "normalized-transactions.csv", CANONICAL_TRANSACTION_FIELDS, (base, {**base, "raw_description": "Other"}, blank))
            result = subprocess.run([sys.executable, str(SKILL_ROOT / "scripts" / "validate_ledger.py"), str(ledger)], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("blocked", json.loads(result.stdout)["state"])
            self.assertTrue((ledger / "outputs" / "exceptions.csv").is_file())

    def test_exception_labels_are_opaque_even_when_caller_supplies_raw_label(self) -> None:
        """Catches untrusted account-label values being copied into exception output."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
            finalize_outputs(
                ledger,
                has_transactions=False,
                pending_group_count=0,
                reconciliation_rows=(),
                issues=(Issue(
                    "PDF_PAGE_EMPTY",
                    "checking-001 checking savings-002 123456789012 empty-label-account failed",
                    True,
                ),),
                account_labels={
                    "checking": "checking-001",
                    "savings-002": "123456789012",
                    "empty-label-account": "",
                },
            )
            text = (ledger / "outputs" / "exceptions.csv").read_text(encoding="utf-8")
            for secret in ("checking-001", "checking", "savings-002", "123456789012", "empty-label-account"):
                self.assertNotIn(secret, text)
            for token in (
                "account-490153303548", "account-7f98506ac726", "account-03a60ad81238",
                "account-2a33349e7e60", "account-7bc48469cced",
            ):
                self.assertIn(token, text)

    def test_masked_message_replaces_keys_and_values_without_overlap_or_empty_leaks(self) -> None:
        """Catches raw labels, partial overlap replacement, or empty-label expansion."""
        cases = (
            ("123456789012 failed", {"checking-001": "123456789012"}, "account-2a33349e7e60 failed"),
            ("checking-001 failed", {"checking-001": "123456789012"}, "account-490153303548 failed"),
            (
                "checking-001 checking failed",
                {"checking": "checking-001"},
                "account-490153303548 account-7f98506ac726 failed",
            ),
            ("empty-label-account failed", {"empty-label-account": ""}, "account-7bc48469cced failed"),
        )
        for message, labels, expected in cases:
            with self.subTest(message=message, labels=labels):
                self.assertEqual(expected, _masked_message(message, labels))

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
            self.assertEqual(0, failed.returncode)
            self.assertEqual("blocked", json.loads(blocked.stdout)["state"])
            self.assertEqual(0, succeeded.returncode, succeeded.stderr)
            self.assertNotEqual("blocked", json.loads(cleared.stdout)["state"])

    def test_derived_stage_symlink_is_rejected_without_deleting_outputs(self) -> None:
        """Catches recovery cleaning a resolved symlink target outside its freshly-made protocol directory."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
            status = ledger / "outputs" / "status.json"
            status.write_text('{"sentinel":true}\n', encoding="utf-8")
            (ledger / "work" / "pending-derived-output-stage").symlink_to(ledger / "outputs", target_is_directory=True)
            (ledger / "work" / "pending-derived-output.json").write_text(json.dumps({
                "marker": "0" * 64, "targets": [], "version": 2,
            }), encoding="utf-8")
            result = subprocess.run([sys.executable, str(SKILL_ROOT / "scripts" / "validate_ledger.py"), str(ledger)], capture_output=True, text=True)
            self.assertEqual(3, result.returncode)
            self.assertEqual("LEDGER_SCHEMA_INVALID", json.loads(result.stdout)["error"])
            self.assertEqual('{"sentinel":true}\n', status.read_text(encoding="utf-8"))

    def test_classify_empty_directory_does_not_create_ledger_files(self) -> None:
        """Catches classification recovery or views creating work files before ledger validation."""
        with TemporaryDirectory() as temp:
            empty = Path(temp) / "empty"
            empty.mkdir()
            result = subprocess.run([sys.executable, str(SKILL_ROOT / "scripts" / "classify_transactions.py"), "pending", str(empty)], capture_output=True, text=True)
            self.assertEqual(3, result.returncode)
            self.assertEqual({"error": "LEDGER_SCHEMA_INVALID"}, json.loads(result.stdout))
            self.assertEqual([], list(empty.iterdir()))

    def test_public_commands_reject_a_selected_ledger_symlink_without_mutation(self) -> None:
        """Catches resolving a caller-selected ledger symlink before its lexical lstat gate."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            selected = Path(temp) / "selected-ledger"
            initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
            selected.symlink_to(ledger, target_is_directory=True)
            before = {path.relative_to(ledger).as_posix(): path.read_bytes() for path in ledger.rglob("*") if path.is_file()}
            commands = (
                ("import_statements.py", "inventory", str(selected), "inputs/missing.csv"),
                ("classify_transactions.py", "pending", str(selected)),
                ("reconcile_accounts.py", str(selected)),
                ("validate_ledger.py", str(selected)),
                ("init_ledger.py", str(selected), "--ledger-id", "synthetic", "--company-name", "Synthetic", "--base-currency", "CAD"),
            )
            for command in commands:
                with self.subTest(command=command[0]):
                    result = subprocess.run([sys.executable, str(SKILL_ROOT / "scripts" / command[0]), *command[1:]], capture_output=True, text=True)
                    self.assertEqual(3, result.returncode)
                    self.assertEqual({"error": "LEDGER_SCHEMA_INVALID"}, json.loads(result.stdout))
            after = {path.relative_to(ledger).as_posix(): path.read_bytes() for path in ledger.rglob("*") if path.is_file()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
