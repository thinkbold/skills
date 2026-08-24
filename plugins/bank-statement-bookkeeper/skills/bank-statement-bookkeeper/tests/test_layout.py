import json
from pathlib import Path
import sys
import unittest

SKILL_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))


class LayoutTests(unittest.TestCase):
    def test_manifest_and_contracts(self) -> None:
        manifest = json.loads(
            (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual("bank-statement-bookkeeper", manifest["name"])
        self.assertEqual("0.1.0", manifest["version"])
        self.assertEqual("./skills/", manifest["skills"])
        self.assertNotIn("apps", manifest)
        self.assertNotIn("mcpServers", manifest)
        self.assertNotIn("hooks", manifest)
        from bookkeeper.contracts import CANONICAL_TRANSACTION_FIELDS

        self.assertEqual("transaction_id", CANONICAL_TRANSACTION_FIELDS[0])
        self.assertEqual("source_locations", CANONICAL_TRANSACTION_FIELDS[-1])
        self.assertEqual(21, len(CANONICAL_TRANSACTION_FIELDS))

    def test_required_paths(self) -> None:
        required = (
            "SKILL.md",
            "agents/openai.yaml",
            "requirements.txt",
            "requirements-dev.txt",
            "scripts/init_ledger.py",
            "scripts/import_statements.py",
            "scripts/classify_transactions.py",
            "scripts/reconcile_accounts.py",
            "scripts/validate_ledger.py",
        )
        self.assertEqual(
            [], [path for path in required if not (SKILL_ROOT / path).is_file()]
        )


if __name__ == "__main__":
    unittest.main()
