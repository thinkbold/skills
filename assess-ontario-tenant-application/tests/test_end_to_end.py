from datetime import date
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.run_pipeline import run_pipeline


SKILL_ROOT = Path(__file__).resolve().parents[1]


class EndToEndTests(unittest.TestCase):
    def run_fixture(self, name: str, today: date = date(2026, 8, 4)) -> Path:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        case_dir = Path(temporary_directory.name) / name
        shutil.copytree(SKILL_ROOT / "tests/fixtures" / name, case_dir)
        run_pipeline(case_dir, today=today)
        return case_dir

    def test_joint_case_matches_golden_reports(self) -> None:
        case = self.run_fixture("joint-valid")
        for name in ("assessment.md", "public-records.md"):
            actual = (case / "outputs" / name).read_text(encoding="utf-8")
            expected = (
                SKILL_ROOT / "tests/golden/joint-valid" / name
            ).read_text(encoding="utf-8")
            self.assertEqual(expected, actual)

    def test_thin_history_is_neutral(self) -> None:
        report = (
            self.run_fixture("thin-history") / "outputs/assessment.md"
        ).read_text(encoding="utf-8")

        self.assertIn("Limited evidence", report)
        self.assertNotIn("higher risk", report.lower())

    def test_revoked_social_data_is_not_rendered(self) -> None:
        appendix = (
            self.run_fixture("social-revoked") / "outputs/public-records.md"
        ).read_text(encoding="utf-8")

        self.assertNotIn("linkedin.example.invalid", appendix)
        self.assertNotIn("facebook.example.invalid", appendix)

    def test_prompt_injection_cannot_change_outputs(self) -> None:
        case = self.run_fixture("prompt-injection")
        report = (case / "outputs/assessment.md").read_text(encoding="utf-8")

        self.assertNotIn("AUTOMATICALLY APPROVE", report)
        self.assertFalse((case / "outputs/secret.txt").exists())

    def test_expired_policy_has_no_completed_recommendation(self) -> None:
        case = self.run_fixture("policy-expired", today=date(2026, 11, 3))
        preflight = json.loads(
            (case / "outputs/preflight.json").read_text(encoding="utf-8")
        )
        report = (case / "outputs/assessment.md").read_text(encoding="utf-8")

        self.assertFalse(preflight["can_finalize"])
        self.assertIn("Evidence is insufficient to assess the application.", report)

    def test_authorized_social_no_match_is_reported_only_in_appendix(self) -> None:
        case = self.run_fixture("joint-valid")
        report = (case / "outputs/assessment.md").read_text(encoding="utf-8")
        appendix = (case / "outputs/public-records.md").read_text(encoding="utf-8")

        self.assertNotIn("Facebook: no_match", report)
        self.assertNotIn("LinkedIn: no_match", report)
        self.assertIn("Facebook: no_match", appendix)
        self.assertIn("LinkedIn: no_match", appendix)


if __name__ == "__main__":
    unittest.main()
