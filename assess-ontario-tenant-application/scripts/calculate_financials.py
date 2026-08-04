"""Calculate confirmed financial facts with Decimal arithmetic."""

import argparse
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from scripts.shared import AssessmentError, load_json, parse_decimal, write_json


CENT = Decimal("0.01")
PERIOD_MULTIPLIERS = {
    "annual": Decimal(1) / Decimal(12),
    "monthly": Decimal(1),
    "semimonthly": Decimal(2),
    "biweekly": Decimal(26) / Decimal(12),
    "weekly": Decimal(52) / Decimal(12),
}


def money(value: Decimal) -> str:
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def to_cad(
    amount: Decimal, currency: str, rates: dict[str, Any]
) -> Decimal:
    if currency == "CAD":
        return amount
    if currency not in rates:
        raise AssessmentError(f"Missing Bank of Canada rate for {currency}")
    return amount * parse_decimal(
        rates[currency]["rate_to_cad"], f"exchange_rates.{currency}"
    )


def monthly_income(
    record: dict[str, Any], rates: dict[str, Any]
) -> tuple[Decimal, bool]:
    if not record.get("confirmed") or not record.get("recurring"):
        return Decimal(0), False
    if record.get("basis") not in {
        "gross_employment",
        "net_business_before_personal_tax",
    }:
        raise AssessmentError("Unsupported income basis")
    amount = to_cad(
        parse_decimal(record["amount"], "income.amount"),
        record["currency"],
        rates,
    )
    period = record["period"]
    if period == "period_total":
        months = int(record["months_covered"])
        if months < 1 or months > 12:
            raise AssessmentError("months_covered must be between 1 and 12")
        return amount / Decimal(months), months < 12
    if period not in PERIOD_MULTIPLIERS:
        raise AssessmentError(f"Unsupported income period: {period}")
    return amount * PERIOD_MULTIPLIERS[period], False


def _new_applicant() -> dict[str, Any]:
    return {
        "income": Decimal(0),
        "debt": Decimal(0),
        "unknown_count": 0,
        "unknown_balances": [],
        "limited_income_history": False,
        "confirmed_income_records": 0,
    }


def calculate_financials(evidence: dict[str, Any]) -> dict[str, Any]:
    rates = evidence.get("exchange_rates", {})
    rent = parse_decimal(evidence["monthly_rent_cad"], "monthly_rent_cad")
    applicants: dict[str, dict[str, Any]] = {}
    excluded_income_records: list[dict[str, str]] = []
    formula_traces: list[dict[str, str]] = []

    for record in evidence.get("incomes", []):
        applicant_id = str(record["applicant_id"])
        applicant = applicants.setdefault(applicant_id, _new_applicant())
        normalized, limited = monthly_income(record, rates)
        if not record.get("confirmed") or not record.get("recurring"):
            reason = "unconfirmed" if not record.get("confirmed") else "non_recurring"
            excluded_income_records.append(
                {"applicant_id": applicant_id, "reason": reason}
            )
            continue
        if normalized < 0:
            raise AssessmentError("Monthly income cannot be negative")
        applicant["income"] += normalized
        applicant["limited_income_history"] |= limited
        applicant["confirmed_income_records"] += 1
        formula_traces.append(
            {
                "kind": "income",
                "applicant_id": applicant_id,
                "formula": f"{record['amount']} {record['currency']} / {record['period']}",
                "monthly_amount_cad": money(normalized),
            }
        )

    for record in evidence.get("debts", []):
        applicant_id = str(record["applicant_id"])
        applicant = applicants.setdefault(applicant_id, _new_applicant())
        if not record.get("confirmed"):
            continue
        currency = record["currency"]
        monthly_payment = record.get("monthly_payment")
        if monthly_payment is None:
            balance = to_cad(
                parse_decimal(record["balance"], "debt.balance"), currency, rates
            )
            if balance < 0:
                raise AssessmentError("Debt balance cannot be negative")
            applicant["unknown_count"] += 1
            applicant["unknown_balances"].append(
                {
                    "balance_cad": money(balance),
                    "original_balance": str(record["balance"]),
                    "original_currency": currency,
                }
            )
            continue

        payment = to_cad(
            parse_decimal(monthly_payment, "debt.monthly_payment"), currency, rates
        )
        if payment < 0:
            raise AssessmentError("Monthly debt payment cannot be negative")
        applicant["debt"] += payment
        formula_traces.append(
            {
                "kind": "debt",
                "applicant_id": applicant_id,
                "formula": f"explicit monthly payment {monthly_payment} {currency}",
                "monthly_amount_cad": money(payment),
            }
        )

    household_income = sum(
        (applicant["income"] for applicant in applicants.values()), Decimal(0)
    )
    household_debt = sum(
        (applicant["debt"] for applicant in applicants.values()), Decimal(0)
    )
    confirmed_income_records = sum(
        applicant["confirmed_income_records"] for applicant in applicants.values()
    )
    unknown_balances = [
        {"applicant_id": applicant_id, **balance}
        for applicant_id, applicant in applicants.items()
        for balance in applicant["unknown_balances"]
    ]

    if confirmed_income_records == 0:
        rent_coverage = "insufficient_evidence"
    elif household_income >= rent:
        rent_coverage = "covers"
    else:
        rent_coverage = "does_not_cover"

    applicant_output = {
        applicant_id: {
            "gross_monthly_income_cad": money(applicant["income"]),
            "reported_monthly_debt_cad": money(applicant["debt"]),
            "unknown_monthly_payment_accounts": applicant["unknown_count"],
            "unknown_monthly_payment_balances": applicant["unknown_balances"],
            "limited_income_history": applicant["limited_income_history"],
        }
        for applicant_id, applicant in applicants.items()
    }
    return {
        "monthly_rent_cad": money(rent),
        "applicants": applicant_output,
        "household": {
            "gross_monthly_income_cad": money(household_income),
            "reported_monthly_debt_cad": money(household_debt),
            "unknown_monthly_payment_accounts": len(unknown_balances),
            "unknown_monthly_payment_balances": unknown_balances,
            "rent_coverage": rent_coverage,
        },
        "exchange_rates": rates,
        "excluded_income_records": excluded_income_records,
        "formula_traces": formula_traces,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path)
    args = parser.parse_args()

    sanitized = load_json(args.case_dir / "work/sanitized-evidence.json")
    result = calculate_financials(sanitized["financial_input"])
    write_json(args.case_dir / "work/financials.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
