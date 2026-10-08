# 远端锚点：各平台怎么查

> `USER-CHECKLIST.md` 的 U1–U6、U8，以及审计第 10 维、体检的基线，都要到远端去查。
> 本文件按平台给出**只读**的查法。U 编号的含义和通过标准以 `USER-CHECKLIST.md` 为准，这里只管「怎么查」。
>
> 占位符：`{owner}/{repo}` = 远端仓库；`{agent}` = agent 用的账号；`main` = 受保护的主分支名。

## 0. 通用规则（所有平台）

- **查不了 = 「没查」，不是「通过」，也不是「没保护」。** 命令不存在、没登录、权限不够、平台不认识，
  都记「没查，需人工确认」，体检里计 1 处漂移。只有命令真跑出结果、且结果满足通过标准，才能打勾。
- **403 / 404 先分清原因。** 很多平台读分支保护要管理员权限：agent 的受限账号去查，拿到 403 / 404 很正常，
  这只说明「这个账号看不到」，不说明「没开保护」。这种情况按「没查」记，由你本人用自己的账号查一次。
- **只认远端现取的值。** 本地的 `origin/main`、本地记录、agent 写的报告都不算数。
- **平台网页上看到的设置也可以作证**，但要由你本人看，agent 不能替你截图打勾。

## 1. 任何 git 远端都能用的

| 项 | 命令 | 看什么 |
|---|---|---|
| U1 有远端 | `git remote -v`；`git ls-remote origin refs/heads/main` | 有 origin，且能列出 main 的提交号 |
| 体检基线 | `BASE=$(git ls-remote origin refs/heads/main \| cut -f1)` | 见 `checkup.md`「基线是谁定的」 |
| 引用自检比基线 | `python scripts/verify-refs.py --root . --base $BASE` | 哨兵行 `roots_base=` 等于 `$BASE` 的前 12 位 |

分支保护、CODEOWNERS 是否生效、agent 有没有合并权，这几项 **git 协议本身查不了**，只能用各平台的接口，见下面。

## 2. GitHub（`gh` 命令行）

| 项 | 命令 | 看什么 |
|---|---|---|
| U2 分支保护 | `gh api repos/{owner}/{repo}/branches/main/protection` | `required_pull_request_reviews` 存在。**这个接口要管理员权限**，agent 账号拿到 403 / 404 记「没查」 |
| U2（规则集） | `gh api repos/{owner}/{repo}/rules/branches/main` | 有读权限就能查。返回里有 `type: pull_request` 的规则，`required_approving_review_count` ≥ 1。**只用规则集、没开经典分支保护时，上一条会 404，要看这一条** |
| U3 必过检查 | 同上两条 | 经典保护看 `required_status_checks.contexts`；规则集看 `type: required_status_checks` 里的 `context` |
| U4 CODEOWNERS | `gh api repos/{owner}/{repo}/contents/.github/CODEOWNERS --jq .content \| base64 -d` | 也可能在根目录或 `docs/` 下。再跑 `gh api repos/{owner}/{repo}/codeowners/errors`，`errors` 应为空，否则写错的行不会生效 |
| U5 代码所有者审批 | U2 的两条 | 经典保护：`required_pull_request_reviews.require_code_owner_reviews` 为 `true`；规则集：`require_code_owner_review` 为 `true` |
| U6 agent 权限 | `gh api repos/{owner}/{repo}/collaborators/{agent}/permission --jq .permission` | 见 U6 通过标准 |

- 私有仓库开分支保护需要付费套餐；免费账号的私有仓库查 U2 会失败，按「没查 / 未开」处理，不能跳过。
- 规则集可以设「绕过者」（`bypass_actors`）。agent 账号或它所在的团队在绕过名单里，等于没保护。
  这一项只有对规则集有写权限的账号才能看到，所以要由你本人确认。

## 3. GitLab（`glab` 命令行；自建 GitLab 加 `--hostname <你的域名>`）

`glab api` 在仓库目录里运行时，`:fullpath` 会自动换成当前项目路径。`glab api` 没有 `--jq`，过滤用 `jq`。

| 项 | 命令 | 看什么 |
|---|---|---|
| U2 受保护分支 | `glab api projects/:fullpath/protected_branches/main` | `push_access_levels` 不含 agent 能达到的级别（通常只允许「No one」或 Maintainer），`merge_access_levels` 只允许你（Maintainer = 40），`allow_force_push` 为 `false` |
| U2 审批 | `glab api projects/:fullpath/approval_rules` | 至少一条规则，`approvals_required` ≥ 1。**这是付费功能**；免费版查不到，见下方说明 |
| U3 必过检查 | `glab api projects/:fullpath \| jq .only_allow_merge_if_pipeline_succeeds` | `true` |
| U4 CODEOWNERS | 读仓库里的 `CODEOWNERS`、`docs/CODEOWNERS` 或 `.gitlab/CODEOWNERS` | 裁判路径都归你 |
| U5 代码所有者审批 | U2 第一条的返回里 `code_owner_approval_required` | `true`（付费功能） |
| U6 agent 权限 | `glab api "users?username={agent}" \| jq '.[0].id'` 取 ID，再 `glab api projects/:fullpath/members/all/<ID> \| jq .access_level` | 低于 `merge_access_levels` 要求的级别（例如 Developer = 30，而合并只允许 40） |

- **免费版的锚点只能靠「谁能合并」，不能靠「必须审批」。** 做法是：受保护分支只允许 Maintainer 合并，
  你是唯一的 Maintainer，agent 账号只给 Developer。这样 agent 提了合并请求也合不进去。
  CODEOWNERS 在免费版只起通知作用（U5 做不到），审计第 10 维按「只有你能合并」那一档记分，缺的写进残余风险。
- 合并请求的流水线用的是**请求分支里的** `.gitlab-ci.yml`，agent 改了它就能改掉检查本身。
  免费版挡不住这一下，只能靠「你看完合并请求再合并」；付费版用代码所有者审批把 `.gitlab-ci.yml` 归你。

## 4. Gitea / Forgejo（常见的自建平台，用 `curl` + 只读 token）

| 项 | 命令 | 看什么 |
|---|---|---|
| U2 分支保护 | `curl -H "Authorization: token $TOKEN" https://<域名>/api/v1/repos/{owner}/{repo}/branch_protections` | 有一条覆盖 `main` 的规则；`enable_push` 为 `false` 或推送白名单不含 agent；`required_approvals` ≥ 1；`enable_merge_whitelist` 为 `true` 且 `merge_whitelist_usernames` 只有你 |
| U3 必过检查 | 同上 | `enable_status_check` 为 `true`，`status_check_contexts` 含自检任务名 |
| U4 CODEOWNERS | 读 `CODEOWNERS`、`docs/CODEOWNERS` 或 `.gitea/CODEOWNERS` | 裁判路径都归你（较新的版本才支持 CODEOWNERS，以你所用版本的文档为准） |
| U5 代码所有者审批 | 同 U2 | 是否有「需要代码所有者审批」一类的字段取决于版本；没有就记「没查」，靠合并白名单兜底 |
| U6 agent 权限 | `curl -H "Authorization: token $TOKEN" https://<域名>/api/v1/repos/{owner}/{repo}/collaborators/{agent}/permission` | `permission` 不是 `admin`，且 agent 不在合并白名单里 |

`$TOKEN` 从环境变量读，不写进任何文件。

## 5. Gitee

Gitee 的开放接口只能查到「这个分支有没有被保护」，查不到保护规则的细节（谁能推、谁能合、要不要审批、要不要过检查）。

| 项 | 怎么查 | 看什么 |
|---|---|---|
| U2 分支保护（有无） | `curl "https://gitee.com/api/v5/repos/{owner}/{repo}/branches/main?access_token=$TOKEN"` | `protected` 为 `true` |
| U2 规则细节、U3、U5 | **只能你本人在网页的仓库「管理 → 保护分支」里看** | 推送和合并只允许你；需要审批；需要检查通过。agent 记「没查，需人工确认」 |
| U4 CODEOWNERS | 读仓库文件 | 以 Gitee 文档为准确认支持的位置和是否强制 |
| U6 agent 权限 | 仓库「管理 → 仓库成员」里看 agent 的角色 | 不能是管理员；不能在保护分支的合并名单里 |

## 6. 其他平台（Bitbucket、Azure DevOps、公司内部平台等）

本 skill 没有为它们写命令。U1 用第 1 节；U2–U6 一律记「没查，需人工确认」，由你本人在平台上看过后写明「看过，日期，看的是哪个设置页」。
不要因为「平台不支持」就把这几项记成不适用：适用范围内的项目必须有受保护的远端，这是开工前提。

## 7. CI 里怎么防「改掉裁判再自己跑绿」（U8）

| 平台 | 做法 |
|---|---|
| GitHub Actions | 见 U8：`pull_request_target` 触发，裁判脚本从**基线分支**检出，PR 的内容另检出到子目录、只当数据读、不执行；`permissions: contents: read`；`persist-credentials: false`；不用缓存 |
| GitLab CI | 合并请求流水线跑的是请求分支自己的 `.gitlab-ci.yml`，没有对应 `pull_request_target` 的免费做法。靠「只有你能合并」+ 合并前看 `.gitlab-ci.yml` 和裁判文件的改动 |
| Gitea / Forgejo Actions | 语法接近 GitHub Actions；支不支持 `pull_request_target` 以你所用版本的文档为准，不支持就按 GitLab 那一行处理 |
| 其他 | 记「没查」，同第 6 节 |
