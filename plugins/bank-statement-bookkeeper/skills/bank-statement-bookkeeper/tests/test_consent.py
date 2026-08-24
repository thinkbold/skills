"""Consent gates for local admission of third-party extraction results."""

from contextlib import redirect_stdout
import csv
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from io import StringIO
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from bookkeeper.consent import (
    admit_external_result,
    create_external_proposal,
    find_valid_authorization,
    proposal_from_dict,
    proposal_to_dict,
    record_external_decision,
)
from bookkeeper.contracts import CANONICAL_TRANSACTION_FIELDS, AccountContext
from bookkeeper.ledger import initialize_ledger
from bookkeeper.storage import read_audit_events, read_csv_rows
import import_statements


FIXTURES = Path(__file__).parent / "fixtures"
SOURCE_HASH = "a" * 64
PROVIDER = "Synthetic OCR Provider"


class ConsentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.ledger = Path(self.directory.name) / "ledger"
        initialize_ledger(self.ledger, "acme", "Acme", "CAD", None)
        self.proposal = create_external_proposal(
            provider=PROVIDER,
            source_hash=SOURCE_HASH,
            pages=(2,),
            fields=("date", "description", "amount"),
            sensitive_data=("descriptions", "amounts"),
            purpose="Extract one unreadable statement page for local bookkeeping.",
            retention_risk="Provider retention is unknown.",
            training_risk="Provider training use is unknown.",
            regional_risk="Processing region is unknown.",
            human_access_risk="Provider human access is unknown.",
            subprocessor_access_risk="Provider subprocessor access is unknown.",
            redactions=("mask account header",),
            manual_alternative="Enter page 2 into a local CSV template.",
        )
        self.account = AccountContext("checking-001", "Synthetic Bank", "***1001", "CAD")
        self.account_path = self.ledger / "work" / "confirmed-account.json"
        self.account_path.write_text(json.dumps({
            "account_id": "checking-001", "institution": "Synthetic Bank",
            "masked_label": "***1001", "currency": "CAD",
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _authorize(self) -> str:
        return self._authorize_proposal(self.proposal)

    def _authorize_proposal(self, proposal) -> str:
        return record_external_decision(
            self.ledger, proposal, True, "user",
            now=datetime(2026, 8, 24, tzinfo=timezone.utc),
        )

    def _write_result(self, filename: str, changes: dict[str, str]) -> Path:
        with (FIXTURES / "external-result.csv").open("r", encoding="utf-8", newline="") as handle:
            row = next(csv.DictReader(handle))
        row.update(changes)
        path = self.ledger / "work" / filename
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CANONICAL_TRANSACTION_FIELDS)
            writer.writeheader()
            writer.writerow(row)
        return path

    def _run_external_result(self, result_path: Path, consent_id: str) -> tuple[int, dict[str, object]]:
        output = StringIO()
        with redirect_stdout(output):
            return_code = import_statements.main([
                "external-result", str(self.ledger), str(result_path), "--consent-id", consent_id,
                "--provider", PROVIDER, "--source-hash", SOURCE_HASH,
                "--account", str(self.account_path),
            ])
        return return_code, json.loads(output.getvalue())

    def _external_subprocess(
        self,
        result_path: Path,
        consent_id: str,
        account_path: Path | None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable, str(SKILL_ROOT / "scripts" / "import_statements.py"),
            "external-result", str(self.ledger), str(result_path), "--consent-id", consent_id,
            "--provider", PROVIDER, "--source-hash", SOURCE_HASH,
        ]
        if account_path is not None:
            command.extend(("--account", str(account_path)))
        return subprocess.run(command, capture_output=True, text=True)

    def _ledger_bytes(self) -> dict[str, bytes]:
        return {
            path.relative_to(self.ledger).as_posix(): path.read_bytes()
            for path in sorted(self.ledger.rglob("*"))
            if path.is_file()
        }

    def _import_authority_bytes(self) -> dict[str, bytes]:
        paths = (
            self.ledger / "audit" / "audit.jsonl",
            self.ledger / "merchant-rules.csv",
            self.ledger / "work" / "corrections.jsonl",
            self.ledger / "work" / "import-manifest.json",
            self.ledger / "work" / "normalized-transactions.csv",
        )
        result = {
            path.relative_to(self.ledger).as_posix(): path.read_bytes()
            for path in paths if path.is_file()
        }
        contributions = self.ledger / "work" / "import-contributions"
        if contributions.is_dir():
            result.update({
                path.relative_to(self.ledger).as_posix(): path.read_bytes()
                for path in sorted(contributions.rglob("*")) if path.is_file()
            })
        return result

    def test_full_statement_data_scope_admits_matching_local_result(self) -> None:
        """Catches blocking a canonical result authorized for every populated statement-data group."""
        consent_id = self._authorize()

        result = admit_external_result(
            self.ledger, consent_id, PROVIDER, SOURCE_HASH, self.account,
            FIXTURES / "external-result.csv",
        )

        self.assertEqual((), result.issues)
        self.assertEqual("third_party:Synthetic OCR Provider", result.transactions[0]["extraction_method"])
        self.assertTrue(find_valid_authorization(self.ledger, consent_id, self.proposal))

    def test_date_only_scope_rejects_a_full_canonical_result(self) -> None:
        """Catches date-only authorization silently admitting populated descriptions and amounts."""
        proposal = create_external_proposal(
            provider=PROVIDER, source_hash=SOURCE_HASH, pages=(2,), fields=("date",),
            sensitive_data=("dates",), purpose="Extract statement dates for bookkeeping.",
            retention_risk="Unknown.", training_risk="Unknown.", regional_risk="Unknown.",
            human_access_risk="Unknown.", subprocessor_access_risk="Unknown.",
            redactions=("mask account header",),
            manual_alternative="Enter the dates locally.",
        )
        consent_id = self._authorize_proposal(proposal)

        result = admit_external_result(
            self.ledger, consent_id, PROVIDER, SOURCE_HASH, self.account,
            FIXTURES / "external-result.csv",
        )

        self.assertEqual("EXTERNAL_SCOPE_MISMATCH", result.issues[0].code)

    def test_full_scope_rejects_a_result_missing_the_description_group(self) -> None:
        """Catches an authorized group being absent from a returned canonical row."""
        consent_id = self._authorize()
        result = admit_external_result(
            self.ledger, consent_id, PROVIDER, SOURCE_HASH, self.account,
            self._write_result("missing-description-group.csv", {"raw_description": "", "reference": ""}),
        )

        self.assertEqual("EXTERNAL_SCOPE_MISMATCH", result.issues[0].code)

    def test_result_rejects_a_populated_group_outside_current_authorization(self) -> None:
        """Catches a populated description group escaping date-and-amount authorization."""
        proposal = create_external_proposal(
            provider=PROVIDER, source_hash=SOURCE_HASH, pages=(2,), fields=("date", "amount"),
            sensitive_data=("dates", "amounts"), purpose="Extract statement dates and amounts for bookkeeping.",
            retention_risk="Unknown.", training_risk="Unknown.", regional_risk="Unknown.",
            human_access_risk="Unknown.", subprocessor_access_risk="Unknown.",
            redactions=("mask account header",),
            manual_alternative="Enter dates and amounts locally.",
        )
        consent_id = self._authorize_proposal(proposal)

        result = admit_external_result(
            self.ledger, consent_id, PROVIDER, SOURCE_HASH, self.account,
            FIXTURES / "external-result.csv",
        )

        self.assertEqual("EXTERNAL_SCOPE_MISMATCH", result.issues[0].code)

    def test_persisted_scope_edit_with_retained_operation_id_is_rejected(self) -> None:
        """Catches trusting a format-valid operation ID after its provider/source/page/field scope changes."""
        persisted = proposal_to_dict(self.proposal)
        persisted["provider"] = "Different OCR Provider"

        with self.assertRaisesRegex(ValueError, "operation_id"):
            proposal_from_dict(persisted)
        with self.assertRaisesRegex(ValueError, "operation_id"):
            record_external_decision(self.ledger, replace(self.proposal, pages=(3,)), True, "user")

    def test_persisted_risk_disclosure_edit_requires_a_new_operation_id(self) -> None:
        """Catches changing purpose or access risks while retaining the operation the user reviewed."""
        for field, changed in {
            "purpose": "A different external purpose.",
            "human_access_risk": "Human access is permitted.",
            "subprocessor_access_risk": "An undisclosed subprocessor may receive the data.",
        }.items():
            with self.subTest(field=field):
                persisted = proposal_to_dict(self.proposal)
                persisted[field] = changed
                with self.assertRaisesRegex(ValueError, "operation_id"):
                    proposal_from_dict(persisted)

    def test_proposal_requires_purpose_and_each_access_risk(self) -> None:
        """Catches an incomplete human-facing disclosure receiving an operation identity."""
        for field in ("purpose", "human_access_risk", "subprocessor_access_risk"):
            with self.subTest(field=field):
                persisted = proposal_to_dict(self.proposal)
                persisted.pop(field)
                with self.assertRaisesRegex(ValueError, field):
                    proposal_from_dict(persisted)

    def test_cli_rejects_a_persisted_scope_edit_with_retained_operation_id(self) -> None:
        """Catches record-consent appending an edited proposal file that retains an older operation ID."""
        proposal_path = self.ledger / "work" / "proposal.json"
        proposal_path.write_text(json.dumps({
            "provider": PROVIDER, "source_hash": SOURCE_HASH, "pages": [2],
            "fields": ["date", "description", "amount"], "sensitive_data": ["descriptions", "amounts"],
            "purpose": "Extract one unreadable statement page for local bookkeeping.",
            "retention_risk": "Provider retention is unknown.", "training_risk": "Provider training use is unknown.",
            "regional_risk": "Processing region is unknown.",
            "human_access_risk": "Provider human access is unknown.",
            "subprocessor_access_risk": "Provider subprocessor access is unknown.",
            "redactions": ["mask account header"],
            "manual_alternative": "Enter page 2 into a local CSV template.",
        }), encoding="utf-8")
        proposed_output = StringIO()
        with redirect_stdout(proposed_output):
            self.assertEqual(0, import_statements.main(["propose-external", str(self.ledger), "work/proposal.json"]))
        disclosure_digest = json.loads(proposed_output.getvalue())["disclosure_digest"]
        persisted = json.loads(proposal_path.read_text(encoding="utf-8"))
        persisted["pages"] = [3]
        proposal_path.write_text(json.dumps(persisted), encoding="utf-8")

        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(3, import_statements.main([
                "record-consent", str(self.ledger), "work/proposal.json", "--decision", "authorized", "--actor", "user",
                "--disclosure-digest", disclosure_digest,
            ]))

        self.assertEqual("LEDGER_SCHEMA_INVALID", json.loads(output.getvalue())["error"])
        self.assertEqual(1, len(read_audit_events(self.ledger)))

    def test_record_consent_rejects_a_digest_not_emitted_by_the_predecision_disclosure(self) -> None:
        """Catches auditing a decision that is not bound to the exact disclosure shown before the pause."""
        proposal_path = self.ledger / "work" / "proposal.json"
        proposal_path.write_text(json.dumps(proposal_to_dict(self.proposal)), encoding="utf-8")
        audit_before = (self.ledger / "audit" / "audit.jsonl").read_bytes()

        with self.assertRaisesRegex(ValueError, "disclosure digest"):
            import_statements._record_consent(self.ledger, SimpleNamespace(
                proposal="work/proposal.json", decision="authorized", actor="user",
                disclosure_digest="0" * 64,
            ))

        self.assertEqual(audit_before, (self.ledger / "audit" / "audit.jsonl").read_bytes())

    def test_declined_work_is_rejected_before_result_is_read(self) -> None:
        """Catches reading or accepting a result after the user declines its operation."""
        consent_id = record_external_decision(self.ledger, self.proposal, False, "user")

        result = admit_external_result(
            self.ledger, consent_id, PROVIDER, SOURCE_HASH, self.account,
            self.ledger / "inputs" / "does-not-exist.csv",
        )

        self.assertEqual("EXTERNAL_NOT_AUTHORIZED", result.issues[0].code)

    def test_invalid_account_context_is_rejected_before_result_is_read(self) -> None:
        """Catches direct admission opening returned bytes before validating confirmed account context."""
        consent_id = self._authorize()
        invalid = AccountContext("checking-001", "Synthetic Bank", "123456", "CAD")

        result = admit_external_result(
            self.ledger, consent_id, PROVIDER, SOURCE_HASH, invalid,
            self.ledger / "inputs" / "does-not-exist.csv",
        )

        self.assertEqual("ACCOUNT_UNCONFIRMED", result.issues[0].code)

    def test_provider_and_source_mismatches_are_rejected_before_result_is_read(self) -> None:
        """Catches an approval being reused for a different provider or statement source."""
        consent_id = self._authorize()

        provider_result = admit_external_result(
            self.ledger, consent_id, "Different OCR Provider", SOURCE_HASH, self.account,
            self.ledger / "inputs" / "missing.csv",
        )
        source_result = admit_external_result(
            self.ledger, consent_id, PROVIDER, "b" * 64, self.account,
            self.ledger / "inputs" / "missing.csv",
        )

        self.assertEqual("EXTERNAL_SCOPE_MISMATCH", provider_result.issues[0].code)
        self.assertEqual("EXTERNAL_SCOPE_MISMATCH", source_result.issues[0].code)

    def test_page_and_field_scope_mismatches_are_rejected(self) -> None:
        """Catches a consent for page 2/date-description-amount admitting another result shape."""
        consent_id = self._authorize()
        page_result = admit_external_result(
            self.ledger, consent_id, PROVIDER, SOURCE_HASH, self.account,
            FIXTURES / "external-result-page-3.csv",
        )
        fields_result = admit_external_result(
            self.ledger, consent_id, PROVIDER, SOURCE_HASH, self.account,
            FIXTURES / "external-result-missing-amount.csv",
        )

        self.assertEqual("EXTERNAL_SCOPE_MISMATCH", page_result.issues[0].code)
        self.assertEqual("EXTERNAL_SCOPE_MISMATCH", fields_result.issues[0].code)

    def test_later_decline_invalidates_an_earlier_authorization_for_same_operation(self) -> None:
        """Catches using a stale approval after the recorded current decision has changed."""
        approved_id = self._authorize()
        declined_id = record_external_decision(self.ledger, self.proposal, False, "user")

        result = admit_external_result(
            self.ledger, approved_id, PROVIDER, SOURCE_HASH, self.account,
            FIXTURES / "external-result.csv",
        )

        self.assertEqual("EXTERNAL_NOT_AUTHORIZED", result.issues[0].code)
        self.assertFalse(find_valid_authorization(self.ledger, approved_id, self.proposal))
        self.assertEqual(3, len(read_audit_events(self.ledger)))
        self.assertNotEqual(approved_id, declined_id)

    def test_each_repeat_decision_is_append_only_and_audit_is_private(self) -> None:
        """Catches coalescing repeated answers or writing statement details into audit events."""
        first = self._authorize()
        second = self._authorize()
        events = read_audit_events(self.ledger)

        self.assertNotEqual(first, second)
        self.assertEqual(3, len(events))
        audit_text = json.dumps(events)
        self.assertNotIn("Synthetic merchant", audit_text)
        self.assertNotIn("123456", audit_text)
        self.assertNotIn("raw_description", audit_text)

    def test_audit_records_scope_not_the_disclosure_text(self) -> None:
        """Catches a consent audit event retaining statement text supplied in a disclosure alternative."""
        private_proposal = create_external_proposal(
            provider=PROVIDER, source_hash=SOURCE_HASH, pages=(2,), fields=("date",),
            sensitive_data=("descriptions",), purpose="Extract Synthetic merchant from account 123456.",
            retention_risk="Unknown.", training_risk="Unknown.", regional_risk="Unknown.",
            human_access_risk="A person may see Synthetic merchant.",
            subprocessor_access_risk="A processor may see account 123456.",
            redactions=("mask account header",),
            manual_alternative="Enter Synthetic merchant from account 123456 locally.",
        )

        record_external_decision(self.ledger, private_proposal, True, "user")

        audit_text = json.dumps(read_audit_events(self.ledger))
        self.assertNotIn("Synthetic merchant", audit_text)
        self.assertNotIn("123456", audit_text)

    def test_result_requires_matching_provider_method_and_page_provenance(self) -> None:
        """Catches admitting canonical rows without third-party provider provenance or page evidence."""
        consent_id = self._authorize()
        method_result = admit_external_result(
            self.ledger, consent_id, PROVIDER, SOURCE_HASH, self.account,
            FIXTURES / "external-result-provider-mismatch.csv",
        )
        provenance_result = admit_external_result(
            self.ledger, consent_id, PROVIDER, SOURCE_HASH, self.account,
            FIXTURES / "external-result-no-page.csv",
        )

        self.assertEqual("EXTERNAL_RESULT_PROVIDER_MISMATCH", method_result.issues[0].code)
        self.assertEqual("EXTERNAL_RESULT_INVALID", provenance_result.issues[0].code)

    def test_result_rejects_nan_and_infinite_money(self) -> None:
        """Catches non-finite amounts reaching scope checks as if they were valid canonical money."""
        consent_id = self._authorize()
        for value in ("NaN", "Infinity"):
            with self.subTest(value=value):
                result = admit_external_result(
                    self.ledger, consent_id, PROVIDER, SOURCE_HASH, self.account,
                    self._write_result(f"{value}.csv", {"inflow": value, "outflow": "0"}),
                )
                self.assertEqual("EXTERNAL_RESULT_INVALID", result.issues[0].code)

    def test_result_rejects_truncated_and_overlong_rows(self) -> None:
        """Catches CSV row-width errors being ignored or raising while admitting a local result."""
        consent_id = self._authorize()
        with (FIXTURES / "external-result.csv").open("r", encoding="utf-8", newline="") as handle:
            header, row = list(csv.reader(handle))
        cases = {
            "truncated.csv": row[:-1],
            "overlong.csv": row + ["unexpected-cell"],
        }
        for filename, values in cases.items():
            with self.subTest(filename=filename):
                path = self.ledger / "work" / filename
                path.write_text(",".join(header) + "\n" + ",".join(values) + "\n", encoding="utf-8")
                result = admit_external_result(self.ledger, consent_id, PROVIDER, SOURCE_HASH, self.account, path)
                self.assertEqual("EXTERNAL_RESULT_INVALID", result.issues[0].code)

    def test_result_rejects_invalid_dates_and_missing_required_values(self) -> None:
        """Catches malformed canonical dates or blank transaction identity being admitted."""
        consent_id = self._authorize()
        for filename, changes in {
            "bad-date.csv": {"transaction_date": "2026-99-01"},
            "blank-account.csv": {"account_id": ""},
        }.items():
            with self.subTest(filename=filename):
                result = admit_external_result(
                    self.ledger, consent_id, PROVIDER, SOURCE_HASH, self.account,
                    self._write_result(filename, changes),
                )
                self.assertEqual("EXTERNAL_RESULT_INVALID", result.issues[0].code)

    def test_other_ledger_cannot_reuse_a_consent_event(self) -> None:
        """Catches a consent ID escaping the ledger/company that recorded it."""
        consent_id = self._authorize()
        other = Path(self.directory.name) / "other"
        initialize_ledger(other, "other", "Other", "CAD", None)

        result = admit_external_result(
            other, consent_id, PROVIDER, SOURCE_HASH, self.account, FIXTURES / "external-result.csv",
        )

        self.assertEqual("EXTERNAL_NOT_AUTHORIZED", result.issues[0].code)

    def test_cli_records_and_enforces_a_local_proposal_without_sending_files(self) -> None:
        """Catches the public workflow omitting disclosures, consent IDs, or local admission enforcement."""
        proposal_path = self.ledger / "work" / "proposal.json"
        proposal_path.write_text(json.dumps({
            "provider": PROVIDER, "source_hash": SOURCE_HASH, "pages": [2],
            "fields": ["date", "description", "amount"], "sensitive_data": ["descriptions", "amounts"],
            "purpose": "Extract one unreadable statement page for local bookkeeping.",
            "retention_risk": "Provider retention is unknown.", "training_risk": "Provider training use is unknown.",
            "regional_risk": "Processing region is unknown.",
            "human_access_risk": "Provider human access is unknown.",
            "subprocessor_access_risk": "Provider subprocessor access is unknown.",
            "redactions": ["mask account header"],
            "manual_alternative": "Enter page 2 into a local CSV template.",
        }), encoding="utf-8")
        proposed_output = StringIO()
        with redirect_stdout(proposed_output):
            self.assertEqual(0, import_statements.main(["propose-external", str(self.ledger), "work/proposal.json"]))
        disclosed = json.loads(proposed_output.getvalue())
        self.assertEqual(PROVIDER, disclosed["provider"])
        self.assertEqual(
            "Extract one unreadable statement page for local bookkeeping.",
            disclosed.get("purpose"),
        )
        self.assertEqual("Provider human access is unknown.", disclosed.get("human_access_risk"))
        self.assertEqual("Provider subprocessor access is unknown.", disclosed.get("subprocessor_access_risk"))
        disclosure_digest = str(disclosed.get("disclosure_digest", ""))
        self.assertRegex(disclosure_digest, r"^[0-9a-f]{64}$")
        audit_before = (self.ledger / "audit" / "audit.jsonl").read_bytes()
        missing_digest = subprocess.run([
            sys.executable, str(SKILL_ROOT / "scripts" / "import_statements.py"),
            "record-consent", str(self.ledger), "work/proposal.json",
            "--decision", "authorized", "--actor", "user",
        ], capture_output=True, text=True)
        self.assertEqual(2, missing_digest.returncode)
        self.assertEqual(audit_before, (self.ledger / "audit" / "audit.jsonl").read_bytes())
        wrong_digest = subprocess.run([
            sys.executable, str(SKILL_ROOT / "scripts" / "import_statements.py"),
            "record-consent", str(self.ledger), "work/proposal.json",
            "--decision", "authorized", "--actor", "user",
            "--disclosure-digest", "0" * 64,
        ], capture_output=True, text=True)
        self.assertEqual(3, wrong_digest.returncode)
        self.assertEqual(audit_before, (self.ledger / "audit" / "audit.jsonl").read_bytes())
        recorded = subprocess.run([
            sys.executable, str(SKILL_ROOT / "scripts" / "import_statements.py"),
            "record-consent", str(self.ledger), "work/proposal.json",
            "--decision", "authorized", "--actor", "user",
            "--disclosure-digest", disclosure_digest,
        ], capture_output=True, text=True)
        self.assertEqual(0, recorded.returncode, recorded.stderr)
        consent_record = json.loads(recorded.stdout)
        self.assertNotIn("disclosure", consent_record)
        self.assertEqual(disclosure_digest, consent_record["disclosure_digest"])
        consent_id = consent_record["consent_id"]
        returned = self.ledger / "work" / "external-result.csv"
        returned.write_bytes((FIXTURES / "external-result.csv").read_bytes())
        result_output = StringIO()
        with redirect_stdout(result_output):
            self.assertEqual(0, import_statements.main([
                "external-result", str(self.ledger), str(returned), "--consent-id", consent_id,
                "--provider", PROVIDER, "--source-hash", SOURCE_HASH,
                "--account", str(self.account_path),
            ]))
        self.assertEqual("imported", json.loads(result_output.getvalue())["status"])

    def test_cli_imports_external_rows_through_canonical_manifest_outputs_and_audit(self) -> None:
        """Catches admitting provider rows without persisting sanitized workflow state."""
        consent_id = self._authorize()
        returned = self._write_result("classified-provider-result.csv", {
            "transaction_id": "provider-controlled-id",
            "normalized_merchant": "PROVIDER MERCHANT",
            "classification_status": "classified",
            "account_code": "9999",
            "account_name": "Provider Category",
            "rule_id": "provider-rule",
            "review_note": "provider-reviewed",
        })
        returned_hash = hashlib.sha256(returned.read_bytes()).hexdigest()
        logical_source = f"external:{self.proposal.operation_id}"
        id_basis = json.dumps({
            "operation_id": self.proposal.operation_id,
            "result_hash": returned_hash,
            "row_ordinal": 1,
            "source_page_or_row": "page:2/row:1",
        }, sort_keys=True, separators=(",", ":"))
        expected_id = hashlib.sha256(id_basis.encode("utf-8")).hexdigest()

        return_code, output = self._run_external_result(returned, consent_id)

        self.assertEqual(0, return_code)
        self.assertEqual("imported", output["status"])
        canonical = read_csv_rows(self.ledger / "work" / "normalized-transactions.csv")
        self.assertEqual(1, len(canonical))
        row = canonical[0]
        self.assertEqual(expected_id, row["transaction_id"])
        self.assertEqual(logical_source, row["source_file"])
        self.assertEqual("page:2/row:1", row["source_page_or_row"])
        self.assertEqual(
            f"{logical_source}:inputs/synthetic.pdf:page:2/row:1",
            row["source_locations"],
        )
        self.assertEqual("SYNTHETIC MERCHANT", row["normalized_merchant"])
        self.assertEqual("unclassified", row["classification_status"])
        self.assertEqual(("", "", "", ""), tuple(row[field] for field in (
            "account_code", "account_name", "rule_id", "review_note",
        )))
        manifest = json.loads((self.ledger / "work" / "import-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual({logical_source: returned_hash}, manifest["source_hashes"])
        self.assertEqual(1, manifest["transaction_count"])
        contribution = read_csv_rows(self.ledger / manifest["source_contributions"][logical_source]["path"])
        self.assertEqual(1, len(contribution))
        self.assertEqual(logical_source, contribution[0]["source_file"])
        self.assertEqual("unclassified", contribution[0]["classification_status"])
        self.assertEqual(("", "", "", "", ""), tuple(contribution[0][field] for field in (
            "normalized_merchant", "account_code", "account_name", "rule_id", "review_note",
        )))
        self.assertEqual(1, len(read_csv_rows(self.ledger / "outputs" / "normalized-transactions.csv")))
        self.assertEqual(1, len(read_csv_rows(self.ledger / "outputs" / "classified-transactions.csv")))
        self.assertTrue((self.ledger / "outputs" / "status.json").is_file())
        imported_events = [
            event for event in read_audit_events(self.ledger)
            if event["event_type"] == "external_result_import_recorded"
        ]
        self.assertEqual(1, len(imported_events))
        self.assertEqual(returned_hash, imported_events[0]["payload"]["source_hashes"][logical_source])
        consent_events = [
            event for event in read_audit_events(self.ledger)
            if event["event_type"] == "external_processing_consent_decision"
        ]
        self.assertEqual(SOURCE_HASH, consent_events[0]["payload"]["source_hash"])

    def test_cli_external_result_requires_an_account_context_argument(self) -> None:
        """Catches admitting provider account fields when no confirmed local account was selected."""
        consent_id = self._authorize()
        returned = self._write_result("missing-account-argument.csv", {})

        rejected = self._external_subprocess(returned, consent_id, None)

        self.assertEqual(2, rejected.returncode)
        self.assertEqual("USAGE", json.loads(rejected.stdout)["error"])

    def test_cli_rejects_invalid_account_context_before_reading_the_returned_file(self) -> None:
        """Catches opening returned bytes before rejecting blank or unmasked local account confirmation."""
        consent_id = self._authorize()
        missing_result = self.ledger / "work" / "must-not-be-read.csv"
        cases = {
            "blank": {
                "account_id": "", "institution": "Synthetic Bank",
                "masked_label": "***1001", "currency": "CAD",
            },
            "unmasked": {
                "account_id": "checking-001", "institution": "Synthetic Bank",
                "masked_label": "123456", "currency": "CAD",
            },
        }
        for name, account in cases.items():
            with self.subTest(name=name):
                self.account_path.write_text(json.dumps(account), encoding="utf-8")
                expected = self._ledger_bytes()

                rejected = self._external_subprocess(missing_result, consent_id, self.account_path)

                self.assertEqual(3, rejected.returncode)
                self.assertEqual("LEDGER_SCHEMA_INVALID", json.loads(rejected.stdout)["error"])
                self.assertEqual(expected, self._ledger_bytes())

    def test_cli_matching_account_context_is_authoritative_for_sanitized_rows(self) -> None:
        """Catches provider account fields bypassing the selected local account context."""
        consent_id = self._authorize()
        returned = self._write_result("matching-account.csv", {
            "account_id": "checking-001", "currency": "CAD",
        })

        admitted = self._external_subprocess(returned, consent_id, self.account_path)

        self.assertEqual(0, admitted.returncode, admitted.stdout)
        row = read_csv_rows(self.ledger / "work" / "normalized-transactions.csv")[0]
        self.assertEqual(("checking-001", "CAD"), (row["account_id"], row["currency"]))

    def test_cli_blocks_account_and_currency_mismatches_without_ledger_mutation(self) -> None:
        """Catches provider account or currency values overriding one confirmed local unit."""
        consent_id = self._authorize()
        for filename, changes in {
            "wrong-account.csv": {"account_id": "savings-002"},
            "wrong-currency.csv": {"currency": "USD"},
        }.items():
            with self.subTest(filename=filename):
                returned = self._write_result(filename, changes)
                expected = self._import_authority_bytes()

                blocked = self._external_subprocess(returned, consent_id, self.account_path)

                self.assertEqual(0, blocked.returncode, blocked.stdout)
                self.assertEqual({"status": "blocked", "issues": ["EXTERNAL_ACCOUNT_MISMATCH"]}, json.loads(blocked.stdout))
                self.assertEqual(expected, self._import_authority_bytes())
                self.assertEqual(
                    "blocked",
                    json.loads((self.ledger / "outputs" / "status.json").read_text(encoding="utf-8"))["state"],
                )
                self.assertIn(
                    "EXTERNAL_ACCOUNT_MISMATCH",
                    {row["code"] for row in read_csv_rows(self.ledger / "outputs" / "exceptions.csv")},
                )

    def test_cli_blocks_mixed_account_or_currency_rows_as_one_unit_without_mutation(self) -> None:
        """Catches silently partitioning a multi-account external result under one confirmed context."""
        consent_id = self._authorize()
        with (FIXTURES / "external-result.csv").open("r", encoding="utf-8", newline="") as handle:
            first = next(csv.DictReader(handle))
        second = dict(first)
        second.update({
            "transaction_id": "external-2", "transaction_date": "2026-01-06", "posting_date": "2026-01-06",
            "account_id": "savings-002", "currency": "USD", "reference": "SYN-2",
            "source_page_or_row": "page:2/row:2", "source_locations": "inputs/synthetic.pdf:page:2/row:2",
        })
        returned = self.ledger / "work" / "mixed-account-result.csv"
        with returned.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CANONICAL_TRANSACTION_FIELDS)
            writer.writeheader()
            writer.writerows((first, second))
        expected = self._import_authority_bytes()

        blocked = self._external_subprocess(returned, consent_id, self.account_path)

        self.assertEqual(0, blocked.returncode, blocked.stdout)
        self.assertEqual({"status": "blocked", "issues": ["EXTERNAL_ACCOUNT_MISMATCH"]}, json.loads(blocked.stdout))
        self.assertEqual(expected, self._import_authority_bytes())
        self.assertEqual(
            "blocked", json.loads((self.ledger / "outputs" / "status.json").read_text(encoding="utf-8"))["state"],
        )

    def test_cli_rejects_outside_and_cross_ledger_account_context_without_target_mutation(self) -> None:
        """Catches loading confirmed account context from outside the selected ledger."""
        consent_id = self._authorize()
        returned = self._write_result("account-path-result.csv", {})
        other_ledger = Path(self.directory.name) / "other-account-ledger"
        initialize_ledger(other_ledger, "other-account", "Other", "CAD", None)
        cross_ledger = other_ledger / "work" / "account.json"
        outside = Path(self.directory.name) / "outside-account.json"
        for path in (cross_ledger, outside):
            path.write_bytes(self.account_path.read_bytes())
        expected = self._ledger_bytes()

        for account_path in (cross_ledger, outside):
            with self.subTest(account_path=account_path):
                rejected = self._external_subprocess(returned, consent_id, account_path)
                self.assertEqual(3, rejected.returncode)
                self.assertEqual("LEDGER_SCHEMA_INVALID", json.loads(rejected.stdout)["error"])
                self.assertEqual(expected, self._ledger_bytes())

    def test_cli_external_result_rerun_is_byte_event_and_row_idempotent(self) -> None:
        """Catches a repeated admitted result changing bytes, IDs, rows, or audit events."""
        consent_id = self._authorize()
        returned = self._write_result("stable-result.csv", {})

        first_code, first_output = self._run_external_result(returned, consent_id)
        first_bytes = self._ledger_bytes()
        first_rows = read_csv_rows(self.ledger / "work" / "normalized-transactions.csv")
        first_events = read_audit_events(self.ledger)
        second_code, second_output = self._run_external_result(returned, consent_id)

        self.assertEqual((0, 0), (first_code, second_code))
        self.assertEqual(first_output["audit_event_id"], second_output["audit_event_id"])
        self.assertEqual(first_bytes, self._ledger_bytes())
        self.assertEqual(first_rows, read_csv_rows(self.ledger / "work" / "normalized-transactions.csv"))
        self.assertEqual(first_events, read_audit_events(self.ledger))

    def test_external_inflow_with_decimal_zero_outflow_replays_its_selected_classification(self) -> None:
        """Catches direction replay treating decimal zero as an outflow after an unrelated import."""
        consent_id = self._authorize()
        returned = self._write_result("external-inflow.csv", {
            "inflow": "20.00", "outflow": "0.00", "running_balance": "1020.00",
        })
        first_code, _ = self._run_external_result(returned, consent_id)
        self.assertEqual(0, first_code)
        classify = str(SKILL_ROOT / "scripts" / "classify_transactions.py")
        pending = subprocess.run(
            [sys.executable, classify, "pending", str(self.ledger)],
            check=True, capture_output=True, text=True,
        )
        group = json.loads(pending.stdout)["groups"][0]
        self.assertEqual("inflow", group["direction"])
        subprocess.run([
            sys.executable, classify, "confirm", str(self.ledger), group["group_id"],
            "--account-code", "", "--account-name", "Selected Inflow", "--actor", "user",
        ], check=True, capture_output=True, text=True)
        historical = read_csv_rows(self.ledger / "work" / "normalized-transactions.csv")[0]
        second_hash = "b" * 64
        second_proposal = create_external_proposal(
            provider=PROVIDER, source_hash=second_hash, pages=(2,), fields=("date", "description", "amount"),
            sensitive_data=("descriptions", "amounts"), purpose="Extract an unrelated statement row.",
            retention_risk="Unknown.", training_risk="Unknown.", regional_risk="Unknown.",
            human_access_risk="Unknown.", subprocessor_access_risk="Unknown.",
            redactions=("mask account header",), manual_alternative="Enter locally.",
        )
        second_id = self._authorize_proposal(second_proposal)
        unrelated = self._write_result("external-unrelated.csv", {
            "transaction_date": "2026-02-05", "posting_date": "2026-02-05",
            "raw_description": "Unrelated merchant", "inflow": "0.00", "outflow": "12.00",
            "running_balance": "1008.00", "reference": "UNRELATED-1",
        })
        output = StringIO()

        with redirect_stdout(output):
            second_code = import_statements.main([
                "external-result", str(self.ledger), str(unrelated), "--consent-id", second_id,
                "--provider", PROVIDER, "--source-hash", second_hash,
                "--account", str(self.account_path),
            ])

        self.assertEqual(0, second_code, output.getvalue())
        rebuilt = next(
            row for row in read_csv_rows(self.ledger / "work" / "normalized-transactions.csv")
            if row["transaction_id"] == historical["transaction_id"]
        )
        self.assertEqual(("classified", "Selected Inflow", ""), (
            rebuilt["classification_status"], rebuilt["account_name"], rebuilt["rule_id"],
        ))

    def test_cli_changed_external_bytes_replace_one_operation_without_stale_rows(self) -> None:
        """Catches changed returned bytes appending beside the prior contribution for one operation."""
        consent_id = self._authorize()
        returned = self._write_result("changing-result.csv", {})
        first_hash = hashlib.sha256(returned.read_bytes()).hexdigest()
        first_code, _ = self._run_external_result(returned, consent_id)
        first_id = read_csv_rows(self.ledger / "work" / "normalized-transactions.csv")[0]["transaction_id"]
        self._write_result("changing-result.csv", {
            "raw_description": "Changed synthetic merchant", "reference": "SYN-2", "outflow": "25.00",
        })
        second_hash = hashlib.sha256(returned.read_bytes()).hexdigest()

        second_code, _ = self._run_external_result(returned, consent_id)

        self.assertEqual((0, 0), (first_code, second_code))
        self.assertNotEqual(first_hash, second_hash)
        rows = read_csv_rows(self.ledger / "work" / "normalized-transactions.csv")
        self.assertEqual(1, len(rows))
        self.assertEqual("Changed synthetic merchant", rows[0]["raw_description"])
        self.assertNotEqual(first_id, rows[0]["transaction_id"])
        logical_source = f"external:{self.proposal.operation_id}"
        manifest = json.loads((self.ledger / "work" / "import-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual({logical_source: second_hash}, manifest["source_hashes"])
        current_snapshot = Path(manifest["source_contributions"][logical_source]["path"]).name
        self.assertEqual(
            {current_snapshot},
            {path.name for path in (self.ledger / "work" / "import-contributions").iterdir()},
        )
        imported_events = [
            event for event in read_audit_events(self.ledger)
            if event["event_type"] == "external_result_import_recorded"
        ]
        self.assertEqual(2, len(imported_events))

    def test_cli_changed_external_result_removes_old_provenance_collapsed_into_local_row(self) -> None:
        """Catches external replacement leaving its old location on another source's overlap primary."""
        mapping_path = self.ledger / "work" / "local-map.json"
        mapping_path.write_text(json.dumps({
            "transaction_date": "Date", "posting_date": "Posted", "description": "Description",
            "debit": "Debit", "credit": "Credit", "balance": "Balance", "reference": "Reference",
            "date_formats": ["%Y-%m-%d"],
        }), encoding="utf-8")
        account_path = self.ledger / "work" / "local-account.json"
        account_path.write_text(json.dumps({
            "account_id": "checking-001", "institution": "Synthetic Bank",
            "masked_label": "***1001", "currency": "CAD",
        }), encoding="utf-8")
        local = self.ledger / "inputs" / "local-overlap.csv"
        local.write_text(
            "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
            "2026-01-05,2026-01-05,Synthetic merchant,20.00,,980.00,SYN-1\n",
            encoding="utf-8",
        )
        with redirect_stdout(StringIO()):
            self.assertEqual(0, import_statements.main([
                "csv", str(self.ledger), "inputs/local-overlap.csv",
                "--mapping", "work/local-map.json", "--account", "work/local-account.json",
            ]))
        consent_id = self._authorize()
        returned = self._write_result("overlapping-result.csv", {})
        first_code, _ = self._run_external_result(returned, consent_id)
        self.assertEqual(0, first_code)
        old_provider_location = "inputs/synthetic.pdf:page:2/row:1"
        self.assertIn(
            old_provider_location,
            read_csv_rows(self.ledger / "work" / "normalized-transactions.csv")[0]["source_locations"],
        )
        self._write_result("overlapping-result.csv", {
            "raw_description": "Changed synthetic merchant", "reference": "SYN-2", "outflow": "25.00",
            "source_page_or_row": "page:2/row:2",
            "source_locations": "inputs/changed.pdf:page:2/row:2",
        })

        second_code, _ = self._run_external_result(returned, consent_id)

        self.assertEqual(0, second_code)
        canonical = read_csv_rows(self.ledger / "work" / "normalized-transactions.csv")
        derived = read_csv_rows(self.ledger / "outputs" / "normalized-transactions.csv")
        self.assertEqual(2, len(canonical))
        self.assertEqual(
            {row["transaction_id"]: row for row in canonical},
            {row["transaction_id"]: row for row in derived},
        )
        local_row = next(row for row in canonical if row["source_file"] == "inputs/local-overlap.csv")
        external_row = next(row for row in canonical if row["source_file"].startswith("external:"))
        self.assertEqual("inputs/local-overlap.csv:2", local_row["source_locations"])
        self.assertIn("inputs/changed.pdf:page:2/row:2", external_row["source_locations"])
        self.assertNotIn(old_provider_location, "|".join(row["source_locations"] for row in canonical))

    def test_cli_changed_external_result_rebuilds_local_contribution_folded_into_external_primary(self) -> None:
        """Catches reverse import order dropping a local row that was folded into an external primary."""
        mapping_path = self.ledger / "work" / "local-map.json"
        mapping_path.write_text(json.dumps({
            "transaction_date": "Date", "posting_date": "Posted", "description": "Description",
            "debit": "Debit", "credit": "Credit", "balance": "Balance", "reference": "Reference",
            "date_formats": ["%Y-%m-%d"],
        }), encoding="utf-8")
        account_path = self.ledger / "work" / "local-account.json"
        account_path.write_text(json.dumps({
            "account_id": "checking-001", "institution": "Synthetic Bank",
            "masked_label": "***1001", "currency": "CAD",
        }), encoding="utf-8")
        local_source = "inputs/local-overlap.csv"
        local = self.ledger / local_source
        local.write_text(
            "Date,Posted,Description,Debit,Credit,Balance,Reference\n"
            "2026-01-05,2026-01-05,Synthetic merchant,20.00,,980.00,SYN-1\n",
            encoding="utf-8",
        )
        consent_id = self._authorize()
        logical_source = f"external:{self.proposal.operation_id}"
        returned = self._write_result("reverse-overlap-result.csv", {})
        first_code, _ = self._run_external_result(returned, consent_id)
        self.assertEqual(0, first_code)
        with redirect_stdout(StringIO()):
            self.assertEqual(0, import_statements.main([
                "csv", str(self.ledger), local_source,
                "--mapping", "work/local-map.json", "--account", "work/local-account.json",
            ]))
        folded = read_csv_rows(self.ledger / "work" / "normalized-transactions.csv")
        self.assertEqual(1, len(folded))
        self.assertEqual(logical_source, folded[0]["source_file"])
        self.assertIn(f"{local_source}:2", folded[0]["source_locations"])
        self._write_result("reverse-overlap-result.csv", {
            "raw_description": "Changed synthetic merchant", "reference": "SYN-2", "outflow": "25.00",
            "source_page_or_row": "page:2/row:2",
            "source_locations": "inputs/changed.pdf:page:2/row:2",
        })

        second_code, _ = self._run_external_result(returned, consent_id)

        self.assertEqual(0, second_code)
        canonical = read_csv_rows(self.ledger / "work" / "normalized-transactions.csv")
        derived = read_csv_rows(self.ledger / "outputs" / "normalized-transactions.csv")
        manifest = json.loads((self.ledger / "work" / "import-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(2, len(canonical))
        self.assertEqual({local_source, logical_source}, set(manifest["source_hashes"]))
        self.assertEqual({local_source, logical_source}, {row["source_file"] for row in canonical})
        self.assertEqual(
            {row["transaction_id"]: row for row in canonical},
            {row["transaction_id"]: row for row in derived},
        )
        locations = "|".join(row["source_locations"] for row in canonical)
        self.assertIn(f"{local_source}:2", locations)
        self.assertIn("inputs/changed.pdf:page:2/row:2", locations)
        self.assertNotIn("inputs/synthetic.pdf:page:2/row:1", locations)

    def test_cli_same_external_bytes_for_distinct_operations_are_independently_audited(self) -> None:
        """Catches equal returned bytes coalescing two independently authorized operations."""
        first_id = self._authorize()
        second_proposal = create_external_proposal(
            provider=PROVIDER, source_hash=SOURCE_HASH, pages=(2,), fields=("date", "description", "amount"),
            sensitive_data=("descriptions", "amounts"), purpose="Extract a separately authorized result.",
            retention_risk="Unknown.", training_risk="Unknown.", regional_risk="Unknown.",
            human_access_risk="Unknown.", subprocessor_access_risk="Unknown.",
            redactions=("mask account header",),
            manual_alternative="Enter page 2 locally.",
        )
        second_id = self._authorize_proposal(second_proposal)
        returned = self._write_result("shared-result.csv", {})
        returned_hash = hashlib.sha256(returned.read_bytes()).hexdigest()

        first_code, first_output = self._run_external_result(returned, first_id)
        second_code, second_output = self._run_external_result(returned, second_id)

        self.assertEqual((0, 0), (first_code, second_code))
        self.assertNotEqual(first_output["audit_event_id"], second_output["audit_event_id"])
        manifest = json.loads((self.ledger / "work" / "import-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual({
            f"external:{self.proposal.operation_id}": returned_hash,
            f"external:{second_proposal.operation_id}": returned_hash,
        }, manifest["source_hashes"])
        imported_events = [
            event for event in read_audit_events(self.ledger)
            if event["event_type"] == "external_result_import_recorded"
        ]
        self.assertEqual(2, len(imported_events))
        self.assertEqual(2, len({event["dedupe_key"] for event in imported_events}))
        self.assertEqual(1, len(read_csv_rows(self.ledger / "work" / "normalized-transactions.csv")))
        self.assertEqual(1, imported_events[-1]["payload"]["overlap_count"])

    def test_cli_fails_closed_when_existing_manifest_has_no_contribution_mapping(self) -> None:
        """Catches reconstructing folded sources from canonical when a legacy manifest has no snapshots."""
        consent_id = self._authorize()
        returned = self._write_result("legacy-manifest-result.csv", {})
        first_code, _ = self._run_external_result(returned, consent_id)
        self.assertEqual(0, first_code)
        manifest_path = self.ledger / "work" / "import-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        del manifest["source_contributions"]
        del manifest["source_order"]
        manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        self._write_result("legacy-manifest-result.csv", {
            "raw_description": "Changed synthetic merchant", "reference": "SYN-2", "outflow": "25.00",
        })
        expected = self._ledger_bytes()

        return_code, output = self._run_external_result(returned, consent_id)

        self.assertEqual(3, return_code)
        self.assertEqual("LEDGER_SCHEMA_INVALID", output["error"])
        self.assertEqual(expected, self._ledger_bytes())

    def test_cli_fails_closed_when_a_current_contribution_snapshot_is_missing(self) -> None:
        """Catches silently losing a source whose manifest-bound normalized snapshot disappeared."""
        consent_id = self._authorize()
        returned = self._write_result("missing-snapshot-result.csv", {})
        first_code, _ = self._run_external_result(returned, consent_id)
        self.assertEqual(0, first_code)
        manifest = json.loads((self.ledger / "work" / "import-manifest.json").read_text(encoding="utf-8"))
        logical_source = f"external:{self.proposal.operation_id}"
        snapshot = self.ledger / manifest["source_contributions"][logical_source]["path"]
        snapshot.unlink()
        self._write_result("missing-snapshot-result.csv", {
            "raw_description": "Changed synthetic merchant", "reference": "SYN-2", "outflow": "25.00",
        })
        expected = self._ledger_bytes()

        return_code, output = self._run_external_result(returned, consent_id)

        self.assertEqual(3, return_code)
        self.assertEqual("LEDGER_SCHEMA_INVALID", output["error"])
        self.assertEqual(expected, self._ledger_bytes())

    def test_cli_fails_closed_when_a_current_contribution_snapshot_is_tampered(self) -> None:
        """Catches rebuilding canonical from normalized snapshot bytes that no longer match the manifest."""
        consent_id = self._authorize()
        returned = self._write_result("tampered-snapshot-result.csv", {})
        first_code, _ = self._run_external_result(returned, consent_id)
        self.assertEqual(0, first_code)
        manifest = json.loads((self.ledger / "work" / "import-manifest.json").read_text(encoding="utf-8"))
        logical_source = f"external:{self.proposal.operation_id}"
        snapshot = self.ledger / manifest["source_contributions"][logical_source]["path"]
        snapshot.write_bytes(snapshot.read_bytes() + b"\n")
        self._write_result("tampered-snapshot-result.csv", {
            "raw_description": "Changed synthetic merchant", "reference": "SYN-2", "outflow": "25.00",
        })
        expected = self._ledger_bytes()

        return_code, output = self._run_external_result(returned, consent_id)

        self.assertEqual(3, return_code)
        self.assertEqual("LEDGER_SCHEMA_INVALID", output["error"])
        self.assertEqual(expected, self._ledger_bytes())

    def test_cli_rejects_outside_and_cross_ledger_results_without_target_mutation(self) -> None:
        """Catches a result path escaping the selected ledger before admission persistence."""
        consent_id = self._authorize()
        other_ledger = Path(self.directory.name) / "other-ledger"
        initialize_ledger(other_ledger, "other", "Other", "CAD", None)
        cross_ledger = other_ledger / "work" / "result.csv"
        cross_ledger.write_bytes((FIXTURES / "external-result.csv").read_bytes())
        outside = Path(self.directory.name) / "outside.csv"
        outside.write_bytes((FIXTURES / "external-result.csv").read_bytes())
        expected = self._ledger_bytes()

        for result_path in (outside, cross_ledger):
            with self.subTest(result_path=result_path.name):
                return_code, output = self._run_external_result(result_path, consent_id)
                self.assertEqual(3, return_code)
                self.assertEqual("LEDGER_SCHEMA_INVALID", output["error"])
                self.assertEqual(expected, self._ledger_bytes())

    def test_cli_rejects_a_result_file_symlink_without_ledger_mutation(self) -> None:
        """Catches resolving an in-ledger returned-file symlink before the lexical safety gate."""
        consent_id = self._authorize()
        target = self._write_result("real-result.csv", {})
        linked = self.ledger / "work" / "linked-result.csv"
        linked.symlink_to(target.name)
        expected = self._ledger_bytes()

        return_code, output = self._run_external_result(linked, consent_id)

        self.assertEqual(3, return_code)
        self.assertEqual("LEDGER_SCHEMA_INVALID", output["error"])
        self.assertEqual(expected, self._ledger_bytes())

    def test_cli_rejects_a_symlinked_result_ancestor_without_ledger_mutation(self) -> None:
        """Catches traversing an in-ledger symlinked directory to read a returned CSV."""
        consent_id = self._authorize()
        real_directory = self.ledger / "work" / "real-results"
        real_directory.mkdir()
        target = real_directory / "returned.csv"
        target.write_bytes((FIXTURES / "external-result.csv").read_bytes())
        linked_directory = self.ledger / "work" / "linked-results"
        linked_directory.symlink_to(real_directory.name, target_is_directory=True)
        expected = self._ledger_bytes()

        return_code, output = self._run_external_result(linked_directory / target.name, consent_id)

        self.assertEqual(3, return_code)
        self.assertEqual("LEDGER_SCHEMA_INVALID", output["error"])
        self.assertEqual(expected, self._ledger_bytes())

    def test_cli_does_not_normalize_away_a_result_path_symlink_component(self) -> None:
        """Catches parent traversal erasing a symlink component before the lexical lstat walk."""
        consent_id = self._authorize()
        real_directory = self.ledger / "work" / "real-results"
        real_directory.mkdir()
        target = real_directory / "returned.csv"
        target.write_bytes((FIXTURES / "external-result.csv").read_bytes())
        linked_directory = self.ledger / "work" / "linked-results"
        linked_directory.symlink_to(real_directory.name, target_is_directory=True)
        disguised = linked_directory / ".." / real_directory.name / target.name
        expected = self._ledger_bytes()

        return_code, output = self._run_external_result(disguised, consent_id)

        self.assertEqual(3, return_code)
        self.assertEqual("LEDGER_SCHEMA_INVALID", output["error"])
        self.assertEqual(expected, self._ledger_bytes())


if __name__ == "__main__":
    unittest.main()
