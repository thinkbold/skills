from pathlib import Path
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]


class SkillLayoutTests(unittest.TestCase):
    def test_required_paths_exist(self) -> None:
        expected = [
            "SKILL.md",
            "agents/openai.yaml",
            "scripts/shared.py",
            "references/policy-version.json",
            "assets/case-manifest.template.json",
        ]
        missing = [path for path in expected if not (SKILL_ROOT / path).exists()]
        self.assertEqual([], missing)

    def test_skill_frontmatter_has_only_required_keys(self) -> None:
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]
        keys = {
            line.split(":", 1)[0].strip()
            for line in frontmatter.splitlines()
            if ":" in line
        }
        self.assertEqual({"name", "description"}, keys)


if __name__ == "__main__":
    unittest.main()
