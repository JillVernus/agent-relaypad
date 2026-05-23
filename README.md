# Agent Relaypad

Agent Relaypad is a local relay pad for cross-agent planning, review, and
handoff.

The first included skill, `agent-relaypad`, lets Codex, Claude Code,
Antigravity CLI, and other agents coordinate plan reviews and implementation
reviews through project-local `.agent-relaypad/` files.

The first version supports one active review at a time. Each reviewing agent
writes only its own response file, and the approved result is saved as
`final.md` when the review is archived.

## What Is Included

```text
agent-relaypad/
  SKILL.md
  agents/openai.yaml
  scripts/relaypad.py
  scripts/relaypad_driver.py
  tests/test_relaypad.py
  tests/test_relaypad_driver.py
```

The skill instructions tell agents how to use the workflow. The Python helper
does the deterministic file operations.

## Requirements

- Python 3
- No third-party Python packages
- A project folder where agents can read and write files

## Install

Install the whole `agent-relaypad/` folder into each agent's user skills
directory.

Recommended agent-driven install or update:

```text
Read INSTALL.md and install or update the agent-relaypad skill for your own
runtime. First identify the correct user skills directory for this agent. If
you cannot identify it confidently, stop and ask me for the target path. Remove
the old installed agent-memo-review skill folder if it exists. Do not delete
any project-local .agent-relaypad folders. Verify the installed helper with
--help after copying.
```

Common Codex install location:

```bash
mkdir -p ~/.codex/skills
cp -R agent-relaypad ~/.codex/skills/
```

For Claude Code and Antigravity CLI, copy the same `agent-relaypad/` folder
to the user skills directory configured for that agent. If the exact directory
differs on your machine, keep the folder name and internal structure unchanged.

After installing, restart or reload the agent so it discovers the new skill.

## Direct CLI Use

You can also run the helper directly from this repo or from an installed skill
folder.

Initialize relaypad state in a project:

```bash
python agent-relaypad/scripts/relaypad.py init --root /path/to/project
```

Create a planning review:

```bash
python agent-relaypad/scripts/relaypad.py create \
  --root /path/to/project \
  --owner codex \
  --phase planning \
  --topic "auth flow" \
  --reviewers agy,cc \
  --artifact-file docs/plan.md
```

Check the active review as a reviewer:

```bash
python agent-relaypad/scripts/relaypad.py check \
  --root /path/to/project \
  --agent agy
```

Write reviewer feedback:

```bash
python agent-relaypad/scripts/relaypad.py respond \
  --root /path/to/project \
  --agent agy \
  --status changes_requested \
  --body-file /tmp/agy-review.md
```

Reconcile feedback as the owner:

```bash
python agent-relaypad/scripts/relaypad.py reconcile \
  --root /path/to/project \
  --owner codex \
  --decisions-file /tmp/decisions.md
```

Start another review round after changes:

```bash
python agent-relaypad/scripts/relaypad.py reconcile \
  --root /path/to/project \
  --owner codex \
  --decisions-file /tmp/decisions.md \
  --next-round
```

Archive an approved review:

```bash
python agent-relaypad/scripts/relaypad.py archive \
  --root /path/to/project \
  --owner codex \
  --final-file /tmp/final.md
```

For planning reviews, `/tmp/final.md` should be the approved plan itself or a
concise pointer to the approved project plan/spec file. The owner should update
the real plan/spec outside `.agent-relaypad/` before archiving.

Invoke Agy directly, when you already know the Agy conversation ID:

```bash
python agent-relaypad/scripts/relaypad_driver.py invoke \
  --root /path/to/project \
  --driver agy \
  --conversation-id 7f6f3fc1-2fda-4b8c-8d1f-1cec82b125bf \
  --prompt "Use agent-relaypad. Check the active review as agy and respond."
```

Preview the command without invoking Agy:

```bash
python agent-relaypad/scripts/relaypad_driver.py invoke \
  --root /path/to/project \
  --driver agy \
  --conversation-id test-conversation \
  --prompt "hello" \
  --dry-run
```

The v1.1 Agy driver passes prompts through standard input and always uses
`--conversation`; it does not use `--continue`. Agy model override is not
supported unless Agy exposes a safe per-invocation model flag.

## Typical Agent Workflow

1. Codex creates a review request after planning or implementation.
2. You switch to Agy or Claude Code.
3. The reviewer checks the active review and writes feedback to its own response
   file.
4. You switch back to Codex.
5. Codex reconciles feedback, applies accepted changes to the real plan or
   implementation, and either starts another round or archives the approved
   result.

## Project Relaypad Layout

The helper creates this inside the target project:

```text
.agent-relaypad/
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

By default, `.agent-relaypad/.gitignore` contains:

```gitignore
active/
state.json
runtimes/
```

This keeps active local state out of git while allowing archived review records
to be committed if your team wants that. The helper preserves an existing
`.agent-relaypad/.gitignore` override.

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
- `no_active_review`: relaypad state exists, but there is no active review.
- `invalid_json`: a relaypad JSON file is corrupt. Ask before repairing it.
- `broken_state`: state points to missing or malformed files. Ask before repair.
- `archive_interrupted`: active and archived copies both exist. Ask whether to
  finish archive cleanup.

## Validate

Run the test suite:

```bash
PYTHONPATH=agent-relaypad/scripts python -m unittest discover -s agent-relaypad/tests -v
```

Expected result:

```text
Ran 48 tests
OK
```
