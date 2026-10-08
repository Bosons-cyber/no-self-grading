# 体检模式（check-up）

> 对**已经做过 agent-ready 改造**的工作区重跑一遍，报告漂移。只读，不改任何文件。
> 适合定期跑（例如每周一次，或每次合并后）。

## 基线是谁定的

所有「对比 main」的项（D1 的 `external_roots` 检查、D2、D3、D5、D10），基线都是**远端受保护 main 上的一个提交号**，体检开始时取一次，整轮不变：

```bash
git fetch origin && BASE=$(git ls-remote origin refs/heads/main | cut -f1)
git rev-parse origin/main   # 必须等于 $BASE，不等就拒绝给结论
```

- **不用 agent 本地生成的快照或基线文件**：agent 能挑开工时间、能先改再生成，基线就跟着它走。
- **不直接信本地的 `origin/main` 引用**：本地引用 agent 也改得动，所以要跟 `ls-remote` 现取的值核对。
- 远端 main 没有分支保护时，这个基线同样不可信，第 10 维照常记 0 分。

## 查什么

| # | 漂移来源 | 怎么查 | 计入 |
|---|---|---|---|
| D1 | 文档与文件系统不一致 | `verify-refs.py --root . --base $BASE` 的 `errors`；哨兵行里 `roots_base` 必须等于 `$BASE` 的前 12 位 | `drift += errors`；`roots_base=-` 或对不上时，D1 记为**没查**，`+1` |
| D2 | 仓库里的 `verify-refs.py` 与 skill 远端 main 上的版本不一致 | 调用方在脚本外 `sha256sum` 仓库里那份，对比远端 main 上那份；`###VERIFY` 的 `sha=` 只作初筛 | 不一致 `+1` |
| D3 | 豁免比 `main` 多 | `###VERIFY` 的 `exempt_lines` / `exempt_ranges` / `legacy_allow_files` / `ignore_hits` / `skip_rules` 逐项对比在 `$BASE` 上重跑的结果 | **只累加正增量**：每项取 max(0, 增量) 再相加。一项涨、一项跌不能相互抵消，否则放宽会被藏住 |
| D4 | 「只有你能做」清单里有项不再通过 | 重跑 `USER-CHECKLIST.md` 每一行的验证命令 | 每项不过 `+1` |
| D5 | 本机 skill 与 skill 远端 main 不一致 | 本机 skill 目录哈希对比远端 main 的哈希 | 不一致 `+1` |
| D6 | 闸门过期 / 红样本缺失 | 读 `GATES.md`：过了有效期没续、红样本文件不存在、关掉闸门红样本不报红 | 每项 `+1` |
| D7 | 审计分数下降 | 按 `audit-checklist.md` 重新打分，对比上次记在 `STATUS.md` 的分数 | 仅报告，不计入 |
| D8 | 概念碎片 | `audit-workspace.py` 的「概念碎片」节：新冒出的同义名、退役 id 复活、与 `vocab.json` 冲突 | 每项 `+1` |
| D9 | 草稿区越界 | `audit-workspace.py` 的「草稿区边界」节（`scratch_imports`）：草稿区外的代码引用了草稿区；解析失败数也要看 | 每条引用 `+1`；解析失败数比上次多也 `+1` |
| D10 | 判据文件被改过 | 把**整份**判据文件（`audit-checklist.md` 第 10 维列出的那些：`.agent-ready.json`、`GATES.md`、`vocab.json`、`CODEOWNERS`、测试与红样本、检查脚本）跟 `$BASE` 逐项比对：`git diff $BASE -- <判据文件>`，JSON 按键逐项列出 | 每处变化 `+1`，**全部列给用户**。算放宽还是收紧由用户判，agent 不替用户分类 |

## 输出

先列每一项的发现，最后一行固定为机器可读的哨兵：

```
###AGENTREADY drift=<n> score=<x>/20 exempt_up=<n> judge_diff=<n> base=<12位提交号> skill=<版本或哈希>
```

`base` 写 `$BASE` 的前 12 位，`judge_diff` = D10 的变化处数。

`exempt_up` = D3 的结果：各豁免计数（`exempt_lines` / `exempt_ranges` / `legacy_allow_files` / `ignore_hits` / `skip_rules`）相对 `origin/main` 的**正增量之和**。不报各项总和，因为一涨一跌时总和不变。

- `drift=0` 不等于「完成」，只表示没有发现新的漂移。
- 第 10 维为 0 分时，`score` 后追加 ` veto=judge-independence`。
- D5 的基准是 **skill 的远端 main**，不是本机那一份：本机那份被改松了，拿它当基准两边照样对得上。
- **D10 是判据，D3 和各脚本报的计数只是提示。** 计数器只能防住已经想到的开关（例如 `concept_ignore`、`scratch_dirs`），
  换一种写法照样能在计数不变的情况下放宽；整份比对不依赖事先知道有哪些开关。
- 检查脚本的退出码只是辅助，体检只认哨兵行。「需人工复核」那一档装什么，由判据文件里的规则决定，不由 agent 判断；
  改分档规则本身就是 D10 的一处变化，按放宽报给用户。
- D2、D5 的哈希比对**由调用方在脚本外面做**（`sha256sum` 对远端 main 上那一版）。脚本 `###VERIFY` 行自报的 `sha=` 只能防无意中落后，
  防不了有意篡改：被改过的脚本完全可以报一个假的哈希。

## 升级脚本时（旧版 → 新版）

体检拿**新脚本**在 main 上重跑出基线，新旧两次读数一样，所以**看不出新脚本本身带来的放宽**。
例：1.1.0 修了「裸文件名不查 `ignore_refs`」的缺陷 —— 以前写进 `ignore_refs` 的裸文件名不生效、照报 WARN，
升级后会一下子全被吞掉，WARN 由黄转绿。按 `GATES.md` 治理规则第 3 条，这属于放宽，要用户批。

已有项目升级前：

1. 用**旧脚本**跑一遍 `--json`，把 WARN / ERROR 清单存下来；
2. 换新脚本再跑一遍；
3. 对比：**旧有新无**的每一条，逐条确认它本来就该忽略，确认结果写进升级 PR 的说明，由用户批准后再合。
   反方向（新脚本多报出来的）多半是以前被藏住的真问题，按 ERROR 正常修。

### 1.1.0 起：`project_roots` 换成 `external_roots`（收紧）

- 旧配置里的 `project_roots` **必须删掉**，留着会被拒绝给结论（退出码 2）。需要报 WARN 的外部前缀改写进 `external_roots`。
- `external_roots` 里**不能写本仓库里真实存在的目录**，写了也会被拒绝给结论：那等于把这个目录下的坏引用整批降成 WARN。
- 升级后会**多出 ERROR**：凡是解析不到、首段又不在 `external_roots` 里的引用，一律算 ERROR。
  最常见的是**整个目录被删掉以后留下的引用**，以前只报 WARN，现在是 ERROR。
  **前提是带了 `--base <受保护 main 的提交号>`**：不带时，脚本只看磁盘上现在有没有这个目录，
  「先删目录、再把它写进 `external_roots`」就能把这些引用降回 WARN（哨兵行会显示 `roots_base=-`），只能靠 D10 的整份比对兜底。这是以前被藏住的真问题，按 ERROR 修，
  不要为了消掉它把目录名写进 `external_roots`（那是放宽，要用户批）。
- 退出码：0 干净，1 有 ERROR，3 只剩 WARN、需人工复核，2 拒绝给结论。退出码只是提示，以 `###VERIFY` 哨兵行为准。
