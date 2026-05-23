# Agent Relaypad v1.1 Driver Design

Date: 2026-05-23
Status: Draft

## Goal

Add an optional driver layer that lets a coordinating agent invoke another
installed agent CLI to perform relaypad work without manual terminal switching.

Version 1.1 should keep the existing `.agent-relaypad/` review protocol intact.
The review files remain the source of truth. Driver invocation is convenience
automation around that protocol, not a replacement for it.

## Scope

In scope:

- Add a generic driver structure for agent CLI invocation.
- Implement the first concrete driver for Antigravity CLI (`agy`).
- Persist runtime driver metadata in `.agent-relaypad/runtimes/`.
- Support invoking Agy with an explicit conversation ID.
- Discover the stored Agy conversation ID from Antigravity's workspace
  conversation cache when it is readable.
- Use Agy's configured default model.
- Return a clear unsupported error if the user requests a model override on an
  Agy CLI version that does not expose a safe per-invocation model flag.
- Send prompts to Agy over stdin instead of as positional command arguments.
- Add tests for command construction, metadata persistence, permission-aware
  cache fallback, model override rejection, and no-op behavior when required
  runtime data is missing.

Out of scope:

- Multiple active relaypad reviews.
- Long-running agent daemons.
- Background hooks.
- Generic model switching for all agents.
- Editing global agent settings files for temporary model overrides.
- Automatic edits to Codex or Claude Code runtime settings.
- Replacing the existing `create`, `check`, `respond`, `reconcile`, or
  `archive` workflow.

## Commands

Add a new script:

```text
agent-relaypad/scripts/relaypad_driver.py
```

This keeps subprocess orchestration separate from the deterministic file-state
helper in `relaypad.py`.

Initial CLI:

```bash
python agent-relaypad/scripts/relaypad_driver.py invoke \
  --root . \
  --driver agy \
  --prompt "Use agent-relaypad. Check the active review as agy and respond."
```

Optional flags:

```bash
--conversation-id <id>
--model "<model name>"
--timeout 300
--dry-run
```

`--dry-run` prints the command and planned metadata changes without invoking
the external CLI.

## Runtime Metadata

Driver metadata lives under:

```text
.agent-relaypad/runtimes/
  agy.json
```

Example:

```json
{
  "version": 1,
  "driver": "agy",
  "conversation_id": "7f6f3fc1-2fda-4b8c-8d1f-1cec82b125bf",
  "conversation_source": "antigravity_last_conversations",
  "last_invoked_at": "2026-05-23T00:00:00Z",
  "last_exit_code": 0
}
```

`runtimes/` is local runtime state. It should not be committed by default.
Update `.agent-relaypad/.gitignore` to ignore it:

```gitignore
active/
state.json
runtimes/
```

## Agy Driver

The Agy driver invokes Antigravity CLI with print mode:

```bash
printf '%s\n' "<prompt>" | agy --print --print-timeout <duration> --conversation <conversation-id>
```

Conversation ID resolution order:

1. Explicit `--conversation-id`.
2. Stored `.agent-relaypad/runtimes/agy.json`.
3. Antigravity cache entry for the project root in:
   ```text
   ~/.gemini/antigravity-cli/cache/last_conversations.json
   ```
4. If none is found, return a JSON error telling the user to run Agy once or
   pass `--conversation-id`.

Do not use `agy --continue` because it may resume the wrong conversation.
Do not pass the prompt as a positional argument. Live dogfood testing showed
that this can cause Agy to answer about CLI flags such as `--print-timeout`
instead of performing the requested relaypad task.

Reading Antigravity's cache is best-effort only. If the cache path is missing,
unreadable, or blocked by sandbox permissions, return a recoverable JSON error
that asks for `--conversation-id`; do not crash.

## Model Override

Default behavior uses Agy's configured default model.

The current Agy CLI help does not expose a per-invocation model flag. Therefore
v1.1 must not implement model override by editing
`~/.gemini/antigravity-cli/settings.json`.

If the user passes `--model`, return:

```json
{
  "status": "unsupported",
  "driver": "agy",
  "error": "Agy model override is not supported without a safe per-invocation model flag.",
  "next_step": "Use Agy's configured default model or configure Agy manually before invoking."
}
```

This avoids sandbox permission failures, global settings races, formatting loss,
and permanently modified settings if the driver is interrupted.

## Output

The driver prints JSON so agents can consume it reliably.

Success:

```json
{
  "status": "invoked",
  "driver": "agy",
  "conversation_id": "...",
  "exit_code": 0,
  "stdout": "...",
  "stderr": "",
  "metadata_path": ".agent-relaypad/runtimes/agy.json"
}
```

Dry run:

```json
{
  "status": "dry_run",
  "driver": "agy",
  "command": ["agy", "--print", "--print-timeout", "300s", "--conversation", "..."],
  "stdin": "..."
}
```

Failure:

```json
{
  "status": "error",
  "driver": "agy",
  "error": "No Agy conversation ID found",
  "next_step": "Open Agy in this workspace once or pass --conversation-id."
}
```

## Skill Guidance

Update `SKILL.md` with a small optional section:

- Manual relaypad review remains the default workflow.
- If the user asks Codex to invoke Agy directly, use `relaypad_driver.py`.
- Prefer an explicit or stored Agy conversation ID.
- Do not use `--model` for Agy unless a future Agy CLI exposes a safe
  per-invocation model flag.
- Summarize driver JSON output and then inspect `.agent-relaypad/` review state.

## Tests

Add `agent-relaypad/tests/test_relaypad_driver.py`.

Test cases:

- Resolves explicit conversation ID.
- Resolves stored `.agent-relaypad/runtimes/agy.json` conversation ID.
- Resolves Antigravity last conversation cache for the project root.
- Treats unreadable or permission-blocked Antigravity cache as recoverable.
- Returns JSON error when no conversation ID can be found.
- `--dry-run` does not invoke subprocess.
- Invocation constructs `agy --print --print-timeout ... --conversation ...`
  and passes the prompt through stdin.
- Runtime metadata is written after invocation.
- Agy `--model` returns unsupported without invoking subprocess.
- Existing `relaypad.py` tests still pass unchanged.

## Acceptance Criteria

- `relaypad.py` review behavior remains unchanged.
- `relaypad_driver.py --dry-run` can show the exact Agy command.
- Agy invocation always uses `--conversation`, never `--continue`.
- Agy prompts are passed through stdin, not positional arguments.
- Driver metadata is stored under `.agent-relaypad/runtimes/agy.json`.
- Agy model override does not mutate global settings in v1.1.
- All tests pass.
