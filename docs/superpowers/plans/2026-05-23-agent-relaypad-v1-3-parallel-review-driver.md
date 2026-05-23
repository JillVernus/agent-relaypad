# Agent Relaypad v1.3 Parallel Review Driver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `relaypad_driver.py invoke-many` so Codex can start Agy and Claude Code reviews concurrently, wait on subprocess completion, and report per-reviewer results.

**Architecture:** Keep deterministic relaypad file operations in `relaypad.py`; extend only `relaypad_driver.py` for process orchestration. Add small helper functions for driver validation, prompt loading, subprocess launch/wait, metadata persistence, and response-header inspection. Preserve existing `invoke` behavior while moving the default timeout to 1000 seconds.

**Tech Stack:** Python 3 standard library (`argparse`, `json`, `subprocess`, `time`, `pathlib`, `unittest`), existing relaypad file protocol.

---

## File Structure

- Modify `agent-relaypad/scripts/relaypad_driver.py`
  - Add `DEFAULT_TIMEOUT = 1000`.
  - Add prompt loading for `--prompt` and `--prompt-file`.
  - Add `invoke-many` CLI command.
  - Add launch/wait helpers using `subprocess.Popen`.
  - Add process-level timeout protection for both Agy and Claude Code.
  - Add response-header inspection for current-round reviewer responses.
- Modify `agent-relaypad/tests/test_relaypad_driver.py`
  - Add focused unit tests for `invoke-many`, prompt files, unsupported drivers, timeout behavior, response inspection, and default timeout.
- Modify `README.md`
  - Document `invoke-many`, 1000 second default timeout, and owner behavior when reviewers finish at different times.
- Modify `INSTALL.md`
  - Update expected test count after adding tests.
- Modify `agent-relaypad/SKILL.md`
  - Document direct parallel reviewer invocation and the conservative owner reaction rules.
- Create `docs/superpowers/specs/2026-05-23-agent-relaypad-v1-3-parallel-review-driver-implementation.md`
  - Implementation review artifact after code is complete.

---

### Task 1: Timeout Defaults And Agy Process Timeout

**Files:**
- Modify: `agent-relaypad/scripts/relaypad_driver.py`
- Test: `agent-relaypad/tests/test_relaypad_driver.py`

- [ ] **Step 1: Write failing tests**

Add tests that prove:

```python
def test_invoke_default_timeout_is_1000_for_agy_dry_run(self):
    result = relaypad_driver.invoke_driver(
        root=Path(tmp),
        driver="agy",
        prompt="hello",
        conversation_id="conv-1",
        dry_run=True,
    )
    self.assertIn("1000s", result["command"])

def test_agy_invoke_passes_process_timeout_to_runner(self):
    # runner receives timeout=1000 by default and command still includes --print-timeout 1000s
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=agent-relaypad/scripts python -m unittest agent-relaypad/tests/test_relaypad_driver.py -v
```

Expected: new tests fail because the default is still 300 and Agy does not pass `timeout`.

- [ ] **Step 3: Implement minimal code**

Add `DEFAULT_TIMEOUT = 1000`, change default timeout arguments and CLI default to use it, and pass `timeout=timeout` into Agy's `subprocess.run`.

- [ ] **Step 4: Run focused tests**

Run the same unittest command. Expected: all driver tests pass.

---

### Task 2: Prompt Loading

**Files:**
- Modify: `agent-relaypad/scripts/relaypad_driver.py`
- Test: `agent-relaypad/tests/test_relaypad_driver.py`

- [ ] **Step 1: Write failing tests**

Add tests that prove:

```python
def test_load_prompt_reads_prompt_file_once(self):
    prompt = relaypad_driver.load_prompt(prompt=None, prompt_file=path)
    self.assertEqual(prompt, "review prompt")

def test_cli_rejects_missing_prompt_and_prompt_file(self):
    # main(...) returns 1 and JSON error

def test_cli_rejects_prompt_and_prompt_file_together(self):
    # main(...) returns 1 and JSON error
```

- [ ] **Step 2: Run tests to verify failure**

Expected: `load_prompt` does not exist and CLI requires `--prompt`.

- [ ] **Step 3: Implement minimal code**

Add `load_prompt(prompt=None, prompt_file=None)` and update `invoke` / `invoke-many` parsers so exactly one prompt source is required.

- [ ] **Step 4: Run focused tests**

Expected: prompt loading tests pass and existing CLI dry-run tests still pass.

---

### Task 3: Response Inspection Helpers

**Files:**
- Modify: `agent-relaypad/scripts/relaypad_driver.py`
- Test: `agent-relaypad/tests/test_relaypad_driver.py`

- [ ] **Step 1: Write failing tests**

Add tests for current-round response headers:

```python
def test_inspect_reviewer_response_reports_current_round_status(self):
    # status.json round 2, responses/agy.md has Status: approved and Round: 2
    # returns response_exists=True, response_status="approved", response_round=2

def test_inspect_reviewer_response_ignores_prior_round_status(self):
    # status.json round 2, responses/agy.md has Round: 1
    # returns response_exists=True, response_status=None, response_round=1

def test_compute_review_status_from_response_headers_reports_approved(self):
    # required reviewers agy,cc both have current-round Status: approved
    # returns "approved" even if status.json still says waiting_for_review

def test_compute_review_status_from_response_headers_reports_changes_requested(self):
    # one current-round response is changes_requested
    # returns "changes_requested"

def test_compute_review_status_from_response_headers_reports_waiting_for_review(self):
    # one response is missing or old-round
    # returns "waiting_for_review"
```

- [ ] **Step 2: Run tests to verify failure**

Expected: response inspection helper does not exist.

- [ ] **Step 3: Implement minimal code**

Add small helpers that read `.agent-relaypad/state.json`, active `status.json`, and `responses/<driver>.md` headers. Do not mutate relaypad state.
Compute `review_status` non-mutatingly from the current-round response headers
instead of trusting stored `status.json`, because normal response writes can
leave `status.json` at `waiting_for_review` until owner reconciliation.

- [ ] **Step 4: Run focused tests**

Expected: response inspection tests pass.

---

### Task 4: `invoke-many` Core

**Files:**
- Modify: `agent-relaypad/scripts/relaypad_driver.py`
- Test: `agent-relaypad/tests/test_relaypad_driver.py`

- [ ] **Step 1: Write failing tests**

Add tests for:

```python
def test_invoke_many_starts_all_drivers_before_waiting(self):
    # fake process records start order and wait calls
    # assert agy and cc are both started before any wait completes

def test_invoke_many_sends_prompt_to_all_drivers_before_blocking_wait(self):
    # fake launcher records stdin write/flush/close calls
    # assert agy and cc both receive prompt text before any process wait blocks

def test_invoke_many_drains_stdout_and_stderr_while_waiting(self):
    # fake process exposes stdout/stderr streams that must be read before exit
    # assert output is drained concurrently with waiting, avoiding pipe deadlock

def test_invoke_many_reports_mixed_speed_completion(self):
    # one fake process completes quickly, one later
    # both return completed with response metadata

def test_invoke_many_does_not_cancel_after_changes_requested(self):
    # agy response is changes_requested, cc still completes

def test_invoke_many_reports_timeout_without_archiving_or_deleting_active_review(self):
    # one fake process raises subprocess.TimeoutExpired from communicate
    # active review directory still exists

def test_invoke_many_rejects_unsupported_driver_before_launching_anything(self):
    # --drivers agy,unknown returns error and launcher is not called

def test_invoke_many_persists_agy_runtime_metadata_after_completion(self):
    # completed agy process writes .agent-relaypad/runtimes/agy.json
    # with conversation_id and last_exit_code

def test_invoke_many_persists_cc_session_id_metadata_after_completion(self):
    # completed cc process stdout contains {"session_id": "new-session"}
    # metadata stores conversation_id=new-session and model=opus[1m]
```

- [ ] **Step 2: Run tests to verify failure**

Expected: `invoke_many` and CLI command do not exist.

- [ ] **Step 3: Implement minimal code**

Add:

```python
SUPPORTED_DRIVERS = {"agy", "cc"}
def parse_driver_list(text): ...
def build_driver_invocation(root, driver, prompt, timeout, conversation_id=None, model=None): ...
def invoke_many(root, drivers, prompt, timeout=DEFAULT_TIMEOUT, launcher=None, now=None): ...
```

Use `subprocess.Popen` by default. Start all processes first, then deliver the
prompt to every process stdin before any blocking wait. Do not use sequential
`communicate(input=prompt, ...)` in a way that leaves later reviewers waiting
for stdin while an earlier reviewer is still running.

Implementation shape:

- launch every process with `stdin=subprocess.PIPE`, `stdout=subprocess.PIPE`,
  `stderr=subprocess.PIPE`, and `text=True`;
- write/flush/close the same prompt text to each process stdin immediately
  after all processes launch;
- drain stdout and stderr while processes are running, after stdin has been
  delivered to every reviewer, using reader threads, selectors, or an
  equivalent concurrent drain approach;
- wait for process completion independently with a total timeout budget while
  output is being drained;
- collect drained stdout/stderr for each process result;
- on timeout, terminate/kill defensively and report `timed_out`.

After each completed process, persist the same metadata that single-driver
invocation persists:

- Agy: stored or explicit `conversation_id`, `conversation_source`,
  `last_exit_code`.
- Claude Code: parsed JSON `session_id` when present, fallback stored/explicit
  conversation ID when available, `model`, `last_exit_code`, and warning when
  no `session_id` is available.

- [ ] **Step 4: Run focused tests**

Expected: new `invoke-many` tests pass.

---

### Task 5: CLI And JSON Output

**Files:**
- Modify: `agent-relaypad/scripts/relaypad_driver.py`
- Test: `agent-relaypad/tests/test_relaypad_driver.py`

- [ ] **Step 1: Write failing tests**

Add tests that call `main([...])` for:

```bash
invoke-many --root TMP --drivers agy,cc --prompt-file prompt.txt --timeout 1000
```

Assert:

- exit code is 0 when all complete,
- JSON has top-level `status`,
- `results.agy.status` and `results.cc.status` are present,
- `review_status` is included and is computed from current-round response
  headers, not stale stored `status.json`,
- prompt file content is passed to each driver.

- [ ] **Step 2: Run tests to verify failure**

Expected: parser does not recognize `invoke-many`.

- [ ] **Step 3: Implement minimal CLI**

Add the `invoke-many` subparser with `--drivers`, `--prompt`, `--prompt-file`, `--timeout`, and optional `--model` for drivers that support it. Return exit code 0 for `completed`, 1 for `timed_out` or `error`.

- [ ] **Step 4: Run focused tests**

Expected: CLI tests pass.

---

### Task 6: Documentation And Implementation Review Artifact

**Files:**
- Modify: `README.md`
- Modify: `INSTALL.md`
- Modify: `agent-relaypad/SKILL.md`
- Create: `docs/superpowers/specs/2026-05-23-agent-relaypad-v1-3-parallel-review-driver-implementation.md`

- [ ] **Step 1: Update docs**

Document:

- `invoke-many` command,
- 1000 second default reviewer timeout,
- direct owner-launched reviews wait on subprocess completion,
- manual/external reviewer polling guidance should be 60 seconds if needed later,
- owner should wait for slower reviewers and not archive early.

- [ ] **Step 2: Update expected test count**

Run the full suite to get the new count, then update `INSTALL.md`.

- [ ] **Step 3: Create implementation review artifact**

Summarize files changed, behavior implemented, and verification commands.

---

### Task 7: Final Verification

**Files:**
- No code changes unless verification finds issues.

- [ ] **Step 1: Run full test suite**

```bash
PYTHONPATH=agent-relaypad/scripts python -m unittest discover -s agent-relaypad/tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run dry-runs**

```bash
python agent-relaypad/scripts/relaypad_driver.py invoke --root . --driver agy --prompt hello --conversation-id test-conversation --dry-run
python agent-relaypad/scripts/relaypad_driver.py invoke --root . --driver cc --prompt hello --dry-run
```

Expected: Agy uses `--print-timeout 1000s`; Claude Code uses `opus[1m]`.

- [ ] **Step 3: Run whitespace and state checks**

```bash
git diff --check
python agent-relaypad/scripts/relaypad.py check --root . --agent codex
git status --short --branch
```

Expected: whitespace clean, relaypad idle, only intended files modified.

- [ ] **Step 4: Create implementation review**

Use relaypad to request implementation review from Agy and Claude Code after code and docs are complete.
