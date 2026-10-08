# 「只有你能做」清单（USER-CHECKLIST.md）

> agent 把能自动做的都做完之后，**剩下这些只有你（仓库主人）能做**：它们是判定权的锚点，
> 必须落在 agent 够不着的地方。规则不能自己执行自己 —— 这些项不做，第 10 维（判定独立性）就到不了 2 分。
>
> 每一项都带一条**只读验证命令**。agent 可以随时跑这些命令确认你做没做，但**不能替你做，也不能替你打勾**。
> 体检模式会重跑全部验证命令，验证不过的项计入 `drift`。
>
> 占位符：`{owner}/{repo}` = 远端仓库；`{agent}` = agent 使用的账号或 token 所属账号。

| # | 你要做的事 | 为什么 | 验证命令（只读） | 通过标准 | 状态 |
|---|---|---|---|---|---|
| U1 | 建远端仓库并推送 | 本地仓库谁都能改历史，远端才是基准 | `git remote -v` / `git ls-remote origin main` | 有 origin，且 main 能列出 | ☐ |
| U2 | 给 main 开分支保护：必须走 PR、至少 1 个审批 | 不保护 = agent 可以直接推 main | 按平台查，命令照抄 skill 的 `references/remote-platforms.md` 对应平台那一行。GitHub 例：`gh api repos/{owner}/{repo}/rules/branches/main`（规则集，有读权限就能查）或 `…/branches/main/protection`（经典保护，要管理员权限） | 合并前必须审批，至少 1 人。**查到 403 / 404 只说明这个账号看不到，记「没查」，由你本人再查一次，不算通过也不算没保护** | ☐ |
| U3 | 把自检设为必过检查（required status check） | 红了也能合 = 闸门形同虚设 | U2 的命令（GitHub 例：经典保护看 `required_status_checks.contexts`，规则集看 `required_status_checks` 规则里的 `context`） | 含自检任务名 | ☐ |
| U4 | 写 `CODEOWNERS`，把裁判归到你名下：测试 / 契约测试、闸门配置（`.agent-ready.json`、`GATES.md`）、词表 `vocab.json`、自检脚本目录、`.github/workflows/`、`CODEOWNERS` 本身 | 裁判归被裁判的一方 = 没有裁判 | `gh api repos/{owner}/{repo}/contents/.github/CODEOWNERS --jq .content \| base64 -d` | 上述路径都指向你 | ☐ |
| U5 | 开「Require review from Code Owners」 | 不开的话 CODEOWNERS 只是通知 | U2 的命令（GitHub 例：经典保护看 `required_pull_request_reviews.require_code_owner_reviews`，规则集看 `require_code_owner_review`）。有的平台免费版没有这项，按 `references/remote-platforms.md` 的说明记分 | 开启 | ☐ |
| U6 | 给 agent 单独的凭据，且**没有合并权** | 用你本人的 token = agent 就是你 | 按平台查，命令照抄 skill 的 `references/remote-platforms.md` 对应平台那一行。GitHub 例：`gh api repos/{owner}/{repo}/collaborators/{agent}/permission --jq .permission` | agent 的权限够不着合并（GitHub 是 `read` / `triage` / `write`，不是 `maintain` / `admin`） | ☐ |
| U7 | 确认 `GATES.md` 里每道闸门的红样本是你认可的 | 红样本是裁判的裁判 | 打开 `GATES.md` 逐行看 | 每行的红样本存在，且你看过 | ☐ |
| U8 | （若用 CI）workflow 用 `pull_request_target` + 分离 checkout，`permissions: contents: read`，`persist-credentials: false`，不用缓存 | 防 PR 里的代码改掉裁判后自己跑出绿 | 读 `.github/workflows/*.yml` | 满足左侧四条 | ☐ |
| U9 | **本 skill 自己**也放进单独的 git 仓库，推远端、开分支保护、只有你能合并 | skill 给以后每个项目定裁判，被改松一次，之后所有新项目都继承 | `git -C <skill目录> remote -v`；分支保护按 U2 的平台查法查 skill 仓库 | 有远端且受保护；体检比对的基准是**远端 main**，不是本机那份 | ☐ |

**规则**：

- agent 汇报时只能说「agent 侧完成，还有 N 项待你处理」，**不能说「完成」**。
- 你做完一项，让 agent 跑对应验证命令；通过了再打勾。打勾的人是你。
- 不适用的项（例如纯本地仓库不打算上远端）写明「不适用 + 原因」，同时在 `STATUS.md` 记为残余风险。
