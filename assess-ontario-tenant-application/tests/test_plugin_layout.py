import json
from pathlib import Path
import unittest


PLUGIN_NAME = "assess-ontario-tenant-application"


def find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError("repository root not found")


REPO_ROOT = find_repo_root(Path(__file__).resolve())
PLUGIN_ROOT = REPO_ROOT / "plugins" / PLUGIN_NAME
MANIFEST_PATH = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
MARKETPLACE_PATH = REPO_ROOT / ".agents" / "plugins" / "marketplace.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PluginLayoutTests(unittest.TestCase):
    def test_manifest_declares_the_skills_only_plugin(self) -> None:
        manifest = load_json(MANIFEST_PATH)
        self.assertEqual(PLUGIN_NAME, manifest["name"])
        self.assertEqual("1.0.0", manifest["version"])
        self.assertEqual("./skills/", manifest["skills"])
        self.assertEqual("ThinkBold", manifest["author"]["name"])
        self.assertEqual("MIT", manifest["license"])
        self.assertNotIn("mcpServers", manifest)
        self.assertNotIn("apps", manifest)
        self.assertNotIn("hooks", manifest)

        interface = manifest["interface"]
        self.assertEqual("Assess Ontario Tenant Application", interface["displayName"])
        self.assertEqual("ThinkBold", interface["developerName"])
        self.assertEqual("Productivity", interface["category"])
        self.assertEqual(["Read", "Write"], interface["capabilities"])
        self.assertGreaterEqual(len(interface["defaultPrompt"]), 1)
        self.assertLessEqual(len(interface["defaultPrompt"]), 3)

    def test_marketplace_resolves_the_local_plugin(self) -> None:
        marketplace = load_json(MARKETPLACE_PATH)
        self.assertEqual("thinkbold-skills", marketplace["name"])
        self.assertEqual("ThinkBold Skills", marketplace["interface"]["displayName"])
        self.assertEqual(1, len(marketplace["plugins"]))

        entry = marketplace["plugins"][0]
        self.assertEqual(PLUGIN_NAME, entry["name"])
        self.assertEqual(
            {"source": "local", "path": f"./plugins/{PLUGIN_NAME}"},
            entry["source"],
        )
        self.assertEqual(
            {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            entry["policy"],
        )
        self.assertNotIn("products", entry["policy"])
        self.assertEqual("Productivity", entry["category"])
        self.assertEqual(PLUGIN_ROOT.resolve(), (REPO_ROOT / entry["source"]["path"]).resolve())


if __name__ == "__main__":
    unittest.main()
