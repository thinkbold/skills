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
- Local filesystem and shell access to one controlled case directory.
- A browser or web-search tool for the authorized open-web stage.
- An operator who can approve tool use, verify extracted facts, handle consent,
  and complete the final human decision.
- Controlled storage approved for applicant personal information. Do not place
  a live case in a public repository, ordinary chat attachment, or unapproved
  cloud workspace.

完整执行需要同时满足以下条件：

- Python 3.10 或更高版本；随附脚本只使用 Python 标准库。
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

## Get the Skill / 获取 Skill

Clone or update the repository, then point `SKILL_SOURCE` at the canonical
skill directory:

克隆或更新仓库，然后让 `SKILL_SOURCE` 指向权威 skill 目录：

```bash
git clone https://github.com/thinkbold/skills.git
cd skills
export SKILL_SOURCE="$PWD/assess-ontario-tenant-application"
test -f "$SKILL_SOURCE/SKILL.md"
```

The following examples use a symbolic link so one checkout can serve multiple
local agents. Use the copy command instead when links are unavailable. Run only
the command for the runtime and scope you intend to use.

下列示例优先使用软链接，让同一个源码目录可供多个本地 agent 使用。如果环境
不支持软链接，可以改用复制命令。只执行与你需要的运行时和作用域对应的命令。

## Install / 安装

### Codex: personal or cross-runtime / Codex：个人或跨运行时

Install in the shared personal Agent Skills location:

安装到个人级通用 Agent Skills 目录：

```bash
mkdir -p "$HOME/.agents/skills"
ln -s "$SKILL_SOURCE" \
  "$HOME/.agents/skills/assess-ontario-tenant-application"
```

For one repository, link it under that repository's `.agents/skills` folder:

如果只供一个项目使用，在该项目的 `.agents/skills` 目录中建立链接：

```bash
export PROJECT_ROOT="/path/to/your/project"
mkdir -p "$PROJECT_ROOT/.agents/skills"
ln -s "$SKILL_SOURCE" \
  "$PROJECT_ROOT/.agents/skills/assess-ontario-tenant-application"
```

`agents/openai.yaml` provides optional Codex display metadata. Other agents do
not need it.

`agents/openai.yaml` 只提供可选的 Codex 界面元数据，其他 agent 不依赖它。

### Claude Code: personal or project / Claude Code：个人或项目

Claude Code uses `~/.claude/skills` for personal skills and `.claude/skills`
for project skills:

Claude Code 的个人级目录是 `~/.claude/skills`，项目级目录是
`.claude/skills`：

```bash
# Personal / 个人级
mkdir -p "$HOME/.claude/skills"
ln -s "$SKILL_SOURCE" \
  "$HOME/.claude/skills/assess-ontario-tenant-application"

# Project / 项目级
export PROJECT_ROOT="/path/to/your/project"
mkdir -p "$PROJECT_ROOT/.claude/skills"
ln -s "$SKILL_SOURCE" \
  "$PROJECT_ROOT/.claude/skills/assess-ontario-tenant-application"
```

If the top-level skills directory is created while Claude Code is already
running and the skill does not appear, restart that Claude Code session.

如果在 Claude Code 已运行时才新建顶层 skills 目录，而 skill 没有出现，请重启
该 Claude Code 会话。

### GitHub Copilot CLI: personal or project / GitHub Copilot CLI：个人或项目

Use `~/.agents/skills` for a personal skill shared with other compatible
runtimes, or `.agents/skills` for one project. Copilot also recognizes
`.github/skills` for project-specific skills.

个人级、可与其他兼容运行时共享时使用 `~/.agents/skills`；单个项目使用
`.agents/skills`。Copilot 也支持项目内的 `.github/skills`。

```bash
# Personal / 个人级
mkdir -p "$HOME/.agents/skills"
ln -s "$SKILL_SOURCE" \
  "$HOME/.agents/skills/assess-ontario-tenant-application"

# Project using the GitHub-specific location / 使用 GitHub 项目级目录
export PROJECT_ROOT="/path/to/your/project"
mkdir -p "$PROJECT_ROOT/.github/skills"
ln -s "$SKILL_SOURCE" \
  "$PROJECT_ROOT/.github/skills/assess-ontario-tenant-application"
```

Use a local or otherwise privacy-approved Copilot environment for live
applicant data. Installing the skill does not by itself approve a cloud agent
to receive personal information.

真实申请人资料只能在本地或已经通过隐私审批的 Copilot 环境中处理。安装该 skill
本身并不代表可以把个人信息交给云端 agent。

### Other runtimes / 其他运行时

For another Agent Skills-compatible runtime, place the complete canonical
directory under the personal or project skills parent documented by that
runtime. Preserve the directory name and every bundled `scripts/`,
`references/`, `assets/`, and `agents/` file. Format compatibility alone is not
enough: the runtime must also satisfy the prerequisites above.

对于其他 Agent Skills 兼容运行时，请按照该运行时的文档，把完整的权威目录放到
个人级或项目级 skills 父目录下。必须保留目录名，以及其中全部 `scripts/`、
`references/`、`assets/` 和 `agents/` 文件。仅格式兼容还不够，运行时也必须满足
上述前置条件。

### Copy instead of linking / 使用复制而不是软链接

For any destination above, replace the link command with the following, after
confirming the destination does not already exist:

对于上述任一目标目录，确认目标尚不存在后，可以用下面的复制命令替代软链接：

```bash
export SKILLS_PARENT="/the/runtime/skills/parent"
mkdir -p "$SKILLS_PARENT"
cp -R "$SKILL_SOURCE" \
  "$SKILLS_PARENT/assess-ontario-tenant-application"
```

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

For a symlink installation, update the checkout and rerun the tests before live
use:

软链接安装只需更新源码 checkout，并在处理真实案件前重新运行测试：

```bash
cd "$(dirname "$SKILL_SOURCE")"
git pull --ff-only
PYTHONPATH=assess-ontario-tenant-application python3 -m unittest discover \
  -s assess-ontario-tenant-application/tests -v
```

For a copied installation, verify no live case data is stored inside the skill
directory, remove the old copied skill directory through your normal approved
file-management process, then repeat the copy command from the updated source.

如果使用复制安装，先确认 skill 目录内没有真实案件数据，再通过正常且获准的文件
管理流程移除旧副本，然后从更新后的源码重新执行复制命令。

## Uninstall / 卸载

Remove only the installed skill link or copied skill directory from the chosen
runtime's skills parent. Do not delete case directories as part of uninstall.
Case deletion follows the retention plan and requires a reviewed dry run.

只从所选运行时的 skills 父目录移除已安装的软链接或 skill 副本。卸载 skill 时
不得删除案件目录。案件删除必须遵循留存计划，并先人工审阅 dry run。

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
