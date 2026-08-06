from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.run_pipeline import run_pipeline


def case_manifest(shared_space: bool = False) -> dict:
    return {
        "schema_version": "1.0",
        "case_id": "synthetic-pipeline-001",
        "jurisdiction": {"country": "CA", "province": "ON"},
        "housing": {
            "market_type": "market",
            "owner_shared_kitchen_or_bathroom": shared_space,
            "address": "100 Example Street, Toronto, ON",
            "monthly_rent_cad": "2400.00",
            "expected_start_date": "2026-09-01",
            "term_months": 12,
        },
        "applicants": [
            {
                "applicant_id": "a",
                "lease_signer": True,
                "files": [
                    {"path": "inputs/application-a.pdf", "kind": "application"}
                ],
            }
        ],
        "privacy": {
            "responsible_person": "Synthetic Manager",
            "controlled_storage_confirmed": True,
            "access_correction_process_confirmed": True,
        },
        "authorizations": {
            "general": {
                "version": "counsel-approved-1",
                "signed_at": "2026-08-01",
                "open_web_disclosed": True,
            },
            "social": {"status": "not_requested"},
        },
        "decision": {"status": "pending", "legal_hold": False},
    }


def extracted_evidence() -> dict:
    return {
        "core": {
            "evidence_available": True,
            "credit_history_available": True,
            "rental_history_available": True,
        },
        "core_facts": [],
        "discrepancies": [],
        "payment_facts": [],
        "public_records": [],
        "accommodation_review_required": False,
        "note": "Synthetic SIN 123-456-789",
        "financial_input": {
            "monthly_rent_cad": "2400.00",
            "exchange_rates": {},
            "incomes": [
                {
                    "applicant_id": "a",
                    "amount": "72000",
                    "period": "annual",
                    "currency": "CAD",
                    "confirmed": True,
                    "recurring": True,
                    "basis": "gross_employment",
                }
            ],
            "debts": [],
        },
    }


class PipelineTests(unittest.TestCase):
    def make_case(self, root: Path, shared_space: bool = False) -> Path:
        (root / "inputs").mkdir()
        (root / "inputs/application-a.pdf").write_bytes(b"%PDF-1.4 synthetic")
        (root / "work").mkdir()
        (root / "case-manifest.json").write_text(
            json.dumps(case_manifest(shared_space)), encoding="utf-8"
        )
        (root / "work/extracted-evidence.json").write_text(
            json.dumps(extracted_evidence()), encoding="utf-8"
        )
        return root

    def test_valid_case_builds_package_after_sanitization(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            case_dir = self.make_case(Path(temporary_directory))

            paths = run_pipeline(case_dir, today=date(2026, 8, 4))

            sanitized = (case_dir / "work/sanitized-evidence.json").read_text()
            assessment = (case_dir / "outputs/assessment.md").read_text()
            financials = json.loads((case_dir / "work/financials.json").read_text())

        self.assertNotIn("123-456-789", sanitized)
        self.assertNotIn("123-456-789", assessment)
        self.assertEqual(
            "6000.00", financials["household"]["gross_monthly_income_cad"]
        )
        self.assertIn("assessment.md", {path.name for path in paths})

    def test_blocking_preflight_does_not_build_assessment(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            case_dir = self.make_case(Path(temporary_directory), shared_space=True)

            paths = run_pipeline(case_dir, today=date(2026, 8, 4))

            preflight = json.loads(
                (case_dir / "outputs/preflight.json").read_text()
            )
            assessment_exists = (case_dir / "outputs/assessment.md").exists()

        self.assertFalse(preflight["can_extract"])
        self.assertFalse(assessment_exists)
        self.assertEqual(["preflight.json"], [path.name for path in paths])

    def test_missing_manifest_writes_preflight_instead_of_crashing(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            case_dir = Path(temporary_directory)

            paths = run_pipeline(case_dir, today=date(2026, 8, 4))
            preflight = json.loads(
                (case_dir / "outputs/preflight.json").read_text(encoding="utf-8")
            )

        self.assertEqual(["preflight.json"], [path.name for path in paths])
        self.assertEqual("MANIFEST_MISSING", preflight["issues"][0]["code"])


if __name__ == "__main__":
    unittest.main()
