# Agent Relaypad v1.3 Parallel Review Driver Design

Date: 2026-05-23
Status: Design review

## Summary

Add an owner-side parallel review invocation path for cases where Codex starts
multiple reviewer runtimes directly. The owner should wait on the actual
subprocesses it launched, not poll relaypad state every few seconds.

## Problem

The v1.2 driver can invoke Agy or Claude Code one at a time. During the
parallel Agy and Claude Code smoke test, both reviewers could run concurrently,
but the owner had to coordinate the two subprocesses manually.

Two practical issues came out of that test:

- A fixed 5 second relaypad polling interval is too frequent for normal review
  work and wastes runtime attention.
- The current 300 second reviewer timeout can be too short when a reviewer must
  understand a larger project before responding.

## Goals

- Start multiple reviewer drivers at the same time from one owner command.
- Track each launched subprocess independently.
- Know when each reviewer finishes, even if one is much faster than another.
- Keep waiting for slower reviewers after faster reviewers finish.
- Use a practical default reviewer timeout of 1000 seconds.
- Add process-level timeout protection for both Agy and Claude Code.
- Run final relaypad checks after subprocess completion to verify response files.
- Leave review reconciliation and archive decisions under owner control.

## Non-Goals

- Do not archive automatically.
- Do not stop waiting for other reviewers just because one reviewer requests
  changes.
- Do not add a manual-review polling command in this version unless direct
  invocation cannot cover the workflow.
- Do not change relaypad's one-active-review model.

## Proposed Command

```bash
python agent-relaypad/scripts/relaypad_driver.py invoke-many \
  --root . \
  --drivers agy,cc \
  --prompt-file /tmp/review-prompt.md \
  --timeout 1000
```

`--prompt` should remain available for short prompts. `--prompt-file` should be
preferred for realistic review prompts.

The implementation should read `--prompt-file` once before spawning reviewer
subprocesses, then pass the same prompt text to every requested driver.

## Behavior

1. Parse the requested drivers in order.
2. Build each driver command using the existing per-driver behavior.
3. Start all requested drivers without waiting for the previous one to finish.
4. Track each subprocess independently.
5. When a reviewer exits:
   - record elapsed seconds,
   - record exit code,
   - capture stdout and stderr,
   - parse and persist driver metadata where applicable.
6. Continue waiting for unfinished reviewers until they exit or hit the timeout.
7. If a reviewer times out:
   - terminate that subprocess,
   - report the reviewer as `timed_out`,
   - check whether a response file already exists,
   - leave the active review in place.
8. After all subprocesses are complete or timed out, check relaypad responses
   for each reviewer by reading the corresponding `responses/<agent-id>.md`
   headers for the current review round.
9. Return a JSON summary with per-driver outcome and overall review state.

## Owner Reaction Rules

If one reviewer finishes early:

- Mark that reviewer complete in the command result.
- Keep waiting for the slower reviewers.
- Do not reconcile or archive yet.

If one reviewer requests changes early:

- Keep waiting for the other reviewers by default.
- Collect all feedback in the same round before owner reconciliation.

If one reviewer times out:

- Report `timed_out`.
- Report whether a partial response file exists.
- Do not archive automatically.
- Leave the owner to retry, continue waiting manually, or reconcile with an
  explicit decision.

## Timeouts and Polling

Direct owner-launched reviews should wait on subprocess completion instead of
using frequent relaypad polling.

Default reviewer timeout:

```text
1000 seconds
```

Manual or external reviewer polling, if added later, should default to a more
practical interval:

```text
60 seconds
```

The 60 second interval is only for workflows where the owner did not launch the
reviewer process and therefore cannot observe subprocess completion directly.

## Driver Timeout Details

Agy currently receives timeout through:

```bash
agy --print-timeout 300s
```

v1.3 should still pass Agy's print timeout, but it should also wrap the Agy
process with Python process-level timeout protection. Claude Code already uses
`subprocess.run(..., timeout=timeout)` for single-driver invocation; the
parallel path should provide equivalent protection for every driver.

## Expected JSON Shape

Example success:

```json
{
  "status": "completed",
  "timeout": 1000,
  "results": {
    "agy": {
      "status": "completed",
      "exit_code": 0,
      "elapsed_seconds": 42,
      "response_exists": true,
      "response_status": "approved"
    },
    "cc": {
      "status": "completed",
      "exit_code": 0,
      "elapsed_seconds": 180,
      "response_exists": true,
      "response_status": "approved"
    }
  },
  "review_status": "approved"
}
```

Example partial timeout:

```json
{
  "status": "timed_out",
  "timeout": 1000,
  "results": {
    "agy": {
      "status": "completed",
      "exit_code": 0,
      "elapsed_seconds": 42,
      "response_exists": true,
      "response_status": "approved"
    },
    "cc": {
      "status": "timed_out",
      "elapsed_seconds": 1000,
      "response_exists": false,
      "response_status": null
    }
  },
  "review_status": "waiting_for_review"
}
```

## Testing

Add unit tests for:

- `invoke-many` starts multiple drivers before waiting for completion.
- A faster reviewer can complete while the slower reviewer continues.
- A `changes_requested` response from one reviewer does not cancel the other
  reviewer.
- Timeout is reported for one reviewer without deleting the active review.
- Agy receives both `--print-timeout 1000s` and process-level timeout protection.
- Claude Code still defaults to exactly `opus[1m]`.
- Final response inspection reports each reviewer's response file status.
- `--prompt-file` reads prompt text once and passes it to every driver.
- Unsupported driver names in `--drivers` are reported cleanly without
  launching any reviewers.
- Overall `status` is `completed` only when every reviewer process completes,
  and `timed_out` when any reviewer times out.

## Review Focus

- Confirm subprocess completion is the right primary signal for owner-launched
  reviewer processes.
- Confirm 1000 seconds is a reasonable default reviewer timeout.
- Confirm 60 seconds is a reasonable future/default polling interval for manual
  reviewers.
- Confirm owner reaction rules are conservative enough for mixed-speed reviews.
