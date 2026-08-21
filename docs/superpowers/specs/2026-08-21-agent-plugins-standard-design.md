# Agent Plugins Standardization Design

**Date:** 2026-08-21

## Goal

Package the tracked `assess-ontario-tenant-application` skill as a standards-compliant, skills-only OpenAI Agent Plugin while preserving the same skill as a portable Agent Skills bundle for Codex, Claude Code, GitHub Copilot CLI, and other compatible runtimes.

The result must have one authoritative copy of the workflow. Plugin installation and standalone skill installation must both resolve to that copy.

## Current State

The main branch tracks one skill at the repository root:

```text
assess-ontario-tenant-application/
├── SKILL.md
├── agents/openai.yaml
├── scripts/
├── references/
├── assets/
├── tests/
└── USER_GUIDE.md
```

It follows the portable Agent Skills convention but is not an Agent Plugin because the repository has no `.codex-plugin/plugin.json`, plugin directory, or repository marketplace.

Ignored worktrees and the planned Canadian Practice platform are outside this migration. This change covers only files tracked on the current branch.

## Chosen Architecture

Use a repository marketplace containing one skills-only plugin. Move the portable skill into the plugin's `skills/` directory and move its automated tests to the plugin root:

```text
.agents/
└── plugins/
    └── marketplace.json
plugins/
└── assess-ontario-tenant-application/
    ├── .codex-plugin/
    │   └── plugin.json
    ├── skills/
    │   └── assess-ontario-tenant-application/
    │       ├── SKILL.md
    │       ├── agents/openai.yaml
    │       ├── scripts/
    │       ├── references/
    │       ├── assets/
    │       └── USER_GUIDE.md
    └── tests/
```

No duplicate compatibility copy remains at the repository root. A user who wants only the Agent Skills bundle installs or links `plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application/`.

## Plugin Identity and Manifest

The plugin and its outer directory both use the stable identifier `assess-ontario-tenant-application`. The nested skill uses the same name because it exposes the plugin's single user-facing workflow.

The manifest at `.codex-plugin/plugin.json` contains:

- `name`: `assess-ontario-tenant-application`
- `version`: `1.0.0`
- a concise package description
- publisher metadata for ThinkBold and the existing repository
- the repository's MIT license
- focused discovery keywords
- `skills`: `./skills/`
- install-surface interface metadata, including display name, descriptions, developer name, category, capabilities, and starter prompts

The manifest does not declare `mcpServers`, `apps`, or `hooks`, because the plugin ships none. Optional visual fields are omitted until maintained icon and screenshot assets exist.

## Repository Marketplace

Add `.agents/plugins/marketplace.json` with:

- marketplace name `thinkbold-skills`
- display name `ThinkBold Skills`
- one local plugin entry named `assess-ontario-tenant-application`
- source path `./plugins/assess-ontario-tenant-application`
- installation policy `AVAILABLE`
- authentication policy `ON_INSTALL`
- category `Productivity`

The source path is relative to the repository root, begins with `./`, and stays inside the marketplace root. Product gating is omitted because none was requested. The marketplace is a development and repository-distribution source; it does not claim public-directory publication.

## Portable Skill Contract

The nested skill remains independently installable and retains:

- the existing `SKILL.md` workflow and safety boundaries;
- portable `name`, `description`, and `metadata.compatibility` frontmatter;
- relative links to scripts, references, assets, and optional `agents/openai.yaml` metadata;
- Python 3.10+, local filesystem, shell, authorized browser/search, and final human-review requirements;
- the no-ranking, no-scoring, no-prediction, no-automatic-decision, consent, privacy, and public-source-isolation rules.

`SKILL.md` remains the normative workflow. Plugin metadata may improve discovery and installation but must not replace or weaken skill instructions.

## Documentation Migration

Update `USER_GUIDE.md` so that Agent Plugin installation is the primary Codex/ChatGPT path and standalone skill installation remains documented for other compatible runtimes.

The guide will:

- point plugin users to the repository marketplace and plugin directory;
- point standalone users to the nested canonical skill directory;
- update every clone, link, copy, test, update, and uninstall command for the new paths;
- retain paired English and Chinese coverage;
- distinguish plugin installation from direct Agent Skills installation;
- avoid claiming that repository installation publishes the plugin publicly;
- retain all privacy, consent, capability, and human-decision warnings.

Historical design and implementation documents remain historical records. New active instructions and tests use the new paths; old plans are not rewritten merely to make past commands current.

## Test Strategy

Use test-first migration for the packaging contract.

1. Add failing layout tests for the required plugin manifest, repository marketplace, canonical nested skill path, and absence of the old root-level skill.
2. Add failing manifest tests for the plugin name, version, `skills` pointer, component omissions, interface metadata, and relative path resolution.
3. Add failing marketplace tests for identity, source path, install/auth policies, category, and plugin resolution.
4. Update existing skill-layout tests to resolve the nested skill without weakening any policy assertions.
5. Move the remaining tests to the plugin-level test directory and update import and fixture paths.
6. Move the skill and add the minimum packaging files needed to make the tests pass.
7. Update the bilingual guide and its coverage assertions.

Final verification includes:

- the complete Python unit suite;
- Python compilation for all bundled scripts and tests;
- JSON parsing for all tracked JSON files;
- the official skill validator against the nested skill;
- the official plugin validator against the plugin root;
- manifest and marketplace path-resolution checks;
- unfinished-marker and policy-invariant scans;
- `git diff --check` and a clean review of the final diff.

No live case data, network-backed case processing, or public-source search is needed for packaging verification. Existing synthetic fixtures remain the only case inputs used by tests.

## Failure Handling

- If official validation rejects a manifest field, remove or correct only the unsupported metadata; do not work around validation by weakening the required plugin structure.
- If a moved resource cannot be resolved, fail the layout test and correct the relative path before running behavior tests.
- If behavior tests fail after the move, treat the failure as a migration regression. Do not change assessment rules unless a test demonstrates that the old path was embedded in runtime behavior.
- If a guide command no longer targets the canonical nested skill, fail documentation coverage rather than adding a second skill copy.
- Preserve unrelated untracked files and ignored worktrees throughout the migration.

## Alternatives Rejected

### Repository Root as the Plugin

Rejected because the repository directory is named `skills`, which does not match the plugin identity, and because a root-level plugin makes future multi-plugin expansion awkward.

### Duplicate the Skill Inside a Plugin Wrapper

Rejected because plugin and standalone copies would drift. The design requires one canonical workflow.

### Add an MCP Server, App UI, or Hooks

Rejected because the existing workflow needs packaged instructions, deterministic local scripts, and already available browser/search capabilities. No server-backed capability or lifecycle hook is required for this migration.

## Acceptance Criteria

The migration is complete when:

- the repository marketplace resolves the plugin at the documented path;
- the plugin has a valid `.codex-plugin/plugin.json` and passes official validation;
- the plugin packages exactly one valid, focused skill under `skills/`;
- the nested skill remains independently installable and passes official skill validation;
- no duplicate root-level canonical skill remains;
- all existing workflow and policy tests pass from their new location;
- the bilingual guide accurately covers both plugin and standalone installation;
- no MCP, app, hook, or public-publishing claim is introduced;
- all final static and behavioral verification commands succeed.
