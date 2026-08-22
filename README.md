# ThinkBold Agent Plugins and Skills

Agent Plugins and portable Agent Skills maintained by ThinkBold.

ThinkBold 维护的 Agent Plugins 与可在多个 Agent 运行时使用的 Agent Skills。

## Assess Ontario Tenant Application

`assess-ontario-tenant-application` prepares an auditable evidence package for
one ordinary Ontario market-rental application. It does not rank applicants,
predict default, or make an approval or rejection decision. Final review and
the tenancy decision remain human.

`assess-ontario-tenant-application` 为一宗安大略省普通市场住宅租赁申请生成
可审计的证据包。它不对申请人排序、不预测违约，也不自动批准或拒绝申请；最终
复核和租赁决定必须由人工完成。

### Install / 安装

#### Agent Plugin / Agent 插件

Clone the repository, add its marketplace, and install the plugin in Codex:

克隆仓库，在 Codex 中添加仓库 marketplace，然后安装插件：

```bash
git clone https://github.com/thinkbold/skills.git
cd skills
codex plugin marketplace add "$PWD"
codex plugin add assess-ontario-tenant-application@thinkbold-skills
```

#### Standalone Agent Skill / 独立 Agent Skill

Install globally and choose one or more detected agents interactively:

全局安装，并在交互界面中选择一个或多个已检测到的 Agent：

```bash
npx skills add thinkbold/skills \
  --skill assess-ontario-tenant-application \
  --global
```

For a non-interactive installation into Codex, Claude Code, and GitHub
Copilot:

如需无人值守地安装到 Codex、Claude Code 和 GitHub Copilot：

```bash
DISABLE_TELEMETRY=1 npx skills add thinkbold/skills \
  --skill assess-ontario-tenant-application \
  --global \
  --agent codex \
  --agent claude-code \
  --agent github-copilot \
  --yes
```

The installer requires Node.js and npm. The installed skill itself requires
Python 3.10 or newer and uses only the Python standard library. See the
[bilingual user guide](plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application/USER_GUIDE.md) for
privacy prerequisites, manual installation, case preparation, invocation, and
uninstall instructions.

安装器需要 Node.js 和 npm。Skill 安装后只需要 Python 3.10 或更高版本，其脚本
仅使用 Python 标准库。隐私前置条件、手工安装、案件准备、调用和卸载方法见
[双语用户指南](plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application/USER_GUIDE.md)。

### Use / 使用

```text
Use assess-ontario-tenant-application to assess exactly one Ontario market-rental case at /secure/path/to/case-001. If case-manifest.json is missing, guide me through the required intake and create it before preflight. Do not open evidence until preflight passes, and leave the tenancy decision for human review.
```

```text
使用 assess-ontario-tenant-application 评估 /secure/path/to/case-001 中唯一一宗安大略省普通市场租赁申请。如果缺少 case-manifest.json，请先引导我回答所需问题并自动创建，再运行 preflight。preflight 通过前不要读取证据，并将最终租赁决定留给人工完成。
```

Never place live applicant data in this repository or an unapproved cloud
workspace.

不得把真实申请人资料放入本仓库或未经批准的云端工作区。

### Update or remove / 更新或卸载

For the Codex plugin:

如使用 Codex 插件：

```bash
codex plugin remove assess-ontario-tenant-application@thinkbold-skills
codex plugin marketplace remove thinkbold-skills
```

For a standalone installation managed by the skills CLI:

如使用 skills CLI 管理独立 Skill：

```bash
npx skills update assess-ontario-tenant-application
npx skills remove assess-ontario-tenant-application
```

### Versioned releases / 版本化发布

Production deployments should review and pin a tagged release instead of
following `main` without review. Tags use the format
`assess-ontario-tenant-application-vX.Y.Z`. Each
[GitHub release](https://github.com/thinkbold/skills/releases) includes a skill
archive and a SHA-256 checksum.

生产部署应审阅并固定到一个 tag，不应在未经复核的情况下持续跟随 `main`。Tag
格式为 `assess-ontario-tenant-application-vX.Y.Z`；每个
[GitHub Release](https://github.com/thinkbold/skills/releases) 都包含 skill 压缩包
及 SHA-256 校验文件。

## Development / 开发

```bash
PYTHONPATH=plugins/assess-ontario-tenant-application/skills/assess-ontario-tenant-application \
  python3 -m unittest discover \
  -s plugins/assess-ontario-tenant-application/tests -v
```

## License

[MIT](LICENSE)
