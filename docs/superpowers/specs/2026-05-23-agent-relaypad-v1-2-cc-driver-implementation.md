# Agent Relaypad v1.2 Claude Code Driver Implementation

Date: 2026-05-23
Status: Implementation review

## Summary

Add Claude Code direct invocation support to `relaypad_driver.py` while keeping
the existing Agy driver behavior unchanged.

## Implemented Behavior

- Added driver ID `cc`.
- Added `DEFAULT_CC_MODEL = "opus[1m]"`.
- Claude command shape:

```bash
claude --print --output-format json --model 'opus[1m]' --permission-mode bypassPermissions
```

- If a Claude conversation/session ID exists, the driver resumes with:

```bash
--resume <session-id>
```

- If no explicit or stored Claude session exists, the driver starts a new
  Claude session without `--resume`.
- Prompts are passed through stdin.
- Claude timeout is enforced through `subprocess.run(..., timeout=timeout)`.
- Claude JSON stdout is parsed for `session_id`.
- Returned `session_id` is stored as:

```text
.agent-relaypad/runtimes/cc.json
```

- Stored metadata keeps the cross-driver field name `conversation_id`.
- Claude `--model` override is supported only when explicitly requested.
- Agy `--model` override remains unsupported.
- If Claude stdout is not JSON or lacks `session_id`, the result includes a
  top-level warning. If no previous or explicit session ID exists, no new
  `cc.json` metadata file is written.

## Files Changed

- `agent-relaypad/scripts/relaypad_driver.py`
- `agent-relaypad/tests/test_relaypad_driver.py`
- `agent-relaypad/SKILL.md`
- `README.md`
- `INSTALL.md`

## Verification

```bash
PYTHONPATH=agent-relaypad/scripts python -m unittest discover -s agent-relaypad/tests -v
```

Result: 66 tests passed.

```bash
python agent-relaypad/scripts/relaypad.py check --root . --agent codex
```

Result: `{"status": "no_active_review"}` before creating this implementation
review.

```bash
python agent-relaypad/scripts/relaypad_driver.py invoke --root . --driver cc --prompt hello --dry-run
```

Result includes:

```json
{
  "command": [
    "claude",
    "--print",
    "--output-format",
    "json",
    "--model",
    "opus[1m]",
    "--permission-mode",
    "bypassPermissions"
  ],
  "driver": "cc",
  "status": "dry_run",
  "stdin": "hello"
}
```

```bash
python agent-relaypad/scripts/relaypad_driver.py invoke --root . --driver cc --prompt hello --conversation-id test-session --dry-run
```

Result includes `--resume test-session` and still uses `opus[1m]`.

## Review Focus

- Confirm `cc` defaults to exactly `opus[1m]`, not plain `opus`.
- Confirm no prompt is placed in the command argument list.
- Confirm missing Claude session ID starts a new session instead of failing.
- Confirm returned Claude `session_id` is persisted correctly.
- Confirm invalid Claude JSON warning behavior is acceptable.
- Confirm Agy behavior is not regressed.
