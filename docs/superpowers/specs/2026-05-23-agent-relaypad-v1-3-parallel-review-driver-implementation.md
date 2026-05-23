# Agent Relaypad v1.3 Parallel Review Driver Implementation

Date: 2026-05-23
Status: Implementation review

## Summary

Implemented owner-side parallel reviewer invocation for `relaypad_driver.py`.
The new `invoke-many` command starts requested reviewer runtimes together,
delivers the prompt to every process before waiting, drains stdout and stderr
while processes run, and reports per-reviewer completion and relaypad response
state.

## Implemented Behavior

- Added `DEFAULT_TIMEOUT = 1000`.
- Single-driver Agy invocation now passes Python process-level
  `timeout=timeout` in addition to Agy's `--print-timeout`.
- Added `--prompt-file` support for `invoke` and `invoke-many`.
- Added non-mutating response inspection from current-round
  `responses/<agent-id>.md` headers.
- Added non-mutating `review_status` computation from response headers instead
  of trusting stale `status.json`.
- Added `invoke-many` with:
  - comma-separated `--drivers`,
  - all processes launched before waiting,
  - prompt delivered to all reviewer stdin handles before blocking waits,
  - stdout/stderr drained with reader threads while processes run,
  - independent waiter threads for mixed-speed reviewer completion,
  - timeout reporting without deleting or archiving active reviews,
  - Agy and Claude Code runtime metadata persistence after completion,
  - Claude Code `session_id` parsing and persistence as `conversation_id`,
  - top-level `completed` or `timed_out` status.
- Claude Code still defaults to exactly `opus[1m]`.
- Agy model override remains unsupported.

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

Result: 89 tests passed.

## Review Focus

- Confirm `invoke-many` truly launches all requested reviewers before waiting.
- Confirm prompt text, including absolute relaypad path context when active, is
  delivered to all reviewer stdin handles before blocking waits.
- Confirm stdout/stderr are drained while processes run.
- Confirm timeout handling leaves active review state intact.
- Confirm `review_status` is computed from current-round response headers.
- Confirm Agy and Claude Code metadata persistence matches single-driver
  behavior.
- Confirm Claude Code still defaults to exactly `opus[1m]`.
