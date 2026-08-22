import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


PLUGIN_NAME = "assess-ontario-tenant-application"
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PLUGIN_ROOT.parents[1]
VALIDATOR = REPOSITORY_ROOT / "tools" / "validate_plugin_release.py"


class PluginReleaseVersionTests(unittest.TestCase):
    def test_tag_must_match_manifest_version(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            manifest = Path(temporary_directory) / "plugin.json"
            manifest.write_text(json.dumps({"version": "1.0.0"}), encoding="utf-8")

            matching = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--manifest",
                    str(manifest),
                    "--tag",
                    f"{PLUGIN_NAME}-v1.0.0",
                    "--tag-prefix",
                    f"{PLUGIN_NAME}-v",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            mismatched = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--manifest",
                    str(manifest),
                    "--tag",
                    f"{PLUGIN_NAME}-v1.0.1",
                    "--tag-prefix",
                    f"{PLUGIN_NAME}-v",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(0, matching.returncode, matching.stderr)
        self.assertIn("1.0.0", matching.stdout)
        self.assertNotEqual(0, mismatched.returncode)
        self.assertIn("1.0.1", mismatched.stderr)
        self.assertIn("1.0.0", mismatched.stderr)


if __name__ == "__main__":
    unittest.main()
