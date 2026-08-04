import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.build_report import RECOMMENDATIONS, build_package
from scripts.shared import ValidationIssue, ValidationResult
from scripts.validate_evidence import EvidenceResult


ALLOWED_REASON_CODES = [
    "chronological_first_meeting_uniform_criteria",
    "applicant_withdrew",
    "required_evidence_not_supplied_by_deadline",
    "confirmed_material_conflict",
    "other_requires_explanation",
]


def manifest() -> dict:
    return {
        "case_id": "synthetic-report-001",
        "housing": {
            "address": "100 Example Street, Toronto, ON",
            "monthly_rent_cad": "2400.00",
        },
        "applicants": [
            {"applicant_id": "a", "lease_signer": True},
            {"applicant_id": "b", "lease_signer": True},
        ],
    }


def evidence() -> dict:
    return {
        "core": {
            "evidence_available": True,
            "credit_history_available": True,
            "rental_history_available": True,
        },
        "core_facts": [
            {
                "applicant_id": "a",
                "fact_type": "employment_status",
                "normalized_value": "current",
                "source_file": "inputs/application-a.pdf",
                "location": "page 1",
                "confirmed": True,
                "confidence": "high",
            }
        ],
        "discrepancies": [],
    }


def financials() -> dict:
    return {
        "monthly_rent_cad": "2400.00",
        "applicants": {
            "a": {
                "gross_monthly_income_cad": "6000.00",
                "reported_monthly_debt_cad": "325.00",
                "unknown_monthly_payment_accounts": 0,
                "unknown_monthly_payment_balances": [],
                "limited_income_history": False,
            },
            "b": {
                "gross_monthly_income_cad": "3900.00",
                "reported_monthly_debt_cad": "0.00",
                "unknown_monthly_payment_accounts": 1,
                "unknown_monthly_payment_balances": [
                    {"balance_cad": "5000.00", "original_currency": "CAD"}
                ],
                "limited_income_history": False,
            },
        },
        "household": {
            "gross_monthly_income_cad": "9900.00",
            "reported_monthly_debt_cad": "325.00",
            "unknown_monthly_payment_accounts": 1,
            "unknown_monthly_payment_balances": [],
            "rent_coverage": "covers",
        },
        "exchange_rates": {},
        "excluded_income_records": [],
        "formula_traces": [],
    }


def states() -> EvidenceResult:
    return EvidenceResult(
        integrity_state="no_confirmed_issue",
        payment_state="no_current_negative_payment_evidence_found",
        accepted_public_records=(
            {
                "source_type": "ltb",
                "url": "https://example.invalid/ltb/synthetic-1",
                "identity_matches": ["full_name", "verified_city"],
                "party_role": "tenant",
                "case_type": "synthetic",
                "status": "final",
                "result": "synthetic",
                "finding_against_applicant": True,
            },
        ),
        issues=(),
        requires_accommodation_review=False,
    )


def preflight(can_finalize: bool = True) -> ValidationResult:
    issues = ()
    if not can_finalize:
        issues = (
            ValidationIssue(
                "POLICY_EXPIRED", "blocking_finalization", "Synthetic expiry."
            ),
        )
    return ValidationResult(True, can_finalize, issues)


class BuildReportTests(unittest.TestCase):
    def build(self, case_dir: Path, can_finalize: bool = True) -> list[Path]:
        return build_package(
            case_dir,
            manifest(),
            evidence(),
            financials(),
            states(),
            preflight(can_finalize),
            {"version": "2026.08.03"},
        )

    def test_public_url_is_isolated_from_core_assessment(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            case_dir = Path(temporary_directory)
            self.build(case_dir)

            assessment = (case_dir / "outputs/assessment.md").read_text()
            appendix = (case_dir / "outputs/public-records.md").read_text()

        url = "https://example.invalid/ltb/synthetic-1"
        self.assertNotIn(url, assessment)
        self.assertIn(url, appendix)
        self.assertIn("Not an official criminal record check", appendix)

    def test_unfinalizable_preflight_uses_insufficient_recommendation(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            case_dir = Path(temporary_directory)
            self.build(case_dir, can_finalize=False)
            assessment = (case_dir / "outputs/assessment.md").read_text()

        self.assertIn(RECOMMENDATIONS["insufficient"], assessment)

    def test_core_reports_do_not_direct_a_tenancy_decision(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            case_dir = Path(temporary_directory)
            self.build(case_dir)
            core_text = "\n".join(
                (case_dir / "outputs" / filename).read_text()
                for filename in ("assessment.md", "evidence.json", "discrepancies.md")
            ).lower()

        self.assertNotIn("approve", core_text)
        self.assertNotIn("reject", core_text)

    def test_audit_log_is_json_lines(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            case_dir = Path(temporary_directory)
            self.build(case_dir)
            lines = (case_dir / "outputs/audit.jsonl").read_text().splitlines()

        self.assertGreater(len(lines), 0)
        self.assertTrue(all(isinstance(json.loads(line), dict) for line in lines))

    def test_human_decision_starts_blank_with_allowed_reason_codes(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            case_dir = Path(temporary_directory)
            self.build(case_dir)
            decision = json.loads(
                (case_dir / "outputs/human-decision.json").read_text()
            )

        self.assertEqual("", decision["selected_reason_code"])
        self.assertEqual(ALLOWED_REASON_CODES, decision["allowed_reason_codes"])

    def test_non_recurring_income_is_displayed_separately(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            case_dir = Path(temporary_directory)
            facts = financials()
            facts["excluded_income_records"] = [
                {
                    "applicant_id": "a",
                    "amount": "12000",
                    "currency": "CAD",
                    "period": "annual",
                    "basis": "gross_employment",
                    "reason": "non_recurring",
                }
            ]
            build_package(
                case_dir,
                manifest(),
                evidence(),
                facts,
                states(),
                preflight(),
                {"version": "2026.08.03"},
            )
            assessment = (case_dir / "outputs/assessment.md").read_text()

        self.assertIn("Excluded Income Records", assessment)
        self.assertIn("12000 CAD", assessment)


if __name__ == "__main__":
    unittest.main()
