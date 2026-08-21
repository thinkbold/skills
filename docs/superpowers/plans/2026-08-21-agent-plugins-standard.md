# Agent Plugins Standardization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the tracked Ontario tenant-application skill as one repository-distributed, skills-only Agent Plugin without losing standalone Agent Skills compatibility.

**Architecture:** Create a repository marketplace that points to `plugins/assess-ontario-tenant-application`, give that plugin a validated `.codex-plugin/plugin.json`, and move the single canonical skill beneath the plugin's `skills/` directory. Keep workflow tests at the plugin root and update the bilingual guide so plugin installation and direct skill installation both resolve to the same nested skill.

**Tech Stack:** OpenAI Agent Plugins manifest and marketplace JSON, Agent Skills `SKILL.md`, Python 3.10+ standard library, `unittest`, PyYAML-backed official validators.

**Spec:** `docs/superpowers/specs/2026-08-21-agent-plugins-standard-design.md`

## Global Constraints

- The plugin, plugin folder, and skill name are exactly `assess-ontario-tenant-application`.
- The plugin version starts at strict semver `1.0.0`.
- The repository marketplace is named `thinkbold-skills` and displayed as `ThinkBold Skills`.
- The marketplace entry uses `AVAILABLE`, `ON_INSTALL`, and `Productivity`; omit `policy.products`.
- The plugin is skills-only: do not add or declare MCP servers, apps, or hooks.
- Keep one canonical skill at `plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application/`.
- Preserve Python 3.10+, local filesystem, shell, authorized browser/search, and final human-review requirements.
- Preserve every no-ranking, no-scoring, no-prediction, no-automatic-decision, consent, privacy, and public-source-isolation rule.
- Preserve the English-first, immediately paired Chinese structure of `USER_GUIDE.md`.
- Do not rewrite historical plans or specs merely to update their old paths.
- Do not modify ignored worktrees or unrelated untracked `.superpowers/` files.

---

### Task 1: Create the Plugin Manifest and Repository Marketplace

**Files:**
- Create: `assess-ontario-tenant-application/tests/test_plugin_layout.py`
- Create: `plugins/assess-ontario-tenant-application/.codex-plugin/plugin.json`
- Create: `.agents/plugins/marketplace.json`

**Interfaces:**
- Consumes: the repository root and the approved plugin identity constants.
- Produces: `PLUGIN_ROOT/.codex-plugin/plugin.json` with `skills: "./skills/"`, plus a marketplace entry whose local source resolves to `PLUGIN_ROOT`.

- [ ] **Step 1: Write the failing packaging contract test**

Create `assess-ontario-tenant-application/tests/test_plugin_layout.py` with:

```python
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
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
python3 -m unittest assess-ontario-tenant-application/tests/test_plugin_layout.py -v
```

Expected: both tests error because `.codex-plugin/plugin.json` and `.agents/plugins/marketplace.json` do not exist.

- [ ] **Step 3: Scaffold the repository plugin and marketplace**

Run the built-in plugin creator from the repository root:

```bash
python3 /Users/thinkbold/.codex/skills/.system/plugin-creator/scripts/create_basic_plugin.py \
  assess-ontario-tenant-application \
  --path plugins \
  --marketplace-path .agents/plugins/marketplace.json \
  --marketplace-name thinkbold-skills \
  --with-skills \
  --with-marketplace
```

Expected: the script creates the plugin root, manifest, empty `skills/` directory, and repository marketplace without modifying personal plugin configuration.

- [ ] **Step 4: Replace the scaffold manifest with approved metadata**

Set `plugins/assess-ontario-tenant-application/.codex-plugin/plugin.json` to:

```json
{
  "name": "assess-ontario-tenant-application",
  "version": "1.0.0",
  "description": "Prepare an auditable evidence package for one Ontario residential tenant application.",
  "author": {
    "name": "ThinkBold",
    "url": "https://github.com/thinkbold"
  },
  "homepage": "https://github.com/thinkbold/skills",
  "repository": "https://github.com/thinkbold/skills",
  "license": "MIT",
  "keywords": [
    "ontario",
    "tenant-application",
    "evidence",
    "housing"
  ],
  "skills": "./skills/",
  "interface": {
    "displayName": "Assess Ontario Tenant Application",
    "shortDescription": "Audit one Ontario rental application evidence package",
    "longDescription": "Prepare a structured, auditable evidence package for one Ontario market-rental application while leaving the tenancy decision to a human reviewer.",
    "developerName": "ThinkBold",
    "category": "Productivity",
    "capabilities": [
      "Read",
      "Write"
    ],
    "websiteURL": "https://github.com/thinkbold/skills",
    "defaultPrompt": [
      "Assess one Ontario tenant application case folder.",
      "Validate an Ontario rental application before human review."
    ]
  }
}
```

Confirm `.agents/plugins/marketplace.json` has this exact data shape; if the scaffolder generated different display copy, change only the top-level `name` and `interface.displayName` to the approved values while preserving the generated plugin entry:

```json
{
  "name": "thinkbold-skills",
  "interface": {
    "displayName": "ThinkBold Skills"
  },
  "plugins": [
    {
      "name": "assess-ontario-tenant-application",
      "source": {
        "source": "local",
        "path": "./plugins/assess-ontario-tenant-application"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    }
  ]
}
```

- [ ] **Step 5: Run the packaging contract and verify GREEN**

Run:

```bash
python3 -m unittest assess-ontario-tenant-application/tests/test_plugin_layout.py -v
```

Expected: 2 tests pass.

- [ ] **Step 6: Commit the packaging contract**

```bash
git add .agents/plugins/marketplace.json \
  plugins/assess-ontario-tenant-application/.codex-plugin/plugin.json \
  assess-ontario-tenant-application/tests/test_plugin_layout.py
git commit -m "feat: scaffold Ontario tenant assessment plugin"
```

---

### Task 2: Move the Canonical Skill and Preserve Behavior

**Files:**
- Modify, then move: `assess-ontario-tenant-application/tests/test_plugin_layout.py` → `plugins/assess-ontario-tenant-application/tests/test_plugin_layout.py`
- Move: `assess-ontario-tenant-application/tests/**` → `plugins/assess-ontario-tenant-application/tests/**`
- Move: `assess-ontario-tenant-application/{SKILL.md,agents,scripts,references,assets,USER_GUIDE.md}` → `plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application/**`
- Modify: `plugins/assess-ontario-tenant-application/tests/test_skill_layout.py`
- Modify: `plugins/assess-ontario-tenant-application/tests/test_end_to_end.py`

**Interfaces:**
- Consumes: the Task 1 plugin root, `skills: "./skills/"`, and the existing portable skill bundle.
- Produces: one canonical `SKILL_ROOT` beneath the plugin and a plugin-level `tests/` directory whose behavior suite imports scripts through `PYTHONPATH=SKILL_ROOT`.

- [ ] **Step 1: Add a failing one-canonical-copy assertion**

Append this test to `PluginLayoutTests` in the current `assess-ontario-tenant-application/tests/test_plugin_layout.py`:

```python
    def test_plugin_contains_the_only_canonical_skill(self) -> None:
        canonical = PLUGIN_ROOT / "skills" / PLUGIN_NAME
        legacy = REPO_ROOT / PLUGIN_NAME
        self.assertTrue((canonical / "SKILL.md").is_file())
        self.assertFalse((legacy / "SKILL.md").exists())
        self.assertTrue((canonical / "scripts" / "run_pipeline.py").is_file())
        self.assertTrue((canonical / "references" / "workflow.md").is_file())
        self.assertTrue((canonical / "assets" / "case-manifest.template.json").is_file())
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
python3 -m unittest \
  assess-ontario-tenant-application/tests/test_plugin_layout.py \
  -v
```

Expected: `test_plugin_contains_the_only_canonical_skill` fails because the canonical nested `SKILL.md` is absent and the legacy root-level copy still exists.

- [ ] **Step 3: Move the skill and tests without copying them**

Run:

```bash
mkdir -p plugins/assess-ontario-tenant-application/skills
git mv assess-ontario-tenant-application \
  plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application
git mv plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application/tests \
  plugins/assess-ontario-tenant-application/tests
```

Expected final locations:

```text
plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application/SKILL.md
plugins/assess-ontario-tenant-application/tests/test_plugin_layout.py
```

- [ ] **Step 4: Point layout tests at the nested skill**

Replace the constants at the top of `plugins/assess-ontario-tenant-application/tests/test_skill_layout.py` with:

```python
PLUGIN_NAME = "assess-ontario-tenant-application"
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PLUGIN_ROOT / "skills" / PLUGIN_NAME
```

Keep all existing assertions unchanged below these constants.

- [ ] **Step 5: Point end-to-end fixtures at plugin tests**

Replace the old `SKILL_ROOT` constant in `plugins/assess-ontario-tenant-application/tests/test_end_to_end.py` with:

```python
PLUGIN_NAME = "assess-ontario-tenant-application"
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PLUGIN_ROOT / "skills" / PLUGIN_NAME
TEST_ROOT = Path(__file__).resolve().parent
```

Replace the two fixture/golden path expressions:

```python
shutil.copytree(TEST_ROOT / "fixtures" / name, case_dir)
```

```python
expected = (TEST_ROOT / "golden" / "joint-valid" / name).read_text(
    encoding="utf-8"
)
```

- [ ] **Step 6: Run the focused layout tests and verify GREEN**

Run:

```bash
PYTHONPATH=plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application \
  python3 -m unittest \
  plugins/assess-ontario-tenant-application/tests/test_plugin_layout.py \
  plugins/assess-ontario-tenant-application/tests/test_skill_layout.py \
  -v
```

Expected: all plugin and skill layout tests pass, including the absence of the legacy root-level skill.

- [ ] **Step 7: Run the complete behavior suite and verify no migration regression**

Run:

```bash
PYTHONPATH=plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application \
  python3 -m unittest discover \
  -s plugins/assess-ontario-tenant-application/tests \
  -v
```

Expected: the same existing behavior suite passes from the plugin-level test directory.

- [ ] **Step 8: Commit the canonical move**

```bash
git add -A -- \
  assess-ontario-tenant-application \
  plugins/assess-ontario-tenant-application
git commit -m "refactor: nest portable skill in Agent Plugin"
```

---

### Task 3: Update the Bilingual Plugin and Standalone Installation Guide

**Files:**
- Modify: `plugins/assess-ontario-tenant-application/tests/test_skill_layout.py`
- Modify: `plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application/USER_GUIDE.md`

**Interfaces:**
- Consumes: `REPO_ROOT`, `PLUGIN_ROOT`, `SKILL_SOURCE`, marketplace name `thinkbold-skills`, and the nested canonical skill path from Task 2.
- Produces: English/Chinese installation, update, test, and uninstall instructions for both the repository Agent Plugin and direct Agent Skills installation.

- [ ] **Step 1: Add a failing guide coverage test**

Add this method to `SkillLayoutTests`:

```python
    def test_user_guide_covers_plugin_and_standalone_installation(self) -> None:
        text = (SKILL_ROOT / "USER_GUIDE.md").read_text(encoding="utf-8")
        required = [
            "Agent Plugin / Agent 插件",
            "Standalone Agent Skills / 独立 Agent Skills",
            ".agents/plugins/marketplace.json",
            "plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application",
            'codex plugin marketplace add "$REPO_ROOT"',
            "codex plugin add assess-ontario-tenant-application@thinkbold-skills",
            "codex plugin remove assess-ontario-tenant-application",
            "codex plugin marketplace remove thinkbold-skills",
            'PYTHONPATH="$SKILL_SOURCE"',
            '-s "$PLUGIN_ROOT/tests"',
        ]
        self.assertEqual([], [item for item in required if item not in text])
```

- [ ] **Step 2: Run the guide tests and verify RED**

Run:

```bash
PYTHONPATH=plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application \
  python3 -m unittest \
  plugins/assess-ontario-tenant-application/tests/test_skill_layout.py \
  -v
```

Expected: `test_user_guide_covers_plugin_and_standalone_installation` fails because the guide still targets the legacy root-level skill and has no plugin commands.

- [ ] **Step 3: Define the canonical repository, plugin, and skill paths**

In `USER_GUIDE.md`, replace the current clone-and-source block with this paired explanation and command block:

````markdown
Clone or update the repository, then define the repository plugin and canonical
standalone skill paths. The plugin and every direct skill installation use the
same nested skill directory at
`plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application`.

克隆或更新仓库，然后定义仓库插件及权威独立 skill 的路径。插件安装和所有直接
skill 安装都使用同一个嵌套 skill 目录：
`plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application`。

```bash
git clone https://github.com/thinkbold/skills.git
cd skills
export REPO_ROOT="$PWD"
export PLUGIN_ROOT="$REPO_ROOT/plugins/assess-ontario-tenant-application"
export SKILL_SOURCE="$PLUGIN_ROOT/skills/assess-ontario-tenant-application"
test -f "$REPO_ROOT/.agents/plugins/marketplace.json"
test -f "$PLUGIN_ROOT/.codex-plugin/plugin.json"
test -f "$SKILL_SOURCE/SKILL.md"
```
````

- [ ] **Step 4: Make Agent Plugin installation the primary Codex path**

At the start of `## Install / 安装`, add:

````markdown
### Agent Plugin / Agent 插件

For Codex, register this repository marketplace and install the plugin by its
stable marketplace identity:

对于 Codex，先注册本仓库 marketplace，再通过稳定的 marketplace 标识安装插件：

```bash
codex plugin marketplace add "$REPO_ROOT"
codex plugin add assess-ontario-tenant-application@thinkbold-skills
```

Start a new Codex task after installation so the new skill is discovered. This
local repository installation does not publish the plugin to OpenAI's public
plugin directory.

安装后请新建一个 Codex 任务，使新 skill 被正确发现。本地仓库安装不会把插件
发布到 OpenAI 的公共插件目录。
````

Rename the existing `### Codex: personal or cross-runtime / Codex：个人或跨运行时` heading to:

```markdown
### Standalone Agent Skills / 独立 Agent Skills
```

Keep its existing `~/.agents/skills` and `.agents/skills` copy/link instructions under that heading.

- [ ] **Step 5: Update test, update, and uninstall commands**

Replace the guide's repository test command with:

```bash
cd "$REPO_ROOT"
PYTHONPATH="$SKILL_SOURCE" python3 -m unittest discover \
  -s "$PLUGIN_ROOT/tests" -v
```

In the update section, retain `git pull --ff-only`, run the command above, and add:

```bash
codex plugin add assess-ontario-tenant-application@thinkbold-skills
```

Explain in both languages that re-adding refreshes the installed local plugin after a repository update, while a copied standalone skill must be recopied from `SKILL_SOURCE`.

Use this exact paired text:

```markdown
After pulling a repository update and passing the tests, re-add the plugin to
refresh its installed local copy. A standalone skill installed with a symbolic
link already points at `SKILL_SOURCE`; a copied standalone skill must be copied
again from `SKILL_SOURCE`.

拉取仓库更新并通过测试后，重新添加插件以刷新其本地安装副本。通过软链接安装的
独立 skill 已经指向 `SKILL_SOURCE`；通过复制安装的独立 skill 必须从
`SKILL_SOURCE` 再复制一次。
```

At the start of the uninstall section, add this paired plugin-specific guidance:

````markdown
Remove the installed plugin first. Remove the marketplace only when no other
plugin from `thinkbold-skills` is still needed:

先卸载插件。只有在不再需要 `thinkbold-skills` 中任何其他插件时，才移除该
marketplace：

```bash
codex plugin remove assess-ontario-tenant-application
codex plugin marketplace remove thinkbold-skills
```
````

Keep the existing standalone symlink/copy uninstall guidance and ensure every source path now derives from `SKILL_SOURCE` rather than `$PWD/assess-ontario-tenant-application`.

- [ ] **Step 6: Run the guide and layout tests and verify GREEN**

Run:

```bash
PYTHONPATH=plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application \
  python3 -m unittest \
  plugins/assess-ontario-tenant-application/tests/test_skill_layout.py \
  plugins/assess-ontario-tenant-application/tests/test_plugin_layout.py \
  -v
```

Expected: all guide, skill-layout, and plugin-layout tests pass.

- [ ] **Step 7: Commit the bilingual installation guide**

```bash
git add \
  plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application/USER_GUIDE.md \
  plugins/assess-ontario-tenant-application/tests/test_skill_layout.py
git commit -m "docs: document plugin and standalone skill installation"
```

---

### Task 4: Validate the Complete Agent Plugin

**Files:**
- Verify: `.agents/plugins/marketplace.json`
- Verify: `plugins/assess-ontario-tenant-application/**`
- Verify: `docs/superpowers/specs/2026-08-21-agent-plugins-standard-design.md`
- Verify: `docs/superpowers/plans/2026-08-21-agent-plugins-standard.md`

**Interfaces:**
- Consumes: the completed plugin, nested skill, repository marketplace, synthetic fixtures, and official validators.
- Produces: evidence that packaging, behavior, paths, JSON, Python, documentation, and policy invariants all pass together.

- [ ] **Step 1: Run the complete unit suite**

```bash
PYTHONPATH=plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application \
  python3 -m unittest discover \
  -s plugins/assess-ontario-tenant-application/tests \
  -v
```

Expected: all tests pass with no errors or failures.

- [ ] **Step 2: Run the official skill validator**

```bash
python3 /Users/thinkbold/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application
```

Expected: `Skill is valid!`

- [ ] **Step 3: Run the official plugin validator**

```bash
python3 /Users/thinkbold/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py \
  plugins/assess-ontario-tenant-application
```

Expected: `Plugin validation passed` for the absolute plugin path.

- [ ] **Step 4: Compile Python and validate every tracked JSON file**

```bash
python3 -m compileall -q \
  plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application/scripts \
  plugins/assess-ontario-tenant-application/tests
```

Then run:

```bash
while IFS= read -r file; do
  python3 -m json.tool "$file" >/dev/null
done < <(git ls-files '*.json')
```

Expected: both commands exit successfully with no output.

- [ ] **Step 5: Scan for unfinished content and preserved policy boundaries**

Run:

```bash
rg -n "T[B]D|T[O]DO|F[I]XME|P[L]ACEHOLDER" \
  .agents/plugins/marketplace.json \
  plugins/assess-ontario-tenant-application \
  docs/superpowers/specs/2026-08-21-agent-plugins-standard-design.md \
  docs/superpowers/plans/2026-08-21-agent-plugins-standard.md
```

Expected: no matches.

Run:

```bash
rg -n "Never rank|Do not calculate debt-to-income|public-records.md|accommodation" \
  plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application/SKILL.md \
  plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application/references
```

Expected: matches demonstrate that the existing ranking, ratio, public-source-isolation, and accommodation boundaries remain present.

- [ ] **Step 6: Review repository integrity and the final diff**

```bash
git diff --check
git status --short --branch
git diff --stat main...HEAD
git diff --find-renames main...HEAD -- \
  .agents/plugins/marketplace.json \
  plugins/assess-ontario-tenant-application \
  docs/superpowers/specs/2026-08-21-agent-plugins-standard-design.md \
  docs/superpowers/plans/2026-08-21-agent-plugins-standard.md
```

Expected: no whitespace errors; only the pre-existing untracked `.superpowers/` directory remains unrelated; the diff shows one marketplace, one plugin, one nested canonical skill, moved tests, and the two approved design/plan documents.

- [ ] **Step 7: Commit validation fixes only if verification changed tracked files**

If Steps 1–6 required a tracked correction, rerun the failed command, stage only that correction, and commit it with:

```bash
git commit -m "fix: satisfy Agent Plugin validation"
```

If verification is clean and makes no tracked changes, do not create an empty commit.
