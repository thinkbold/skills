from pathlib import Path
import unittest


PLUGIN_NAME = "assess-ontario-tenant-application"
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PLUGIN_ROOT / "skills" / PLUGIN_NAME
REPOSITORY_ROOT = PLUGIN_ROOT.parents[1]


class SkillLayoutTests(unittest.TestCase):
    def test_required_paths_exist(self) -> None:
        expected = [
            "SKILL.md",
            "agents/openai.yaml",
            "scripts/init_case.py",
            "scripts/shared.py",
            "references/case-intake.md",
            "references/policy-version.json",
            "assets/case-intake.template.json",
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

    def test_distribution_has_one_command_install_and_manual_fallback(self) -> None:
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        guide = (SKILL_ROOT / "USER_GUIDE.md").read_text(encoding="utf-8")
        required_readme = [
            "npx skills add thinkbold/skills",
            "--skill assess-ontario-tenant-application",
            "--agent codex",
            "--agent claude-code",
            "--agent github-copilot",
        ]
        required_guide = [
            "Agent Plugin / Agent 插件",
            "Standalone Agent Skills / 独立 Agent Skills",
            "Recommended: one command / 推荐：一条命令",
            "Manual fallback / 手工安装 fallback",
            ".agents/plugins/marketplace.json",
            "plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application",
            "codex plugin marketplace add \"$REPO_ROOT\"",
            "codex plugin add assess-ontario-tenant-application@thinkbold-skills",
            "Every plugin-content release must change the `version`",
            "每个包含插件内容的发布都必须更改",
            "then start a new Codex task.",
            "然后新建一个 Codex 任务。",
            "codex plugin remove assess-ontario-tenant-application@thinkbold-skills",
            "codex plugin marketplace remove thinkbold-skills",
            "npx skills update assess-ontario-tenant-application",
            "npx skills remove assess-ontario-tenant-application",
        ]
        self.assertEqual(
            [], [item for item in required_readme if item not in readme]
        )
        self.assertEqual([], [item for item in required_guide if item not in guide])

    def test_release_workflow_validates_and_packages_the_skill(self) -> None:
        path = REPOSITORY_ROOT / ".github/workflows/validate-and-release.yml"
        self.assertTrue(path.is_file(), "validation and release workflow is missing")
        text = path.read_text(encoding="utf-8")
        required = [
            "assess-ontario-tenant-application-v*",
            "python -m unittest discover",
            "npx --yes skills add . --list",
            "tar -czf",
            "sha256sum",
            "gh release create",
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

    def test_skill_guides_missing_manifest_intake(self) -> None:
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        required = [
            "case-manifest.json",
            "references/case-intake.md",
            "scripts/init_case.py",
            "Never overwrite",
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

    def test_workflow_commands_use_the_canonical_skill_source(self) -> None:
        text = (SKILL_ROOT / "references" / "workflow.md").read_text(
            encoding="utf-8"
        )
        self.assertIn('PYTHONPATH="$SKILL_SOURCE"', text)
        self.assertIn('"$SKILL_SOURCE/scripts/validate_case.py"', text)
        self.assertIn('"$SKILL_SOURCE/scripts/run_pipeline.py"', text)
        self.assertNotIn("PYTHONPATH=assess-ontario-tenant-application", text)

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
