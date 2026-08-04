from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.manage_retention import apply_retention, plan_retention


class RetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directories: list[TemporaryDirectory] = []

    def tearDown(self) -> None:
        for temporary_directory in self.temporary_directories:
            temporary_directory.cleanup()

    def make_case(self, legal_hold: bool = False, status: str = "completed") -> Path:
        temporary_directory = TemporaryDirectory()
        self.temporary_directories.append(temporary_directory)
        case_dir = Path(temporary_directory.name)
        for directory in ("inputs", "work", "outputs"):
            target = case_dir / directory
            target.mkdir()
            (target / "synthetic.txt").write_text("synthetic", encoding="utf-8")
        (case_dir / "case-manifest.json").write_text(
            json.dumps(
                {
                    "case_id": "synthetic-retention-001",
                    "decision": {
                        "status": status,
                        "completed_at": "2026-01-01" if status == "completed" else "",
                        "legal_hold": legal_hold,
                    },
                }
            ),
            encoding="utf-8",
        )
        return case_dir

    def test_raw_files_are_planned_after_30_days(self) -> None:
        actions = plan_retention(self.make_case(), date(2026, 2, 1))
        paths = [item.relative_path for item in actions]

        self.assertIn("inputs/synthetic.txt", paths)
        self.assertIn("work/synthetic.txt", paths)
        self.assertNotIn("outputs/synthetic.txt", paths)

    def test_all_artifacts_are_planned_after_13_months(self) -> None:
        actions = plan_retention(self.make_case(), date(2027, 2, 1))
        paths = {item.relative_path for item in actions}

        self.assertIn("inputs/synthetic.txt", paths)
        self.assertIn("work/synthetic.txt", paths)
        self.assertIn("outputs/synthetic.txt", paths)

    def test_legal_hold_blocks_every_action(self) -> None:
        self.assertEqual(
            (),
            plan_retention(self.make_case(legal_hold=True), date(2028, 1, 1)),
        )

    def test_pending_case_has_no_retention_actions(self) -> None:
        self.assertEqual(
            (), plan_retention(self.make_case(status="pending"), date(2028, 1, 1))
        )

    def test_default_dry_run_does_not_delete(self) -> None:
        case_dir = self.make_case()
        actions = plan_retention(case_dir, date(2026, 2, 1))

        apply_retention(case_dir, actions, apply=False)

        self.assertTrue((case_dir / "inputs/synthetic.txt").exists())


if __name__ == "__main__":
    unittest.main()
