---
name: agent-relaypad
description: Use when coordinating plan reviews or implementation reviews between Codex, Claude Code, Antigravity CLI, or other agents through a project-local .agent-relaypad folder, or when installing/updating the agent-relaypad skill.
---

# Agent Relaypad

Use this skill to create, check, review, reconcile, or archive one active cross-agent review in the current project.

## Core Rules

- Use `.agent-relaypad/` in the project root.
- Version 1 supports one active review at a time.
- Each reviewer writes only `responses/<agent-id>.md`.
- `request.md` is immutable after creation.
- `final.md` is the approved result and must exist before archive.
- For planning reviews, the owner should update the real plan/spec file outside
  `.agent-relaypad/` before archiving, then archive that approved plan as
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

- Initialize relaypad state:
  `python agent-relaypad/scripts/relaypad.py init --root .`
- Create review (any of `codex`, `cc`, `agy`, or a custom agent id is valid as `--owner`):
  `python agent-relaypad/scripts/relaypad.py create --root . --owner <your-agent-id> --phase planning --topic "auth flow" --reviewers agy,cc --artifact-file docs/plan.md`
- Check review:
  `python agent-relaypad/scripts/relaypad.py check --root . --agent agy`
- Write feedback:
  `python agent-relaypad/scripts/relaypad.py respond --root . --agent agy --status approved --body-file /tmp/review.md`
- Reconcile feedback:
  `python agent-relaypad/scripts/relaypad.py reconcile --root . --owner <your-agent-id> --decisions-file /tmp/decisions.md [--next-round]`
- Archive review:
  `python agent-relaypad/scripts/relaypad.py archive --root . --owner <your-agent-id> --final-file /tmp/final.md`

## Install Or Update This Skill

- If this repo has `INSTALL.md`, read it first and follow it as the source of
  truth.
- Install or update the whole `agent-relaypad/` folder, not only `SKILL.md`.
  Include `agents/openai.yaml`, `scripts/relaypad.py`,
  `scripts/relaypad_driver.py`, and the tests.
- Install into the current runtime's user skills directory. Known Codex target:
  `~/.codex/skills/agent-relaypad/`. For Claude Code, Antigravity CLI, or an
  unknown runtime, identify the configured user skills directory first; if it
  cannot be identified confidently, ask:
  `What user skills directory should I use for this agent runtime?`
- Keep the installed folder name exactly `agent-relaypad`.
- During migration, it is safe to remove only the old installed
  `agent-memo-review/` skill folder. Do not delete project-local
  `.agent-relaypad/` folders.
- For a Codex install or update from this repo:
  `mkdir -p ~/.codex/skills && rm -rf ~/.codex/skills/agent-relaypad ~/.codex/skills/agent-memo-review && cp -R agent-relaypad ~/.codex/skills/`
- After copying, verify the installed helper:
  `python ~/.codex/skills/agent-relaypad/scripts/relaypad.py --help`
- For non-Codex runtimes, replace `~/.codex/skills` with that runtime's user
  skills directory and run the same helper verification.
- If the runtime has a marketplace, plugin cache, refresh, restart, or reload
  step for skills, run that normal refresh after copying.

## Owner Finalization

- Reviewer feedback is advisory, not automatically authoritative. The owner
  must evaluate each reviewer point against the codebase, user intent, and
  current project constraints before applying it.
- When summarizing reviewer feedback to the user, include the owner's own
  judgment for each material point: accepted, rejected, modified, or needs
  discussion. Do not only summarize reviewer comments.
- If the owner disagrees with any reviewer point, explain the technical reason
  and ask the user whether to send that disagreement and rationale back to the
  reviewer for another discussion round.
- On `changes_requested`, apply accepted feedback to the reviewed plan or
  implementation outside `.agent-relaypad/`, record decisions, and start another
  round with `--next-round` when reviewer confirmation is needed.
- On approved planning reviews, treat the updated project plan/spec as the
  working source and archive it as `final.md`; future agents should not rebuild
  the final plan from archived response comments.
- On approved implementation reviews, archive a concise final result describing
  what was approved, verification evidence, and known follow-up.

## Optional Driver Invocation

- Manual relaypad review remains the default workflow.
- The optional driver supports `agy`, `cc`, and `codex`. Any of these agents can
  own the review and dispatch any other as a reviewer. Same-model review (for
  example a `cc` owner driving a `cc` reviewer) is permitted but loses
  cross-model diversity; prefer different agents when possible.
- If the user asks Codex to invoke Agy directly, use `python agent-relaypad/scripts/relaypad_driver.py invoke`.
- Prefer an explicit or stored Agy conversation ID. If none exists, invoke Agy
  without `--conversation` so it starts a new session.
- If the user asks Codex to invoke Claude Code directly, use the same driver
  script with `--driver cc`.
- If the user (typically running CC or Agy as owner) asks to invoke Codex
  directly, use the same driver script with `--driver codex`. The driver stores
  Codex's `thread_id` as `.agent-relaypad/runtimes/codex.json` and reuses it on
  the next call.
- For unrelated tasks where resuming prior context is undesirable, pass
  `--new-session`. It bypasses `--conversation-id` and stored runtime metadata
  for `agy`, `cc`, and `codex`; for `agy`, it also bypasses the Antigravity
  last-conversation cache. New session or thread ids reported by the runtime
  are still stored afterward.
- If the user asks to invoke multiple reviewers at the same time, use
  `python agent-relaypad/scripts/relaypad_driver.py invoke-many --drivers agy,cc`
  (any comma-separated subset of `agy,cc,codex` is valid).
- Direct owner-launched reviews apply the same wait policy for `codex`, `cc`,
  and `agy` owners. The owner waits silently on the original driver subprocess
  until it exits or reaches the configured timeout. Do not send periodic waiting
  updates, do not run relaypad polling loops, do not search the filesystem for
  reviewer output, do not re-invoke reviewers, and do not trigger additional
  semantic/model turns merely to wait while the subprocess is still running. If
  manual or external polling is needed later, estimate the task complexity and
  use a tiered initial wait before the first check, followed by a 2-3 minute poll interval:
  - Small doc/spec review: 3 minutes default (range: 2-5 mins)
  - Medium implementation: 7 minutes default (range: 5-10 mins)
  - Large implementation: 15 minutes default (range: 15-20 mins)
- Runtime billing behavior is outside prompt-level enforcement: host CLIs should
  not re-enter model loops or emit billable model/API calls merely to wait for a
  subprocess. Any required heartbeat while waiting should be non-model and
  non-token-consuming.
- During direct driver invocation, the driver adds absolute project and relaypad
  paths to the reviewer prompt. Reviewers must write to that absolute
  `responses/<agent-id>.md` path, not to a scratch workspace relaypad.
- The default reviewer timeout is 1000 seconds. Do not archive automatically on
  partial timeout; leave the active review for an explicit owner decision.
- If one reviewer finishes early or requests changes early, keep waiting for the
  remaining reviewers by default so the owner can reconcile all feedback
  together.
- For Claude Code, prefer the stored Claude session ID. If none exists, the
  driver starts a new Claude session and stores the returned `session_id`.
- For Claude Code, use `--model` only when the user requests it; otherwise the
  driver defaults to `opus[1m]`. Do not use plain `opus` as the default.
- Do not use `claude --continue`; use the stored or explicit session ID through
  the driver.
- For Codex, prefer the stored Codex `thread_id`. If none exists, the driver
  starts a new Codex thread and stores the returned `thread_id` (saved as
  `conversation_id` in `runtimes/codex.json`).
- For Codex, default model is unset (uses the user's Codex CLI configuration).
  Pass `--model` only when the user requests a specific Codex model for that
  invocation.
- Do not request an Agy model override; the driver returns unsupported
  unless Agy exposes a safe per-invocation model flag.
- After invoking, inspect `.agent-relaypad/` review state before summarizing
  success.

## Interpreting Output

- Run the helper and read its JSON output before responding.
- Summarize the pending action in plain language.
- Open referenced markdown files only when needed to answer or act.
- Treat `final.md` in archived reviews as the source of truth.
- Ask the user before repairing invalid JSON, broken state, or `archive_interrupted` states.
