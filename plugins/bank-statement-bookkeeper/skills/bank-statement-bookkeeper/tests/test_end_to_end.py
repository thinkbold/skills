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
            confirmed = self.run_script(
                "classify_transactions.py", "confirm", str(ledger), groups[0]["group_id"],
                "--account-code", "6100", "--account-name", "Membership Fee",
                "--apply-future", "--actor", "user",
            )
            self.assertEqual(0, confirmed.returncode, confirmed.stderr)
            self.assertEqual(0, self.run_script("reconcile_accounts.py", str(ledger)).returncode)
            status = json.loads(self.run_script("validate_ledger.py", str(ledger)).stdout)
            self.assertEqual("complete", status["state"])
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

            later_rows = (ledger / "work" / "normalized-transactions.csv").read_bytes()
            self.assertEqual(0, import_later_fixture(self, ledger).returncode)
            self.assertEqual(later_rows, (ledger / "work" / "normalized-transactions.csv").read_bytes())
            self.assertEqual(first_audit, (ledger / "audit" / "audit.jsonl").read_bytes()[:len(first_audit)])
            self.assertNotEqual(first_hashes["outputs/status.json"], _bundle_hashes(ledger)["outputs/status.json"])

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
        self.assertEqual(1, len(validation_events))
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
            "work/import-manifest.json",
        )
    }


if __name__ == "__main__":
    unittest.main()
