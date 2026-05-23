# Agent Relaypad v1.2 Claude Code Driver Design

Date: 2026-05-23
Status: Draft

## Goal

Add Claude Code as the second direct-invocation driver in Agent Relaypad.

Version 1.2 should reuse the v1.1 driver architecture: review files remain the
source of truth, prompts are passed through stdin, and runtime metadata is
stored under `.agent-relaypad/runtimes/`.

## Scope

In scope:

- Add driver ID `cc` for Claude Code.
- Invoke Claude Code through the `claude` executable.
- Use `claude --print --output-format json`.
- Pass prompts through stdin.
- Support `--model` for Claude Code because Claude exposes safe
  per-invocation model selection.
- Default Claude model to `opus[1m]` when the user does not specify `--model`.
- Do not default to `opus`, `sonnet`, or any non-1m alias in this environment.
- Persist returned Claude `session_id` in `.agent-relaypad/runtimes/cc.json`.
- Resume stored sessions with `--resume <session-id>`.
- Support explicit `--conversation-id` as a Claude session ID.
- Continue to support Agy behavior from v1.1 unchanged.

Out of scope:

- Editing `~/.claude/settings.json`.
- Reading Claude session history files directly.
- Using `claude --continue`.
- Claude-specific background agents.
- Multiple active relaypad reviews.

## Claude CLI Shape

Validated locally:

```bash
printf 'Reply exactly: HELLO_STDIN\n' | \
  claude --print --output-format json --model 'opus[1m]' --permission-mode bypassPermissions
```

The JSON result includes:

```json
{
  "session_id": "ff804d02-0edb-4443-b9ec-01cfeafca15c",
  "result": "HELLO_STDIN"
}
```

Resume by session ID:

```bash
printf 'Reply exactly: RESUMED_OK\n' | \
  claude --print --output-format json --model 'opus[1m]' \
  --permission-mode bypassPermissions \
  --resume ff804d02-0edb-4443-b9ec-01cfeafca15c
```

## Command Construction

For a new Claude session:

```bash
claude --print --output-format json --model 'opus[1m]' --permission-mode bypassPermissions
```

For a resumed Claude session:

```bash
claude --print --output-format json --model 'opus[1m]' --permission-mode bypassPermissions --resume <session-id>
```

`--conversation-id` maps to Claude's `--resume` session ID. If neither
`--conversation-id` nor stored `cc.json` exists, the driver should start a new
session and persist the returned `session_id`.

This means the `cc` driver must not require conversation ID resolution before
invocation. Unlike Agy, a missing conversation ID is valid for Claude Code and
means "start a new session." If a conversation ID exists, include `--resume`;
otherwise omit `--resume`.

Claude Code does not expose an Agy-style `--print-timeout` flag. The v1.2
driver must enforce timeout through the subprocess runner:

```python
subprocess.run(command, input=prompt, text=True, capture_output=True, cwd=str(root), timeout=timeout)
```

## Runtime Metadata

Store Claude metadata at:

```text
.agent-relaypad/runtimes/cc.json
```

Example:

```json
{
  "version": 1,
  "driver": "cc",
  "conversation_id": "ff804d02-0edb-4443-b9ec-01cfeafca15c",
  "conversation_source": "claude_json_result",
  "last_invoked_at": "2026-05-23T00:00:00Z",
  "last_exit_code": 0,
  "model": "opus[1m]"
}
```

Keep the existing field name `conversation_id` for cross-driver consistency,
but document that it means Claude `session_id` for driver `cc`.

## Output

Dry run:

```json
{
  "status": "dry_run",
  "driver": "cc",
  "command": [
    "claude",
    "--print",
    "--output-format",
    "json",
    "--model",
    "opus[1m]",
    "--permission-mode",
    "bypassPermissions",
    "--resume",
    "..."
  ],
  "stdin": "..."
}
```

Success:

```json
{
  "status": "invoked",
  "driver": "cc",
  "conversation_id": "...",
  "exit_code": 0,
  "stdout": "...",
  "stderr": "",
  "metadata_path": ".agent-relaypad/runtimes/cc.json"
}
```

If Claude exits `0` but stdout is not valid JSON or does not contain
`session_id`, still return `status: "invoked"` but preserve the previous or
explicit conversation ID if one was used. If no session ID is available, do not
write `cc.json`; include a top-level warning:

```json
{
  "status": "invoked",
  "driver": "cc",
  "exit_code": 0,
  "stdout": "...",
  "stderr": "",
  "warning": "Claude JSON output did not contain session_id; runtime metadata was not updated."
}
```

## Tests

Add coverage in `agent-relaypad/tests/test_relaypad_driver.py`:

- Builds a new Claude command with default model `opus[1m]`.
- Tests must assert the exact default model string `opus[1m]`.
- Builds a resumed Claude command when conversation ID exists.
- Missing `cc` conversation ID starts a new session instead of returning an
  error.
- `cc` subprocess invocation passes `timeout=<seconds>` to the runner.
- `cc` dry-run includes stdin and does not put the prompt in the command.
- `cc` allows model override and includes the model in the command.
- `cc` invocation parses JSON stdout and writes `cc.json` with `session_id`.
- `cc` invocation uses stored metadata session ID on later calls.
- Invalid Claude JSON stdout returns an invoked result with warning and no new
  metadata when no session ID exists.
- Existing `agy` tests remain unchanged.

## Skill Guidance

Update `SKILL.md`:

- If the user asks to invoke Claude Code directly, use `relaypad_driver.py`
  with `--driver cc`.
- Prefer the stored Claude session ID.
- Use `--model` only when the user requests it; otherwise default to `opus[1m]`.
- Do not use `claude --continue`.

## Acceptance Criteria

- All existing Agy driver behavior remains unchanged.
- `cc` dry-run prints a valid Claude command and stdin prompt.
- Real or fake `cc` invocation stores returned `session_id` as
  `conversation_id`.
- `--model` works for `cc` and remains unsupported for `agy`.
- All tests pass.
