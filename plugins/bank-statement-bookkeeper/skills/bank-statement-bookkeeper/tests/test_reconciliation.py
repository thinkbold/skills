from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from bookkeeper.contracts import BALANCE_FIELDS
from bookkeeper.ledger import initialize_ledger
from bookkeeper.reconciliation import (
    derive_opening_from_prior_statement,
    reconcile_account_period,
    reconcile_all,
    load_balance_rows,
    validate_period_continuity,
    write_reconciliation_outputs,
)


def transaction(account_id: str, currency: str, date: str, inflow: str, outflow: str) -> dict[str, str]:
    return {
        "transaction_id": f"{account_id}-{currency}-{date}-{inflow}-{outflow}",
        "account_id": account_id,
        "currency": currency,
        "transaction_date": date,
        "posting_date": date,
        "raw_description": "Synthetic merchant private description",
        "inflow": inflow,
        "outflow": outflow,
    }


def balance(**values: str) -> dict[str, str]:
    row = {field: "" for field in BALANCE_FIELDS}
    row.update({
        "account_id": "checking-001", "currency": "CAD",
        "period_start": "2026-01-01", "period_end": "2026-01-31",
        "opening_balance": "1000.00", "closing_balance": "1200.00",
        "opening_source_type": "user_provided", "opening_source_file": "synthetic-balance.txt",
        "opening_source_location": "line 1", "closing_source_file": "synthetic-statement.csv",
        "closing_source_location": "row 9", "confirmed": "true",
    })
    row.update(values)
    return row


class ReconciliationTests(unittest.TestCase):
    def test_exact_decimal_reconciliation_uses_no_binary_float(self) -> None:
        """Catches converting currency values through binary floating point."""
        row = reconcile_account_period(
            account_id="checking-001", currency="CAD", opening_balance=Decimal("1000.00"),
            inflows=(Decimal("250.00"),), outflows=(Decimal("20.00"), Decimal("30.00")),
            reported_closing_balance=Decimal("1200.00"), period_start="2026-01-01",
            period_end="2026-01-31", opening_source_type="prior_year_end_statement",
            opening_source_date="2025-12-31",
        )
        self.assertEqual(Decimal("0.00"), row.difference)
        self.assertTrue(row.reconciled)

    def test_explicit_tolerance_is_the_only_nonzero_difference_allowed(self) -> None:
        """Catches silently accepting a difference without a configured reported tolerance."""
        without_tolerance = reconcile_account_period(
            "checking-001", "CAD", Decimal("1.00"), (), (), Decimal("1.01"),
            "2026-01-01", "2026-01-31", "user_provided", "2026-01-01",
        )
        with_tolerance = reconcile_account_period(
            "checking-001", "CAD", Decimal("1.00"), (), (), Decimal("1.01"),
            "2026-01-01", "2026-01-31", "user_provided", "2026-01-01",
            tolerance=Decimal("0.01"),
        )
        self.assertFalse(without_tolerance.reconciled)
        self.assertTrue(with_tolerance.reconciled)
        self.assertEqual(Decimal("0.01"), with_tolerance.tolerance)

    def test_prior_year_closing_can_supply_opening_only_with_same_unit_and_continuity(self) -> None:
        """Catches deriving an opening from another currency or a non-adjacent statement."""
        opening = derive_opening_from_prior_statement(
            account_id="checking-001", currency="CAD", prior_account_id="checking-001",
            prior_currency="CAD", prior_period_end="2025-12-31",
            prior_closing_balance=Decimal("1000.00"), current_period_start="2026-01-01",
            confirmed=True,
        )
        wrong_currency = derive_opening_from_prior_statement(
            account_id="checking-001", currency="CAD", prior_account_id="checking-001",
            prior_currency="USD", prior_period_end="2025-12-31",
            prior_closing_balance=Decimal("1000.00"), current_period_start="2026-01-01",
            confirmed=True,
        )
        self.assertEqual(Decimal("1000.00"), opening.amount)
        self.assertEqual("prior_year_end_statement", opening.source_type)
        self.assertIsNone(wrong_currency.amount)
        self.assertIn("OPENING_BALANCE_MISSING", {issue.code for issue in wrong_currency.issues})

    def test_prior_year_failures_are_pending_or_coverage_issues(self) -> None:
        """Catches accepting unconfirmed or gapped prior evidence as an opening balance."""
        unconfirmed = derive_opening_from_prior_statement(
            account_id="checking-001", currency="CAD", prior_account_id="checking-001",
            prior_currency="CAD", prior_period_end="2025-12-31",
            prior_closing_balance=Decimal("1000.00"), current_period_start="2026-01-01",
            confirmed=False,
        )
        gapped = derive_opening_from_prior_statement(
            account_id="checking-001", currency="CAD", prior_account_id="checking-001",
            prior_currency="CAD", prior_period_end="2025-12-30",
            prior_closing_balance=Decimal("1000.00"), current_period_start="2026-01-01",
            confirmed=True,
        )
        self.assertIn("BALANCE_UNCONFIRMED", {issue.code for issue in unconfirmed.issues})
        self.assertIn("STATEMENT_COVERAGE_GAP", {issue.code for issue in gapped.issues})

    def test_period_continuity_reports_gaps_and_overlaps_per_account_currency(self) -> None:
        """Catches treating two statements with a gap or overlap as continuous."""
        issues = validate_period_continuity((
            balance(period_end="2026-01-31"),
            balance(period_start="2026-02-02", period_end="2026-02-28"),
            balance(period_start="2026-02-20", period_end="2026-03-20"),
        ))
        self.assertEqual({"STATEMENT_COVERAGE_GAP", "STATEMENT_COVERAGE_OVERLAP"}, {issue.code for issue in issues})

    def test_reconcile_all_requires_one_complete_balance_row_per_imported_period(self) -> None:
        """Catches missing, duplicate, and malformed balance evidence being treated as reconciled."""
        rows = reconcile_all(
            (transaction("checking-001", "CAD", "2026-01-03", "250.00", "0"),),
            (balance(), balance(closing_balance="1200.00"), balance(currency="USD", closing_balance="0.00")),
        )
        cad = next(row for row in rows if row.currency == "CAD")
        self.assertFalse(cad.reconciled)
        self.assertIn("BALANCE_EVIDENCE_DUPLICATE", {issue.code for issue in cad.issues})
        usd = next(row for row in rows if row.currency == "USD")
        self.assertFalse(usd.reconciled)
        self.assertIn("RECONCILIATION_DIFFERENCE", {issue.code for issue in usd.issues})

    def test_balance_amount_without_source_provenance_remains_pending(self) -> None:
        """Catches a bare balance amount being accepted as explicit opening/closing evidence."""
        row = reconcile_all(
            (transaction("checking-001", "CAD", "2026-01-03", "10.00", "0"),),
            (balance(opening_source_file="", opening_source_location="", closing_source_file="", closing_source_location="", opening_balance="100.00", closing_balance="110.00"),),
        )[0]
        self.assertFalse(row.reconciled)
        self.assertEqual({"OPENING_BALANCE_MISSING", "CLOSING_BALANCE_MISSING"}, {issue.code for issue in row.issues})

    def test_unconfirmed_balance_evidence_remains_reconciliation_pending(self) -> None:
        """Catches matching unconfirmed balances being presented as reconciled."""
        row = reconcile_all(
            (transaction("checking-001", "CAD", "2026-01-03", "10.00", "0"),),
            (balance(opening_balance="100.00", closing_balance="110.00", confirmed="false"),),
        )[0]
        self.assertFalse(row.reconciled)
        self.assertIn("BALANCE_UNCONFIRMED", {issue.code for issue in row.issues})

    def test_prior_opening_requires_a_distinct_confirmed_predecessor_row(self) -> None:
        """Catches a current row self-certifying a fabricated prior-year statement date."""
        rows = reconcile_all(
            (transaction("checking-001", "CAD", "2026-01-03", "10.00", "0"),),
            (balance(
                opening_source_type="prior_year_end_statement", opening_source_location="2025-12-31",
                opening_balance="100.00", closing_balance="110.00",
            ),),
        )
        self.assertFalse(rows[0].reconciled)
        self.assertIn("OPENING_BALANCE_MISSING", {issue.code for issue in rows[0].issues})

    def test_prior_opening_is_derived_from_a_confirmed_matching_predecessor(self) -> None:
        """Catches a valid predecessor balance being ignored or counted as another currency."""
        rows = reconcile_all(
            (transaction("checking-001", "CAD", "2026-01-03", "10.00", "0"),),
            (
                balance(period_start="2025-12-01", period_end="2025-12-31", opening_balance="100.00", closing_balance="100.00", opening_source_type="user_provided"),
                balance(opening_balance="", closing_balance="110.00", opening_source_type="prior_year_end_statement", opening_source_location="2025-12-31"),
            ),
        )
        current = next(row for row in rows if row.period_start == "2026-01-01")
        self.assertEqual(Decimal("100.00"), current.opening_balance)
        self.assertTrue(current.reconciled)

    def test_prior_opening_mismatch_or_unconfirmed_predecessor_cannot_reconcile(self) -> None:
        """Catches contradictory or unconfirmed predecessor evidence being trusted."""
        mismatch = reconcile_all(
            (), (
                balance(period_start="2025-12-01", period_end="2025-12-31", opening_balance="100.00", closing_balance="100.00"),
                balance(opening_balance="99.00", closing_balance="99.00", opening_source_type="prior_year_end_statement", opening_source_location="2025-12-31"),
            ),
        )
        unconfirmed = reconcile_all(
            (), (
                balance(period_start="2025-12-01", period_end="2025-12-31", opening_balance="100.00", closing_balance="100.00", confirmed="false"),
                balance(opening_balance="", closing_balance="100.00", opening_source_type="prior_year_end_statement", opening_source_location="2025-12-31"),
            ),
        )
        mismatch_current = next(row for row in mismatch if row.period_start == "2026-01-01")
        unconfirmed_current = next(row for row in unconfirmed if row.period_start == "2026-01-01")
        self.assertTrue(any(issue.blocking for issue in mismatch_current.issues))
        self.assertIn("OPENING_BALANCE_MISSING", {issue.code for issue in unconfirmed_current.issues})

    def test_prior_opening_cannot_use_an_unreconciled_predecessor(self) -> None:
        """Catches a finite closing on an invalid predecessor unlocking a later period."""
        rows = reconcile_all((), (
            balance(period_start="2025-12-01", period_end="2025-12-31", opening_balance="90.00", closing_balance="101.00"),
            balance(opening_balance="", closing_balance="100.00", opening_source_type="prior_year_end_statement", opening_source_location="2025-12-31"),
        ))
        current = next(row for row in rows if row.period_start == "2026-01-01")
        self.assertFalse(current.reconciled)
        self.assertIn("OPENING_BALANCE_MISSING", {issue.code for issue in current.issues})

    def test_truncated_and_overlong_balance_csv_are_blocking_not_unexpected(self) -> None:
        """Catches DictReader None cells escaping balance schema validation."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
            path = ledger / "inputs" / "account-balances.csv"
            header = ",".join(BALANCE_FIELDS)
            path.write_text(header + "\n" + ",".join(("checking", "CAD")) + "\n", encoding="utf-8")
            _, truncated = load_balance_rows(ledger)
            path.write_text(header + "\n" + ",".join(("checking", "CAD") + ("x",) * len(BALANCE_FIELDS)) + "\n", encoding="utf-8")
            _, overlong = load_balance_rows(ledger)
            self.assertEqual("BALANCE_SCHEMA_INVALID", truncated[0].code)
            self.assertEqual("BALANCE_SCHEMA_INVALID", overlong[0].code)

    def test_reconcile_all_keeps_cad_and_usd_independent(self) -> None:
        """Catches netting different currencies together when reconciling a shared account."""
        rows = reconcile_all(
            (
                transaction("checking-001", "CAD", "2026-01-03", "10.00", "0"),
                transaction("checking-001", "USD", "2026-01-03", "0", "10.00"),
            ),
            (
                balance(currency="CAD", opening_balance="100.00", closing_balance="110.00"),
                balance(currency="USD", opening_balance="50.00", closing_balance="40.00"),
            ),
        )
        self.assertEqual({("checking-001", "CAD"), ("checking-001", "USD")}, {(row.account_id, row.currency) for row in rows})
        self.assertTrue(all(row.reconciled for row in rows))

    def test_prior_source_date_without_predecessor_row_remains_pending(self) -> None:
        """Catches a current balance row impersonating its missing predecessor statement."""
        row = reconcile_all(
            (transaction("checking-001", "CAD", "2026-01-03", "10.00", "0"),),
            (balance(
                opening_source_type="prior_year_end_statement", opening_source_location="2025-12-31",
                opening_balance="100.00", closing_balance="110.00",
            ),),
        )[0]
        self.assertFalse(row.reconciled)
        self.assertIn("OPENING_BALANCE_MISSING", {issue.code for issue in row.issues})
        self.assertEqual("2025-12-31", row.opening_source_date)

    def test_transaction_outside_statement_coverage_is_blocking(self) -> None:
        """Catches activity outside supplied statement periods being silently omitted."""
        rows = reconcile_all(
            (transaction("checking-001", "CAD", "2026-02-03", "10.00", "0"),),
            (balance(),),
        )
        uncovered = next(row for row in rows if row.period_start == "2026-02-03")
        self.assertFalse(uncovered.reconciled)
        self.assertIn("STATEMENT_COVERAGE_GAP", {issue.code for issue in uncovered.issues})
        self.assertTrue(any(issue.blocking for issue in uncovered.issues))

    def test_outputs_are_masked_and_report_each_currency_separately(self) -> None:
        """Catches reports exposing descriptions or combining CAD and USD totals."""
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger"
            initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
            rows = reconcile_all(
                (transaction("checking-001", "CAD", "2026-01-03", "10.00", "0"), transaction("checking-001", "USD", "2026-01-03", "0", "10.00")),
                (balance(currency="CAD", opening_balance="100.00", closing_balance="110.00"), balance(currency="USD", opening_balance="50.00", closing_balance="40.00")),
            )
            write_reconciliation_outputs(ledger, rows, "complete", {"checking-001": "********9012"})
            report = (ledger / "outputs" / "reconciliation-report.md").read_text(encoding="utf-8")
            self.assertIn("Currency: CAD", report)
            self.assertIn("Currency: USD", report)
            self.assertNotIn("Synthetic merchant private description", report)
            self.assertNotIn("checking-001", report)


if __name__ == "__main__":
    unittest.main()
