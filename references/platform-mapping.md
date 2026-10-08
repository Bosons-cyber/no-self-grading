# 平台对应表：概念 → 各 agent 平台的落地形式

> **本文件是「调查结果」，不是「凭印象的清单」。** 每条都标了来源与置信度，**带调查日期**。
> 平台迭代快 —— 用之前先看日期，必要时按 §6 的方法重新取证，而不是相信记忆。

- **调查日期**：2026-09-11
- **调查方法**：官方文档优先（站点 / 产品文档），二手来源仅作补充并标注
- **置信度**：`官方` = 来自厂商文档或项目官方站；`高可信二手` = 多来源一致但非官方；`未核实` = 待验证，**不要当依据**

---

## 0. 最核心的一条：AGENTS.md 是当前唯一有跨厂商共识的落点

| 事实 | 证据 | 置信度 |
|---|---|---|
| 由 OpenAI Codex、Amp、Jules(Google)、Cursor、Factory 共同推动，现由 **Agentic AI Foundation（aaif.io）在 Linux 基金会下**托管 | [agents.md](https://agents.md/) | 官方 |
| **23 个工具**原生支持（含 Codex、Jules、Factory、Aider、goose、opencode、Zed、Warp、VS Code、Devin、UiPath、Junie(JetBrains)、Amp、Cursor、RooCode、**Gemini CLI**、Kilo Code、Phoenix、Semgrep、**GitHub Copilot**、Ona、**Windsurf**、Augment Code） | 同上 | 官方 |
| GitHub 上已有 **60,000+** 个 `AGENTS.md`（OpenAI 主仓库内部就有 88 个） | 同上 | 官方 |
| **无必填字段**：就是标准 Markdown，标题随意；建议含 项目概览 / 构建与测试命令 / 代码风格 / 测试说明 / 安全注意 | 同上 | 官方 |
| **嵌套生效**：代理读目录树中**最近**的一份，**最近者优先**；显式用户提示覆盖一切 | 同上 | 官方 |
| Cursor 把 `AGENTS.md` 定位为 `.cursor/rules` 的「**更简单的替代方案**」，支持嵌套并与父目录**合并**，**更具体者优先** | [Cursor Docs · Rules](https://cursor.com/docs/rules) | 官方 |
| Gemini CLI 默认 `GEMINI.md`，但文件名**可配置**；官方示例即把它指向 `AGENTS.md` | [agents.md](https://agents.md/)、Gemini CLI 配置文档 | 官方 |
| Aider 通过 `.aider.conf.yml` 的 `read: AGENTS.md` 接入 | [agents.md](https://agents.md/) | 官方 |

> **推论（本技能的默认决策依据）**：给一个**新**仓库或**没有既有约定**的仓库建入口文档时，
> 默认用 **`AGENTS.md`** —— 它是唯一「一份文件被最多工具认」的选择，且**纯 Markdown、无 schema 负担**。
> 不要默认用某个单一平台的专属文件名。

---

## 1. 入口文档（默认进入上下文 / 首屏导航）

| 平台 / 概念 | 落点 | 置信度 |
|---|---|---|
| **跨工具** | `AGENTS.md`（支持嵌套；最近者优先） | 官方 |
| 兼容旧名单数写法 | `AGENT.md`（如 Android Studio 某些版本用单数） | 官方（Android Studio 文档） |
| Claude Code | `CLAUDE.md`（项目级 / 用户级） | 高可信二手 |
| Gemini CLI | `GEMINI.md`（**可配置** → `.gemini/settings.json` 的 `context.fileName`） | 官方 |
| GitHub Copilot | `.github/copilot-instructions.md`（仓库级）；路径级见 §2 | 官方 |
| Cursor | `.cursor/rules/`（**必须 `.mdc`**）；纯 Markdown 用 `AGENTS.md` | 官方 |
| CodeBuddy | `CODEBUDDY.md`；**若根目录没有 `CODEBUDDY.md` 而已有 `AGENTS.md`，则自动加载 `AGENTS.md`** —— 即 CodeBuddy 本身就是「AGENTS.md 兜底」的实践者 | 官方 |
| Windsurf | `.windsurf/rules/` | 未核实 |
| Aider / 其他 | `.aider.conf.yml` 的 `read:`、`CONVENTIONS.md` | 官方（Aider 配置） |

**通用做法**：正文写成**平台无关**的一版；按平台改名 / 软链（agents.md 官方给的迁移手法就是
`mv AGENT.md AGENTS.md && ln -s AGENTS.md AGENT.md`）。
内容只干一件事：**把读者送到权威文档**（状态 + 规范），不要在这里堆细节。

---

## 2. 始终生效的规则 / 路径级指令

| 平台 | 落点 | 生效机制 | 置信度 |
|---|---|---|---|
| Cursor | `.cursor/rules/*.mdc` | frontmatter：`alwaysApply: true` → 始终包含；`false` + `globs` → 匹配文件进上下文时附加；`false` + `description` → 由 Agent 判断是否引入；**三者都无 → 只在 `@` 提及时才用** | 官方 |
| GitHub Copilot | `.github/instructions/*.instructions.md` | frontmatter `applyTo` 匹配到正在处理的文件时才包含 | 官方 |
| CodeBuddy | **项目规则**：`.codebuddy/rules/<规则名>/RULE.mdc`（一条规则一个文件夹）；**用户规则**：存在于「本机用户目录」，**官方未公开具体路径** | frontmatter `description` / `alwaysApply` / `enabled`；`alwaysApply: true` → 每次会话加载原文；`false` → 只加载名称与描述、由模型按相关性决定 | 官方 |
| Claude Code | `CLAUDE.md`（根 / 子目录） | 自动读取 | 高可信二手 |
| Gemini CLI | `GEMINI.md`（或配置的文件名） | 自动读取 | 官方 |
| 跨工具 | `AGENTS.md` | 自动读取（嵌套合并，最近者优先） | 官方 |

> ⚠️ **Cursor 专属坑（官方文档明写）**：`.cursor/rules/` 里的**普通 `.md` 会被规则系统忽略**
> （因为缺少规定 `description` / `globs` / `alwaysApply` 的 frontmatter）。
> 想在该目录用纯 Markdown 是无效的 —— 要么改名 `.mdc` 并加 frontmatter，要么改用 `AGENTS.md`。

> ⚠️ **优先级只在部分平台被明确规定**：Cursor 明说「团队规则 → 项目规则 → 用户规则，靠前者优先」，
> 但**未规定** `AGENTS.md` 与 `.cursor/rules` 冲突时谁赢。**不要凭空假设跨来源的优先级** ——
> 这正是「同一事实只留一份」比「多份共存 + 猜优先级」更可靠的原因。

**关键坑**：这类文件通常在**会话开始时**加载 —— 改完要**新开会话**才生效，务必在文件里写明。
（CodeBuddy 官方原文：规则「只在每个会话的开始部分添加一次」，创建或修改后**当前会话不会自动加载**。）

**另一个实践约束**（CodeBuddy 官方最佳实践，其它平台同理）：`alwaysApply: true` 的规则建议只保留
**3–5 个**，单个规则**控制在 500 行以内** —— 常驻上下文是有成本的。因此「铁律」要**少而硬**，
细则放按需加载的规则或普通文档。

---

## 3. 跨会话记忆与交接 —— **没有业界标准**（这是空白点）

| 来源 | 做法 | 置信度 |
|---|---|---|
| CodeBuddy ·「记忆偏好」 | **全局、跨项目**，由 AI **通过对话**自动管理，**官方未公开文件路径**；官方明确「记忆是全局的，会在所有项目中生效」，**无项目级/用户级之分** | 官方 |
| CodeBuddy · 工作记忆文件 | `.codebuddy/memory/*.md`（本运行环境提供的机制，与上面的「记忆偏好」是两回事） | 观察（环境行为） |
| 其他平台 | 私有目录（如 `.claude/` 等），互不通用 | 未逐一核实 |
| 社区实践 | `HANDOFF.md`（会话收尾写交接文档）、按 session 的 JSON 日志 | 高可信二手 |
| 公开标准 | **没有**。截至调查日期，未见任何跨厂商的「记忆文件」规范 | 调查结论 |

**因此本技能的做法是「补空白」而非「遵循惯例」**，并明确推荐：

1. **把记忆放在项目内、用相对路径引用**（跨平台最稳；平台私有目录换平台就丢）。
2. **关键不是路径，而是「入口文档必须引用它」** —— 否则别的 agent 不会读也不会写。
3. **状态分层**：全局稳定状态一份 + 每个方向自己的 `STATE.md`（只由该方向写）。
4. 不要把平台私有目录当作记忆的**唯一**位置 —— 那等于把项目知识锁死在某个工具里。

---

## 4. 子 agent / 命令 / hooks

| 概念 | 落点 | 置信度 |
|---|---|---|
| 自定义命令 | `.claude/commands/`、`.codebuddy/commands/`、`.github/prompts/` | 未核实（逐平台差异大） |
| 子 agent | 各平台 agents / subagent 目录 | 未核实 |
| hooks（自动执行） | 平台各自配置（如 `.claude/settings.json`） | 未核实 |

**通用做法**：把「改完跑自检」固化成一个**平台无关的命令**（如 `python tools/verify-refs.py`），
再按需用各平台的 hook / CI 挂上去。**逻辑不绑定平台，只有触发方式绑定平台。**

---

## 5. 默认决策表（由上面的证据推导）

**先探测，再决定；什么都探测不到才套默认。**

| 探测到的现状 | 该怎么做 |
|---|---|
| 已有 `AGENTS.md`（可能有多层） | **沿用**。新约定加进最近的那一层；不要另起平台专属入口文档 |
| 已有 `.cursor/rules/*.mdc` 且在用 | 沿用 Cursor 规则；但要意识到它**只被 Cursor/同类工具读**，跨工具信息仍应放 `AGENTS.md` |
| 已有 `CLAUDE.md` / `GEMINI.md` / `CODEBUDDY.md` 等单一平台入口 | **保留**（改动小、迁移成本低），但建议同时放一份 `AGENTS.md`（或软链）以覆盖其他工具 |
| 有多种入口文档并存 | 让它们**都指向同一份** `STATUS.md` + `STRUCTURE.md`；**不要各维护一套内容**（必然漂移） |
| **什么都没有** | 建 **`AGENTS.md`**（证据最充分：23 工具支持、无 schema、可嵌套），并按生命周期逐步加 `STATUS.md` / `STRUCTURE.md` / `STATE.md` |
| 需要路径级 / 文件类型级生效的规则 | Cursor 用 `.mdc` + `globs`；Copilot 用 `instructions.md` + `applyTo`；其余情形优先放进 `AGENTS.md` 的对应小节 |

---

## 6. 怎么重新取证（本文件会过期）

1. **优先官方来源**：项目官方站（如 `agents.md`）、厂商产品文档（Cursor Docs、GitHub Docs、Gemini CLI 文档）。
2. **看传播面**：某约定的支持工具数与仓库数，比单个博客的推荐更有分量。
3. **记录"调查日期 + 来源链接 + 置信度"**，把 `未核实` 显式标出来 —— 不要让下一轮把猜测当事实。
4. **不要凭记忆断言行业约定**：记忆会过期，且无法被审阅。取一次证的成本远低于按错的默认改一轮。
5. 平台自身往往能回答：**直接问当前运行的 agent 平台「你的规则文件 / 记忆文件放在哪」**，
   比在外网找二手资料更快更准。
