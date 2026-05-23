---
name: agent-memo-review
description: Use when coordinating plan reviews or implementation reviews between Codex, Claude Code, Antigravity CLI, or other agents through a project-local .agent_memo folder.
---

# Agent Memo Review

Use this skill to create, check, review, reconcile, or archive one active cross-agent review in the current project.

## Core Rules

- Use `.agent_memo/` in the project root.
- Version 1 supports one active review at a time.
- Each reviewer writes only `responses/<agent-id>.md`.
- `request.md` is immutable after creation.
- `final.md` is the approved result and must exist before archive.
- For planning reviews, the owner should update the real plan/spec file outside
  `.agent_memo/` before archiving, then archive that approved plan as
  `final.md` or as a concise pointer to the approved plan file.
- If agent identity is unclear, ask the user instead of guessing.

## Agent ID

Infer agent ID in this order:

1. Explicit user wording such as "as agy" or "for cc".
2. Script argument such as `--agent agy`.
3. Reliable host runtime identity.
4. Ask the user for the current action.

Never infer identity from owner, missing responses, or recently edited files.

## Common Intents

- Initialize memo state:
  `python agent-memo-review/scripts/agent_memo.py init --root .`
- Create review:
  `python agent-memo-review/scripts/agent_memo.py create --root . --owner codex --phase planning --topic "auth flow" --reviewers agy,cc --artifact-file docs/plan.md`
- Check review:
  `python agent-memo-review/scripts/agent_memo.py check --root . --agent agy`
- Write feedback:
  `python agent-memo-review/scripts/agent_memo.py respond --root . --agent agy --status approved --body-file /tmp/review.md`
- Reconcile feedback:
  `python agent-memo-review/scripts/agent_memo.py reconcile --root . --owner codex --decisions-file /tmp/decisions.md [--next-round]`
- Archive review:
  `python agent-memo-review/scripts/agent_memo.py archive --root . --owner codex --final-file /tmp/final.md`

## Owner Finalization

- On `changes_requested`, apply accepted feedback to the reviewed plan or
  implementation outside `.agent_memo/`, record decisions, and start another
  round with `--next-round` when reviewer confirmation is needed.
- On approved planning reviews, treat the updated project plan/spec as the
  working source and archive it as `final.md`; future agents should not rebuild
  the final plan from archived response comments.
- On approved implementation reviews, archive a concise final result describing
  what was approved, verification evidence, and known follow-up.

## Interpreting Output

- Run the helper and read its JSON output before responding.
- Summarize the pending action in plain language.
- Open referenced markdown files only when needed to answer or act.
- Treat `final.md` in archived reviews as the source of truth.
- Ask the user before repairing invalid JSON, broken state, or `archive_interrupted` states.
