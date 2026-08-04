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

    def test_skill_frontmatter_is_portable(self) -> None:
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]
        keys = {
            line.split(":", 1)[0].strip()
            for line in frontmatter.splitlines()
            if ":" in line and not line.startswith((" ", "\t"))
        }
        self.assertEqual({"name", "description", "metadata"}, keys)
        self.assertIn("  compatibility:", frontmatter)
        self.assertIn("Python 3.10+", frontmatter)
        self.assertIn("web/browser", frontmatter)

    def test_skill_stops_when_runtime_capability_is_missing(self) -> None:
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("missing runtime capability", text.lower())
        self.assertIn("Do not silently skip", text)

    def test_bilingual_user_guide_covers_supported_runtimes(self) -> None:
        path = SKILL_ROOT / "USER_GUIDE.md"
        self.assertTrue(path.is_file(), "bilingual user guide is missing")
        text = path.read_text(encoding="utf-8")
        required = [
            "English",
            "中文",
            "Codex",
            "Claude Code",
            "GitHub Copilot CLI",
            "Agent Skills-compatible",
            "~/.agents/skills",
            "~/.claude/skills",
            ".agents/skills",
            ".claude/skills",
        ]
        self.assertEqual([], [item for item in required if item not in text])

    def test_user_guide_covers_operation_and_safety(self) -> None:
        path = SKILL_ROOT / "USER_GUIDE.md"
        self.assertTrue(path.is_file(), "bilingual user guide is missing")
        text = path.read_text(encoding="utf-8")
        required = [
            "Prerequisites / 前置条件",
            "Install / 安装",
            "Use / 使用",
            "Update / 更新",
            "Uninstall / 卸载",
            "outputs/",
            "human",
            "人工",
            "Do not silently skip",
            "不得静默跳过",
        ]
        self.assertEqual([], [item for item in required if item not in text])

    def test_skill_body_names_hard_stops_and_pipeline(self) -> None:
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        required = [
            "validate_case.py",
            "redact_sensitive_data.py",
            "calculate_financials.py",
            "validate_evidence.py",
            "build_report.py",
            "Never rank",
            "public-records.md",
            "accommodation",
        ]
        self.assertEqual([], [item for item in required if item not in text])

    def test_authorization_draft_requires_counsel_review(self) -> None:
        path = SKILL_ROOT / "assets/authorization-draft.md"
        self.assertTrue(path.is_file(), "authorization draft is missing")
        text = path.read_text(encoding="utf-8")
        self.assertIn("DRAFT - ONTARIO COUNSEL REVIEW REQUIRED", text)
        self.assertIn("Facebook", text)
        self.assertIn("LinkedIn", text)
        self.assertIn("withdraw", text.lower())

    def test_references_are_linked_directly(self) -> None:
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        names = (
            "workflow.md",
            "ontario-compliance-policy.md",
            "evidence-schema.md",
            "assessment-rules.md",
            "public-source-policy.md",
        )
        self.assertEqual(
            [], [name for name in names if f"references/{name}" not in text]
        )

    def test_policy_references_cover_high_risk_boundaries(self) -> None:
        paths = {
            name: SKILL_ROOT / "references" / name
            for name in (
                "workflow.md",
                "assessment-rules.md",
                "public-source-policy.md",
            )
        }
        self.assertEqual(
            [], [name for name, path in paths.items() if not path.is_file()]
        )
        workflow = paths["workflow.md"].read_text(encoding="utf-8")
        assessment = paths["assessment-rules.md"].read_text(encoding="utf-8")
        public = paths["public-source-policy.md"].read_text(encoding="utf-8")
        self.assertIn("declared income and declared debt payments only", workflow)
        self.assertIn("Do not calculate debt-to-income", assessment)
        self.assertIn("Do not store a full page or screenshot", public)
        self.assertIn("Not an official criminal record check", public)


if __name__ == "__main__":
    unittest.main()
