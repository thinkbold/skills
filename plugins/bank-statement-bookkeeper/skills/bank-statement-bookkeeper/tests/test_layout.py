import json
from pathlib import Path
import re
import sys
import unittest

SKILL_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))


def parse_mapping_yaml(text: str) -> dict[str, object]:
    """Parse the mapping-only YAML subset used by skill metadata."""
    root: dict[str, object] = {}
    stack: list[tuple[int, dict[str, object]]] = [(-1, root)]
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indentation = len(line) - len(line.lstrip(" "))
        if indentation % 2:
            raise ValueError("metadata indentation must use pairs of spaces")
        key, separator, raw_value = line.strip().partition(":")
        if not separator or not key:
            raise ValueError("metadata must contain mapping entries")
        while indentation <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        value_text = raw_value.strip()
        if not value_text:
            value: object = {}
            parent[key] = value
            stack.append((indentation, value))
        elif value_text in {"true", "false"}:
            parent[key] = value_text == "true"
        elif value_text.startswith(('"', "'")):
            if value_text.startswith("'"):
                parent[key] = value_text[1:-1].replace("''", "'")
            else:
                parent[key] = json.loads(value_text)
        else:
            parent[key] = value_text
    return root


def skill_frontmatter() -> dict[str, object]:
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"\A---\n(?P<yaml>.*?)\n---\n", text, re.DOTALL)
    if match is None:
        raise ValueError("SKILL.md must start with YAML frontmatter")
    return parse_mapping_yaml(match.group("yaml"))


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
            "references/workflow.md",
            "references/ledger-schema.md",
            "references/privacy-and-consent.md",
        )
        self.assertEqual(
            [], [path for path in required if not (SKILL_ROOT / path).is_file()]
        )

    def test_skill_frontmatter_contract(self) -> None:
        metadata = skill_frontmatter()
        self.assertEqual(
            {"name", "description", "metadata"},
            set(metadata),
        )
        self.assertEqual("bank-statement-bookkeeper", metadata["name"])
        self.assertIsInstance(metadata["description"], str)
        self.assertTrue(str(metadata["description"]).strip())
        self.assertEqual(
            {
                "compatibility": (
                    "Requires Python 3.10+, local filesystem and shell access, "
                    "pdfplumber for local PDF extraction, and optional local ocrmypdf "
                    "for scanned PDFs; external processing requires operation-specific consent."
                )
            },
            metadata["metadata"],
        )

    def test_skill_reference_links_resolve(self) -> None:
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        destinations = {
            destination
            for destination in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
            if destination.startswith("references/")
        }
        expected = {
            "references/workflow.md",
            "references/ledger-schema.md",
            "references/privacy-and-consent.md",
        }
        self.assertEqual(expected, destinations)
        self.assertEqual([], [path for path in destinations if not (SKILL_ROOT / path).is_file()])

    def test_openai_metadata_contract(self) -> None:
        metadata = parse_mapping_yaml(
            (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual({"interface", "policy"}, set(metadata))
        self.assertEqual(
            {
                "display_name": "Bank Statement Bookkeeper",
                "short_description": "Classify and reconcile bank statement transactions",
                "default_prompt": (
                    "Use $bank-statement-bookkeeper to process the bank statements "
                    "in my company ledger."
                ),
            },
            metadata["interface"],
        )
        self.assertEqual({"allow_implicit_invocation": True}, metadata["policy"])


if __name__ == "__main__":
    unittest.main()
