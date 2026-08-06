from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.init_case import initialize_case
from scripts.shared import AssessmentError
from scripts.validate_case import validate_case


def valid_intake() -> dict:
    return {
        "case_id": "synthetic-intake-001",
        "scope": {
            "ordinary_ontario_market_rental": True,
            "owner_shared_kitchen_or_bathroom": False,
        },
        "housing": {
            "address": "100 Example Street, Toronto, ON",
            "monthly_rent_cad": "2400",
            "expected_start_date": "2026-09-01",
            "term_months": 12,
        },
        "applicants": [
            {
                "applicant_id": "applicant-a",
                "files": [
                    {"path": "inputs/application-a.pdf", "kind": "application"}
                ],
            }
        ],
        "privacy": {
            "responsible_person": "Synthetic Manager",
            "controlled_storage_confirmed": True,
            "access_correction_process_confirmed": True,
        },
        "general_authorization": {
            "available": True,
            "version": "counsel-approved-1",
            "signed_at": "2026-08-01",
            "open_web_disclosed": True,
        },
        "social_consent": {
            "facebook": "granted",
            "linkedin": "refused",
        },
        "legal_hold": False,
    }


class CaseInitializationTests(unittest.TestCase):
    def make_case(self, root: Path, intake: dict) -> tuple[Path, Path]:
        case_dir = root / "case"
        case_dir.mkdir()
        for applicant in intake.get("applicants", []):
            for file_record in applicant.get("files", []):
                path = case_dir / file_record["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"%PDF-1.4\n% synthetic test fixture\n")
        answers_path = root / "case-intake.json"
        answers_path.write_text(json.dumps(intake), encoding="utf-8")
        return case_dir, answers_path

    def test_valid_intake_creates_manifest_and_case_directories(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            case_dir, answers_path = self.make_case(root, valid_intake())

            manifest_path = initialize_case(case_dir, answers_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            self.assertEqual("2400.00", manifest["housing"]["monthly_rent_cad"])
            self.assertTrue(manifest["applicants"][0]["lease_signer"])
            self.assertEqual(
                ["facebook"], manifest["authorizations"]["social"]["platforms"]
            )
            self.assertEqual(
                {"facebook": "granted", "linkedin": "refused"},
                manifest["authorizations"]["social"]["platform_statuses"],
            )
            self.assertTrue((case_dir / "inputs").is_dir())
            self.assertTrue((case_dir / "work").is_dir())
            self.assertTrue((case_dir / "outputs").is_dir())

    def test_existing_manifest_is_never_overwritten(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            case_dir, answers_path = self.make_case(root, valid_intake())
            manifest_path = case_dir / "case-manifest.json"
            manifest_path.write_text('{"sentinel": true}\n', encoding="utf-8")

            with self.assertRaisesRegex(AssessmentError, "already exists"):
                initialize_case(case_dir, answers_path)

            self.assertEqual(
                {"sentinel": True},
                json.loads(manifest_path.read_text(encoding="utf-8")),
            )

    def test_out_of_scope_case_is_not_initialized(self) -> None:
        intake = valid_intake()
        intake["scope"]["owner_shared_kitchen_or_bathroom"] = True
        with TemporaryDirectory() as temporary_directory:
            case_dir, answers_path = self.make_case(
                Path(temporary_directory), intake
            )

            with self.assertRaisesRegex(AssessmentError, "outside this skill"):
                initialize_case(case_dir, answers_path)

            self.assertFalse((case_dir / "case-manifest.json").exists())

    def test_case_file_cannot_escape_case_directory(self) -> None:
        intake = valid_intake()
        intake["applicants"][0]["files"][0]["path"] = "../outside.pdf"
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            case_dir, answers_path = self.make_case(root, intake)

            with self.assertRaisesRegex(AssessmentError, "must stay inside"):
                initialize_case(case_dir, answers_path)

            self.assertFalse((case_dir / "case-manifest.json").exists())

    def test_unavailable_general_authorization_creates_blocked_manifest(self) -> None:
        intake = deepcopy(valid_intake())
        intake["general_authorization"] = {"available": False}
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            case_dir, answers_path = self.make_case(root, intake)

            initialize_case(case_dir, answers_path)
            result = validate_case(case_dir, today=date(2026, 8, 4))

            self.assertFalse(result.can_extract)
            self.assertIn(
                "GENERAL_AUTHORIZATION_INCOMPLETE",
                {issue.code for issue in result.issues},
            )

    def test_privacy_preflight_must_be_confirmed_before_creation(self) -> None:
        intake = valid_intake()
        intake["privacy"]["controlled_storage_confirmed"] = False
        with TemporaryDirectory() as temporary_directory:
            case_dir, answers_path = self.make_case(
                Path(temporary_directory), intake
            )

            with self.assertRaisesRegex(AssessmentError, "privacy preflight"):
                initialize_case(case_dir, answers_path)

            self.assertFalse((case_dir / "case-manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
