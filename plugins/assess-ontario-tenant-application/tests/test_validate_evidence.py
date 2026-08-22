from datetime import date
import unittest

from scripts.validate_evidence import validate_and_classify


def manifest(status: str = "not_requested") -> dict:
    social = {"status": status}
    if status == "granted":
        social["platforms"] = ["facebook", "linkedin"]
    return {
        "authorizations": {
            "general": {"open_web_disclosed": True},
            "social": social,
        }
    }


def evidence() -> dict:
    return {
        "core": {"evidence_available": True},
        "discrepancies": [],
        "payment_facts": [],
        "public_records": [],
        "accommodation_review_required": False,
    }


class EvidencePolicyTests(unittest.TestCase):
    def test_missing_history_is_limited_not_negative(self) -> None:
        data = evidence()
        data["core"].update(
            credit_history_available=False, rental_history_available=False
        )

        result = validate_and_classify(data, manifest())

        self.assertEqual("limited_evidence", result.payment_state)

    def test_verified_current_payment_fact_requires_review(self) -> None:
        data = evidence()
        data["payment_facts"] = [
            {
                "kind": "current_delinquency",
                "verified": True,
                "current": True,
                "source_surface": "core",
            }
        ]

        result = validate_and_classify(data, manifest())

        self.assertEqual(
            "negative_payment_evidence_requires_human_review",
            result.payment_state,
        )

    def test_ltb_record_never_changes_core_state(self) -> None:
        data = evidence()
        data["public_records"] = [
            {
                "source_type": "ltb",
                "url": "https://example.invalid/ltb/1",
                "identity_matches": ["full_name", "verified_city"],
                "party_role": "tenant",
                "case_type": "synthetic",
                "status": "final",
                "result": "synthetic",
                "finding_against_applicant": True,
            }
        ]

        result = validate_and_classify(data, manifest())

        self.assertEqual(
            "no_current_negative_payment_evidence_found", result.payment_state
        )
        self.assertEqual(1, len(result.accepted_public_records))

    def test_social_record_requires_separate_consent(self) -> None:
        data = evidence()
        data["public_records"] = [
            {
                "source_type": "linkedin",
                "url": "https://linkedin.example.invalid/profile",
                "identity_matches": ["full_name", "verified_employer"],
                "permitted_facts": {"declared_employer_matches": True},
            }
        ]

        result = validate_and_classify(data, manifest("not_requested"))

        self.assertEqual((), result.accepted_public_records)
        self.assertIn(
            "SOCIAL_CONSENT_REQUIRED", [issue.code for issue in result.issues]
        )

    def test_one_identity_match_is_hidden(self) -> None:
        data = evidence()
        data["public_records"] = [
            {
                "source_type": "news",
                "url": "https://example.invalid/1",
                "identity_matches": ["full_name"],
            }
        ]

        result = validate_and_classify(data, manifest())

        self.assertEqual((), result.accepted_public_records)

    def test_accommodation_signal_stops_classification(self) -> None:
        data = evidence()
        data["accommodation_review_required"] = True

        result = validate_and_classify(data, manifest())

        self.assertTrue(result.requires_accommodation_review)
        self.assertEqual("unable_to_assess", result.payment_state)

    def test_applicant_supplied_credit_report_is_not_verified(self) -> None:
        data = evidence()
        data["core"]["credit_report"] = {
            "acquisition": "applicant_supplied",
            "generated_at": "2026-08-01",
            "score": 720,
        }

        result = validate_and_classify(
            data, manifest(), today=date(2026, 8, 4)
        )

        self.assertIn(
            "CREDIT_REPORT_UNVERIFIED", [issue.code for issue in result.issues]
        )

    def test_stale_credit_report_cannot_create_negative_evidence(self) -> None:
        data = evidence()
        data["core"]["credit_report"] = {
            "acquisition": "manager_authorized",
            "generated_at": "2026-06-01",
            "score": 500,
        }
        data["payment_facts"] = [
            {
                "kind": "current_delinquency",
                "verified": True,
                "current": True,
                "source_surface": "core",
                "source_id": "credit-report",
            }
        ]

        result = validate_and_classify(
            data, manifest(), today=date(2026, 8, 4)
        )

        self.assertNotEqual(
            "negative_payment_evidence_requires_human_review",
            result.payment_state,
        )
        self.assertIn("CREDIT_REPORT_STALE", [issue.code for issue in result.issues])

    def test_credit_score_alone_never_changes_state(self) -> None:
        data = evidence()
        data["core"]["credit_report"] = {
            "acquisition": "manager_authorized",
            "generated_at": "2026-08-01",
            "score": 400,
        }

        result = validate_and_classify(
            data, manifest(), today=date(2026, 8, 4)
        )

        self.assertEqual(
            "no_current_negative_payment_evidence_found", result.payment_state
        )

    def test_protected_public_record_is_hidden(self) -> None:
        data = evidence()
        data["public_records"] = [
            {
                "source_type": "news",
                "url": "https://example.invalid/2",
                "identity_matches": ["full_name", "verified_city"],
                "religion": "synthetic",
            }
        ]

        result = validate_and_classify(data, manifest())

        self.assertEqual((), result.accepted_public_records)
        self.assertIn(
            "PUBLIC_RECORD_PROTECTED_DATA",
            [issue.code for issue in result.issues],
        )

    def test_identity_matches_must_be_a_list(self) -> None:
        data = evidence()
        data["public_records"] = [
            {
                "source_type": "news",
                "url": "https://example.invalid/string-matches",
                "identity_matches": "full_name",
            }
        ]

        result = validate_and_classify(data, manifest())

        self.assertEqual((), result.accepted_public_records)

    def test_social_excerpt_is_not_an_allowed_identity_fact(self) -> None:
        data = evidence()
        data["public_records"] = [
            {
                "source_type": "linkedin",
                "url": "https://linkedin.example.invalid/profile",
                "identity_matches": ["full_name", "verified_employer"],
                "permitted_facts": {"declared_employer_matches": True},
                "excerpt": "Synthetic post content",
            }
        ]

        result = validate_and_classify(data, manifest("granted"))

        self.assertEqual((), result.accepted_public_records)
        self.assertIn("SOCIAL_FIELD_NOT_ALLOWED", [item.code for item in result.issues])

    def test_every_unresolved_discrepancy_goes_to_human_review(self) -> None:
        data = evidence()
        data["discrepancies"] = [
            {
                "classification": "minor_difference",
                "human_disposition": "",
            }
        ]

        result = validate_and_classify(data, manifest())

        self.assertEqual("clarification_pending", result.integrity_state)

    def test_unconfirmed_recurring_income_goes_to_human_review(self) -> None:
        data = evidence()
        data["financial_input"] = {
            "incomes": [
                {
                    "confirmed": False,
                    "recurring": True,
                    "amount": "5000",
                }
            ],
            "debts": [],
        }

        result = validate_and_classify(data, manifest())

        self.assertEqual("clarification_pending", result.integrity_state)
        self.assertIn("CRITICAL_VALUE_UNCONFIRMED", [item.code for item in result.issues])

    def test_future_dated_credit_report_is_not_current(self) -> None:
        data = evidence()
        data["core"]["credit_report"] = {
            "acquisition": "manager_authorized",
            "generated_at": "2026-08-05",
            "score": 720,
        }

        result = validate_and_classify(
            data, manifest(), today=date(2026, 8, 4)
        )

        self.assertIn("CREDIT_REPORT_FUTURE_DATE", [item.code for item in result.issues])


if __name__ == "__main__":
    unittest.main()
