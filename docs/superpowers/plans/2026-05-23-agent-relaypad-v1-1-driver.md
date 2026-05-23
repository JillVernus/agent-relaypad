# Agent Relaypad v1.1 Driver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional Agy CLI driver that can invoke Antigravity from Codex while keeping `.agent-relaypad/` review files as the source of truth.

**Architecture:** Add a separate `relaypad_driver.py` script for subprocess orchestration so the existing deterministic `relaypad.py` review-state helper stays stable. The driver has generic driver naming and metadata shape, but v1.1 only implements `agy`. It resolves conversation IDs from explicit input, stored runtime metadata, or a best-effort Antigravity cache read, invokes Agy through stdin, and writes local runtime metadata.

**Tech Stack:** Python 3 standard library only (`argparse`, `json`, `subprocess`, `os`, `pathlib`, `datetime`, `unittest`, `tempfile`, `contextlib`, `io`).

---

## File Structure

- Create: `agent-relaypad/scripts/relaypad_driver.py`
  - Owns driver metadata paths, conversation ID resolution, Agy command construction, subprocess invocation, dry-run output, and CLI JSON output.
- Create: `agent-relaypad/tests/test_relaypad_driver.py`
  - Unit tests for the driver. Tests must avoid invoking real `agy`; inject fake subprocess runners and fake cache/settings paths.
- Modify: `agent-relaypad/SKILL.md`
  - Adds optional driver guidance for direct Agy invocation.
- Modify: `README.md`
  - Documents the v1.1 driver command and safety constraints.
- Modify: `INSTALL.md`
  - Updates included file list to include `scripts/relaypad_driver.py` and `tests/test_relaypad_driver.py`.
- Existing: `agent-relaypad/scripts/relaypad.py`
  - Do not change review-state behavior.

---

## Task 1: Add Driver Test Skeleton And Metadata Path Tests

**Files:**
- Create: `agent-relaypad/tests/test_relaypad_driver.py`
- Create: `agent-relaypad/scripts/relaypad_driver.py`

- [ ] **Step 1: Write failing tests for runtime metadata paths**

Create `agent-relaypad/tests/test_relaypad_driver.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import relaypad_driver


class RelaypadDriverTests(unittest.TestCase):
    def test_runtime_metadata_path_uses_agent_relaypad(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            path = relaypad_driver.runtime_metadata_path(root, "agy")

            self.assertEqual(path, root / ".agent-relaypad" / "runtimes" / "agy.json")

    def test_write_runtime_metadata_creates_runtimes_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            path = relaypad_driver.write_runtime_metadata(
                root,
                "agy",
                {
                    "version": 1,
                    "driver": "agy",
                    "conversation_id": "abc",
                    "conversation_source": "explicit",
                    "last_invoked_at": "2026-05-23T00:00:00Z",
                    "last_exit_code": 0,
                },
            )

            self.assertEqual(path, root / ".agent-relaypad" / "runtimes" / "agy.json")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["conversation_id"], "abc")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=agent-relaypad/scripts python -m unittest agent-relaypad/tests/test_relaypad_driver.py -v
```

Expected: FAIL because `relaypad_driver` does not exist.

- [ ] **Step 3: Add minimal driver module**

Create `agent-relaypad/scripts/relaypad_driver.py`:

```python
#!/usr/bin/env python3
import json
from pathlib import Path


VERSION = 1


def utc_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def relaypad_dir(root):
    return Path(root) / ".agent-relaypad"


def runtime_metadata_path(root, driver):
    return relaypad_dir(root) / "runtimes" / f"{driver}.json"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_runtime_metadata(root, driver, data):
    path = runtime_metadata_path(root, driver)
    write_json(path, data)
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=agent-relaypad/scripts python -m unittest agent-relaypad/tests/test_relaypad_driver.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent-relaypad/scripts/relaypad_driver.py agent-relaypad/tests/test_relaypad_driver.py
git commit -m "Add relaypad driver metadata foundation"
```

---

## Task 2: Implement Conversation ID Resolution

**Files:**
- Modify: `agent-relaypad/scripts/relaypad_driver.py`
- Modify: `agent-relaypad/tests/test_relaypad_driver.py`

- [ ] **Step 1: Write failing tests for conversation ID sources**

Append tests:

```python
    def test_resolve_conversation_id_prefers_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = relaypad_driver.resolve_conversation_id(Path(tmp), "agy", explicit_id="explicit-1")

            self.assertEqual(result["status"], "resolved")
            self.assertEqual(result["conversation_id"], "explicit-1")
            self.assertEqual(result["conversation_source"], "explicit")

    def test_resolve_conversation_id_uses_stored_runtime_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            relaypad_driver.write_runtime_metadata(
                root,
                "agy",
                {"version": 1, "driver": "agy", "conversation_id": "stored-1"},
            )

            result = relaypad_driver.resolve_conversation_id(root, "agy")

            self.assertEqual(result["conversation_id"], "stored-1")
            self.assertEqual(result["conversation_source"], "runtime_metadata")

    def test_resolve_conversation_id_uses_antigravity_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            cache = Path(tmp) / "last_conversations.json"
            cache.write_text(json.dumps({str(root): "cache-1"}), encoding="utf-8")

            result = relaypad_driver.resolve_conversation_id(root, "agy", agy_cache_path=cache)

            self.assertEqual(result["conversation_id"], "cache-1")
            self.assertEqual(result["conversation_source"], "antigravity_last_conversations")

    def test_resolve_conversation_id_handles_unreadable_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing.json"

            result = relaypad_driver.resolve_conversation_id(root, "agy", agy_cache_path=missing)

            self.assertEqual(result["status"], "error")
            self.assertIn("conversation ID", result["error"])
            self.assertIn("--conversation-id", result["next_step"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=agent-relaypad/scripts python -m unittest agent-relaypad/tests/test_relaypad_driver.py -v
```

Expected: FAIL because `resolve_conversation_id` does not exist.

- [ ] **Step 3: Implement resolver**

Add to `relaypad_driver.py`:

```python
def default_agy_cache_path():
    return Path.home() / ".gemini" / "antigravity-cli" / "cache" / "last_conversations.json"


def resolve_conversation_id(root, driver, explicit_id=None, agy_cache_path=None):
    root = Path(root)
    if explicit_id:
        return {
            "status": "resolved",
            "conversation_id": explicit_id,
            "conversation_source": "explicit",
        }

    metadata_path = runtime_metadata_path(root, driver)
    if metadata_path.is_file():
        try:
            metadata = read_json(metadata_path)
        except (OSError, json.JSONDecodeError):
            metadata = {}
        if metadata.get("conversation_id"):
            return {
                "status": "resolved",
                "conversation_id": metadata["conversation_id"],
                "conversation_source": "runtime_metadata",
            }

    if driver == "agy":
        cache_path = Path(agy_cache_path) if agy_cache_path is not None else default_agy_cache_path()
        try:
            cache = read_json(cache_path)
        except (OSError, json.JSONDecodeError, PermissionError):
            cache = {}
        conversation_id = cache.get(str(root.resolve())) or cache.get(str(root))
        if conversation_id:
            return {
                "status": "resolved",
                "conversation_id": conversation_id,
                "conversation_source": "antigravity_last_conversations",
            }

    return {
        "status": "error",
        "driver": driver,
        "error": f"No {driver} conversation ID found",
        "next_step": f"Open {driver} in this workspace once or pass --conversation-id.",
    }
```

- [ ] **Step 4: Run tests**

Run:

```bash
PYTHONPATH=agent-relaypad/scripts python -m unittest agent-relaypad/tests/test_relaypad_driver.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent-relaypad/scripts/relaypad_driver.py agent-relaypad/tests/test_relaypad_driver.py
git commit -m "Resolve driver conversation IDs"
```

---

## Task 3: Implement Agy Command Construction, Dry Run, And Unsupported Model Handling

**Files:**
- Modify: `agent-relaypad/scripts/relaypad_driver.py`
- Modify: `agent-relaypad/tests/test_relaypad_driver.py`

- [ ] **Step 1: Write failing tests**

Append tests:

```python
    def test_build_agy_command_uses_conversation_and_no_prompt_argument(self):
        command = relaypad_driver.build_agy_command("conv-1", timeout=300)

        self.assertEqual(command, ["agy", "--print", "--print-timeout", "300s", "--conversation", "conv-1"])

    def test_dry_run_returns_command_and_stdin(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = relaypad_driver.invoke_driver(
                root=Path(tmp),
                driver="agy",
                prompt="hello",
                conversation_id="conv-1",
                dry_run=True,
            )

            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(result["stdin"], "hello")
            self.assertNotIn("hello", result["command"])

    def test_model_override_is_unsupported_without_invoking(self):
        calls = []

        def runner(*args, **kwargs):
            calls.append((args, kwargs))

        with tempfile.TemporaryDirectory() as tmp:
            result = relaypad_driver.invoke_driver(
                root=Path(tmp),
                driver="agy",
                prompt="hello",
                conversation_id="conv-1",
                model="Some Model",
                runner=runner,
            )

            self.assertEqual(result["status"], "unsupported")
            self.assertEqual(calls, [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=agent-relaypad/scripts python -m unittest agent-relaypad/tests/test_relaypad_driver.py -v
```

Expected: FAIL because command and invocation functions do not exist.

- [ ] **Step 3: Implement command construction and dry-run path**

Add imports and functions:

```python
import subprocess


def build_agy_command(conversation_id, timeout):
    return ["agy", "--print", "--print-timeout", f"{int(timeout)}s", "--conversation", conversation_id]


def unsupported_model_result(driver):
    return {
        "status": "unsupported",
        "driver": driver,
        "error": "Agy model override is not supported without a safe per-invocation model flag.",
        "next_step": "Use Agy's configured default model or configure Agy manually before invoking.",
    }


def invoke_driver(root, driver, prompt, conversation_id=None, model=None, timeout=300, dry_run=False, runner=None):
    root = Path(root)
    if driver != "agy":
        return {"status": "error", "driver": driver, "error": f"Unsupported driver: {driver}"}
    if model:
        return unsupported_model_result(driver)

    resolved = resolve_conversation_id(root, driver, explicit_id=conversation_id)
    if resolved.get("status") != "resolved":
        return resolved

    command = build_agy_command(resolved["conversation_id"], timeout)
    if dry_run:
        return {"status": "dry_run", "driver": driver, "command": command, "stdin": prompt}

    run = runner or subprocess.run
    completed = run(command, input=prompt, text=True, capture_output=True, cwd=str(root))
    metadata_path = write_runtime_metadata(
        root,
        driver,
        {
            "version": VERSION,
            "driver": driver,
            "conversation_id": resolved["conversation_id"],
            "conversation_source": resolved["conversation_source"],
            "last_invoked_at": utc_now(),
            "last_exit_code": completed.returncode,
        },
    )
    return {
        "status": "invoked",
        "driver": driver,
        "conversation_id": resolved["conversation_id"],
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "metadata_path": str(metadata_path),
    }
```

- [ ] **Step 4: Run tests**

Run:

```bash
PYTHONPATH=agent-relaypad/scripts python -m unittest agent-relaypad/tests/test_relaypad_driver.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent-relaypad/scripts/relaypad_driver.py agent-relaypad/tests/test_relaypad_driver.py
git commit -m "Add Agy driver dry-run behavior"
```

---

## Task 4: Implement Real Invocation Metadata And CLI

**Files:**
- Modify: `agent-relaypad/scripts/relaypad_driver.py`
- Modify: `agent-relaypad/tests/test_relaypad_driver.py`

- [ ] **Step 1: Write failing tests for runner invocation and CLI JSON**

Append tests:

```python
    def test_invoke_driver_passes_prompt_to_runner_stdin_and_writes_metadata(self):
        class Completed:
            returncode = 0
            stdout = "ok"
            stderr = ""

        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return Completed()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = relaypad_driver.invoke_driver(
                root=root,
                driver="agy",
                prompt="review please",
                conversation_id="conv-1",
                runner=runner,
            )

            self.assertEqual(result["status"], "invoked")
            self.assertEqual(calls[0][1]["input"], "review please")
            self.assertTrue((root / ".agent-relaypad" / "runtimes" / "agy.json").is_file())

    def test_cli_dry_run_outputs_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = relaypad_driver.main(
                    [
                        "invoke",
                        "--root",
                        tmp,
                        "--driver",
                        "agy",
                        "--prompt",
                        "hello",
                        "--conversation-id",
                        "conv-1",
                        "--dry-run",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(result, 0)
            self.assertEqual(payload["status"], "dry_run")
```

- [ ] **Step 2: Run tests to verify CLI test fails**

Run:

```bash
PYTHONPATH=agent-relaypad/scripts python -m unittest agent-relaypad/tests/test_relaypad_driver.py -v
```

Expected: FAIL because `main` does not exist.

- [ ] **Step 3: Implement CLI**

Add to `relaypad_driver.py`:

```python
import argparse


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p_invoke = sub.add_parser("invoke")
    p_invoke.add_argument("--root", default=".")
    p_invoke.add_argument("--driver", required=True)
    p_invoke.add_argument("--prompt", required=True)
    p_invoke.add_argument("--conversation-id")
    p_invoke.add_argument("--model")
    p_invoke.add_argument("--timeout", type=int, default=300)
    p_invoke.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "invoke":
            result = invoke_driver(
                root=Path(args.root),
                driver=args.driver,
                prompt=args.prompt,
                conversation_id=args.conversation_id,
                model=args.model,
                timeout=args.timeout,
                dry_run=args.dry_run,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result.get("status") in {"dry_run", "invoked"} else 1
    except Exception as exc:
        print(
            json.dumps(
                {"status": "error", "error_type": type(exc).__name__, "error": str(exc)},
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests**

Run:

```bash
PYTHONPATH=agent-relaypad/scripts python -m unittest agent-relaypad/tests/test_relaypad_driver.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent-relaypad/scripts/relaypad_driver.py agent-relaypad/tests/test_relaypad_driver.py
git commit -m "Add relaypad driver CLI"
```

---

## Task 5: Update Relaypad Initialization And Docs

**Files:**
- Modify: `agent-relaypad/scripts/relaypad.py`
- Modify: `agent-relaypad/tests/test_relaypad.py`
- Modify: `agent-relaypad/SKILL.md`
- Modify: `README.md`
- Modify: `INSTALL.md`

- [ ] **Step 1: Write failing test for `runtimes/` gitignore**

Modify `test_init_creates_idle_memo_tree` in `agent-relaypad/tests/test_relaypad.py`:

```python
self.assertEqual((memo / ".gitignore").read_text(encoding="utf-8"), "active/\nstate.json\nruntimes/\n")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=agent-relaypad/scripts python -m unittest agent-relaypad/tests/test_relaypad.py -v
```

Expected: FAIL because `runtimes/` is not in the generated `.gitignore`.

- [ ] **Step 3: Update `init_relaypad`**

Change in `agent-relaypad/scripts/relaypad.py`:

```python
gitignore_path.write_text("active/\nstate.json\nruntimes/\n", encoding="utf-8")
```

Do not overwrite an existing `.agent-relaypad/.gitignore`.

- [ ] **Step 4: Update docs and skill**

Add to `agent-relaypad/SKILL.md`:

```markdown
## Optional Driver Invocation

- Manual relaypad review remains the default workflow.
- If the user asks Codex to invoke Agy directly, use `python agent-relaypad/scripts/relaypad_driver.py invoke`.
- Prefer an explicit or stored Agy conversation ID.
- Do not request an Agy model override in v1.1; the driver returns unsupported unless Agy exposes a safe per-invocation model flag.
- After invoking, inspect `.agent-relaypad/` review state before summarizing success.
```

Update `README.md` with a short `relaypad_driver.py invoke --dry-run` example.
Update `INSTALL.md` included file list and verification notes to mention `relaypad_driver.py`.

- [ ] **Step 5: Run all tests and smoke checks**

Run:

```bash
PYTHONPATH=agent-relaypad/scripts python -m unittest discover -s agent-relaypad/tests -v
python agent-relaypad/scripts/relaypad.py --help
python agent-relaypad/scripts/relaypad_driver.py invoke --root . --driver agy --prompt "hello" --conversation-id test-conv --dry-run
```

Expected:
- All tests pass.
- Both help/dry-run commands exit `0`.
- Dry-run JSON command uses `agy --print --print-timeout 300s --conversation test-conv`.
- Dry-run JSON includes `"stdin": "hello"`.

- [ ] **Step 6: Commit**

```bash
git add agent-relaypad/scripts agent-relaypad/tests agent-relaypad/SKILL.md README.md INSTALL.md
git commit -m "Document and wire Agy driver"
```

---

## Task 6: Final Verification And Implementation Review

**Files:**
- No new files expected unless review feedback requires changes.

- [ ] **Step 1: Run full verification**

Run:

```bash
PYTHONPATH=agent-relaypad/scripts python -m unittest discover -s agent-relaypad/tests -v
python agent-relaypad/scripts/relaypad.py check --root . --agent codex
python agent-relaypad/scripts/relaypad_driver.py invoke --root . --driver agy --prompt "Use agent-relaypad. Check active review as agy." --conversation-id dry-run-conv --dry-run
git status --short --branch
```

Expected:
- All tests pass.
- Relaypad state is `no_active_review` before starting implementation review.
- Driver dry run exits `0`.
- Git status is clean except intentional committed work.

- [ ] **Step 2: Create implementation review**

Run:

```bash
python agent-relaypad/scripts/relaypad.py create \
  --root . \
  --owner codex \
  --phase implementation_review \
  --topic "v1.1 agy driver implementation" \
  --reviewers agy \
  --artifact-file docs/superpowers/specs/2026-05-23-agent-relaypad-v1-1-driver-design.md
```

Then ask Agy to review implementation using stdin prompt invocation, not positional prompt arguments.

- [ ] **Step 3: Reconcile, fix if needed, archive**

If Agy requests changes, reconcile with `--next-round` after fixes. If Agy approves, reconcile and archive with a final result describing implementation, tests run, and any limitations.

- [ ] **Step 4: Push**

Run:

```bash
git push
```

Expected: `main` pushed to `origin/main`.
