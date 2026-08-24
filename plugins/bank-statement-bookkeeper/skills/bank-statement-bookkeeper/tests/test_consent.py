"""Consent gates for local admission of third-party extraction results."""

from contextlib import redirect_stdout
import csv
from dataclasses import replace
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
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
from bookkeeper.contracts import CANONICAL_TRANSACTION_FIELDS
from bookkeeper.ledger import initialize_ledger
from bookkeeper.storage import read_audit_events
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
            retention_risk="Provider retention is unknown.",
            training_risk="Provider training use is unknown.",
            regional_risk="Processing region is unknown.",
            redactions=("mask account header",),
            manual_alternative="Enter page 2 into a local CSV template.",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _authorize(self) -> str:
        return record_external_decision(
            self.ledger, self.proposal, True, "user",
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

    def test_exact_authorization_admits_matching_local_result(self) -> None:
        """Catches treating an exact authorized operation as blocked."""
        consent_id = self._authorize()

        result = admit_external_result(
            self.ledger, consent_id, PROVIDER, SOURCE_HASH,
            FIXTURES / "external-result.csv",
        )

        self.assertEqual((), result.issues)
        self.assertEqual("third_party:Synthetic OCR Provider", result.transactions[0]["extraction_method"])
        self.assertTrue(find_valid_authorization(self.ledger, consent_id, self.proposal))

    def test_persisted_scope_edit_with_retained_operation_id_is_rejected(self) -> None:
        """Catches trusting a format-valid operation ID after its provider/source/page/field scope changes."""
        persisted = proposal_to_dict(self.proposal)
        persisted["provider"] = "Different OCR Provider"

        with self.assertRaisesRegex(ValueError, "operation_id"):
            proposal_from_dict(persisted)
        with self.assertRaisesRegex(ValueError, "operation_id"):
            record_external_decision(self.ledger, replace(self.proposal, pages=(3,)), True, "user")

    def test_cli_rejects_a_persisted_scope_edit_with_retained_operation_id(self) -> None:
        """Catches record-consent appending an edited proposal file that retains an older operation ID."""
        proposal_path = self.ledger / "work" / "proposal.json"
        proposal_path.write_text(json.dumps({
            "provider": PROVIDER, "source_hash": SOURCE_HASH, "pages": [2],
            "fields": ["date", "description", "amount"], "sensitive_data": ["descriptions", "amounts"],
            "retention_risk": "Provider retention is unknown.", "training_risk": "Provider training use is unknown.",
            "regional_risk": "Processing region is unknown.", "redactions": ["mask account header"],
            "manual_alternative": "Enter page 2 into a local CSV template.",
        }), encoding="utf-8")
        with redirect_stdout(StringIO()):
            self.assertEqual(0, import_statements.main(["propose-external", str(self.ledger), "work/proposal.json"]))
        persisted = json.loads(proposal_path.read_text(encoding="utf-8"))
        persisted["pages"] = [3]
        proposal_path.write_text(json.dumps(persisted), encoding="utf-8")

        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(2, import_statements.main([
                "record-consent", str(self.ledger), "work/proposal.json", "--decision", "authorized", "--actor", "user",
            ]))

        self.assertIn("operation_id", json.loads(output.getvalue())["error"])
        self.assertEqual(1, len(read_audit_events(self.ledger)))

    def test_declined_work_is_rejected_before_result_is_read(self) -> None:
        """Catches reading or accepting a result after the user declines its operation."""
        consent_id = record_external_decision(self.ledger, self.proposal, False, "user")

        result = admit_external_result(
            self.ledger, consent_id, PROVIDER, SOURCE_HASH,
            self.ledger / "inputs" / "does-not-exist.csv",
        )

        self.assertEqual("EXTERNAL_NOT_AUTHORIZED", result.issues[0].code)

    def test_provider_and_source_mismatches_are_rejected_before_result_is_read(self) -> None:
        """Catches an approval being reused for a different provider or statement source."""
        consent_id = self._authorize()

        provider_result = admit_external_result(
            self.ledger, consent_id, "Different OCR Provider", SOURCE_HASH,
            self.ledger / "inputs" / "missing.csv",
        )
        source_result = admit_external_result(
            self.ledger, consent_id, PROVIDER, "b" * 64,
            self.ledger / "inputs" / "missing.csv",
        )

        self.assertEqual("EXTERNAL_SCOPE_MISMATCH", provider_result.issues[0].code)
        self.assertEqual("EXTERNAL_SCOPE_MISMATCH", source_result.issues[0].code)

    def test_page_and_field_scope_mismatches_are_rejected(self) -> None:
        """Catches a consent for page 2/date-description-amount admitting another result shape."""
        consent_id = self._authorize()
        page_result = admit_external_result(
            self.ledger, consent_id, PROVIDER, SOURCE_HASH,
            FIXTURES / "external-result-page-3.csv",
        )
        fields_result = admit_external_result(
            self.ledger, consent_id, PROVIDER, SOURCE_HASH,
            FIXTURES / "external-result-missing-amount.csv",
        )

        self.assertEqual("EXTERNAL_SCOPE_MISMATCH", page_result.issues[0].code)
        self.assertEqual("EXTERNAL_RESULT_INVALID", fields_result.issues[0].code)

    def test_later_decline_invalidates_an_earlier_authorization_for_same_operation(self) -> None:
        """Catches using a stale approval after the recorded current decision has changed."""
        approved_id = self._authorize()
        declined_id = record_external_decision(self.ledger, self.proposal, False, "user")

        result = admit_external_result(
            self.ledger, approved_id, PROVIDER, SOURCE_HASH,
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
            sensitive_data=("descriptions",), retention_risk="Unknown.", training_risk="Unknown.",
            regional_risk="Unknown.", redactions=("mask account header",),
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
            self.ledger, consent_id, PROVIDER, SOURCE_HASH,
            FIXTURES / "external-result-provider-mismatch.csv",
        )
        provenance_result = admit_external_result(
            self.ledger, consent_id, PROVIDER, SOURCE_HASH,
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
                    self.ledger, consent_id, PROVIDER, SOURCE_HASH,
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
                result = admit_external_result(self.ledger, consent_id, PROVIDER, SOURCE_HASH, path)
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
                    self.ledger, consent_id, PROVIDER, SOURCE_HASH, self._write_result(filename, changes),
                )
                self.assertEqual("EXTERNAL_RESULT_INVALID", result.issues[0].code)

    def test_other_ledger_cannot_reuse_a_consent_event(self) -> None:
        """Catches a consent ID escaping the ledger/company that recorded it."""
        consent_id = self._authorize()
        other = Path(self.directory.name) / "other"
        initialize_ledger(other, "other", "Other", "CAD", None)

        result = admit_external_result(other, consent_id, PROVIDER, SOURCE_HASH, FIXTURES / "external-result.csv")

        self.assertEqual("EXTERNAL_NOT_AUTHORIZED", result.issues[0].code)

    def test_cli_records_and_enforces_a_local_proposal_without_sending_files(self) -> None:
        """Catches the public workflow omitting disclosures, consent IDs, or local admission enforcement."""
        proposal_path = self.ledger / "work" / "proposal.json"
        proposal_path.write_text(json.dumps({
            "provider": PROVIDER, "source_hash": SOURCE_HASH, "pages": [2],
            "fields": ["date", "description", "amount"], "sensitive_data": ["descriptions", "amounts"],
            "retention_risk": "Provider retention is unknown.", "training_risk": "Provider training use is unknown.",
            "regional_risk": "Processing region is unknown.", "redactions": ["mask account header"],
            "manual_alternative": "Enter page 2 into a local CSV template.",
        }), encoding="utf-8")
        proposed_output = StringIO()
        with redirect_stdout(proposed_output):
            self.assertEqual(0, import_statements.main(["propose-external", str(self.ledger), "work/proposal.json"]))
        disclosed = json.loads(proposed_output.getvalue())
        self.assertEqual(PROVIDER, disclosed["provider"])
        consent_output = StringIO()
        with redirect_stdout(consent_output):
            self.assertEqual(0, import_statements.main([
                "record-consent", str(self.ledger), "work/proposal.json", "--decision", "authorized", "--actor", "user",
            ]))
        consent_records = [json.loads(line) for line in consent_output.getvalue().splitlines()]
        self.assertEqual(disclosed, consent_records[0]["disclosure"])
        consent_id = consent_records[1]["consent_id"]
        result_output = StringIO()
        with redirect_stdout(result_output):
            self.assertEqual(0, import_statements.main([
                "external-result", str(self.ledger), str(FIXTURES / "external-result.csv"), "--consent-id", consent_id,
                "--provider", PROVIDER, "--source-hash", SOURCE_HASH,
            ]))
        self.assertEqual("admitted", json.loads(result_output.getvalue())["status"])


if __name__ == "__main__":
    unittest.main()
