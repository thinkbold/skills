from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
FIXTURE = Path(__file__).parent / "fixtures" / "end-to-end"
_EVIDENCE_FIELDS = (
    "account_id", "currency", "transaction_date", "posting_date", "raw_description",
    "inflow", "outflow", "running_balance", "reference", "source_file",
    "source_page_or_row", "extraction_method", "extraction_confidence", "source_locations",
)
_INITIAL_EVIDENCE_BY_TRANSACTION_ID = {
    "457148970687a84487f6e0090863acfeb6a0957af982dff9e8b03a7044950fcd": {
        "account_id": "card-usd-002",
        "currency": "USD",
        "transaction_date": "2026-01-06",
        "posting_date": "2026-01-06",
        "raw_description": "OPENAI *CHATGPT SUBSCRIPTION 7H4K9",
        "inflow": "0",
        "outflow": "30.00",
        "running_balance": "170.00",
        "reference": "AI-USD-01",
        "source_file": "inputs/usd-january.csv",
        "source_page_or_row": "2",
        "extraction_method": "csv",
        "extraction_confidence": "high",
        "source_locations": "inputs/usd-january.csv:2",
    },
    "4a617d801eefa5e5fcf2de4b23fa2334153bdf5027c652492d0bda8dc128519b": {
        "account_id": "checking-cad-001",
        "currency": "CAD",
        "transaction_date": "2026-01-06",
        "posting_date": "2026-01-06",
        "raw_description": "OPENAI *CHATGPT SUBSCRIPTION 9F3A2",
        "inflow": "0",
        "outflow": "20.00",
        "running_balance": "80.00",
        "reference": "AI-CAD-01",
        "source_file": "inputs/cad-january.csv",
        "source_page_or_row": "2",
        "extraction_method": "csv",
        "extraction_confidence": "high",
        "source_locations": "inputs/cad-january.csv:2|inputs/cad-overlap.csv:2",
    },
    "25db7937074e7fad8dbec34409ade7ebfbea0301dcc2181b9e29496ca5651ae9": {
        "account_id": "checking-cad-001",
        "currency": "CAD",
        "transaction_date": "2026-01-08",
        "posting_date": "2026-01-08",
        "raw_description": "OPENAI *CHATGPT SUBSCRIPTION 7H4K9",
        "inflow": "0",
        "outflow": "5.00",
        "running_balance": "70.00",
        "reference": "AI-REPEAT-01",
        "source_file": "inputs/cad-overlap.csv",
        "source_page_or_row": "4",
        "extraction_method": "csv",
        "extraction_confidence": "high",
        "source_locations": "inputs/cad-overlap.csv:4",
    },
    "b33a7d128dcb8c257e14d81fd174eba40b0bda5bc0206fd0ae5f7f2271e95669": {
        "account_id": "checking-cad-001",
        "currency": "CAD",
        "transaction_date": "2026-01-08",
        "posting_date": "2026-01-08",
        "raw_description": "OPENAI *CHATGPT SUBSCRIPTION 7H4K9",
        "inflow": "0",
        "outflow": "5.00",
        "running_balance": "75.00",
        "reference": "AI-REPEAT-01",
        "source_file": "inputs/cad-overlap.csv",
        "source_page_or_row": "3",
        "extraction_method": "csv",
        "extraction_confidence": "high",
        "source_locations": "inputs/cad-overlap.csv:3",
    },
}


class EndToEndTests(unittest.TestCase):
    def run_script(self, name: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / name), *arguments],
            check=False, capture_output=True, text=True,
        )

    def test_two_accounts_two_currencies_learn_and_reuse_rule(self) -> None:
        """Catches non-atomic final output or a rule that fails to classify a later exact import."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "acme"
            initialized = self.run_script(
                "init_ledger.py", str(ledger), "--ledger-id", "acme-2026",
                "--company-name", "Acme Synthetic Inc.", "--base-currency", "CAD",
            )
            self.assertEqual(0, initialized.returncode, initialized.stderr)
            install_fixture_inputs(FIXTURE, ledger)
            self.assertEqual(0, import_all_fixture_statements(self, ledger).returncode)
            pending = json.loads(
                self.run_script("classify_transactions.py", "pending", str(ledger)).stdout
            )
            groups = [g for g in pending["groups"] if g["normalized_merchant"] == "OPENAI CHATGPT SUBSCRIPTION"]
            self.assertEqual(1, len(groups))
            self.assertEqual(["card-usd-002", "checking-cad-001"], groups[0]["account_ids"])
            self.assertEqual(["CAD", "USD"], groups[0]["currencies"])
            self.assertEqual([["CAD", "30.00"], ["USD", "30.00"]], groups[0]["totals_by_currency"])
            self.assertNotIn("total", groups[0])
            initial_rows = read_classified_rows(ledger)
            self.assertEqual(len(_INITIAL_EVIDENCE_BY_TRANSACTION_ID), len(initial_rows))
            self.assertEqual(len(initial_rows), len({row["transaction_id"] for row in initial_rows}))
            initial_evidence = {
                row["transaction_id"]: {field: row[field] for field in _EVIDENCE_FIELDS}
                for row in initial_rows
            }
            self.assertEqual(_INITIAL_EVIDENCE_BY_TRANSACTION_ID, initial_evidence)
            confirmed = self.run_script(
                "classify_transactions.py", "confirm", str(ledger), groups[0]["group_id"],
                "--account-code", "6100", "--account-name", "Membership Fee",
                "--apply-future", "--actor", "user",
            )
            self.assertEqual(0, confirmed.returncode, confirmed.stderr)
            self.assertEqual(0, self.run_script("reconcile_accounts.py", str(ledger)).returncode)
            status = json.loads(self.run_script("validate_ledger.py", str(ledger)).stdout)
            self.assertEqual("complete", status["state"])
            with (ledger / "outputs" / "reconciliation.csv").open(newline="", encoding="utf-8") as handle:
                reconciliations = list(csv.DictReader(handle))
            self.assertEqual(3, len(reconciliations))
            self.assertEqual(sorted([("CAD", "2025-12-31", "statement_opening", "100.00", "100.00", "0.00", "true"), ("CAD", "2026-01-01", "prior_year_end_statement", "100.00", "70.00", "0.00", "true"), ("USD", "2026-01-01", "statement_opening", "200.00", "170.00", "0.00", "true")]), sorted((row["currency"], row["period_start"], row["opening_source_type"], row["opening_balance"], row["reported_closing"], row["difference"], row["reconciled"]) for row in reconciliations))
            cad_current = next(row for row in reconciliations if row["currency"] == "CAD" and row["period_start"] == "2026-01-01")
            self.assertEqual("prior_year_end_statement", cad_current["opening_source_type"])
            self._assert_output_bundle(ledger, status)
            first_hashes = _bundle_hashes(ledger)
            first_audit = (ledger / "audit" / "audit.jsonl").read_bytes()
            repeated_status = json.loads(self.run_script("validate_ledger.py", str(ledger)).stdout)
            self.assertEqual(status, repeated_status)
            self.assertEqual(first_audit, (ledger / "audit" / "audit.jsonl").read_bytes())
            self.assertEqual(first_hashes, _bundle_hashes(ledger))

            import_later_fixture(self, ledger)
            later = read_classified_rows(ledger)
            exact = [r for r in later if r["normalized_merchant"] == "OPENAI CHATGPT SUBSCRIPTION"]
            fuzzy = [r for r in later if r["normalized_merchant"] == "OPENAL CHATGPT SUBSCRIPTION"]
            self.assertEqual({"classified"}, {r["classification_status"] for r in exact})
            self.assertEqual({"unclassified"}, {r["classification_status"] for r in fuzzy})
            self.assertEqual({"CAD", "USD"}, {r["currency"] for r in later})
            self.assertEqual(6, len(later))

            self.assertEqual(1, len(read_rules(ledger)))
            self.assertEqual(1, len([line for line in (ledger / "audit" / "audit.jsonl").read_text(encoding="utf-8").splitlines() if 'merchant_group_confirmed' in line]))

            self.assertEqual(0, self.run_script("validate_ledger.py", str(ledger)).returncode)
            later_snapshot = _bundle_hashes(ledger)
            later_rows = (ledger / "work" / "normalized-transactions.csv").read_bytes()
            later_audit = (ledger / "audit" / "audit.jsonl").read_bytes()
            later_rules = (ledger / "merchant-rules.csv").read_bytes()
            later_manifest = (ledger / "work" / "import-manifest.json").read_bytes()
            later_ids = [row["transaction_id"] for row in later]
            self.assertEqual(0, import_later_fixture(self, ledger).returncode)
            repeated_later_status = json.loads(self.run_script("validate_ledger.py", str(ledger)).stdout)
            self.assertEqual(later_rows, (ledger / "work" / "normalized-transactions.csv").read_bytes())
            self.assertEqual(later_snapshot, _bundle_hashes(ledger))
            self.assertEqual(later_audit, (ledger / "audit" / "audit.jsonl").read_bytes())
            self.assertEqual(later_rules, (ledger / "merchant-rules.csv").read_bytes())
            self.assertEqual(later_manifest, (ledger / "work" / "import-manifest.json").read_bytes())
            self.assertEqual(later_ids, [row["transaction_id"] for row in read_classified_rows(ledger)])
            self._assert_output_bundle(ledger, repeated_later_status)

            other = Path(temp) / "other"
            self.assertEqual(0, self.run_script("init_ledger.py", str(other), "--ledger-id", "other", "--company-name", "Other", "--base-currency", "CAD").returncode)
            install_fixture_inputs(FIXTURE, other)
            self.assertEqual(0, _import_phase(self, other, "initial").returncode)
            self.assertEqual([], read_rules(other))
            self.assertTrue(any(row["normalized_merchant"] == "OPENAI CHATGPT SUBSCRIPTION" and row["classification_status"] == "unclassified" for row in read_classified_rows(other)))

    def _assert_output_bundle(self, ledger: Path, status: dict[str, object]) -> None:
        paths = (
            "outputs/normalized-transactions.csv", "outputs/classified-transactions.csv",
            "outputs/account-summary.csv", "outputs/reconciliation.csv",
            "outputs/reconciliation-report.md", "outputs/exceptions.csv", "outputs/status.json",
            "work/import-manifest.json", "work/pending-merchant-groups.csv", "audit/audit.jsonl",
        )
        for relative in paths:
            self.assertTrue((ledger / relative).is_file(), relative)
        hashes = status["output_hashes"]
        self.assertNotIn("outputs/status.json", hashes)
        self.assertEqual(set(paths) - {"outputs/status.json"}, set(hashes))
        for relative, digest in hashes.items():
            self.assertEqual(_sha256(ledger / relative), digest)
        validation_events = [json.loads(line) for line in (ledger / "audit" / "audit.jsonl").read_text(encoding="utf-8").splitlines() if 'validation_completed' in line]
        self.assertIn(len(validation_events), {1, 2})
        self.assertIn("output_hashes", validation_events[0]["payload"])
        self.assertNotIn("statement", json.dumps(validation_events[0], sort_keys=True).lower())


def install_fixture_inputs(source: Path, ledger: Path) -> None:
    shutil.copytree(source / "ledger-overlay", ledger, dirs_exist_ok=True)


def _import_phase(
    case: EndToEndTests,
    ledger: Path,
    phase: str,
) -> subprocess.CompletedProcess[str]:
    jobs = json.loads((ledger / "work" / "import-jobs.json").read_text(encoding="utf-8"))
    selected = [job for job in jobs if job["phase"] == phase]
    if not selected:
        raise AssertionError(f"no fixture import jobs for phase {phase}")
    last_result: subprocess.CompletedProcess[str] | None = None
    for job in selected:
        last_result = case.run_script(
            "import_statements.py", job["kind"], str(ledger),
            str(ledger / job["statement"]), "--mapping", job["mapping"],
            "--account", job["account"],
        )
        case.assertEqual(0, last_result.returncode, last_result.stderr)
    if last_result is None:
        raise AssertionError("fixture import loop did not execute")
    return last_result


def import_all_fixture_statements(
    case: EndToEndTests,
    ledger: Path,
) -> subprocess.CompletedProcess[str]:
    return _import_phase(case, ledger, "initial")


def import_later_fixture(
    case: EndToEndTests,
    ledger: Path,
) -> subprocess.CompletedProcess[str]:
    return _import_phase(case, ledger, "later")


def read_classified_rows(ledger: Path) -> list[dict[str, str]]:
    with (ledger / "outputs" / "classified-transactions.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        return list(csv.DictReader(handle))


def read_rules(ledger: Path) -> list[dict[str, str]]:
    with (ledger / "merchant-rules.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle_hashes(ledger: Path) -> dict[str, str]:
    return {
        relative: _sha256(ledger / relative)
        for relative in (
            "outputs/normalized-transactions.csv", "outputs/classified-transactions.csv",
            "outputs/account-summary.csv", "outputs/reconciliation.csv",
            "outputs/reconciliation-report.md", "outputs/exceptions.csv", "outputs/status.json",
            "work/import-manifest.json", "work/pending-merchant-groups.csv", "merchant-rules.csv", "audit/audit.jsonl",
        )
    }


if __name__ == "__main__":
    unittest.main()
