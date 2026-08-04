import unittest

from scripts.calculate_financials import calculate_financials
from scripts.shared import AssessmentError


class FinancialCalculationTests(unittest.TestCase):
    def test_joint_income_and_monthly_debt_stay_separate(self) -> None:
        evidence = {
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
                },
                {
                    "applicant_id": "b",
                    "amount": "1800",
                    "period": "biweekly",
                    "currency": "CAD",
                    "confirmed": True,
                    "recurring": True,
                    "basis": "gross_employment",
                },
            ],
            "debts": [
                {
                    "applicant_id": "a",
                    "balance": "10000",
                    "monthly_payment": "325",
                    "currency": "CAD",
                    "confirmed": True,
                },
                {
                    "applicant_id": "b",
                    "balance": "5000",
                    "monthly_payment": None,
                    "currency": "CAD",
                    "confirmed": True,
                },
            ],
        }

        result = calculate_financials(evidence)

        self.assertEqual(
            "9900.00", result["household"]["gross_monthly_income_cad"]
        )
        self.assertEqual(
            "325.00", result["household"]["reported_monthly_debt_cad"]
        )
        self.assertEqual(
            1, result["household"]["unknown_monthly_payment_accounts"]
        )
        self.assertEqual("covers", result["household"]["rent_coverage"])
        self.assertNotIn("debt_to_income", str(result))
        self.assertNotIn("rent_to_income", str(result))

    def test_variable_income_uses_observed_months(self) -> None:
        result = calculate_financials(
            {
                "monthly_rent_cad": "2000",
                "exchange_rates": {},
                "incomes": [
                    {
                        "applicant_id": "a",
                        "amount": "15000",
                        "period": "period_total",
                        "months_covered": 5,
                        "currency": "CAD",
                        "confirmed": True,
                        "recurring": True,
                        "basis": "gross_employment",
                    }
                ],
                "debts": [],
            }
        )

        self.assertEqual(
            "3000.00", result["applicants"]["a"]["gross_monthly_income_cad"]
        )
        self.assertTrue(result["applicants"]["a"]["limited_income_history"])

    def test_unconfirmed_income_does_not_enter_total(self) -> None:
        result = calculate_financials(
            {
                "monthly_rent_cad": "2000",
                "exchange_rates": {},
                "incomes": [
                    {
                        "applicant_id": "a",
                        "amount": "6000",
                        "period": "monthly",
                        "currency": "CAD",
                        "confirmed": False,
                        "recurring": True,
                        "basis": "gross_employment",
                    }
                ],
                "debts": [],
            }
        )

        self.assertEqual(
            "0.00", result["household"]["gross_monthly_income_cad"]
        )
        self.assertEqual(
            "insufficient_evidence", result["household"]["rent_coverage"]
        )

    def test_foreign_income_uses_recorded_rate(self) -> None:
        result = calculate_financials(
            {
                "monthly_rent_cad": "2000",
                "exchange_rates": {
                    "USD": {
                        "rate_to_cad": "1.40",
                        "date": "2026-08-04",
                        "source": "Bank of Canada",
                    }
                },
                "incomes": [
                    {
                        "applicant_id": "a",
                        "amount": "3000",
                        "period": "monthly",
                        "currency": "USD",
                        "confirmed": True,
                        "recurring": True,
                        "basis": "gross_employment",
                    }
                ],
                "debts": [],
            }
        )

        self.assertEqual(
            "4200.00", result["household"]["gross_monthly_income_cad"]
        )

    def test_self_employment_uses_net_business_before_personal_tax(self) -> None:
        result = calculate_financials(
            {
                "monthly_rent_cad": "2000",
                "exchange_rates": {},
                "incomes": [
                    {
                        "applicant_id": "a",
                        "amount": "48000",
                        "period": "annual",
                        "currency": "CAD",
                        "confirmed": True,
                        "recurring": True,
                        "basis": "net_business_before_personal_tax",
                    }
                ],
                "debts": [],
            }
        )

        self.assertEqual(
            "4000.00", result["household"]["gross_monthly_income_cad"]
        )

    def test_one_time_income_is_excluded(self) -> None:
        result = calculate_financials(
            {
                "monthly_rent_cad": "2000",
                "exchange_rates": {},
                "incomes": [
                    {
                        "applicant_id": "a",
                        "amount": "12000",
                        "period": "monthly",
                        "currency": "CAD",
                        "confirmed": True,
                        "recurring": False,
                        "basis": "gross_employment",
                    }
                ],
                "debts": [],
            }
        )

        self.assertEqual(
            "0.00", result["household"]["gross_monthly_income_cad"]
        )
        self.assertEqual(1, len(result["excluded_income_records"]))
        self.assertEqual(
            {
                "applicant_id": "a",
                "amount": "12000",
                "currency": "CAD",
                "period": "monthly",
                "basis": "gross_employment",
                "reason": "non_recurring",
            },
            result["excluded_income_records"][0],
        )

    def test_negative_monthly_debt_is_rejected(self) -> None:
        with self.assertRaisesRegex(AssessmentError, "cannot be negative"):
            calculate_financials(
                {
                    "monthly_rent_cad": "2000",
                    "exchange_rates": {},
                    "incomes": [],
                    "debts": [
                        {
                            "applicant_id": "a",
                            "balance": "100",
                            "monthly_payment": "-25",
                            "currency": "CAD",
                            "confirmed": True,
                        }
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
