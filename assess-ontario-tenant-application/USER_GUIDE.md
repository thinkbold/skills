# Install and Use / 安装与使用

This guide installs and runs `assess-ontario-tenant-application` as one
portable Agent Skills bundle. The same bundle supports Codex, Claude Code,
GitHub Copilot CLI, and other Agent Skills-compatible runtimes that provide the
required local tools.

本指南说明如何把 `assess-ontario-tenant-application` 作为一份可移植的 Agent
Skills 包安装和运行。同一份包可用于 Codex、Claude Code、GitHub Copilot CLI，
以及具备所需本地工具的其他 Agent Skills 兼容运行时。

## Scope / 适用范围

The skill prepares an auditable evidence package for one ordinary market-rate
residential tenancy application in Ontario, Canada. It lists confirmed gross
income and monthly debt separately, evaluates rent coverage, records material
discrepancies, and keeps authorized public-source findings in a separate
appendix. It does not score or rank people, predict default, approve or reject
an application, or replace the landlord's human and legal review.

本 skill 用于加拿大安大略省一宗普通市场住宅租赁申请，生成可审计的证据包。
它分别列出已确认的税前收入和每月债务，评估租金覆盖能力，记录重大不匹配，
并将经授权的公开来源检索结果单独放入附录。它不对申请人打分或排序，不预测
违约，不批准或拒绝申请，也不替代房东的人工及法律审查。

## Prerequisites / 前置条件

Full execution requires all of the following:

- Python 3.10 or newer. The bundled scripts use only the Python standard
  library.
- Node.js and npm only when using the recommended `npx skills` installer. They
  are not runtime dependencies; use the manual fallback if they are
  unavailable.
- Local filesystem and shell access to one controlled case directory.
- A browser or web-search tool for the authorized open-web stage.
- An operator who can approve tool use, verify extracted facts, handle consent,
  and complete the final human decision.
- Controlled storage approved for applicant personal information. Do not place
  a live case in a public repository, ordinary chat attachment, or unapproved
  cloud workspace.

完整执行需要同时满足以下条件：

- Python 3.10 或更高版本；随附脚本只使用 Python 标准库。
- 只有使用推荐的 `npx skills` 安装器时才需要 Node.js 和 npm；它们不是 skill
  的运行时依赖。若环境中没有 Node.js 和 npm，请使用手工安装 fallback。
- 能通过本地文件系统和 Shell 访问一个受控的案件目录。
- 在已经取得授权的前提下，具备用于开放网络检索的浏览器或网页搜索工具。
- 有操作人员负责批准工具调用、核对提取事实、处理授权，并完成人工决定。
- 使用获准存储申请人个人信息的受控环境。不得将真实案件放入公开仓库、普通
  聊天附件或未经批准的云端工作区。

If any capability is unavailable, stop the affected stage and report the
limitation. Do not silently skip a required search, validation, redaction, or
calculation step.

如果缺少任何能力，必须停止受影响的阶段并说明限制。不得静默跳过必需的检索、
验证、脱敏或计算步骤。

## Install / 安装

### Recommended: one command / 推荐：一条命令

Install globally, then choose one or more detected agents interactively:

全局安装，然后在交互界面中选择一个或多个已检测到的 Agent：

```bash
npx skills add thinkbold/skills \
  --skill assess-ontario-tenant-application \
  --global
```

The installer supports Codex, Claude Code, GitHub Copilot CLI, and other Agent
Skills-compatible runtimes. It selects the appropriate destination and can
manage later updates and removal. Installing the skill does not approve any
cloud agent or external service to receive applicant information.

该安装器支持 Codex、Claude Code、GitHub Copilot CLI 及其他 Agent Skills
兼容运行时，并会选择对应的目标目录，也可以管理后续更新和卸载。安装 skill
并不表示允许任何云端 Agent 或外部服务接收申请人资料。

For a non-interactive global installation into the three supported runtimes:

如需无人值守地全局安装到三个受支持的运行时：

```bash
DISABLE_TELEMETRY=1 npx skills add thinkbold/skills \
  --skill assess-ontario-tenant-application \
  --global \
  --agent codex \
  --agent claude-code \
  --agent github-copilot \
  --yes
```

Omit `--global` to install for the current project. Run `npx skills list` after
installation, note the installed skill path, and point `SKILL_SOURCE` at it for
the case-preparation commands below. Restart an agent session if the skill does
not appear.

如需只安装到当前项目，请省略 `--global`。安装后运行 `npx skills list`，记下 skill
的安装路径，并让 `SKILL_SOURCE` 指向该路径，以便执行下方的案件准备命令。如果
skill 没有出现，请重启对应的 Agent 会话。

```bash
export SKILL_SOURCE="/path/reported/by/skills-list/assess-ontario-tenant-application"
test -f "$SKILL_SOURCE/SKILL.md"
```

### Manual fallback / 手工安装 fallback

Use this fallback when Node.js or npm is unavailable, when the installer cannot
reach GitHub, or when organizational policy requires a reviewed local
checkout. Clone the repository and verify the canonical skill directory:

如果没有 Node.js 或 npm、安装器无法访问 GitHub，或组织政策要求使用经过审核的
本地 checkout，请使用此 fallback。先克隆仓库并验证权威 skill 目录：

```bash
git clone https://github.com/thinkbold/skills.git
cd skills
export SKILL_SOURCE="$PWD/assess-ontario-tenant-application"
test -f "$SKILL_SOURCE/SKILL.md"
```

Copy or link the complete directory into the runtime's documented personal or
project skills parent. Common locations are:

将完整目录复制或链接到运行时文档指定的个人级或项目级 skills 父目录。常见位置
如下：

- Codex and cross-runtime: `~/.agents/skills` or `.agents/skills`
- Claude Code: `~/.claude/skills` or `.claude/skills`
- GitHub Copilot CLI: `~/.agents/skills`, `.agents/skills`, or `.github/skills`

Example:

示例：

```bash
export SKILLS_PARENT="$HOME/.agents/skills"
mkdir -p "$SKILLS_PARENT"
ln -s "$SKILL_SOURCE" \
  "$SKILLS_PARENT/assess-ontario-tenant-application"
```

If symbolic links are unavailable, confirm the destination does not already
exist and replace `ln -s` with:

如果环境不支持软链接，请先确认目标不存在，再用下列复制命令替代 `ln -s`：

```bash
cp -R "$SKILL_SOURCE" \
  "$SKILLS_PARENT/assess-ontario-tenant-application"
```

Preserve the directory name and every bundled `scripts/`, `references/`,
`assets/`, and `agents/` file. `agents/openai.yaml` is optional Codex display
metadata and is not a workflow dependency.

必须保留目录名以及全部 `scripts/`、`references/`、`assets/` 和 `agents/`
文件。`agents/openai.yaml` 是可选的 Codex 界面元数据，不是工作流依赖。

## Prepare One Case / 准备一宗案件

Create one controlled directory per tenancy application. Do not combine or
compare separate applications.

每宗租赁申请使用一个独立的受控目录。不得合并或比较不同申请。

```bash
export CASE_DIR="/secure/path/to/case-001"
mkdir -p "$CASE_DIR/inputs" "$CASE_DIR/work" "$CASE_DIR/outputs"
cp "$SKILL_SOURCE/assets/case-manifest.template.json" \
  "$CASE_DIR/case-manifest.json"
```

Before invoking the skill:

- Edit `case-manifest.json`; replace every synthetic example value.
- Confirm Ontario (`CA`/`ON`), ordinary market housing, no owner-shared kitchen
  or bathroom, proposed rent, and lease term.
- List only applicants who will sign this lease. Put each allowed PDF, PNG,
  JPEG, CSV, TXT, or Markdown file under the case directory and list its
  relative path in the manifest.
- Confirm controlled storage, the privacy-responsible person, and the applicant
  access/correction process.
- Record the current, counsel-approved general authorization. It must disclose
  open-web checks. The bundled authorization is a draft and is not approved for
  production.
- Record Facebook and LinkedIn consent separately. No social-platform search is
  allowed without current, platform-specific consent.

调用 skill 前：

- 编辑 `case-manifest.json`，替换所有合成示例值。
- 确认地点为安大略省（`CA`/`ON`）、属于普通市场住宅、不与业主或其家人共用
  厨房或卫生间，并填写拟议租金和租期。
- 只列入本次租约的签约申请人。把允许的 PDF、PNG、JPEG、CSV、TXT 或 Markdown
  文件放在案件目录内，并在 manifest 中填写相对路径。
- 确认受控存储、隐私负责人，以及申请人的访问和更正流程。
- 记录当前已经安大略省律师审核的一般授权版本；授权必须披露开放网络检索。
  随附授权文本只是草案，不得直接用于生产。
- 分别记录 Facebook 和 LinkedIn 授权。没有当前有效的平台专项授权时，不得搜索
  对应社交平台。

## Use / 使用

Start the agent from an environment that can see both the installed skill and
the controlled case directory. Name the skill explicitly the first time.

从能够访问已安装 skill 和受控案件目录的环境启动 agent。首次使用时应明确写出
skill 名称。

English prompt:

```text
Use assess-ontario-tenant-application to assess exactly one Ontario market-rental case at /secure/path/to/case-001. Run preflight before opening evidence. Use only current authorizations, keep public-source results isolated, run the deterministic pipeline, and leave the tenancy decision for human review.
```

中文提示词：

```text
使用 assess-ontario-tenant-application 评估 /secure/path/to/case-001 中唯一一宗安大略省普通市场租赁申请。读取证据前先运行 preflight；只使用当前有效授权；将公开来源结果与核心评估隔离；运行确定性 pipeline；最终租赁决定留给人工完成。
```

Claude Code and Copilot CLI can also expose the skill as
`/assess-ontario-tenant-application`. Add the case path and the same scope
constraints after the command. Automatic discovery is runtime-dependent, so an
explicit name is preferred for the first run.

Claude Code 和 Copilot CLI 也可能把它显示为
`/assess-ontario-tenant-application`。在命令后附上案件路径及相同的范围限制。
自动发现行为取决于运行时，因此首次运行建议明确写出名称。

The expected execution order is:

1. Preflight and policy check before evidence access.
2. Provenance-rich extraction to `work/extracted-evidence.json`.
3. Redaction and protected-field isolation.
4. Verification of income, monthly debt, credit, rental, and optional bank
   evidence.
5. Authorized open-web searches, with Facebook and LinkedIn gated separately.
6. Deterministic calculation, evidence validation, and report generation.
7. Human discrepancy handling, applicant correction opportunity, and final
   human decision.

预期执行顺序为：

1. 在读取证据前完成 preflight 和政策检查。
2. 将带完整来源定位的信息提取到 `work/extracted-evidence.json`。
3. 脱敏并隔离受保护字段。
4. 核验收入、每月债务、信用、租赁历史和可选银行资料。
5. 执行已授权的开放网络检索，并分别检查 Facebook 和 LinkedIn 专项授权。
6. 运行确定性计算、证据验证和报告生成。
7. 由人工处理不匹配，给予申请人更正机会，并完成人工决定。

The agent may prepare employer, previous-landlord, and applicant clarification
messages, but must not send them automatically.

Agent 可以准备雇主、前房东及申请人澄清所需的邮件、短信或电话内容，但不得
自动发送或联系。

## Outputs / 输出

The generated `outputs/` directory contains:

- `preflight.json`: scope, privacy, authorization, and policy gates.
- `assessment.md`: core evidence assessment and rent-coverage facts.
- `evidence.json`: cited, sanitized evidence states.
- `discrepancies.md`: material mismatches and pending human dispositions.
- `public-records.md`: isolated authorized public-source search outcomes.
- `human-decision.json`: blank decision fields for the property manager or
  individual landlord.
- `audit.jsonl`: generated-artifact audit trail.
- Prepared outreach content, when applicable; nothing is sent automatically.

生成的 `outputs/` 目录包含：

- `preflight.json`：范围、隐私、授权和政策门槛。
- `assessment.md`：核心证据评估和租金覆盖事实。
- `evidence.json`：带来源、已脱敏的证据状态。
- `discrepancies.md`：重大不匹配及待人工填写的处理结果。
- `public-records.md`：隔离保存的、经授权的公开来源检索结果。
- `human-decision.json`：留给物业经理或个人房东填写的空白决定字段。
- `audit.jsonl`：生成文件的审计轨迹。
- 适用时生成的联络内容；任何内容都不会被自动发送。

Review every limitation and pending discrepancy. The generated package is
evidence support for a human decision, not a decision or legal opinion.

必须人工审阅所有限制和待处理不匹配。生成的证据包只用于支持人工决定，不是
决定本身，也不是法律意见。

## Update / 更新

For an installation managed by the recommended installer:

如果使用推荐安装器管理 skill：

```bash
npx skills update assess-ontario-tenant-application
```

Review the release notes and rerun the bundled tests before using an updated
version on a live case. For a manual symlink installation, update the canonical
checkout with `git pull --ff-only`. For a manual copied installation, verify no
case data is stored inside the skill directory, then replace the copy through
your approved file-management process.

在真实案件中使用更新版本前，应审阅 release notes 并重新运行随附测试。手工
软链接安装可在权威 checkout 中运行 `git pull --ff-only`；手工复制安装则应先确认
skill 目录内没有案件资料，再通过获准的文件管理流程替换副本。

## Uninstall / 卸载

For an installation managed by the recommended installer:

如果使用推荐安装器管理 skill：

```bash
npx skills remove assess-ontario-tenant-application
```

For a manual installation, remove only the installed skill link or copied
skill directory from the chosen runtime's skills parent. Do not delete case
directories as part of uninstall. Case deletion follows the retention plan and
requires a reviewed dry run.

手工安装时，只从所选运行时的 skills 父目录移除已安装的软链接或 skill 副本。
卸载 skill 时不得删除案件目录。案件删除必须遵循留存计划，并先人工审阅 dry
run。

To preview case retention actions without deleting anything:

以下命令只预览案件留存动作，不会删除文件：

```bash
PYTHONPATH="$SKILL_SOURCE" python3 \
  "$SKILL_SOURCE/scripts/manage_retention.py" "$CASE_DIR"
```

## Troubleshooting / 故障排查

- **Skill is not discovered / 找不到 skill**: confirm the directory name,
  `SKILL.md`, and runtime-specific parent path; restart a session that was open
  before a new top-level skills directory was created.
- **Python import error / Python 导入错误**: set `PYTHONPATH` to the canonical
  skill directory and run the bundled script by its absolute path.
- **Preflight stops / Preflight 停止**: read only `outputs/preflight.json` and
  correct its listed prerequisites before evidence access.
- **No browser or web tool / 没有浏览器或网页工具**: report a missing runtime
  capability and leave the required public-source stage incomplete. Do not
  silently skip it / 不得静默跳过。
- **Cloud runtime / 云端运行时**: do not upload applicant data unless that
  environment, its retention terms, its network behavior, and every external
  service have been approved for the case.

## Standards and Runtime Documentation / 标准与运行时文档

- [Agent Skills specification](https://agentskills.io/specification)
- [Claude Code skills](https://code.claude.com/docs/en/slash-commands)
- [GitHub Copilot agent skills](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/add-skills)

以上链接用于核对当前格式和安装目录。各运行时可能更新其发现路径或权限模型；
部署前应以对应运行时的最新官方文档为准。
