# Cross-Agent Skill Distribution Design

**Date:** 2026-08-04

## Goal

Distribute `assess-ontario-tenant-application` as one portable Agent Skills
bundle that can be installed in Codex, Claude Code, GitHub Copilot CLI, and
other runtimes that implement the Agent Skills `SKILL.md` convention. Add a
bilingual English/Chinese guide that explains installation, prerequisites,
invocation, case preparation, outputs, and safety limits.

## Approach

Keep one canonical skill directory. Do not duplicate the skill under
runtime-specific directory trees. Runtime-specific installation consists of
copying or symlinking the canonical directory into that runtime's personal or
project skill location.

`SKILL.md` remains the only normative workflow. `agents/openai.yaml` remains
optional Codex interface metadata and must not be required by the scripts or
other agents. Declare the runtime capabilities needed for full execution under
`metadata.compatibility`, which is accepted by the current Codex validator and
by Agent Skills implementations that accept the standard metadata mapping.

## Files

- Add `assess-ontario-tenant-application/USER_GUIDE.md` as the bilingual
  installation and usage guide distributed with the skill.
- Update `assess-ontario-tenant-application/SKILL.md` frontmatter and wording
  only where needed to remove Codex-specific assumptions and declare runtime
  requirements.
- Keep `assess-ontario-tenant-application/agents/openai.yaml` unchanged unless
  validation shows its prompt is inconsistent with the portable workflow.
- Extend `tests/test_skill_layout.py` with portable-format and guide-content
  assertions.

## Guide Structure

Each section presents English first and Chinese immediately after it:

1. Scope and non-decision purpose.
2. Runtime prerequisites and privacy requirements.
3. Installation for Codex, Claude Code, GitHub Copilot CLI, and generic Agent
   Skills-compatible runtimes.
4. Personal installation, project installation, copy, and symlink examples.
5. Case-directory preparation and required consent fields.
6. Invocation examples that name the skill and provide one case directory.
7. Expected outputs and the human decision boundary.
8. Updating, uninstalling, troubleshooting, and capability limitations.

Commands use a `SKILL_SOURCE` variable and quote paths. The guide does not
pre-authorize shell or browser tools, promise automatic discovery in an
undocumented path, or claim full support for a cloud runtime that cannot expose
the case directory and required tools.

## Compatibility Contract

The bundle follows the Agent Skills directory convention: a directory named
`assess-ontario-tenant-application` containing `SKILL.md` with portable `name`,
`description`, and `metadata` frontmatter plus relative references to bundled
resources. The metadata mapping contains a `compatibility` value.

Full execution requires:

- Python 3.10 or newer and permission to run the bundled standard-library
  scripts;
- local read/write access to one controlled case directory;
- a web or browser search capability for the separately authorized public
  source stages;
- an operator who can grant tool permissions and perform the final human
  review.

If a runtime lacks a required capability, the agent must stop that stage,
identify the missing capability, and leave the assessment incomplete. It must
not replace deterministic scripts with prose arithmetic, silently omit required
searches, or make a tenancy decision.

## Tests

Add tests before implementation that require:

- `USER_GUIDE.md` exists and contains paired English and Chinese sections;
- the guide covers Codex, Claude Code, Copilot CLI, generic runtimes, personal
  and project paths, invocation, outputs, updating, and uninstalling;
- `SKILL.md` declares runtime requirements under `metadata.compatibility` and
  does not require `agents/openai.yaml`;
- portable relative resource paths remain valid;
- the existing no-score, no-ranking, no-prediction, no-automatic-decision, and
  public-source isolation invariants remain present.

Run all existing unit tests, the official skill validator, Python compilation,
JSON validation, whitespace checks, and policy-invariant scans before pushing
the updated branch.
