from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.validate_case import validate_case


def valid_manifest() -> dict:
    return {
        "schema_version": "1.0",
        "case_id": "synthetic-001",
        "jurisdiction": {"country": "CA", "province": "ON"},
        "housing": {
            "market_type": "market",
            "owner_shared_kitchen_or_bathroom": False,
            "address": "100 Example Street, Toronto, ON",
            "monthly_rent_cad": "2400.00",
            "expected_start_date": "2026-09-01",
            "term_months": 12,
        },
        "applicants": [
            {
                "applicant_id": "applicant-a",
                "lease_signer": True,
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
        "authorizations": {
            "general": {
                "version": "counsel-approved-1",
                "signed_at": "2026-08-01",
                "open_web_disclosed": True,
            },
            "social": {"status": "not_requested"},
        },
        "decision": {"status": "pending", "legal_hold": False},
    }


class CaseValidationTests(unittest.TestCase):
    def validate(self, manifest: dict, today: date = date(2026, 8, 4)):
        with TemporaryDirectory() as temporary_directory:
            case_dir = Path(temporary_directory)
            input_path = case_dir / manifest["applicants"][0]["files"][0]["path"]
            input_path.parent.mkdir(parents=True)
            input_path.write_bytes(b"%PDF-1.4\n% synthetic test fixture\n")
            (case_dir / "case-manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            return validate_case(case_dir, today=today)

    def test_valid_case_can_extract_and_finalize(self) -> None:
        result = self.validate(valid_manifest())

        self.assertTrue(result.can_extract)
        self.assertTrue(result.can_finalize)
        self.assertEqual((), result.issues)

    def test_owner_shared_space_blocks_extraction(self) -> None:
        manifest = valid_manifest()
        manifest["housing"]["owner_shared_kitchen_or_bathroom"] = True

        result = self.validate(manifest)

        self.assertFalse(result.can_extract)
        self.assertIn("OUT_OF_SCOPE_SHARED_SPACE", {issue.code for issue in result.issues})

    def test_expired_policy_allows_extraction_but_blocks_finalization(self) -> None:
        result = self.validate(valid_manifest(), today=date(2026, 11, 3))

        self.assertTrue(result.can_extract)
        self.assertFalse(result.can_finalize)
        self.assertIn("POLICY_EXPIRED", {issue.code for issue in result.issues})

    def test_unsupported_file_type_blocks_extraction(self) -> None:
        manifest = valid_manifest()
        manifest["applicants"][0]["files"][0]["path"] = "inputs/application.xlsm"

        result = self.validate(manifest)

        self.assertFalse(result.can_extract)
        self.assertIn("UNSUPPORTED_FILE_TYPE", {issue.code for issue in result.issues})

    def test_missing_privacy_or_general_authorization_blocks_extraction(self) -> None:
        cases = []
        missing_privacy = valid_manifest()
        missing_privacy.pop("privacy")
        cases.append(("privacy", missing_privacy, "PRIVACY_PREFLIGHT_INCOMPLETE"))
        missing_general = deepcopy(valid_manifest())
        missing_general["authorizations"].pop("general")
        cases.append(
            ("authorization", missing_general, "GENERAL_AUTHORIZATION_INCOMPLETE")
        )

        for label, manifest, expected_code in cases:
            with self.subTest(label=label):
                result = self.validate(manifest)
                self.assertFalse(result.can_extract)
                self.assertIn(expected_code, {issue.code for issue in result.issues})


if __name__ == "__main__":
    unittest.main()
