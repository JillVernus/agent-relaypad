# Agent Memo Review Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a portable skill that lets Codex, Claude Code, and Antigravity CLI coordinate one active planning or implementation review through project-local `.agent_memo/` files.

**Architecture:** Create a self-contained skill folder with concise `SKILL.md` instructions and one deterministic stdlib Python helper for file operations. Agents use the skill to decide intent and summarize results; the helper owns review creation, status checks, response writes, reconciliation metadata, and archive safety.

**Tech Stack:** Markdown skill files, Python 3 stdlib (`argparse`, `json`, `pathlib`, `shutil`, `tempfile`, `unittest`), no server, no third-party dependencies.

---

## File Structure

- Create `agent-memo-review/SKILL.md`
  - Agent-facing workflow, trigger description, safety rules, and command examples.
- Create `agent-memo-review/agents/openai.yaml`
  - Codex UI metadata for the skill.
- Create `agent-memo-review/scripts/agent_memo.py`
  - Deterministic CLI helper for `.agent_memo/` operations.
- Create `agent-memo-review/tests/test_agent_memo.py`
  - Stdlib `unittest` coverage for core behavior.
- Modify `docs/superpowers/specs/2026-05-22-agent-memo-review-skill-design.md`
  - Only if implementation uncovers a spec mismatch.

The helper script should keep responsibilities grouped by operation:

- `init_memo(root)` creates `.agent_memo/`, `.gitignore`, `active/`, `archive/`, and idle `state.json`.
- `create_review(...)` creates one active review with immutable `request.md`.
- `check_review(...)` returns machine-readable state and pending action hints.
- `write_response(...)` writes only `responses/<agent-id>.md`.
- `reconcile_review(...)` creates or updates `decisions.md`, increments rounds when requested, and rolls up reviewer statuses.
- `archive_review(...)` validates `final.md`, copies to archive, verifies the copy, clears state, and deletes active.

## CLI Contract

The script should support these subcommands:

```bash
python agent-memo-review/scripts/agent_memo.py init --root .
python agent-memo-review/scripts/agent_memo.py create --root . --owner codex --phase planning --topic "auth flow" --reviewers agy,cc --artifact-file docs/plan.md
python agent-memo-review/scripts/agent_memo.py check --root . --agent agy
python agent-memo-review/scripts/agent_memo.py respond --root . --agent agy --status changes_requested --body-file /tmp/agy-review.md
python agent-memo-review/scripts/agent_memo.py reconcile --root . --owner codex --decisions-file /tmp/decisions.md --next-round
python agent-memo-review/scripts/agent_memo.py archive --root . --owner codex --final-file /tmp/final.md
```

All commands should print JSON so agents can summarize reliably. Human-readable prose belongs in `SKILL.md`, not the helper output.

## Task 1: Create Skill Shell

**Files:**
- Create: `agent-memo-review/SKILL.md`
- Create: `agent-memo-review/agents/openai.yaml`

- [ ] **Step 1: Write the skill instructions**

Create `agent-memo-review/SKILL.md` with this structure:

```markdown
---
name: agent-memo-review
description: Use when coordinating plan reviews or implementation reviews between Codex, Claude Code, Antigravity CLI, or other agents through a project-local .agent_memo folder.
---

# Agent Memo Review

Use this skill to create, check, review, reconcile, or archive one active cross-agent review in the current project.

## Core Rules

- Use `.agent_memo/` in the project root.
- Version 1 supports one active review at a time.
- Each reviewer writes only `responses/<agent-id>.md`.
- `request.md` is immutable after creation.
- `final.md` is the approved result and must exist before archive.
- If agent identity is unclear, ask the user instead of guessing.

## Agent ID

Infer agent ID in this order:

1. Explicit user wording such as "as agy" or "for cc".
2. Script argument such as `--agent agy`.
3. Reliable host runtime identity.
4. Ask the user for the current action.

Never infer identity from owner, missing responses, or recently edited files.

## Common Intents

- Create review: run `scripts/agent_memo.py create`.
- Check review: run `scripts/agent_memo.py check`.
- Write feedback: run `scripts/agent_memo.py respond`.
- Reconcile feedback: run `scripts/agent_memo.py reconcile`.
- Archive review: run `scripts/agent_memo.py archive`.

After running a command, summarize the JSON result in plain language and point to the relevant `.agent_memo/` file.
```

- [ ] **Step 2: Add Codex UI metadata**

Create `agent-memo-review/agents/openai.yaml`:

```yaml
interface:
  display_name: "Agent Memo Review"
  short_description: "Coordinate cross-agent plan and code reviews"
  default_prompt: "Use $agent-memo-review to check or create a shared agent review memo."
policy:
  allow_implicit_invocation: true
```

- [ ] **Step 3: Verify files exist**

Run:

```bash
test -f agent-memo-review/SKILL.md
test -f agent-memo-review/agents/openai.yaml
```

Expected: both commands exit `0`.

## Task 2: Add Helper Script Skeleton and Initialization

**Files:**
- Create: `agent-memo-review/scripts/agent_memo.py`
- Create: `agent-memo-review/tests/test_agent_memo.py`

- [ ] **Step 1: Write failing initialization tests**

Create `agent-memo-review/tests/test_agent_memo.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from agent_memo import init_memo


class AgentMemoTests(unittest.TestCase):
    def test_init_creates_idle_memo_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = init_memo(root)

            memo = root / ".agent_memo"
            self.assertEqual(result["status"], "initialized")
            self.assertTrue((memo / "active").is_dir())
            self.assertTrue((memo / "archive").is_dir())
            self.assertEqual(
                json.loads((memo / "state.json").read_text()),
                {"version": 1, "active_review_id": None, "updated_at": result["updated_at"]},
            )
            self.assertEqual((memo / ".gitignore").read_text(), "active/\nstate.json\n")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=agent-memo-review/scripts python -m unittest agent-memo-review/tests/test_agent_memo.py
```

Expected: FAIL because `agent_memo` does not exist.

- [ ] **Step 3: Implement init skeleton**

Create `agent-memo-review/scripts/agent_memo.py`:

```python
#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


VERSION = 1


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def memo_dir(root):
    return Path(root) / ".agent_memo"


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def init_memo(root):
    root = Path(root)
    memo = memo_dir(root)
    (memo / "active").mkdir(parents=True, exist_ok=True)
    (memo / "archive").mkdir(parents=True, exist_ok=True)
    (memo / ".gitignore").write_text("active/\nstate.json\n")
    state_path = memo / "state.json"
    if state_path.exists():
        state = read_json(state_path)
        return {"status": "exists", "updated_at": state.get("updated_at")}
    updated_at = utc_now()
    write_json(state_path, {"version": VERSION, "active_review_id": None, "updated_at": updated_at})
    return {"status": "initialized", "updated_at": updated_at}


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init")
    p_init.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    if args.command == "init":
        print(json.dumps(init_memo(Path(args.root)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run initialization tests**

Run:

```bash
PYTHONPATH=agent-memo-review/scripts python -m unittest agent-memo-review/tests/test_agent_memo.py
```

Expected: PASS.

## Task 3: Implement Review Creation

**Files:**
- Modify: `agent-memo-review/scripts/agent_memo.py`
- Modify: `agent-memo-review/tests/test_agent_memo.py`

- [ ] **Step 1: Add failing creation tests**

Add these methods inside the existing `AgentMemoTests(unittest.TestCase)`
class. Do not add module-level test functions, because `python -m unittest`
will not discover them in this file shape.

```python
from agent_memo import create_review


    def test_create_review_writes_request_status_and_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            artifact = root / "plan.md"
            artifact.write_text("# Plan\n\nDo the work.\n")

            result = create_review(
                root=root,
                owner="codex",
                phase="planning",
                topic="auth flow",
                reviewers=["agy", "cc"],
                artifact_text=artifact.read_text(),
            )

            review_dir = root / ".agent_memo" / "active" / result["review_id"]
            self.assertTrue((review_dir / "request.md").is_file())
            self.assertTrue((review_dir / "status.json").is_file())
            self.assertFalse((review_dir / "decisions.md").exists())
            self.assertFalse((review_dir / "final.md").exists())
            self.assertEqual(json.loads((root / ".agent_memo" / "state.json").read_text())["active_review_id"], result["review_id"])
            self.assertIn("# Plan", (review_dir / "request.md").read_text())


    def test_create_review_rejects_second_active_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            create_review(root, "codex", "planning", "first", ["agy"], "one")
            with self.assertRaises(ValueError):
                create_review(root, "codex", "planning", "second", ["agy"], "two")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=agent-memo-review/scripts python -m unittest agent-memo-review/tests/test_agent_memo.py
```

Expected: FAIL because `create_review` is missing.

- [ ] **Step 3: Implement `create_review`**

Add helpers for slugging, phase tokens, active review discovery, request template, and optimistic `state.json` updates. Keep the public function signature:

```python
def create_review(root, owner, phase, topic, reviewers, artifact_text):
    ...
```

Implementation requirements:

- Call `init_memo(root)` first.
- Allow `phase` values `planning` and `implementation_review`.
- Create review IDs as `YYYY-MM-DD-plan-topic` or `YYYY-MM-DD-impl-topic`.
- Reject if `state.json.active_review_id` is not `None`.
- Reject if `.agent_memo/active/` already contains a review folder.
- Create `request.md`, `status.json`, and `responses/`.
- Do not create `decisions.md`, `final.md`, or reviewer response files.
- Update `state.json` with an `updated_at` re-read guard.

- [ ] **Step 4: Add CLI `create` subcommand**

Support:

```bash
python agent-memo-review/scripts/agent_memo.py create --root . --owner codex --phase planning --topic "auth flow" --reviewers agy,cc --artifact-file docs/plan.md
```

Expected output:

```json
{
  "review_id": "2026-05-22-plan-auth-flow",
  "status": "created"
}
```

- [ ] **Step 5: Run tests**

Run:

```bash
PYTHONPATH=agent-memo-review/scripts python -m unittest agent-memo-review/tests/test_agent_memo.py
```

Expected: PASS.

## Task 4: Implement Check and Respond

**Files:**
- Modify: `agent-memo-review/scripts/agent_memo.py`
- Modify: `agent-memo-review/tests/test_agent_memo.py`

- [ ] **Step 1: Add failing check/respond tests**

Add tests for:

- `check_review(root, "agy")` returns `{"status": "no_active_review"}` when `active_review_id` is `None`.
- `check_review(root, "agy")` returns the active `review_id`, current `round`, and missing own response when active.
- `write_response(root, "agy", "changes_requested", "Needs tests.")` writes only `responses/agy.md`.
- Invalid response status raises `ValueError`.
- Corrupt `.agent_memo/state.json` makes `check_review` return
  `{"status": "invalid_json", "path": ...}` instead of raising a traceback or
  overwriting the file.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=agent-memo-review/scripts python -m unittest agent-memo-review/tests/test_agent_memo.py
```

Expected: FAIL because functions are missing.

- [ ] **Step 3: Implement `check_review`**

Requirements:

- If `.agent_memo/` or `state.json` is missing, return `{"status": "not_initialized"}`.
- If `active_review_id` is `None`, return `{"status": "no_active_review"}`.
- If state points to missing active folder, return `{"status": "broken_state", "error": ...}`.
- If more than one active folder exists, return `{"status": "multiple_active_reviews", ...}`.
- If any required JSON file is invalid, return `{"status": "invalid_json", "path": ...}`
  and do not rewrite the broken file.
- Include whether `responses/<agent-id>.md` exists.

- [ ] **Step 4: Implement `write_response`**

Requirements:

- Require active review.
- Read current `round` from `status.json`.
- Accept only `approved` or `changes_requested`.
- Create or replace `responses/<agent-id>.md`.
- Include `Status`, `Round`, and `Reviewed at` headers.
- Do not update other agents' files.

- [ ] **Step 5: Add CLI `check` and `respond` subcommands**

Support:

```bash
python agent-memo-review/scripts/agent_memo.py check --root . --agent agy
python agent-memo-review/scripts/agent_memo.py respond --root . --agent agy --status approved --body-file /tmp/review.md
```

- [ ] **Step 6: Run tests**

Run:

```bash
PYTHONPATH=agent-memo-review/scripts python -m unittest agent-memo-review/tests/test_agent_memo.py
```

Expected: PASS.

## Task 5: Implement Reconcile and Round Rollup

**Files:**
- Modify: `agent-memo-review/scripts/agent_memo.py`
- Modify: `agent-memo-review/tests/test_agent_memo.py`

- [ ] **Step 1: Add failing reconciliation tests**

Add tests for:

- One current-round `changes_requested` response rolls thread status to `changes_requested`.
- All required current-round responses as `approved` rolls thread status to `approved`.
- Missing current-round responses keep status `waiting_for_review`.
- `reconcile_review(..., next_round=False)` changes a current
  `changes_requested` thread to `waiting_for_owner` after writing decisions.
- `reconcile_review(..., next_round=True)` creates or updates `decisions.md`, increments `round`, and sets status to `waiting_for_review`.
- `request.md` content is unchanged after reconciliation.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=agent-memo-review/scripts python -m unittest agent-memo-review/tests/test_agent_memo.py
```

Expected: FAIL because reconciliation is missing.

- [ ] **Step 3: Implement response parsing**

Parse response files by reading header lines:

```text
Status: approved
Round: 1
```

Ignore responses for older rounds during current rollup.

- [ ] **Step 4: Implement `rollup_status` and `reconcile_review`**

Requirements:

- `rollup_status(root)` reads required reviewers from `status.json`.
- `reconcile_review(root, owner, decisions_text, next_round)` updates only owner-controlled files.
- `decisions.md` is created on first reconcile.
- If the current thread status is `changes_requested`, reconciliation first
  records owner action by setting status to `waiting_for_owner`.
- `next_round=True` increments round and sets `waiting_for_review`.
- `next_round=False` rolls up current response state, then moves
  `changes_requested` to `waiting_for_owner` when the owner writes decisions.
  If rollup is `approved` or `waiting_for_review`, keep that rolled-up status.
- Owner must match `status.json.owner`.

- [ ] **Step 5: Add CLI `reconcile` subcommand**

Support:

```bash
python agent-memo-review/scripts/agent_memo.py reconcile --root . --owner codex --decisions-file /tmp/decisions.md
python agent-memo-review/scripts/agent_memo.py reconcile --root . --owner codex --decisions-file /tmp/decisions.md --next-round
```

- [ ] **Step 6: Run tests**

Run:

```bash
PYTHONPATH=agent-memo-review/scripts python -m unittest agent-memo-review/tests/test_agent_memo.py
```

Expected: PASS.

## Task 6: Implement Archive Safety

**Files:**
- Modify: `agent-memo-review/scripts/agent_memo.py`
- Modify: `agent-memo-review/tests/test_agent_memo.py`

- [ ] **Step 1: Add failing archive tests**

Add tests for:

- Archive rejects when `final_text` is empty.
- Archive rejects when thread is not `approved`.
- Archive copies active review to `archive/REVIEW_ID`.
- Archive copy contains `request.md`, `status.json`, `final.md`, and `responses/`.
- `state.json.active_review_id` becomes `None`.
- `active/REVIEW_ID` is deleted after successful archive.
- If both active and archive copies exist during check, `check_review` reports duplicate/interrupted archive state.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=agent-memo-review/scripts python -m unittest agent-memo-review/tests/test_agent_memo.py
```

Expected: FAIL because archive behavior is missing.

- [ ] **Step 3: Implement `archive_review`**

Requirements:

- Owner must match.
- Current thread status must be `approved`.
- `final_text.strip()` must be non-empty.
- Write `final.md` before copying.
- Set status to `archived`.
- Copy active directory to archive.
- Verify required archive files.
- Clear `state.json.active_review_id` using optimistic guard.
- Delete active directory after state clears.

- [ ] **Step 4: Add CLI `archive` subcommand**

Support:

```bash
python agent-memo-review/scripts/agent_memo.py archive --root . --owner codex --final-file /tmp/final.md
```

- [ ] **Step 5: Run tests**

Run:

```bash
PYTHONPATH=agent-memo-review/scripts python -m unittest agent-memo-review/tests/test_agent_memo.py
```

Expected: PASS.

## Task 7: Polish Skill Instructions Against Real Commands

**Files:**
- Modify: `agent-memo-review/SKILL.md`
- Modify: `agent-memo-review/agents/openai.yaml` if metadata becomes stale

- [ ] **Step 1: Update `SKILL.md` with final command examples**

Make sure examples exactly match implemented CLI flags:

```bash
python agent-memo-review/scripts/agent_memo.py check --root . --agent codex
```

- [ ] **Step 2: Add concise interpretation guidance**

Document that agents should:

- Run the helper.
- Read JSON output.
- Summarize pending action.
- Open referenced markdown files only when needed.
- Ask the user before repairing invalid JSON or broken state.

- [ ] **Step 3: Validate `openai.yaml`**

Run:

```bash
python - <<'PY'
from pathlib import Path
p = Path("agent-memo-review/agents/openai.yaml")
text = p.read_text()
assert 'display_name: "Agent Memo Review"' in text
assert "$agent-memo-review" in text
PY
```

Expected: exits `0`.

## Task 8: Full Verification

**Files:**
- No new files expected.

- [ ] **Step 1: Run all unit tests**

Run:

```bash
PYTHONPATH=agent-memo-review/scripts python -m unittest discover -s agent-memo-review/tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run a manual happy-path smoke test**

Run in a temporary directory:

```bash
tmpdir=$(mktemp -d)
printf '# Plan\n\nShip it.\n' > "$tmpdir/plan.md"
python agent-memo-review/scripts/agent_memo.py init --root "$tmpdir"
python agent-memo-review/scripts/agent_memo.py create --root "$tmpdir" --owner codex --phase planning --topic "smoke plan" --reviewers agy,cc --artifact-file "$tmpdir/plan.md"
printf 'Looks workable.\n' > "$tmpdir/agy.md"
python agent-memo-review/scripts/agent_memo.py respond --root "$tmpdir" --agent agy --status approved --body-file "$tmpdir/agy.md"
printf 'Approved.\n' > "$tmpdir/cc.md"
python agent-memo-review/scripts/agent_memo.py respond --root "$tmpdir" --agent cc --status approved --body-file "$tmpdir/cc.md"
printf '# Decisions\n\nAll approved.\n' > "$tmpdir/decisions.md"
python agent-memo-review/scripts/agent_memo.py reconcile --root "$tmpdir" --owner codex --decisions-file "$tmpdir/decisions.md"
printf '# Final\n\nApproved smoke plan.\n' > "$tmpdir/final.md"
python agent-memo-review/scripts/agent_memo.py archive --root "$tmpdir" --owner codex --final-file "$tmpdir/final.md"
test "$(find "$tmpdir/.agent_memo/archive" -mindepth 1 -maxdepth 1 -type d | wc -l)" -eq 1
```

Expected: each command prints JSON success output and the final `test` exits `0`.

- [ ] **Step 3: Check no active state remains after smoke test**

Run:

```bash
python agent-memo-review/scripts/agent_memo.py check --root "$tmpdir" --agent codex
```

Expected: JSON status is `no_active_review`.

- [ ] **Step 4: Verify CLI invalid JSON output**

Run:

```bash
badroot=$(mktemp -d)
mkdir -p "$badroot/.agent_memo"
printf '{bad json\n' > "$badroot/.agent_memo/state.json"
python agent-memo-review/scripts/agent_memo.py check --root "$badroot" --agent codex
```

Expected: command prints JSON with `"status": "invalid_json"` and a `path`
pointing at `state.json`. It must not print a Python traceback.

- [ ] **Step 5: Commit if repository has git initialized**

Run:

```bash
git status --short
```

Expected: if this is a git repo, review changed files and commit. If not a git repo, report that commit was skipped.
