# No Self-Grading

An agent skill for **LLM-assisted code development where several agents write the same repository**.
It audits and refactors the repo so that agents with no chat history can start work correctly and cheaply,
and so that **no agent can loosen the checks that judge its own work without your approval**.

面向「多个 agent 写同一个仓库」的 LLM 辅助代码开发：让没有对话历史的 agent 也能正确、省 token 地开工，
并且让被检查的一方不经你批准，就改不松检查自己的东西。

## Is this for you?

**Yes**, if several agents write the same repo. One chat window can still count: sub-agents dispatched by a main
agent, agents running in parallel in the background, or one LLM writing code while another writes or runs the tests.

**No**, if only one agent writes at any time **and** you read every round's diff yourself. The day you stop
reading every diff, you are back in scope. If you only want consistent naming, the concept vocabulary part
works on its own.

**Before you start** you need a protected remote repository where nothing reaches `main` without your approval
(review by the code owner, required checks, no bypass for the agent account, which has its own login) and a small
`vocab.json` of core concepts.
The skill checks both and stops until they exist.

## What it does

1. **Collect facts** with read-only scripts: entry docs, contradictions between docs and the filesystem,
   duplicated facts, handoff gaps, concept fragmentation.
2. **Score ten dimensions** (max 20) and report before changing anything. Dimension 10, judge independence, is a veto.
3. **Fix in a safe order**: safety net first, then structure and handoff, then hardening.
4. **Check-up mode** runs again later, read only, and reports drift against a commit on the protected remote `main`.

Everything the agent cannot do for you (protection rules, `CODEOWNERS`, the agent account) goes into a
user checklist with a read-only command to verify each item. The agent reports
"agent side complete, N user items pending" and never declares the work done.

## How it is built

The skill does not invent new techniques. It combines mature practices and applies them to one situation:
the agent that changes a check may be the agent that check is judging.

- **Red samples** (in the spirit of mutation testing): every gate has a sample it must reject; if switching
  the gate off does not turn the sample red, the gate is broken.
- **Ratchet**: exemptions and skip rules are counted; any increase versus `main` needs your approval.
- **Shadow mode first**: a new gate can only report at first, before it starts blocking.
- **`CODEOWNERS` and branch protection**: the judge files belong to you, and no change reaches `main` without your approval.
- **Loosening and tightening are approved separately**, so a fix cannot quietly relax a check.

## Install

Copy this folder to wherever your agent tool loads skills, keeping the folder name `no-self-grading`.
The skill is platform-neutral; `references/platform-mapping.md` lists, with sources and dates, where common
agent tools expect entry docs, rule files and memory.

Then ask your agent something like "make this repo ready for several agents" or "run a check-up".

## Contents

| Path | What it is |
|---|---|
| `SKILL.md` | The skill itself: scope, workflow, rules |
| `scripts/` | Read-only fact collection and the referential self-check |
| `references/` | Scoring rubric, check-up, per-platform remote checks, real incidents, vocabulary interview |
| `assets/templates/` | Skeletons for entry docs, status and handoff, gate registry, user checklist |
| `release/` | This repo's own publish gate (the `public-names` check) |

## Contributing

Changes go through pull requests and need the code owner's approval. To add a word to the publish allowlist,
open a separate pull request that changes only `release/public-names.allow`.

## License

MIT, see `LICENSE`.
