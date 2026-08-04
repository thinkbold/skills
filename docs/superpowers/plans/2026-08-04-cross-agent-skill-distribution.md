# Cross-Agent Skill Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bilingual installation and usage guide and make the Ontario tenant application skill explicitly portable across Agent Skills-compatible runtimes.

**Architecture:** Keep one canonical Agent Skills bundle with `SKILL.md` as the normative workflow. Declare runtime requirements in standard frontmatter, keep Codex-only UI metadata optional, and distribute a bilingual operator guide inside the bundle.

**Tech Stack:** Agent Skills `SKILL.md`, Markdown, Python 3.10+ standard library, `unittest`.

## Global Constraints

- Do not duplicate the skill into runtime-specific source directories.
- English appears first and Chinese immediately after it in every guide section.
- Full execution requires Python 3.10+, local case-directory access, authorized web/browser search, tool permissions, and final human review.
- Missing runtime capabilities stop the affected stage; they are never silently skipped.
- Preserve every existing no-score, no-ranking, no-prediction, no-automatic-decision, consent, and public-source-isolation rule.

---

### Task 1: Define the portable bundle contract

**Files:**
- Modify: `assess-ontario-tenant-application/tests/test_skill_layout.py`
- Modify: `assess-ontario-tenant-application/SKILL.md`

**Interfaces:**
- Consumes: Agent Skills YAML frontmatter parsed from the text between the first two `---` delimiters.
- Produces: `name`, `description`, and `metadata` keys with a nested `compatibility` value; a runtime-capability stop rule in the skill body.

- [ ] **Step 1: Write the failing frontmatter and runtime-capability tests**

```python
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
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONPATH=assess-ontario-tenant-application python3 -m unittest \
  assess-ontario-tenant-application/tests/test_skill_layout.py -v
```

Expected: FAIL because `metadata.compatibility` and the runtime stop wording are absent.

- [ ] **Step 3: Add portable compatibility metadata and stop behavior**

Add this frontmatter field:

```yaml
metadata:
  compatibility: "Requires Python 3.10+, local filesystem and shell access, and authorized web/browser search for public-source stages; final review remains human."
```

Add a short runtime compatibility section that treats `agents/openai.yaml` as optional UI metadata and requires the agent to stop an affected stage, identify the missing capability, and leave the package incomplete.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the Step 2 command. Expected: all layout tests pass.

### Task 2: Add the bilingual operator guide

**Files:**
- Create: `assess-ontario-tenant-application/USER_GUIDE.md`
- Modify: `assess-ontario-tenant-application/tests/test_skill_layout.py`

**Interfaces:**
- Consumes: the canonical skill directory and a user-selected agent installation root.
- Produces: copy and symlink commands that preserve the directory name `assess-ontario-tenant-application`, plus invocation and lifecycle instructions.

- [ ] **Step 1: Write failing guide coverage tests**

```python
def test_bilingual_user_guide_covers_supported_runtimes(self) -> None:
    path = SKILL_ROOT / "USER_GUIDE.md"
    self.assertTrue(path.is_file(), "bilingual user guide is missing")
    text = path.read_text(encoding="utf-8")
    required = [
        "English", "中文", "Codex", "Claude Code", "GitHub Copilot CLI",
        "Agent Skills-compatible", "~/.agents/skills",
        "~/.claude/skills", ".agents/skills", ".claude/skills",
    ]
    self.assertEqual([], [item for item in required if item not in text])

def test_user_guide_covers_operation_and_safety(self) -> None:
    text = (SKILL_ROOT / "USER_GUIDE.md").read_text(encoding="utf-8")
    required = [
        "Prerequisites / 前置条件", "Install / 安装", "Use / 使用",
        "Update / 更新", "Uninstall / 卸载", "outputs/",
        "human", "人工", "Do not silently skip", "不得静默跳过",
    ]
    self.assertEqual([], [item for item in required if item not in text])
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run the Task 1 focused test command. Expected: FAIL because `USER_GUIDE.md` does not exist.

- [ ] **Step 3: Write `USER_GUIDE.md`**

Write paired English/Chinese sections for scope, prerequisites, installation, case preparation, invocation, outputs, updating, uninstalling, troubleshooting, and runtime limitations. Cover:

- Codex and cross-runtime personal installation at `~/.agents/skills/`;
- Claude Code personal and project paths at `~/.claude/skills/` and `.claude/skills/`;
- GitHub Copilot CLI personal and project paths at `~/.agents/skills/` and `.agents/skills/`;
- a generic instruction to use the path documented by any other Agent Skills-compatible runtime;
- copy and symlink commands using quoted variables;
- one-case invocation prompts for English and Chinese;
- the required case manifest, consent, evidence, `outputs/` results, and human decision boundary;
- capability failures, updates, uninstalling, and sensitive-data handling.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Task 1 focused test command. Expected: all layout tests pass.

### Task 3: Validate and publish the update

**Files:**
- Verify: `assess-ontario-tenant-application/**`
- Verify: `docs/superpowers/specs/2026-08-04-cross-agent-skill-distribution-design.md`
- Verify: `docs/superpowers/plans/2026-08-04-cross-agent-skill-distribution.md`

**Interfaces:**
- Consumes: the completed portable skill bundle.
- Produces: a clean commit pushed to `origin/feat/ontario-tenant-assessment` and visible in PR #1.

- [ ] **Step 1: Run the complete unit suite**

```bash
PYTHONPATH=assess-ontario-tenant-application python3 -m unittest discover \
  -s assess-ontario-tenant-application/tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run package validation and static checks**

Run the official `quick_validate.py`, compile all Python files, parse every JSON file, run `git diff --check`, scan for unfinished markers, and run the existing policy-invariant and synthetic-identifier scans. Expected: every command succeeds with no findings requiring changes.

- [ ] **Step 3: Commit and push**

```bash
git add assess-ontario-tenant-application docs/superpowers
git commit -m "docs: support cross-agent skill installation"
git push
```

- [ ] **Step 4: Confirm the branch and PR**

Run `git status --short --branch`. Expected: the branch is clean and tracks `origin/feat/ontario-tenant-assessment`; PR #1 contains the new commit.
