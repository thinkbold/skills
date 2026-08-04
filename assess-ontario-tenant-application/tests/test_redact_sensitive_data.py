import unittest

from scripts.redact_sensitive_data import sanitize_value


class RedactionTests(unittest.TestCase):
    def test_redacts_common_sin_formats(self) -> None:
        result = sanitize_value({"note": "SIN 123-456-789 and 987 654 321"})

        self.assertNotIn("123-456-789", str(result.value))
        self.assertNotIn("987 654 321", str(result.value))
        self.assertEqual(2, len(result.findings))

    def test_isolates_protected_keys(self) -> None:
        result = sanitize_value(
            {
                "applicant_id": "a",
                "religion": "synthetic",
                "marital_status": "synthetic",
                "income": "5000.00",
            }
        )

        self.assertEqual(
            {"applicant_id": "a", "income": "5000.00"}, result.value
        )

    def test_birth_date_becomes_match_state(self) -> None:
        result = sanitize_value({"birth_date": "1990-01-02"})

        self.assertEqual(
            {"identity_birth_date_match": "not_confirmed"}, result.value
        )

    def test_protected_key_matching_is_case_and_separator_insensitive(self) -> None:
        result = sanitize_value(
            {
                "Applicant_ID": "a",
                "Religion": "synthetic",
                "Marital Status": "synthetic",
            }
        )

        self.assertEqual({"Applicant_ID": "a"}, result.value)


if __name__ == "__main__":
    unittest.main()
