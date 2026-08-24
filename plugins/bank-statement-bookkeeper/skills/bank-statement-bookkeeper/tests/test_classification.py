from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


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
import bookkeeper.classification as classification
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

    @staticmethod
    def ledger_bytes(ledger: Path) -> dict[str, bytes]:
        return {
            path.relative_to(ledger).as_posix(): path.read_bytes()
            for path in sorted(ledger.rglob("*"))
            if path.is_file() and not path.is_symlink()
        }

    def test_normalization_removes_terminal_references_but_preserves_words(self) -> None:
        """Catches normalization keeping random terminal references or deleting merchant words."""
        self.assertEqual("OPENAI CHATGPT SUBSCRIPTION", normalize_merchant("OPENAI *CHATGPT SUBSCRIPTION 9F3A2"))
        self.assertEqual("OPENAI CHATGPT SUBSCRIPTION", normalize_merchant("OPENAI *CHATGPT SUBSCRIPTION 7H4K9"))
        self.assertEqual("CAFÉ 2026 MARKET", normalize_merchant("Caf\u00e9 2026 Market"))

    def test_normalization_preserves_non_latin_merchant_words_for_grouping(self) -> None:
        """Catches normalization deleting meaningful non-Latin merchant names."""
        japanese = row("jp", "checking", "CAD", "株式会社 テスト 9F3A2", "20.00", "2026-01-08")
        self.assertEqual("株式会社 テスト", normalize_merchant(japanese["raw_description"]))
        self.assertEqual("株式会社 テスト", build_pending_groups((japanese,))[0].normalized_merchant)

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

    def test_confirmation_blocks_duplicate_ids_before_audit_or_rule_changes(self) -> None:
        """Catches a colliding transaction ID widening a confirmation to an unrelated row."""
        collision = row("cad-openai", "other", "CAD", "OTHER SYNTHETIC MERCHANT", "40.00", "2026-01-09")
        with self.assertRaisesRegex(ValueError, "unique non-empty transaction_id"):
            confirm_group(self.ledger, self.openai_rows + (collision,), "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        self.assertEqual([], load_rules(self.ledger))
        self.assertEqual([], [event for event in read_audit_events(self.ledger) if event["event_type"] != "ledger_initialized"])

    def test_confirmation_rejects_a_stale_group_member_before_mutation(self) -> None:
        """Catches a stale pending group classifying a row no longer in its merchant/direction/status set."""
        group = build_pending_groups(self.openai_rows)[0]
        stale = (self.openai_rows[0], {**self.openai_rows[1], "classification_status": "classified"})
        with self.assertRaisesRegex(ValueError, "group no longer matches"):
            confirm_group(self.ledger, stale, group.normalized_merchant, group.direction, "6100", "Membership Fee", True, "user", group.transaction_ids)
        self.assertEqual([], load_rules(self.ledger))
        self.assertEqual([], [event for event in read_audit_events(self.ledger) if event["event_type"] != "ledger_initialized"])

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

    def test_chart_name_is_canonical_for_confirmation(self) -> None:
        """Catches a chart-backed confirmation persisting a caller-supplied alias for an active code."""
        before = self.ledger_bytes(self.ledger)
        with self.assertRaisesRegex(ValueError, "account name does not match active chart"):
            confirm_group(
                self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION",
                "outflow", "6100", "Subscriptions", True, "user",
            )
        self.assertEqual(before, self.ledger_bytes(self.ledger))
        confirmed = confirm_group(
            self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION",
            "outflow", "6100", "", True, "user",
        )
        self.assertEqual({"Membership Fee"}, {item["account_name"] for item in confirmed.transactions})
        self.assertEqual("Membership Fee", load_rules(self.ledger)[0]["account_name"])

    def test_chart_name_is_canonical_for_correction(self) -> None:
        """Catches a chart-backed correction persisting a noncanonical name for an active code."""
        confirmed = confirm_group(
            self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION",
            "outflow", "6100", "Membership Fee", True, "user",
        )
        before = self.ledger_bytes(self.ledger)
        with self.assertRaisesRegex(ValueError, "account name does not match active chart"):
            correct_transactions(
                self.ledger, confirmed.transactions, ("cad-openai",),
                "6200", "Technology", "selected", "user",
            )
        self.assertEqual(before, self.ledger_bytes(self.ledger))
        corrected = correct_transactions(
            self.ledger, confirmed.transactions, ("cad-openai",),
            "6200", "", "selected", "user",
        )
        selected = next(item for item in corrected.transactions if item["transaction_id"] == "cad-openai")
        self.assertEqual(("6200", "Software"), (selected["account_code"], selected["account_name"]))

    def test_header_only_chart_rejects_confirmation_without_mutation(self) -> None:
        """Catches an empty supplied chart being mistaken for permission to use a free-form category."""
        atomic_write_csv(
            self.ledger / "chart-of-accounts.csv",
            ("account_code", "account_name", "active"),
            (),
        )
        before = self.ledger_bytes(self.ledger)

        with self.assertRaisesRegex(ValueError, "account code is not active"):
            confirm_group(
                self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION",
                "outflow", "", "Subscriptions", False, "user",
            )

        self.assertEqual(before, self.ledger_bytes(self.ledger))

    def test_header_only_chart_rejects_correction_without_mutation(self) -> None:
        """Catches correction bypassing a supplied chart that currently has no active accounts."""
        atomic_write_csv(
            self.ledger / "chart-of-accounts.csv",
            ("account_code", "account_name", "active"),
            (),
        )
        classified = tuple({
            **item,
            "classification_status": "classified",
            "account_name": "Legacy category",
        } for item in self.openai_rows)
        before = self.ledger_bytes(self.ledger)

        with self.assertRaisesRegex(ValueError, "account code is not active"):
            correct_transactions(
                self.ledger, classified, ("cad-openai",),
                "", "Subscriptions", "selected", "user",
            )

        self.assertEqual(before, self.ledger_bytes(self.ledger))

    def test_exact_conflict_leaves_row_unclassified_and_scopes_only_after_conflict(self) -> None:
        """Catches ambiguous exact rules silently classifying a transaction or prematurely scoping rules."""
        first = row("first-rule", "checking", "CAD", "OPENAI CHATGPT SUBSCRIPTION A1B2C", "10.00", "2026-01-01")
        second = row("second-rule", "card", "USD", "OPENAI CHATGPT SUBSCRIPTION D4E5F", "11.00", "2026-01-02")
        confirm_group(
            self.ledger, (first,), "OPENAI CHATGPT SUBSCRIPTION", "outflow",
            "6100", "Membership Fee", True, "user",
        )
        confirm_group(
            self.ledger, (second,), "OPENAI CHATGPT SUBSCRIPTION", "outflow",
            "6200", "Software", True, "user",
        )
        result = apply_exact_rules((self.openai_rows[0],), load_rules(self.ledger))
        self.assertEqual("unclassified", result.transactions[0]["classification_status"])
        self.assertEqual("MERCHANT_RULE_CONFLICT", result.issues[0].code)
        corrected = correct_transactions(self.ledger, result.transactions, ("cad-openai",), "6200", "Software", "future_rule", "user")
        self.assertEqual("checking", corrected.created_rules[0]["account_scope"])

    def test_exact_application_rejects_rules_not_loaded_from_a_ledger_audit(self) -> None:
        """Catches direct callers bypassing rule-audit validation with a copied rule dictionary."""
        confirm_group(
            self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION",
            "outflow", "6100", "Membership Fee", True, "user",
        )
        copied_rules = [dict(load_rules(self.ledger)[0])]
        with self.assertRaisesRegex(ValueError, "audit-authorized"):
            apply_exact_rules((self.fuzzy_row,), copied_rules)

    def test_rule_loading_rejects_tampered_metadata_and_unrelated_audit_ids(self) -> None:
        """Catches forged rule rows borrowing an audit ID or changing audit-bound matching/category data."""
        confirm_group(
            self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION",
            "outflow", "6100", "Membership Fee", True, "user",
        )
        rules_path = self.ledger / "merchant-rules.csv"
        original = read_csv_rows(rules_path)[0]
        unrelated_event_id = next(
            str(event["event_id"])
            for event in read_audit_events(self.ledger)
            if event["event_type"] == "ledger_initialized"
        )
        tampered_values = (
            ("rule_id", "rule-" + "f" * 32),
            ("normalized_merchant", "FORGED MERCHANT"),
            ("direction", "inflow"),
            ("account_scope", "other-account"),
            ("account_code", "6200"),
            ("account_name", "Software"),
            ("status", "pending"),
            ("audit_event_id", unrelated_event_id),
        )
        for field, value in tampered_values:
            with self.subTest(field=field):
                forged = dict(original)
                forged[field] = value
                atomic_write_csv(rules_path, MERCHANT_RULE_FIELDS, (forged,))
                before = self.ledger_bytes(self.ledger)
                with self.assertRaisesRegex(ValueError, "merchant rule"):
                    load_rules(self.ledger)
                self.assertEqual(before, self.ledger_bytes(self.ledger))
        atomic_write_csv(rules_path, MERCHANT_RULE_FIELDS, (original,))

    def test_public_rule_view_rejects_forged_rule_before_mutation(self) -> None:
        """Catches a public command accepting an unaudited active rule and publishing classified output."""
        forged = {field: "" for field in MERCHANT_RULE_FIELDS}
        forged.update({
            "rule_id": "rule-" + "a" * 32,
            "normalized_merchant": "OPENAI CHATGPT SUBSCRIPTION",
            "direction": "outflow", "account_code": "6100",
            "account_name": "Membership Fee", "match_type": "exact_normalized",
            "status": "active", "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z", "audit_event_id": "b" * 32,
        })
        atomic_write_csv(self.ledger / "merchant-rules.csv", MERCHANT_RULE_FIELDS, (forged,))
        atomic_write_csv(
            self.ledger / "work" / "normalized-transactions.csv",
            CANONICAL_TRANSACTION_FIELDS, (self.openai_rows[0],),
        )
        before = self.ledger_bytes(self.ledger)
        command = [
            sys.executable, str(SKILL_ROOT / "scripts" / "classify_transactions.py"),
            "pending", str(self.ledger),
        ]
        rejected = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(3, rejected.returncode)
        self.assertEqual("LEDGER_SCHEMA_INVALID", json.loads(rejected.stdout)["error"])
        self.assertEqual(before, self.ledger_bytes(self.ledger))

    def test_rule_loading_rejects_a_truncated_row_as_schema_invalid(self) -> None:
        """Catches malformed CSV cells escaping the forged-rule gate as an unexpected type error."""
        rules_path = self.ledger / "merchant-rules.csv"
        with rules_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(MERCHANT_RULE_FIELDS)
            writer.writerow(("rule-" + "0" * 32,))

        with self.assertRaisesRegex(ValueError, "schema"):
            load_rules(self.ledger)

    def test_rule_lifecycle_and_export_reject_forged_rules_before_mutation(self) -> None:
        """Catches lifecycle/export paths trusting a rule merely because its audit ID is nonempty."""
        confirmed = confirm_group(
            self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION",
            "outflow", "6100", "Membership Fee", True, "user",
        )
        rule_id = confirmed.created_rules[0]["rule_id"]
        rules_path = self.ledger / "merchant-rules.csv"
        forged = read_csv_rows(rules_path)[0]
        forged["normalized_merchant"] = "FORGED MERCHANT"
        atomic_write_csv(rules_path, MERCHANT_RULE_FIELDS, (forged,))
        before = self.ledger_bytes(self.ledger)
        with self.assertRaisesRegex(ValueError, "merchant rule"):
            deactivate_rule(self.ledger, rule_id, "user")
        with self.assertRaisesRegex(ValueError, "merchant rule"):
            export_rules(self.ledger, "outputs/forged-export.csv")
        self.assertEqual(before, self.ledger_bytes(self.ledger))

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

    def test_deactivate_rule_retry_is_idempotent(self) -> None:
        """Catches a repeated deactivation appending another event or changing a completed target."""
        confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        rule_id = load_rules(self.ledger)[0]["rule_id"]
        first = deactivate_rule(self.ledger, rule_id, "user")
        repeated = deactivate_rule(self.ledger, rule_id, "user")
        self.assertEqual(first, repeated)
        self.assertEqual("inactive", load_rules(self.ledger)[0]["status"])
        self.assertEqual(1, len([event for event in read_audit_events(self.ledger) if event["event_type"] == "merchant_rule_deactivated"]))

    def test_delete_rule_retry_is_idempotent(self) -> None:
        """Catches a repeated deletion appending another event or restoring a removed current rule."""
        confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        rule_id = load_rules(self.ledger)[0]["rule_id"]
        first = delete_rule(self.ledger, rule_id, "user")
        repeated = delete_rule(self.ledger, rule_id, "user")
        self.assertEqual(first, repeated)
        self.assertEqual([], load_rules(self.ledger))
        self.assertEqual(1, len([event for event in read_audit_events(self.ledger) if event["event_type"] == "merchant_rule_deleted"]))

    def test_interrupted_deactivation_recovers_inactive_target_and_one_audit_event(self) -> None:
        """Catches an audit failure leaving an active rule without a recoverable deactivation target."""
        confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        rule_id = load_rules(self.ledger)[0]["rule_id"]
        with patch("bookkeeper.classification.append_audit_event", side_effect=OSError("synthetic audit interruption")):
            with self.assertRaisesRegex(OSError, "synthetic audit interruption"):
                deactivate_rule(self.ledger, rule_id, "user")
        self.assertEqual("inactive", read_csv_rows(self.ledger / "merchant-rules.csv")[0]["status"])
        with self.assertRaisesRegex(ValueError, "audit lifecycle"):
            load_rules(self.ledger)
        self.assertEqual([], [event for event in read_audit_events(self.ledger) if event["event_type"] == "merchant_rule_deactivated"])
        self.assertTrue((self.ledger / "work" / "pending-classification-operation.json").exists())
        recovered = deactivate_rule(self.ledger, rule_id, "user")
        self.assertEqual("inactive", load_rules(self.ledger)[0]["status"])
        self.assertEqual(1, len([event for event in read_audit_events(self.ledger) if event["event_type"] == "merchant_rule_deactivated"]))
        self.assertTrue(recovered)

    def test_interrupted_deletion_recovers_absent_target_and_one_audit_event(self) -> None:
        """Catches an audit failure leaving a current rule row without a recoverable deletion target."""
        confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        rule_id = load_rules(self.ledger)[0]["rule_id"]
        with patch("bookkeeper.classification.append_audit_event", side_effect=OSError("synthetic audit interruption")):
            with self.assertRaisesRegex(OSError, "synthetic audit interruption"):
                delete_rule(self.ledger, rule_id, "user")
        self.assertEqual([], load_rules(self.ledger))
        self.assertEqual([], [event for event in read_audit_events(self.ledger) if event["event_type"] == "merchant_rule_deleted"])
        self.assertTrue((self.ledger / "work" / "pending-classification-operation.json").exists())
        recovered = delete_rule(self.ledger, rule_id, "user")
        self.assertEqual([], load_rules(self.ledger))
        self.assertEqual(1, len([event for event in read_audit_events(self.ledger) if event["event_type"] == "merchant_rule_deleted"]))
        self.assertTrue(recovered)

    def test_future_rule_retry_is_idempotent_and_invalid_precondition_leaves_no_audit(self) -> None:
        """Catches retrying a successful correction replacing another rule or auditing a rejected correction."""
        confirmed = confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        first = correct_transactions(self.ledger, confirmed.transactions, ("cad-openai",), "6200", "Software", "future_rule", "user")
        repeated = correct_transactions(self.ledger, first.transactions, ("cad-openai",), "6200", "Software", "future_rule", "user")
        self.assertEqual((), repeated.created_rules)
        self.assertEqual(1, len([rule for rule in load_rules(self.ledger) if rule["status"] == "active"]))
        before = list(read_audit_events(self.ledger))
        with self.assertRaisesRegex(ValueError, "one matching active rule"):
            correct_transactions(self.ledger, (self.fuzzy_row,), ("fuzzy",), "6200", "Software", "future_rule", "user")
        self.assertEqual(before, read_audit_events(self.ledger))

    def test_interrupted_confirmation_recovers_rows_rules_and_one_audit_event(self) -> None:
        """Catches an interruption leaving a rule/audit without the corresponding classified rows."""
        with patch("bookkeeper.classification._install_staged_file", side_effect=OSError("synthetic interruption")):
            with self.assertRaisesRegex(OSError, "synthetic interruption"):
                confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        self.assertEqual([], [event for event in read_audit_events(self.ledger) if event["event_type"] != "ledger_initialized"])
        recovered = confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        self.assertEqual({"classified"}, {item["classification_status"] for item in recovered.transactions})
        self.assertEqual(1, len(load_rules(self.ledger)))
        self.assertEqual(1, len([event for event in read_audit_events(self.ledger) if event["event_type"] == "merchant_group_confirmed"]))
        self.assertEqual(0, len(recovered.created_rules))

    def test_interrupted_correction_after_rows_install_recovers_one_replacement(self) -> None:
        """Catches a correction installing rows before rules and then replaying a second replacement."""
        confirmed = confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        original_install = classification._install_staged_file
        calls = 0

        def interrupt_after_rows(*args: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic rules interruption")
            original_install(*args)  # type: ignore[arg-type]

        with patch("bookkeeper.classification._install_staged_file", side_effect=interrupt_after_rows):
            with self.assertRaisesRegex(OSError, "synthetic rules interruption"):
                correct_transactions(self.ledger, confirmed.transactions, ("cad-openai",), "6200", "Software", "future_rule", "user")
        recovered = correct_transactions(self.ledger, confirmed.transactions, ("cad-openai",), "6200", "Software", "future_rule", "user")
        self.assertEqual((), recovered.created_rules)
        self.assertEqual("6200", next(item for item in recovered.transactions if item["transaction_id"] == "cad-openai")["account_code"])
        self.assertEqual(1, len([event for event in read_audit_events(self.ledger) if event["event_type"] == "merchant_rule_replaced"]))
        self.assertEqual(1, len([rule for rule in load_rules(self.ledger) if rule["status"] == "active"]))

    def test_confirm_cli_returns_completed_operation_after_recovery_removes_pending_group(self) -> None:
        """Catches CLI recovery completing a confirmation and then rejecting its identical retry as missing."""
        atomic_write_csv(self.ledger / "work" / "normalized-transactions.csv", CANONICAL_TRANSACTION_FIELDS, self.openai_rows)
        group = build_pending_groups(self.openai_rows)[0]
        with patch("bookkeeper.classification._install_staged_file", side_effect=OSError("synthetic interruption")):
            with self.assertRaisesRegex(OSError, "synthetic interruption"):
                confirm_group(self.ledger, self.openai_rows, group.normalized_merchant, group.direction, "6100", "Membership Fee", True, "user", group.transaction_ids)
        command = [sys.executable, str(SKILL_ROOT / "scripts" / "classify_transactions.py"), "confirm", str(self.ledger), group.group_id, "--account-code", "6100", "--account-name", "Membership Fee", "--apply-future", "--actor", "user"]
        completed = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(1, len([event for event in read_audit_events(self.ledger) if event["event_type"] == "merchant_group_confirmed"]))

    def test_export_and_non_pending_outputs_do_not_contain_descriptions(self) -> None:
        """Catches raw statement descriptions escaping through rule export or audit records."""
        confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        output = export_rules(self.ledger, "outputs/exported-rules.csv")
        self.assertTrue(output.is_file())
        self.assertNotIn("9F3A2", output.read_text(encoding="utf-8"))
        self.assertNotIn("9F3A2", str(read_audit_events(self.ledger)))

    def test_rule_export_rejects_authoritative_traversal_and_symlink_destinations(self) -> None:
        """Catches rule export overwriting authoritative ledger state or following a ledger-local symlink."""
        confirm_group(self.ledger, self.openai_rows, "OPENAI CHATGPT SUBSCRIPTION", "outflow", "6100", "Membership Fee", True, "user")
        outside = Path(self.temp.name) / "outside.csv"
        outside.write_text("outside\n", encoding="utf-8")
        symlink = self.ledger / "outputs" / "linked.csv"
        symlink.symlink_to(outside)
        unsafe = (
            "ledger.json", "merchant-rules.csv", "work/export.csv",
            "audit/export.csv", "inputs/export.csv", "outputs/../ledger.json",
            "outputs/status.json", "outputs/linked.csv",
        )
        for destination in unsafe:
            with self.subTest(destination=destination):
                before = self.ledger_bytes(self.ledger)
                with self.assertRaisesRegex(ValueError, "rule export destination"):
                    export_rules(self.ledger, destination)
                self.assertEqual(before, self.ledger_bytes(self.ledger))
        self.assertEqual(b"outside\n", outside.read_bytes())

    def test_public_export_rejects_ledger_json_without_changing_any_bytes(self) -> None:
        """Catches the CLI overwriting ledger.json before rejecting an unsafe export destination."""
        before = self.ledger_bytes(self.ledger)
        command = [
            sys.executable, str(SKILL_ROOT / "scripts" / "classify_transactions.py"),
            "export-rules", str(self.ledger), "ledger.json",
        ]
        rejected = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(3, rejected.returncode)
        self.assertEqual("LEDGER_SCHEMA_INVALID", json.loads(rejected.stdout)["error"])
        self.assertEqual(before, self.ledger_bytes(self.ledger))

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
