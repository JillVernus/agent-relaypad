# Agent Relaypad

Agent Relaypad is a local relay pad for cross-agent planning, review, and
handoff.

The first included skill, `agent-memo-review`, lets Codex, Claude Code,
Antigravity CLI, and other agents coordinate plan reviews and implementation
reviews through project-local `.agent_memo/` files.

The first version supports one active review at a time. Each reviewing agent
writes only its own response file, and the approved result is saved as
`final.md` when the review is archived.

## What Is Included

```text
agent-memo-review/
  SKILL.md
  agents/openai.yaml
  scripts/agent_memo.py
  tests/test_agent_memo.py
```

The skill instructions tell agents how to use the workflow. The Python helper
does the deterministic file operations.

## Requirements

- Python 3
- No third-party Python packages
- A project folder where agents can read and write files

## Install

Install the whole `agent-memo-review/` folder into each agent's user skills
directory.

Common Codex install location:

```bash
mkdir -p ~/.codex/skills
cp -R agent-memo-review ~/.codex/skills/
```

For Claude Code and Antigravity CLI, copy the same `agent-memo-review/` folder
to the user skills directory configured for that agent. If the exact directory
differs on your machine, keep the folder name and internal structure unchanged.

After installing, restart or reload the agent so it discovers the new skill.

## Direct CLI Use

You can also run the helper directly from this repo or from an installed skill
folder.

Initialize memo state in a project:

```bash
python agent-memo-review/scripts/agent_memo.py init --root /path/to/project
```

Create a planning review:

```bash
python agent-memo-review/scripts/agent_memo.py create \
  --root /path/to/project \
  --owner codex \
  --phase planning \
  --topic "auth flow" \
  --reviewers agy,cc \
  --artifact-file docs/plan.md
```

Check the active review as a reviewer:

```bash
python agent-memo-review/scripts/agent_memo.py check \
  --root /path/to/project \
  --agent agy
```

Write reviewer feedback:

```bash
python agent-memo-review/scripts/agent_memo.py respond \
  --root /path/to/project \
  --agent agy \
  --status changes_requested \
  --body-file /tmp/agy-review.md
```

Reconcile feedback as the owner:

```bash
python agent-memo-review/scripts/agent_memo.py reconcile \
  --root /path/to/project \
  --owner codex \
  --decisions-file /tmp/decisions.md
```

Start another review round after changes:

```bash
python agent-memo-review/scripts/agent_memo.py reconcile \
  --root /path/to/project \
  --owner codex \
  --decisions-file /tmp/decisions.md \
  --next-round
```

Archive an approved review:

```bash
python agent-memo-review/scripts/agent_memo.py archive \
  --root /path/to/project \
  --owner codex \
  --final-file /tmp/final.md
```

For planning reviews, `/tmp/final.md` should be the approved plan itself or a
concise pointer to the approved project plan/spec file. The owner should update
the real plan/spec outside `.agent_memo/` before archiving.

## Typical Agent Workflow

1. Codex creates a review request after planning or implementation.
2. You switch to Agy or Claude Code.
3. The reviewer checks the active memo and writes feedback to its own response
   file.
4. You switch back to Codex.
5. Codex reconciles feedback, applies accepted changes to the real plan or
   implementation, and either starts another round or archives the approved
   result.

## Project Memo Layout

The helper creates this inside the target project:

```text
.agent_memo/
  state.json
  .gitignore
  active/
    REVIEW_ID/
      request.md
      decisions.md
      final.md
      status.json
      responses/
        codex.md
        cc.md
        agy.md
  archive/
    REVIEW_ID/
```

Notes:

- `request.md` is the original review snapshot and is immutable.
- `responses/<agent-id>.md` is owned by one agent.
- `decisions.md` records how feedback was resolved.
- `final.md` is the approved result and should be read first after archive.
- For planning reviews, `final.md` is the approved plan snapshot or a concise
  pointer to the approved project plan/spec file.

## Git Policy

By default, `.agent_memo/.gitignore` contains:

```gitignore
active/
state.json
```

This keeps active local state out of git while allowing archived review records
to be committed if your team wants that. The helper preserves an existing
`.agent_memo/.gitignore` override.

## Agent IDs

Agent IDs are used as filenames under `responses/`.

Allowed examples:

- `codex`
- `cc`
- `agy`
- `gemini-1`
- `agent_2`

Invalid IDs with path separators or `..` are rejected.

## Status Values

Review thread statuses:

- `waiting_for_review`
- `changes_requested`
- `waiting_for_owner`
- `approved`
- `archived`

Reviewer response statuses:

- `approved`
- `changes_requested`

Responses are round-aware. A response from round 1 does not count for round 2.

## Troubleshooting

All helper commands print JSON. On ordinary failures, the helper prints a JSON
error instead of a Python traceback.

Common statuses:

- `not_initialized`: run `init` first.
- `no_active_review`: memo state exists, but there is no active review.
- `invalid_json`: a memo JSON file is corrupt. Ask before repairing it.
- `broken_state`: state points to missing or malformed files. Ask before repair.
- `archive_interrupted`: active and archived copies both exist. Ask whether to
  finish archive cleanup.

## Validate

Run the test suite:

```bash
PYTHONPATH=agent-memo-review/scripts python -m unittest discover -s agent-memo-review/tests -v
```

Expected result:

```text
Ran 48 tests
OK
```
