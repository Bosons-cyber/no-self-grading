---
name: no-self-grading
description: "For LLM-assisted code development where several agents write the same repository: audit and refactor it so agents work correctly and cheaply and never hold their own judge (entry points, single sources of truth, handoff, protected-remote gates)."
description_zh: "面向多 agent 写同一仓库的代码开发，审计并重构工作区"
description_en: "Audit repos where several coding agents write the same code base"
version: 1.1.0
license: MIT
slug: no-self-grading
displayName: No Self-Grading
summary: "面向多个 agent 写同一仓库的 LLM 辅助代码开发：审计并重构工作区（入口、单一事实源、交接、受保护远端上的裁判）"
---

# No Self-Grading

## Purpose

Make a workspace **readable and safe for agents that have no conversational history** — whether they are
separate agent sessions, several agents running in parallel, or teammates whose LLMs must pick up the project cold.

Core idea: **turn implicit conventions into explicit, machine-readable, checkable facts.**

- 「约定藏在人脑 / 历史对话里」 → 新会话每次重新探查 = 纯 token 浪费。
- 文档互相矛盾 → 模型读到**矛盾事实**，行为随机化、结论不可复现。
- 多 agent（或多人团队 = 多 LLM 协作）没有写权限边界 → 互相覆盖，且**无法归因**。

So this skill is **positively correlated with both output quality and token efficiency**: a workspace whose
facts are authoritative and non-contradictory lets an agent read once and act correctly.

## Scope — check this before anything else

**In scope:** LLM-assisted code development where **several agents write the same repository**.
One chat window can still mean several agents: sub-agents dispatched by a main agent, agents running in the
background in parallel, or one LLM writing code while another LLM writes or runs the tests.

**Out of scope:** only one agent writes at any time **and** you personally read every round's diff.
That condition is the whole exemption: a later session that does not remember why an earlier one set up a gate
will happily loosen it, and the only thing stopping that is your review. **The day you stop reading every
round's diff, the project is back in scope.** If all you want is consistent naming, use the vocabulary part
(Phase 0.5) on its own.

Also out of scope: unattended agents that are not doing code development (scheduled jobs, ops bots).

If the repository is out of scope, say so and stop; do not apply a reduced version of this skill.

**Prerequisites — set these up before any other phase:**

1. **A protected remote repository** where nothing reaches `main` without the user's approval: branch protection
   on `main` with review by the code owner and required checks, `CODEOWNERS` over the judge files, and separate agent
   credentials that cannot bypass those rules. There is no "no remote" tier: without it the
   judged party holds the judge. If it is missing, the first step is to list it in `USER-CHECKLIST.md` and stop
   until the user has done it.
2. **`vocab.json`**: several agents in separate sessions naming things independently is the main source of concept
   fragmentation. Start with about five concepts that already show divergent names; add the rest when new splits appear.

## Platform Neutrality

**This skill encodes concepts, not a platform.** Every step refers to a concept — entry document,
always-applied rule file, cross-session memory, handoff state, referential self-check — while each agent tool
realizes those concepts with different file names. CodeBuddy is merely one such tool, not the reference
implementation; treat every platform name in this skill (including CodeBuddy) as an example.

- **Never hardcode a single platform's paths.** Discover what the target repo already uses. If it has a
  different convention — or none — prefer **`AGENTS.md`**, the cross-tool convention with the widest support.
- **Concept → location mapping** for the common platforms lives in `references/platform-mapping.md`.
  That file is **evidence-based**: every claim carries a source, a survey date, and a confidence level
  (`official` / `second-hand` / `unverified`). Re-verify rather than trust it indefinitely.
- The bundled scripts accept **multiple candidate locations** and silently skip the ones that are absent,
  so they run unchanged on any platform. `audit-workspace.py` reports a **platform profile** — which
  conventions the repo already uses — so adaptation is driven by detection, not assumption.
- **Keep the automation platform-agnostic**: the self-check is a plain CLI command
  (`python tools/verify-refs.py`) that is *then* wired into whatever hook/CI the platform offers.
  The logic stays portable; only the trigger is platform-specific.

### Conventions must be researched, never asserted

Any default this skill recommends has to be **derived from evidence**, not from memory:

1. **Survey first.** Prefer official docs and project sites. Weigh *propagation* — how many tools and
   repos adopt a convention — over any single blog post's recommendation.
2. **Record source + date + confidence.** Mark anything unverified explicitly, so staleness is visible.
   A default built on a remembered, uncheckable convention propagates errors to everyone downstream.
3. **Derive the default.** Example: the default "create `AGENTS.md` when the repo has no convention" rests on
   documented facts — 23 tools listed as natively supporting it, no required fields, nested-file support,
   stewarded by a foundation under the Linux Foundation.
4. **If no convention exists, say so.** Cross-session memory and handoff have no cross-vendor standard;
   the skill labels that as a gap it fills rather than pretending a convention exists.
5. **Then adapt by detection**: reuse what the repo already has (see the decision table in
   `references/platform-mapping.md` §5), and only fall back to the researched default when nothing is found.

## When to Use

Trigger on any of these signals:

- Several agents write (or are about to write) the same repository — see **Scope** above; that is the entry condition, the signals below only say what to fix first.
- **Docs contradict the filesystem** — references point at paths that no longer exist; a newcomer following the
  README fails.
- A new agent **cannot tell where to start**; there is no status doc, or status lives in chat history.
- **Handoff is unclear** — nobody knows what is in progress, what was abandoned and why.
- **The same fact exists in several places** and has drifted apart (inlined copies, duplicated baselines/prompts).
- The repo has **no version control**, or credentials / large foreign trees are not isolated from it.
- Requests phrased as 工作区重构 / 工作区规范 / 让工作区对 agent 友好 / 多 agent 友好 / 多 agent 协作 / 交接文档 /
  文档一致性 / 文档漂移 / AGENTS.md 或入口文档治理 / onboarding 整理 / 长项目频繁新会话 /
  workspace refactor / make this repo agent-friendly.
- **Platform-neutral by design** — works with any agent tooling (AGENTS.md, CLAUDE.md, GEMINI.md,
  `.cursor/rules`, Copilot instructions, CODEBUDDY.md, …), not tied to one vendor.

## Workflow

### Phase 0 — Collect facts (do not judge yet)

```bash
python scripts/audit-workspace.py --root <repo>            # 人读
python scripts/audit-workspace.py --root <repo> --json     # 机器读，便于后续打分
python scripts/verify-refs.py --root <repo>                # 引用一致性（ERROR 必须归零）
```

`audit-workspace.py` emits a compact fact sheet (git state, directory sizes, sensitive-name candidates,
entry/governance docs, duplicate-content suspects, handoff gaps, signal counts) so that evaluating the
workspace **does not require reading dozens of files**. `verify-refs.py --write-default-config` generates a
starter `.agent-ready.json`.

**Section 0 of that report is the platform profile**: which agent-tooling conventions the repo already uses
(`AGENTS.md`, `.cursor/rules`, `CLAUDE.md`, Copilot instructions, …), with a confidence level per family.
Treat it as the input to adaptation — **reuse what is already there**. Do not introduce a second convention
in parallel, and do not rename existing files to match a preference.

### Phase 0.5 — Concept vocabulary (the user defines, the agent asks)

File-level dedup cannot see **concept fragmentation** — the same thing called `user`, then `account`, then
`member` across sessions. Before scoring, interview the user for the 5–10 core concepts: what each **is**, what
it **is not**, accepted aliases, retired names. Generate a versioned `vocab.json` from
`assets/templates/vocab.json`; the "is not" answers become negative assertions marked pending approval.
`vocab.json` is a judge file (user-owned, under `CODEOWNERS`); everything else references it, never copies it.
The agent asks and records, never answers for the user. Skip the interview if the repo already has a vocabulary.
Procedure: `references/vocab-interview.md`. `audit-workspace.py` reports fragmentation suspects.

### Phase 1 — Score, then report **before** changing anything

Score the ten dimensions in `references/audit-checklist.md` (0–2 each, max 20).
Dimension 10 (**judge independence**) is a veto: if it scores 0, the workspace is not deliverable regardless of total.
Present the findings first: what is missing, what contradicts what, and the proposed fix order.
Split the fix list in two from the start: **what the agent will build**, and **what only the user can do**
(`assets/templates/USER-CHECKLIST.md` — remote, branch protection, CODEOWNERS, separate agent credentials
that cannot bypass the protection). Do not start editing before the diagnosis is on the table.

### Phase 2 — P0: build the safety net first

Order matters. Without this order, later edits are irreversible and unattributable.

1. **Version control** — already in place (the protected remote is a prerequisite, see **Scope**); write `.gitignore` covering credentials, foreign read-only
   trees, archives, and (optionally) generated artifacts. Commit a baseline **before** refactoring.
2. **Isolate sensitive files** — move credentials/keys **out of the workspace**; if that is impossible, ignore
   them *and* record them as an explicit residual risk in the status doc.
3. **Fix must-fix references** — every `ERROR` from `verify-refs.py` (a documented path that does not exist).
   Historical values (migration maps, quoted model output, fictional examples) get **exemption markers**,
   not deletion. Each new marker is listed in the report for the user to approve (Rule 3).

### Phase 3 — P1: structure and handoff

1. **Referential self-check in the repo** — copy `scripts/verify-refs.py` in, write `.agent-ready.json`,
   drive `ERROR` to 0, and (ideally) wire it into a hook/CI.
2. **Entry mechanism** — read the platform profile first and **reuse the repo's existing convention**.
   If one exists, extend it; if none does, create `AGENTS.md` (decision table: `references/platform-mapping.md` §5).
   Then ensure the three layers — always-applied rule file / root navigation / workspace navigation — all point
   at the status and structure docs. The read-only list lives **only** in the structure doc (`STRUCTURE.md` §2);
   the rule file **points to it** instead of copying it. If a platform truly needs an inline copy, generate it from §2
   and let the self-check compare the two — never hand-maintain a second copy.
3. **Status vs. handoff split** — a global `STATUS.md` (stable, low-churn) plus a per-direction `STATE.md`
   that **only that direction writes**. Add a direction index so agents can see who is working on what.
4. **Collapse to single sources of truth** — move duplicated facts to one place, convert other sites to
   references. When transcribing, move content **programmatically** and assert byte-equality afterwards;
   never hand-copy.
5. **Resolve spec contradictions** — pick the authoritative chain (rule > structure doc > local README),
   unify the conflicting statements, and give homeless content types an explicit home.

### Phase 4 — Harden

- **Hand the judge to the user** (dimension 10): install `GATES.md` (gate registry: tier, red-line, expiry,
  red sample, shadow/enforce) and `proposals/` (the `###BLOCKED reason=… at=…` exit). Fill in
  `USER-CHECKLIST.md` with the repo's real `{owner}/{repo}` and agent account, and give it to the user.
  The agent may run each item's verification command; it may not do the item or tick it.
- **Add a `scratch/` zone** for throwaway code (no review, no tests), and make sure production code cannot
  import from it. Side-effecting scripts start from `assets/templates/dry-run-script.py` (dry-run by default,
  `--write` to act).

- Add the **"new file → which docs must be updated"** table so docs stop drifting.
- Wire memory files into the entry docs (otherwise no other agent reads or writes them).
- Fix the **generator**, not just its output, when a generated artifact is wrong.
- Record residual risks explicitly in the status doc rather than leaving them implicit.

### Check-up mode — re-run on an agent-ready workspace

For a workspace that was already made agent-ready, run read-only and report drift instead of rebuilding:
docs vs filesystem, the repo's copy of `verify-refs.py` vs the skill's, exemptions vs `main`, user-checklist
items that no longer verify, expired gates or missing red samples, new concept fragmentation, production code
importing from `scratch/`, any change to the judge files themselves (listed item by item for the user to classify),
and this skill vs **its own remote main**. The baseline is a commit on the **protected remote main**, never a snapshot the agent made.
End with exactly one sentinel line:

```
###AGENTREADY drift=<n> score=<x>/20 exempt_up=<n> judge_diff=<n> base=<12-hex commit> skill=<version-or-hash>
```

Details and the drift table: `references/checkup.md`. **Upgrading the bundled scripts in an existing repo**
follows the old-vs-new diff procedure there: a script fix can itself loosen the judge, and check-up cannot see that. It is a natural candidate for a scheduled run.

## Rules (non-negotiable)

1. **Version control before refactoring.** No safety net, no refactor.
2. **Report before editing.** Diagnosis first, then changes.
3. **A green check nobody trusts is worthless.** Provide exemption markers so `ERROR` can stay at 0;
   a permanently red self-check gets ignored. **But exemptions are loosening the judge, so they are counted
   and approved**: the `###VERIFY` sentinel reports every loosening channel (`exempt_lines` / `exempt_ranges` / `legacy_allow_files` / `ignore_hits` / `skip_rules`);
   any increase in any of them versus `main` needs the user's approval, and the agent proposes new exemptions in `proposals/`
   instead of adding them itself. A green bought with a fresh exemption is not a green.
4. **Never only fix the artifact.** Find who wrote the bad value and fix the source.
5. **No absolute paths in anything that can travel** (generated docs, READMEs, scripts). They break on the
   next rename or move — a real incident baked an old workspace name into 33 generated files.
6. **State files have owners.** Split live state per direction; one shared mutable status file plus parallel
   writers equals lost updates.
7. **Never leave a declared-but-empty source of truth.** An empty `shared/persona/` is worse than no directory:
   agents believe it, read nothing, and improvise.
8. **One read-only list, one place.** It lives in `STRUCTURE.md` §2; every other document points to it.
   A hand-kept second copy will drift, and then agents guess. Unavoidable copies are generated and machine-checked.
9. **Research conventions; never assert them from memory.** Before turning any convention into a default,
   check official sources, and record source + date + confidence so the claim can be audited and expires visibly.
   If no convention exists, state that plainly — naming a gap honestly beats inventing a norm.
10. **Adapt by detection, not by assumption.** Read the repo's platform profile first; reuse the conventions
    already present, and only apply a default when nothing is found. Never rename a repo's existing files
    just to match a preferred convention.
11. **The judged party never holds the judge.** Tests, gate config, checkers, CI workflows and `CODEOWNERS`
    belong to the user. When a gate blocks the agent and the agent thinks the gate is wrong, it stops with
    `###BLOCKED reason=… at=…` and writes a proposal in `proposals/`; it never loosens the gate itself.
    Any change that turns a red sample green is loosening and needs the user's approval.
12. **The agent never declares "done".** It reports "agent side complete, N user items pending";
    the user decides when it is done.

## Bundled Resources

| Resource | Use it for |
|---|---|
| `scripts/audit-workspace.py` | Fact collection (Phase 0). Read-only, platform-neutral; honours `.agent-ready.json`. |
| `scripts/verify-refs.py` | Referential-integrity self-check (Phase 2/3). Target is `ERROR = 0`, **with no increase** in the loosening counters (`exempt_lines` / `exempt_ranges` / `legacy_allow_files` / `ignore_hits` / `skip_rules`) versus `main`, and the script's hash matching the skill's remote main. **That hash comparison is done by the caller, outside the script** (`sha256sum` against the remote-main copy): the `sha=` the script reports about itself, and `--expect-sha`, only catch an accidentally stale copy, not a tampered one; it also prints a `coverage:` line stating what it actually scanned, and **refuses to report (exit 2)** when the scan range cannot be trusted — a wrong cwd would otherwise produce a meaningless green. **Its last line is a machine-readable sentinel** — `###VERIFY stamp=… errors=<n> warns=<n> infos=<n> exempt_lines=<n> … sha=<12 hex>` — wire any gate/CI to **that line only**: the prose lines can contain a stray `0 ERROR` (false green), and the exit code is only a hint (`0` clean, `1` ERROR, `3` WARN only and needs human review, `2` refused). |
| `references/audit-checklist.md` | The ten-dimension scoring rubric (dimension 10 = judge independence, a veto), each with what to check and how. Platform-neutral. |
| `references/platform-mapping.md` | Concept → per-platform locations, **evidence-based** (source + survey date + confidence per claim), plus a default-selection decision table (§5) and a re-verification procedure (§6). |
| `references/traps.md` | Catalogue of real incidents (symptom → root cause → correct practice). Read before implementing. Its own header carries the entry count — kept in one place on purpose. |
| `references/vocab-interview.md` | Phase 0.5: how to interview the user for core concepts and generate `vocab.json`. |
| `references/checkup.md` | Check-up mode: drift sources, how to check each, and the `###AGENTREADY` sentinel. |
| `references/feedback.md` | Trial-feedback questionnaire for someone using this skill on **their own** repo. **Not part of the workflow** — hand it out together with the skill when sharing it. |
| `assets/templates/` | Skeletons (**15**): `vocab.json` (concept vocabulary, user-owned), `USER-CHECKLIST.md` (what only the user can do, each item with a read-only verification command), `GATES.md` (gate registry + governance rules), `proposals-README.md` (the `###BLOCKED` exit; becomes `proposals/README.md`), `dry-run-script.py` (side-effect script skeleton, dry-run by default), `AGENTS.md` (entry; rename or alias per platform), `STATUS.md`, `STRUCTURE.md`, `STATE.md`, `entry-rule.md` (three platform-specific variants), `directions-README.md`, `MEMORY.md`, `gitignore`, `agent-ready.json`, and **`agent-docs-maintainer.md`** — a **docs + knowledge-base maintainer subagent** (role, write/read-only boundary, five duties with their pass criteria, gate-sentinel discipline, off-limits list, reporting format). It is **CodeBuddy-specific by placement** (`.codebuddy/agents/<<name>>.md`) while its content stays project-agnostic (`<<...>>` slots); ⚠️ it deliberately omits the `tools` field — the platform docs do not publish the full value enum, so it inherits the default toolset. |

Placeholders in templates are written as `<<...>>`. Adapt names to the target workspace; delete sections that
do not apply rather than leaving them empty.

## Acceptance Criteria

A workspace can be called agent-ready when an agent with **no prior context** can, using only files in the repo:

- find where to start (entry mechanism) and what is currently in progress (status/handoff);
- know which directories it may write and which are read-only, without ambiguity;
- resolve any documented path reference successfully (`verify-refs.py` → `ERROR = 0`);
- find each fact in exactly one authoritative place;
- roll back any change (version control) and see no credential exposure risk;
- see that it **cannot change the judge on its own**: dimension 10 scores 2, meaning every item in
  `USER-CHECKLIST.md` has been done by the user and its verification command passes.

Until then, the agent reports **"agent side complete, N user items pending"** — never "done".
