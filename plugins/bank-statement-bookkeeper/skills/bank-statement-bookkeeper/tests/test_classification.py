from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from bookkeeper.classification import (
    apply_exact_rules,
    build_pending_groups,
    confirm_group,
    correct_transactions,
    deactivate_rule,
    delete_rule,
    export_rules,
    load_chart,
    load_rules,
    normalize_merchant,
    suggest_fuzzy_rules,
)
from bookkeeper.contracts import CANONICAL_TRANSACTION_FIELDS, MERCHANT_RULE_FIELDS
from bookkeeper.ledger import initialize_ledger
from bookkeeper.storage import atomic_write_csv, read_audit_events, read_csv_rows


def row(transaction_id: str, account_id: str, currency: str, description: str, amount: str, date: str) -> dict[str, str]:
    return {
        "transaction_id": transaction_id, "account_id": account_id, "currency": currency,
        "transaction_date": date, "posting_date": date, "raw_description": description,
        "normalized_merchant": "", "inflow": "0", "outflow": amount,
        "running_balance": "0", "reference": "", "source_file": "synthetic.csv",
        "source_page_or_row": transaction_id, "extraction_method": "local_csv",
        "extraction_confidence": "high", "classification_status": "unclassified",
        "account_code": "", "account_name": "", "rule_id": "", "review_note": "",
        "source_locations": f"synthetic.csv:{transaction_id}",
    }


class ClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.ledger = Path(self.temp.name) / "ledger-a"
        self.other_ledger = Path(self.temp.name) / "ledger-b"
        initialize_ledger(self.ledger, "ledger-a", "Synthetic A", "CAD")
        initialize_ledger(self.other_ledger, "ledger-b", "Synthetic B", "CAD")
        with (self.ledger / "chart-of-accounts.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=("account_code", "account_name", "active"))
            writer.writeheader()
            writer.writerows((
                {"account_code": "6100", "account_name": "Membership Fee", "active": "true"},
                {"account_code": "6999", "account_name": "Retired", "active": "false"},
                {"account_code": "6200", "account_name": "Software", "active": "true"},
            ))
        self.openai_rows = (
            row("cad-openai", "checking", "CAD", "OPENAI *CHATGPT SUBSCRIPTION 9F3A2", "20.00", "2026-01-05"),
            row("usd-openai", "card", "USD", "OPENAI *CHATGPT SUBSCRIPTION 7H4K9", "30.00", "2026-01-06"),
        )
        self.fuzzy_row = row("fuzzy", "checking", "CAD", "OPENAL CHATGPT SUBSCRIPTION", "12.00", "2026-01-07")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_normalization_removes_terminal_references_but_preserves_words(self) -> None:
        """Catches normalization keeping random terminal references or deleting merchant words."""
        self.assertEqual("OPENAI CHATGPT SUBSCRIPTION", normalize_merchant("OPENAI *CHATGPT SUBSCRIPTION 9F3A2"))
        self.assertEqual("OPENAI CHATGPT SUBSCRIPTION", normalize_merchant("OPENAI *CHATGPT SUBSCRIPTION 7H4K9"))
        self.assertEqual("CAFE 2026 MARKET", normalize_merchant("Caf\u00e9 2026 Market"))

    def test_pending_group_keeps_currency_totals_separate(self) -> None:
        """Catches a merchant review question combining CAD and USD into one monetary total."""
        groups = build_pending_groups(self.openai_rows)
        self.assertEqual(1, len(groups))
        group = groups[0]
        self.assertEqual(("CAD", "USD"), group.currencies)
        self.assertEqual((("CAD", "20.00"), ("USD", "30.00")), group.totals_by_currency)
        self.assertEqual(("card", "checking"), group.account_ids)
        self.assertNotIn("total", group.__dict__)

    def test_confirmation_classifies_group_and_creates_one_cross_currency_rule(self) -> None:
        """Catches a confirmation skipping current rows or making currency-specific duplicate rules."""
        result = confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        self.assertEqual({"classified"}, {item["classification_status"] for item in result.transactions})
        self.assertEqual(1, len(result.created_rules))
        self.assertEqual(1, len(load_rules(self.ledger)))
        self.assertEqual({"6100"}, {item["account_code"] for item in result.transactions})

    def test_confirmation_without_future_rule_only_changes_selected_rows(self) -> None:
        """Catches a one-time answer unexpectedly becoming future classification memory."""
        result = confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", False, "user")
        self.assertEqual({"classified"}, {item["classification_status"] for item in result.transactions})
        self.assertEqual((), result.created_rules)
        self.assertEqual([], load_rules(self.ledger))

    def test_repeat_future_confirmation_reuses_the_existing_rule(self) -> None:
        """Catches repeated confirmation growing duplicate identical exact rules."""
        confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        repeated = confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        self.assertEqual((), repeated.created_rules)
        self.assertEqual(1, len(load_rules(self.ledger)))

    def test_rules_and_chart_are_ledger_local(self) -> None:
        """Catches classification memory or a chart leaking into another company ledger."""
        confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        self.assertEqual([], load_rules(self.other_ledger))
        self.assertEqual((), load_chart(self.other_ledger))

    def test_chart_rejects_unknown_or_inactive_code_and_requires_free_form_name_without_chart(self) -> None:
        """Catches classifications bypassing a supplied chart or allowing an unnamed category."""
        with self.assertRaisesRegex(ValueError, "account code is not active"):
            confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "9999", "Invented", True, "user")
        with self.assertRaisesRegex(ValueError, "account code is not active"):
            confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6999", "Retired", True, "user")
        no_chart = Path(self.temp.name) / "no-chart"
        initialize_ledger(no_chart, "no-chart", "No Chart", "CAD")
        with self.assertRaisesRegex(ValueError, "account name is required"):
            confirm_group(no_chart, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "", "", False, "user")
        result = confirm_group(no_chart, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "", "Subscriptions", False, "user")
        self.assertEqual({"Subscriptions"}, {item["account_name"] for item in result.transactions})

    def test_exact_conflict_leaves_row_unclassified_and_scopes_only_after_conflict(self) -> None:
        """Catches ambiguous exact rules silently classifying a transaction or prematurely scoping rules."""
        rule_a = {field: "" for field in MERCHANT_RULE_FIELDS}
        rule_a.update({"rule_id": "r-a", "normalized_merchant": "OPENAI CHATGPT SUBSCRIPTION", "direction": "outflow", "account_code": "6100", "account_name": "Membership Fee", "match_type": "exact_normalized", "status": "active"})
        rule_b = {**rule_a, "rule_id": "r-b", "account_code": "6200", "account_name": "Software"}
        atomic_write_csv(self.ledger / "merchant-rules.csv", MERCHANT_RULE_FIELDS, (rule_a, rule_b))
        result = apply_exact_rules((self.openai_rows[0],), load_rules(self.ledger))
        self.assertEqual("unclassified", result.transactions[0]["classification_status"])
        self.assertEqual("MERCHANT_RULE_CONFLICT", result.issues[0].code)
        corrected = correct_transactions(self.ledger, result.transactions, ("cad-openai",), "6200", "Software", "future_rule", "user")
        self.assertEqual("checking", corrected.created_rules[0]["account_scope"])

    def test_fuzzy_suggestion_never_applies_a_rule(self) -> None:
        """Catches a fuzzy ranking path accidentally classifying a real transaction."""
        confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        rules = load_rules(self.ledger)
        result = apply_exact_rules((self.fuzzy_row,), rules)
        suggestions = suggest_fuzzy_rules("OPENAL CHATGPT SUBSCRIPTION", rules)
        self.assertGreater(len(suggestions), 0)
        self.assertEqual("unclassified", result.transactions[0]["classification_status"])

    def test_correction_scopes_and_rule_lifecycle_are_auditable(self) -> None:
        """Catches scope corrections changing future behavior incorrectly or lifecycle actions lacking audit history."""
        confirmed = confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        selected = correct_transactions(self.ledger, confirmed.transactions, ("cad-openai",), "6200", "Software", "selected", "user")
        self.assertEqual("6200", next(item for item in selected.transactions if item["transaction_id"] == "cad-openai")["account_code"])
        self.assertEqual(1, len(load_rules(self.ledger)))
        future = correct_transactions(self.ledger, selected.transactions, ("usd-openai",), "6200", "Software", "future_rule", "user")
        active = [item for item in load_rules(self.ledger) if item["status"] == "active"]
        self.assertEqual(1, len(active))
        self.assertEqual("6200", active[0]["account_code"])
        self.assertEqual("", active[0]["account_scope"])
        deactivate_rule(self.ledger, active[0]["rule_id"], "user")
        self.assertEqual("inactive", load_rules(self.ledger)[-1]["status"])
        delete_rule(self.ledger, active[0]["rule_id"], "user")
        self.assertEqual({"inactive"}, {item["status"] for item in load_rules(self.ledger)})
        event_types = [event["event_type"] for event in read_audit_events(self.ledger)]
        self.assertIn("merchant_rule_deactivated", event_types)
        self.assertIn("merchant_rule_deleted", event_types)

    def test_export_and_non_pending_outputs_do_not_contain_descriptions(self) -> None:
        """Catches raw statement descriptions escaping through rule export or audit records."""
        confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        output = export_rules(self.ledger, "work/exported-rules.csv")
        self.assertTrue(output.is_file())
        self.assertNotIn("9F3A2", output.read_text(encoding="utf-8"))
        self.assertNotIn("9F3A2", str(read_audit_events(self.ledger)))

    def test_pending_cli_shows_review_descriptions_but_rules_cli_does_not(self) -> None:
        """Catches the review command hiding required samples or another command leaking them."""
        atomic_write_csv(self.ledger / "work" / "normalized-transactions.csv", CANONICAL_TRANSACTION_FIELDS, self.openai_rows)
        command = [sys.executable, str(SKILL_ROOT / "scripts" / "classify_transactions.py")]
        pending = subprocess.run(command + ["pending", str(self.ledger)], check=True, capture_output=True, text=True)
        self.assertIn("9F3A2", pending.stdout)
        confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        rules = subprocess.run(command + ["rules", str(self.ledger)], check=True, capture_output=True, text=True)
        self.assertEqual(1, json.loads(rules.stdout)["rule_count"])
        self.assertNotIn("9F3A2", rules.stdout)


if __name__ == "__main__":
    unittest.main()
