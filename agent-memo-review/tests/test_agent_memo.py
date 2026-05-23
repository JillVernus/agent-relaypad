import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import agent_memo
from agent_memo import archive_review, check_review, create_review, init_memo, reconcile_review, rollup_status, write_response


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
                json.loads((memo / "state.json").read_text(encoding="utf-8")),
                {"version": 1, "active_review_id": None, "updated_at": result["updated_at"]},
            )
            self.assertEqual((memo / ".gitignore").read_text(encoding="utf-8"), "active/\nstate.json\n")

    def test_init_does_not_overwrite_existing_gitignore_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            gitignore = root / ".agent_memo" / ".gitignore"
            gitignore.write_text("custom override\n", encoding="utf-8")

            result = init_memo(root)

            self.assertEqual(result["status"], "exists")
            self.assertEqual(gitignore.read_text(encoding="utf-8"), "custom override\n")

    def test_create_review_writes_request_status_and_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            artifact = root / "plan.md"
            artifact.write_text("# Plan\n\nDo the work.\n", encoding="utf-8")

            result = create_review(
                root=root,
                owner="codex",
                phase="planning",
                topic="auth flow",
                reviewers=["agy", "cc"],
                artifact_text=artifact.read_text(encoding="utf-8"),
            )

            review_dir = root / ".agent_memo" / "active" / result["review_id"]
            status = json.loads((review_dir / "status.json").read_text(encoding="utf-8"))
            self.assertTrue((review_dir / "request.md").is_file())
            self.assertTrue((review_dir / "status.json").is_file())
            self.assertTrue((review_dir / "responses").is_dir())
            self.assertEqual(list((review_dir / "responses").iterdir()), [])
            self.assertFalse((review_dir / "decisions.md").exists())
            self.assertFalse((review_dir / "final.md").exists())
            self.assertIn("plan-auth-flow", result["review_id"])
            self.assertEqual(status["review_id"], result["review_id"])
            self.assertEqual(status["owner"], "codex")
            self.assertEqual(status["phase"], "planning")
            self.assertEqual(status["topic"], "auth flow")
            self.assertEqual(status["required_reviewers"], ["agy", "cc"])
            self.assertEqual(status["round"], 1)
            self.assertEqual(status["status"], "waiting_for_review")
            self.assertEqual(
                json.loads((root / ".agent_memo" / "state.json").read_text(encoding="utf-8"))["active_review_id"],
                result["review_id"],
            )
            self.assertIn("# Plan", (review_dir / "request.md").read_text(encoding="utf-8"))

    def test_create_review_rejects_second_active_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            create_review(root, "codex", "planning", "first", ["agy"], "one")
            with self.assertRaises(ValueError):
                create_review(root, "codex", "planning", "second", ["agy"], "two")

    def test_create_review_rejects_invalid_reviewer_before_creating_active_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with self.assertRaises(ValueError):
                create_review(root, "codex", "planning", "auth flow", ["../evil"], "one")

            active = root / ".agent_memo" / "active"
            self.assertFalse(active.exists() and list(active.iterdir()))

    def test_create_review_rejects_empty_reviewer_list_before_creating_active_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with self.assertRaises(ValueError):
                create_review(root, "codex", "planning", "auth flow", [], "one")

            active = root / ".agent_memo" / "active"
            self.assertFalse(active.exists() and list(active.iterdir()))

    def test_create_review_rejects_unsupported_phase_without_active_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)

            with self.assertRaises(ValueError):
                create_review(root, "codex", "design", "auth flow", ["agy"], "one")

            self.assertEqual(list((root / ".agent_memo" / "active").iterdir()), [])

    def test_create_review_cleans_partial_directory_when_status_write_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            original_write_json = agent_memo.write_json

            def fail_status_write(path, data):
                if Path(path).name == "status.json":
                    raise RuntimeError("status write failed")
                original_write_json(path, data)

            agent_memo.write_json = fail_status_write
            try:
                with self.assertRaises(RuntimeError):
                    create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            finally:
                agent_memo.write_json = original_write_json

            self.assertEqual(list((root / ".agent_memo" / "active").iterdir()), [])

    def test_check_review_returns_no_active_review_when_state_is_idle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)

            self.assertEqual(check_review(root, "agy"), {"status": "no_active_review"})

    def test_check_review_returns_broken_state_when_idle_state_has_stray_active_review_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            stray = root / ".agent_memo" / "active" / "2026-05-22-plan-stray"
            stray.mkdir(parents=True)

            result = check_review(root, "agy")

            self.assertEqual(result["status"], "broken_state")
            self.assertIn("active review folder exists", result["error"])
            self.assertEqual(result["review_ids"], ["2026-05-22-plan-stray"])

    def test_check_review_returns_multiple_active_reviews_when_idle_state_has_stray_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            (root / ".agent_memo" / "active" / "2026-05-22-plan-one").mkdir(parents=True)
            (root / ".agent_memo" / "active" / "2026-05-22-plan-two").mkdir(parents=True)

            result = check_review(root, "agy")

            self.assertEqual(result["status"], "multiple_active_reviews")
            self.assertIsNone(result["active_review_id"])
            self.assertEqual(result["review_ids"], ["2026-05-22-plan-one", "2026-05-22-plan-two"])

    def test_check_review_returns_broken_state_when_active_review_missing_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            request_path = root / ".agent_memo" / "active" / created["review_id"] / "request.md"
            request_path.unlink()

            result = check_review(root, "agy")

            self.assertEqual(result["status"], "broken_state")
            self.assertIn("request is missing", result["error"])

    def test_check_review_returns_active_review_round_and_missing_own_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy"], "one")

            result = check_review(root, "agy")

            self.assertEqual(result["status"], "active_review")
            self.assertEqual(result["review_id"], created["review_id"])
            self.assertEqual(result["round"], 1)
            self.assertFalse(result["response_exists"])
            self.assertTrue(result["missing_response"])

    def test_check_review_reports_same_round_response_as_not_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            write_response(root, "agy", "approved", "Looks good.")

            result = check_review(root, "agy")

            self.assertEqual(result["round"], 1)
            self.assertTrue(result["response_exists"])
            self.assertFalse(result["missing_response"])
            self.assertEqual(result["response_round"], 1)

    def test_check_review_reports_prior_round_response_as_missing_after_next_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            write_response(root, "agy", "changes_requested", "Needs tests.")
            rollup_status(root)
            reconcile_review(root, "codex", "# Decisions\n\nTests added.\n", next_round=True)

            result = check_review(root, "agy")

            self.assertEqual(result["round"], 2)
            self.assertTrue(result["response_exists"])
            self.assertTrue(result["missing_response"])
            self.assertEqual(result["response_round"], 1)

    def test_check_review_rejects_malformed_active_review_id_without_reading_outside_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            outside = root / "outside_review"
            outside.mkdir()
            (outside / "responses").mkdir()
            (outside / "status.json").write_text(
                json.dumps({"review_id": "../../outside_review", "round": 99, "required_reviewers": ["agy"]}),
                encoding="utf-8",
            )
            state_path = root / ".agent_memo" / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["active_review_id"] = "../../outside_review"
            state_path.write_text(json.dumps(state), encoding="utf-8")

            result = check_review(root, "agy")

            self.assertEqual(result["status"], "broken_state")
            self.assertEqual(result["review_id"], "../../outside_review")
            self.assertIn("Invalid active review id", result["error"])
            self.assertFalse((outside / "responses" / "agy.md").exists())

    def test_write_response_writes_only_own_response_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy", "cc"], "one")
            review_dir = root / ".agent_memo" / "active" / created["review_id"]

            result = write_response(root, "agy", "changes_requested", "Needs tests.")

            response_path = review_dir / "responses" / "agy.md"
            self.assertEqual(result["status"], "written")
            self.assertEqual(result["review_id"], created["review_id"])
            self.assertEqual(result["round"], 1)
            self.assertTrue(response_path.is_file())
            self.assertFalse((review_dir / "responses" / "cc.md").exists())
            text = response_path.read_text(encoding="utf-8")
            self.assertIn("Status: changes_requested\n", text)
            self.assertIn("Round: 1\n", text)
            self.assertIn("Reviewed at: ", text)
            self.assertTrue(text.endswith("\n\nNeeds tests.\n"))

    def test_write_response_rejects_malformed_active_review_id_without_writing_outside_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            outside = root / "outside_review"
            outside.mkdir()
            (outside / "responses").mkdir()
            (outside / "status.json").write_text(
                json.dumps({"review_id": "../../outside_review", "round": 99, "required_reviewers": ["agy"]}),
                encoding="utf-8",
            )
            state_path = root / ".agent_memo" / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["active_review_id"] = "../../outside_review"
            state_path.write_text(json.dumps(state), encoding="utf-8")

            with self.assertRaises(ValueError):
                write_response(root, "agy", "approved", "bad")

            self.assertEqual(list((outside / "responses").iterdir()), [])

    def test_check_review_accepts_generated_review_id_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "implementation_review", "auth flow", ["agy"], "one")

            result = check_review(root, "agy")

            self.assertEqual(result["status"], "active_review")
            self.assertEqual(result["review_id"], created["review_id"])

    def test_write_response_rejects_invalid_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            create_review(root, "codex", "planning", "auth flow", ["agy"], "one")

            with self.assertRaises(ValueError):
                write_response(root, "agy", "needs_work", "Needs tests.")

    def test_write_response_rejects_agent_path_traversal_without_writing_outside_responses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            review_dir = root / ".agent_memo" / "active" / created["review_id"]
            request_path = review_dir / "request.md"
            original_request = request_path.read_text(encoding="utf-8")

            with self.assertRaises(ValueError):
                write_response(root, "../request", "approved", "bad")

            self.assertEqual(request_path.read_text(encoding="utf-8"), original_request)
            self.assertEqual(list((review_dir / "responses").iterdir()), [])
            self.assertFalse((review_dir / "request.md.md").exists())

    def test_check_review_rejects_agent_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            create_review(root, "codex", "planning", "auth flow", ["agy"], "one")

            with self.assertRaises(ValueError):
                check_review(root, "../request")

    def test_write_response_accepts_hyphen_and_underscore_agent_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agent_2", "gemini-1"], "one")
            review_dir = root / ".agent_memo" / "active" / created["review_id"]

            write_response(root, "gemini-1", "approved", "Looks good.")
            write_response(root, "agent_2", "changes_requested", "Needs tests.")

            self.assertTrue((review_dir / "responses" / "gemini-1.md").is_file())
            self.assertTrue((review_dir / "responses" / "agent_2.md").is_file())

    def test_check_review_returns_invalid_json_for_corrupt_state_without_rewriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            state_path = root / ".agent_memo" / "state.json"
            state_path.write_text("{not json", encoding="utf-8")

            result = check_review(root, "agy")

            self.assertEqual(result, {"status": "invalid_json", "path": str(state_path)})
            self.assertEqual(state_path.read_text(encoding="utf-8"), "{not json")

    def test_check_review_returns_invalid_json_for_corrupt_state_even_with_duplicate_archive_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            memo = root / ".agent_memo"
            shutil.copytree(memo / "active" / created["review_id"], memo / "archive" / created["review_id"])
            state_path = memo / "state.json"
            state_path.write_text("{not json", encoding="utf-8")

            result = check_review(root, "agy")

            self.assertEqual(result, {"status": "invalid_json", "path": str(state_path)})
            self.assertEqual(state_path.read_text(encoding="utf-8"), "{not json")

    def test_cli_check_and_respond_subcommands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body_file = root / "body.md"
            body_file.write_text("Looks good.", encoding="utf-8")
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy"], "one")

            check_out = io.StringIO()
            with contextlib.redirect_stdout(check_out):
                agent_memo.main(["check", "--root", str(root), "--agent", "agy"])
            self.assertEqual(json.loads(check_out.getvalue())["review_id"], created["review_id"])

            respond_out = io.StringIO()
            with contextlib.redirect_stdout(respond_out):
                agent_memo.main(
                    [
                        "respond",
                        "--root",
                        str(root),
                        "--agent",
                        "agy",
                        "--status",
                        "approved",
                        "--body-file",
                        str(body_file),
                    ]
                )

            self.assertEqual(json.loads(respond_out.getvalue())["status"], "written")
            self.assertTrue((root / ".agent_memo" / "active" / created["review_id"] / "responses" / "agy.md").is_file())

    def test_cli_duplicate_create_prints_json_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "plan.md"
            artifact.write_text("# Plan\n", encoding="utf-8")
            init_memo(root)
            create_review(root, "codex", "planning", "auth flow", ["agy"], "one")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = agent_memo.main(
                    [
                        "create",
                        "--root",
                        str(root),
                        "--owner",
                        "codex",
                        "--phase",
                        "planning",
                        "--topic",
                        "second",
                        "--reviewers",
                        "agy",
                        "--artifact-file",
                        str(artifact),
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(result, 1)
            self.assertEqual(payload["status"], "error")
            self.assertEqual(payload["error_type"], "ValueError")
            self.assertIn("active review", payload["error"])
            self.assertNotIn("Traceback", stdout.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_cli_create_with_invalid_state_json_prints_json_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "plan.md"
            artifact.write_text("# Plan\n", encoding="utf-8")
            init_memo(root)
            (root / ".agent_memo" / "state.json").write_text("{not json", encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = agent_memo.main(
                    [
                        "create",
                        "--root",
                        str(root),
                        "--owner",
                        "codex",
                        "--phase",
                        "planning",
                        "--topic",
                        "auth flow",
                        "--reviewers",
                        "agy",
                        "--artifact-file",
                        str(artifact),
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(result, 1)
            self.assertEqual(payload["status"], "error")
            self.assertEqual(payload["error_type"], "JSONDecodeError")
            self.assertNotIn("Traceback", stdout.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_cli_create_rejects_invalid_reviewer_with_json_error_and_no_active_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "plan.md"
            artifact.write_text("# Plan\n", encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = agent_memo.main(
                    [
                        "create",
                        "--root",
                        str(root),
                        "--owner",
                        "codex",
                        "--phase",
                        "planning",
                        "--topic",
                        "auth flow",
                        "--reviewers",
                        "../evil",
                        "--artifact-file",
                        str(artifact),
                    ]
                )

            payload = json.loads(stdout.getvalue())
            active = root / ".agent_memo" / "active"
            self.assertEqual(result, 1)
            self.assertEqual(payload["status"], "error")
            self.assertEqual(payload["error_type"], "ValueError")
            self.assertIn("Invalid agent id", payload["error"])
            self.assertFalse(active.exists() and list(active.iterdir()))
            self.assertNotIn("Traceback", stdout.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_rollup_status_sets_changes_requested_for_current_round_change_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy", "cc"], "one")
            review_dir = root / ".agent_memo" / "active" / created["review_id"]
            (review_dir / "responses" / "agy.md").write_text(
                "Status: changes_requested\nRound: 1\n\nNeeds work.\n",
                encoding="utf-8",
            )
            (review_dir / "responses" / "cc.md").write_text(
                "Status: approved\nRound: 0\n\nOld approval.\n",
                encoding="utf-8",
            )

            result = rollup_status(root)

            status = json.loads((review_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "changes_requested")
            self.assertEqual(status["status"], "changes_requested")

    def test_rollup_status_sets_approved_when_all_required_current_round_responses_approve(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy", "cc"], "one")
            write_response(root, "agy", "approved", "Looks good.")
            write_response(root, "cc", "approved", "Looks good.")
            review_dir = root / ".agent_memo" / "active" / created["review_id"]

            result = rollup_status(root)

            status = json.loads((review_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "approved")
            self.assertEqual(status["status"], "approved")

    def test_rollup_status_keeps_waiting_for_review_when_current_round_responses_are_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy", "cc"], "one")
            write_response(root, "agy", "approved", "Looks good.")
            review_dir = root / ".agent_memo" / "active" / created["review_id"]

            result = rollup_status(root)

            status = json.loads((review_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "waiting_for_review")
            self.assertEqual(status["status"], "waiting_for_review")

    def test_reconcile_without_next_round_moves_changes_requested_to_waiting_for_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            write_response(root, "agy", "changes_requested", "Needs tests.")
            rollup_status(root)
            review_dir = root / ".agent_memo" / "active" / created["review_id"]

            result = reconcile_review(root, "codex", "# Decisions\n\nWill add tests.\n", next_round=False)

            status = json.loads((review_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "waiting_for_owner")
            self.assertEqual(result["round"], 1)
            self.assertEqual(status["status"], "waiting_for_owner")
            self.assertEqual(status["round"], 1)
            self.assertEqual(
                (review_dir / "decisions.md").read_text(encoding="utf-8"),
                "# Decisions\n\nWill add tests.\n",
            )

    def test_reconcile_next_round_writes_decisions_increments_round_and_waits_for_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            write_response(root, "agy", "changes_requested", "Needs tests.")
            rollup_status(root)
            review_dir = root / ".agent_memo" / "active" / created["review_id"]

            result = reconcile_review(root, "codex", "# Decisions\n\nTests added.\n", next_round=True)

            status = json.loads((review_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "waiting_for_review")
            self.assertEqual(result["round"], 2)
            self.assertEqual(status["status"], "waiting_for_review")
            self.assertEqual(status["round"], 2)
            self.assertEqual(
                (review_dir / "decisions.md").read_text(encoding="utf-8"),
                "# Decisions\n\nTests added.\n",
            )

    def test_reconcile_does_not_change_request_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            review_dir = root / ".agent_memo" / "active" / created["review_id"]
            request_path = review_dir / "request.md"
            original_request = request_path.read_text(encoding="utf-8")

            reconcile_review(root, "codex", "# Decisions\n\nStill waiting.\n", next_round=False)

            self.assertEqual(request_path.read_text(encoding="utf-8"), original_request)

    def test_reconcile_rejects_owner_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            create_review(root, "codex", "planning", "auth flow", ["agy"], "one")

            with self.assertRaises(ValueError):
                reconcile_review(root, "agy", "# Decisions\n\nBad owner.\n", next_round=False)

    def test_reconcile_next_round_rejects_approved_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            write_response(root, "agy", "approved", "Looks good.")
            rollup_status(root)

            with self.assertRaises(ValueError):
                reconcile_review(root, "codex", "# Decisions\n\nAlready approved.\n", next_round=True)

    def test_cli_reconcile_subcommand(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decisions_file = root / "decisions.md"
            decisions_file.write_text("# Decisions\n\nLooks good.\n", encoding="utf-8")
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            write_response(root, "agy", "approved", "Looks good.")

            reconcile_out = io.StringIO()
            with contextlib.redirect_stdout(reconcile_out):
                agent_memo.main(
                    [
                        "reconcile",
                        "--root",
                        str(root),
                        "--owner",
                        "codex",
                        "--decisions-file",
                        str(decisions_file),
                    ]
                )

            review_dir = root / ".agent_memo" / "active" / created["review_id"]
            self.assertEqual(json.loads(reconcile_out.getvalue())["status"], "approved")
            self.assertEqual(
                (review_dir / "decisions.md").read_text(encoding="utf-8"),
                "# Decisions\n\nLooks good.\n",
            )

    def test_cli_reconcile_subcommand_with_next_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decisions_file = root / "decisions.md"
            decisions_file.write_text("# Decisions\n\nTests added.\n", encoding="utf-8")
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            write_response(root, "agy", "changes_requested", "Needs tests.")
            rollup_status(root)

            reconcile_out = io.StringIO()
            with contextlib.redirect_stdout(reconcile_out):
                agent_memo.main(
                    [
                        "reconcile",
                        "--root",
                        str(root),
                        "--owner",
                        "codex",
                        "--decisions-file",
                        str(decisions_file),
                        "--next-round",
                    ]
                )

            review_dir = root / ".agent_memo" / "active" / created["review_id"]
            status = json.loads((review_dir / "status.json").read_text(encoding="utf-8"))
            result = json.loads(reconcile_out.getvalue())
            self.assertEqual(result["status"], "waiting_for_review")
            self.assertEqual(result["round"], 2)
            self.assertEqual(status["status"], "waiting_for_review")
            self.assertEqual(status["round"], 2)

    def test_cli_reconcile_next_round_rolls_up_current_changes_requested_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body_file = root / "body.md"
            body_file.write_text("Needs tests.", encoding="utf-8")
            decisions_file = root / "decisions.md"
            decisions_file.write_text("# Decisions\n\nTests added.\n", encoding="utf-8")
            artifact = root / "plan.md"
            artifact.write_text("# Plan\n", encoding="utf-8")

            create_out = io.StringIO()
            with contextlib.redirect_stdout(create_out):
                create_result = agent_memo.main(
                    [
                        "create",
                        "--root",
                        str(root),
                        "--owner",
                        "codex",
                        "--phase",
                        "planning",
                        "--topic",
                        "auth flow",
                        "--reviewers",
                        "agy",
                        "--artifact-file",
                        str(artifact),
                    ]
                )
            self.assertEqual(create_result, 0)
            review_id = json.loads(create_out.getvalue())["review_id"]

            respond_out = io.StringIO()
            with contextlib.redirect_stdout(respond_out):
                respond_result = agent_memo.main(
                    [
                        "respond",
                        "--root",
                        str(root),
                        "--agent",
                        "agy",
                        "--status",
                        "changes_requested",
                        "--body-file",
                        str(body_file),
                    ]
                )
            self.assertEqual(respond_result, 0)

            reconcile_out = io.StringIO()
            with contextlib.redirect_stdout(reconcile_out):
                reconcile_result = agent_memo.main(
                    [
                        "reconcile",
                        "--root",
                        str(root),
                        "--owner",
                        "codex",
                        "--decisions-file",
                        str(decisions_file),
                        "--next-round",
                    ]
                )

            review_dir = root / ".agent_memo" / "active" / review_id
            status = json.loads((review_dir / "status.json").read_text(encoding="utf-8"))
            result = json.loads(reconcile_out.getvalue())
            self.assertEqual(reconcile_result, 0)
            self.assertEqual(result["status"], "waiting_for_review")
            self.assertEqual(result["round"], 2)
            self.assertEqual(status["status"], "waiting_for_review")
            self.assertEqual(status["round"], 2)

    def test_archive_rejects_empty_final_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            write_response(root, "agy", "approved", "Looks good.")
            rollup_status(root)
            review_dir = root / ".agent_memo" / "active" / created["review_id"]

            with self.assertRaises(ValueError):
                archive_review(root, "codex", "   \n")

            self.assertTrue(review_dir.is_dir())
            self.assertFalse((review_dir / "final.md").exists())
            self.assertFalse((root / ".agent_memo" / "archive" / created["review_id"]).exists())

    def test_archive_rejects_thread_that_is_not_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            review_dir = root / ".agent_memo" / "active" / created["review_id"]

            with self.assertRaises(ValueError):
                archive_review(root, "codex", "# Final\n\nNot approved yet.\n")

            self.assertTrue(review_dir.is_dir())
            self.assertFalse((review_dir / "final.md").exists())

    def test_archive_copies_approved_review_clears_state_and_deletes_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            write_response(root, "agy", "approved", "Looks good.")
            rollup_status(root)
            memo = root / ".agent_memo"
            active_dir = memo / "active" / created["review_id"]

            result = archive_review(root, "codex", "# Final\n\nShip it.\n")

            archive_dir = memo / "archive" / created["review_id"]
            archived_status = json.loads((archive_dir / "status.json").read_text(encoding="utf-8"))
            state = json.loads((memo / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "archived")
            self.assertEqual(result["review_id"], created["review_id"])
            self.assertEqual(result["archive_path"], str(archive_dir))
            self.assertTrue((archive_dir / "request.md").is_file())
            self.assertTrue((archive_dir / "status.json").is_file())
            self.assertTrue((archive_dir / "final.md").is_file())
            self.assertTrue((archive_dir / "responses").is_dir())
            self.assertEqual((archive_dir / "final.md").read_text(encoding="utf-8"), "# Final\n\nShip it.\n")
            self.assertEqual(archived_status["status"], "archived")
            self.assertIsNone(state["active_review_id"])
            self.assertFalse(active_dir.exists())

    def test_archive_rejects_owner_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            write_response(root, "agy", "approved", "Looks good.")
            rollup_status(root)

            with self.assertRaises(ValueError):
                archive_review(root, "agy", "# Final\n\nShip it.\n")

    def test_archive_copy_failure_keeps_active_approved_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            write_response(root, "agy", "approved", "Looks good.")
            rollup_status(root)
            memo = root / ".agent_memo"
            active_dir = memo / "active" / created["review_id"]
            archive_dir = memo / "archive" / created["review_id"]
            original_verify_archive_copy = agent_memo.verify_archive_copy

            def fail_verify(path):
                raise RuntimeError("verification failed")

            agent_memo.verify_archive_copy = fail_verify
            try:
                with self.assertRaises(RuntimeError):
                    archive_review(root, "codex", "# Final\n\nShip it.\n")
            finally:
                agent_memo.verify_archive_copy = original_verify_archive_copy

            state = json.loads((memo / "state.json").read_text(encoding="utf-8"))
            active_status = json.loads((active_dir / "status.json").read_text(encoding="utf-8"))
            self.assertTrue(active_dir.is_dir())
            self.assertFalse(archive_dir.exists())
            self.assertEqual(state["active_review_id"], created["review_id"])
            self.assertEqual(active_status["status"], "approved")

            result = archive_review(root, "codex", "# Final\n\nShip it.\n")

            self.assertEqual(result["status"], "archived")
            self.assertTrue((archive_dir / "final.md").is_file())
            self.assertFalse(active_dir.exists())

    def test_check_review_reports_interrupted_archive_when_active_and_archive_copy_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            memo = root / ".agent_memo"
            shutil.copytree(memo / "active" / created["review_id"], memo / "archive" / created["review_id"])

            result = check_review(root, "agy")

            self.assertEqual(result["status"], "archive_interrupted")
            self.assertEqual(result["review_id"], created["review_id"])

    def test_check_review_reports_interrupted_archive_after_state_cleared_before_active_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            memo = root / ".agent_memo"
            shutil.copytree(memo / "active" / created["review_id"], memo / "archive" / created["review_id"])
            state_path = memo / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["active_review_id"] = None
            state_path.write_text(json.dumps(state), encoding="utf-8")

            result = check_review(root, "codex")

            self.assertEqual(result["status"], "archive_interrupted")
            self.assertEqual(result["review_id"], created["review_id"])

    def test_cli_archive_subcommand(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            final_file = root / "final.md"
            final_file.write_text("# Final\n\nShip it.\n", encoding="utf-8")
            init_memo(root)
            created = create_review(root, "codex", "planning", "auth flow", ["agy"], "one")
            write_response(root, "agy", "approved", "Looks good.")
            rollup_status(root)

            archive_out = io.StringIO()
            with contextlib.redirect_stdout(archive_out):
                agent_memo.main(
                    [
                        "archive",
                        "--root",
                        str(root),
                        "--owner",
                        "codex",
                        "--final-file",
                        str(final_file),
                    ]
                )

            result = json.loads(archive_out.getvalue())
            self.assertEqual(result["status"], "archived")
            self.assertEqual(result["review_id"], created["review_id"])
            self.assertTrue((root / ".agent_memo" / "archive" / created["review_id"] / "final.md").is_file())


if __name__ == "__main__":
    unittest.main()
