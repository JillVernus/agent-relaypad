import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import relaypad_driver


class RelaypadDriverTests(unittest.TestCase):
    def write_active_review(self, root, round_number=1, reviewers=("agy", "cc"), stored_status="waiting_for_review"):
        review_id = "2026-05-23-plan-driver-test"
        review_dir = root / ".agent-relaypad" / "active" / review_id
        (review_dir / "responses").mkdir(parents=True)
        relaypad_driver.write_json(
            root / ".agent-relaypad" / "state.json",
            {"version": 1, "active_review_id": review_id, "updated_at": "2026-05-23T00:00:00Z"},
        )
        relaypad_driver.write_json(
            review_dir / "status.json",
            {
                "version": 1,
                "review_id": review_id,
                "owner": "codex",
                "phase": "planning",
                "topic": "driver test",
                "required_reviewers": list(reviewers),
                "round": round_number,
                "status": stored_status,
                "created_at": "2026-05-23T00:00:00Z",
                "updated_at": "2026-05-23T00:00:00Z",
            },
        )
        return review_dir

    def write_response(self, review_dir, agent, status, round_number):
        response_path = review_dir / "responses" / f"{agent}.md"
        response_path.write_text(
            f"Status: {status}\nRound: {round_number}\nReviewed at: 2026-05-23T00:00:01Z\n\nBody\n",
            encoding="utf-8",
        )
        return response_path

    def write_agy_metadata(self, root, conversation_id="conv-1"):
        relaypad_driver.write_runtime_metadata(
            root,
            "agy",
            {"version": 1, "driver": "agy", "conversation_id": conversation_id},
        )

    def fake_process_factory(self, events, stdout="", stderr="", wait_result=0, should_timeout=False):
        class FakeStdin:
            def __init__(self, driver):
                self.driver = driver

            def write(self, text):
                events.append(f"{self.driver}:stdin:{text}")

            def flush(self):
                events.append(f"{self.driver}:stdin:flush")

            def close(self):
                events.append(f"{self.driver}:stdin:close")

        class FakeStream:
            def __init__(self, driver, name, text):
                self.driver = driver
                self.name = name
                self.text = text
                self.read_called = False

            def read(self):
                self.read_called = True
                events.append(f"{self.driver}:{self.name}:read")
                return self.text

        class FakeProcess:
            def __init__(self, driver):
                self.driver = driver
                self.stdin = FakeStdin(driver)
                self.stdout = FakeStream(driver, "stdout", stdout)
                self.stderr = FakeStream(driver, "stderr", stderr)
                self.returncode = None
                self.terminated = False
                self.killed = False

            def wait(self, timeout=None):
                events.append(f"{self.driver}:wait")
                if timeout:
                    events.append(f"{self.driver}:timeout:{timeout}")
                if self.stdout.read_called and self.stderr.read_called:
                    events.append(f"{self.driver}:drained-before-wait-return")
                if should_timeout:
                    raise subprocess.TimeoutExpired(cmd=[self.driver], timeout=timeout)
                self.returncode = wait_result
                return wait_result

            def terminate(self):
                self.terminated = True
                events.append(f"{self.driver}:terminate")

            def kill(self):
                self.killed = True
                events.append(f"{self.driver}:kill")

        return FakeProcess

    def driver_from_command(self, command):
        if command[0] == "agy":
            return "agy"
        if command[0] == "claude":
            return "cc"
        return command[0]

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
            cache.write_text(json.dumps({str(root.resolve()): "cache-1"}), encoding="utf-8")

            result = relaypad_driver.resolve_conversation_id(root, "agy", agy_cache_path=cache)

            self.assertEqual(result["conversation_id"], "cache-1")
            self.assertEqual(result["conversation_source"], "antigravity_last_conversations")

    def test_resolve_conversation_id_starts_new_agy_session_when_cache_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing.json"

            result = relaypad_driver.resolve_conversation_id(root, "agy", agy_cache_path=missing)

            self.assertEqual(result["status"], "new_session")
            self.assertIsNone(result["conversation_id"])
            self.assertEqual(result["conversation_source"], "new_agy_session")

    def test_build_agy_command_uses_conversation_and_no_prompt_argument(self):
        command = relaypad_driver.build_agy_command("conv-1", timeout=300)

        self.assertEqual(command, ["agy", "--print", "--print-timeout", "300s", "--conversation", "conv-1"])

    def test_build_agy_command_omits_conversation_for_new_session(self):
        command = relaypad_driver.build_agy_command(None, timeout=300)

        self.assertEqual(command, ["agy", "--print", "--print-timeout", "300s"])

    def test_invoke_default_timeout_is_1000_for_agy_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = relaypad_driver.invoke_driver(
                root=Path(tmp),
                driver="agy",
                prompt="hello",
                conversation_id="conv-1",
                dry_run=True,
            )

            self.assertIn("1000s", result["command"])

    def test_build_cc_command_uses_exact_default_1m_model_without_resume_for_new_session(self):
        command = relaypad_driver.build_cc_command(conversation_id=None, model=None)

        self.assertEqual(
            command,
            [
                "claude",
                "--print",
                "--output-format",
                "json",
                "--model",
                "opus[1m]",
                "--permission-mode",
                "bypassPermissions",
            ],
        )

    def test_build_cc_command_uses_resume_when_conversation_exists(self):
        command = relaypad_driver.build_cc_command(conversation_id="session-1", model=None)

        self.assertEqual(command[-2:], ["--resume", "session-1"])
        self.assertIn("opus[1m]", command)

    def test_build_cc_command_allows_model_override(self):
        command = relaypad_driver.build_cc_command(conversation_id=None, model="sonnet[1m]")

        self.assertIn("sonnet[1m]", command)
        self.assertNotIn("opus[1m]", command)

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

    def test_agy_dry_run_starts_new_session_without_conversation_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = relaypad_driver.invoke_driver(
                root=Path(tmp),
                driver="agy",
                prompt="hello",
                dry_run=True,
            )

            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(result["driver"], "agy")
            self.assertNotIn("--conversation", result["command"])
            self.assertEqual(result["stdin"], "hello")

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

    def test_load_prompt_reads_prompt_file_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt_path = Path(tmp) / "prompt.txt"
            prompt_path.write_text("review prompt", encoding="utf-8")

            prompt = relaypad_driver.load_prompt(prompt=None, prompt_file=prompt_path)

            self.assertEqual(prompt, "review prompt")

    def test_load_prompt_rejects_missing_prompt_and_prompt_file(self):
        with self.assertRaises(ValueError):
            relaypad_driver.load_prompt(prompt=None, prompt_file=None)

    def test_load_prompt_rejects_prompt_and_prompt_file_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt_path = Path(tmp) / "prompt.txt"
            prompt_path.write_text("review prompt", encoding="utf-8")

            with self.assertRaises(ValueError):
                relaypad_driver.load_prompt(prompt="hello", prompt_file=prompt_path)

    def test_inspect_reviewer_response_reports_current_round_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_dir = self.write_active_review(root, round_number=2, reviewers=("agy",))
            self.write_response(review_dir, "agy", "approved", 2)

            result = relaypad_driver.inspect_reviewer_response(root, "agy")

            self.assertTrue(result["response_exists"])
            self.assertEqual(result["response_status"], "approved")
            self.assertEqual(result["response_round"], 2)

    def test_inspect_reviewer_response_ignores_prior_round_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_dir = self.write_active_review(root, round_number=2, reviewers=("agy",))
            self.write_response(review_dir, "agy", "approved", 1)

            result = relaypad_driver.inspect_reviewer_response(root, "agy")

            self.assertTrue(result["response_exists"])
            self.assertIsNone(result["response_status"])
            self.assertEqual(result["response_round"], 1)

    def test_compute_review_status_from_response_headers_reports_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_dir = self.write_active_review(root, round_number=1, stored_status="waiting_for_review")
            self.write_response(review_dir, "agy", "approved", 1)
            self.write_response(review_dir, "cc", "approved", 1)

            self.assertEqual(relaypad_driver.compute_review_status(root), "approved")

    def test_compute_review_status_from_response_headers_reports_changes_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_dir = self.write_active_review(root, round_number=1)
            self.write_response(review_dir, "agy", "changes_requested", 1)
            self.write_response(review_dir, "cc", "approved", 1)

            self.assertEqual(relaypad_driver.compute_review_status(root), "changes_requested")

    def test_compute_review_status_from_response_headers_reports_waiting_for_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_dir = self.write_active_review(root, round_number=2)
            self.write_response(review_dir, "agy", "approved", 2)
            self.write_response(review_dir, "cc", "approved", 1)

            self.assertEqual(relaypad_driver.compute_review_status(root), "waiting_for_review")

    def test_build_driver_prompt_includes_absolute_relaypad_paths_for_active_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_dir = self.write_active_review(root, round_number=2, reviewers=("agy",))

            prompt = relaypad_driver.build_driver_prompt(root, "agy", "review please")

            self.assertIn(f"Project root: {root.resolve()}", prompt)
            self.assertIn(f"Review directory: {review_dir.resolve()}", prompt)
            self.assertIn(f"Response file: {(review_dir / 'responses' / 'agy.md').resolve()}", prompt)
            self.assertIn("Do not create or use .agent-relaypad in a scratch workspace", prompt)
            self.assertTrue(prompt.endswith("review please"))

    def test_build_driver_prompt_leaves_prompt_plain_without_active_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt = relaypad_driver.build_driver_prompt(Path(tmp), "agy", "review please")

            self.assertEqual(prompt, "review please")

    def test_invoke_many_starts_all_drivers_before_waiting(self):
        events = []
        FakeProcess = self.fake_process_factory(events)

        def launcher(command, **kwargs):
            driver = self.driver_from_command(command)
            events.append(f"{driver}:launch")
            return FakeProcess(driver)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_agy_metadata(root)

            result = relaypad_driver.invoke_many(root=root, drivers=["agy", "cc"], prompt="review", launcher=launcher)

            self.assertEqual(result["status"], "completed")
            first_wait = min(index for index, event in enumerate(events) if event.endswith(":wait"))
            self.assertLess(events.index("agy:launch"), first_wait)
            self.assertLess(events.index("cc:launch"), first_wait)

    def test_invoke_many_sends_prompt_to_all_drivers_before_blocking_wait(self):
        events = []
        FakeProcess = self.fake_process_factory(events)

        def launcher(command, **kwargs):
            return FakeProcess(self.driver_from_command(command))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_agy_metadata(root)

            relaypad_driver.invoke_many(root=root, drivers=["agy", "cc"], prompt="review", launcher=launcher)

            first_wait = min(index for index, event in enumerate(events) if event.endswith(":wait"))
            self.assertLess(events.index("agy:stdin:review"), first_wait)
            self.assertLess(events.index("cc:stdin:review"), first_wait)

    def test_invoke_many_drains_stdout_and_stderr_while_waiting(self):
        events = []
        FakeProcess = self.fake_process_factory(events, stdout="out", stderr="err")

        def launcher(command, **kwargs):
            return FakeProcess(self.driver_from_command(command))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_agy_metadata(root)

            relaypad_driver.invoke_many(root=root, drivers=["agy"], prompt="review", launcher=launcher)

            self.assertIn("agy:stdout:read", events)
            self.assertIn("agy:stderr:read", events)
            self.assertIn("agy:drained-before-wait-return", events)

    def test_invoke_many_reports_mixed_speed_completion(self):
        events = []

        def launcher(command, **kwargs):
            driver = self.driver_from_command(command)
            stdout = json.dumps({"session_id": "cc-session"}) if driver == "cc" else "agy ok"
            return self.fake_process_factory(events, stdout=stdout)(driver)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_dir = self.write_active_review(root)
            self.write_agy_metadata(root)
            self.write_response(review_dir, "agy", "approved", 1)
            self.write_response(review_dir, "cc", "approved", 1)

            result = relaypad_driver.invoke_many(root=root, drivers=["agy", "cc"], prompt="review", launcher=launcher)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["results"]["agy"]["status"], "completed")
            self.assertEqual(result["results"]["cc"]["status"], "completed")
            self.assertEqual(result["review_status"], "approved")

    def test_invoke_many_does_not_cancel_after_changes_requested(self):
        events = []
        FakeProcess = self.fake_process_factory(events, stdout=json.dumps({"session_id": "cc-session"}))

        def launcher(command, **kwargs):
            return FakeProcess(self.driver_from_command(command))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_dir = self.write_active_review(root)
            self.write_agy_metadata(root)
            self.write_response(review_dir, "agy", "changes_requested", 1)
            self.write_response(review_dir, "cc", "approved", 1)

            result = relaypad_driver.invoke_many(root=root, drivers=["agy", "cc"], prompt="review", launcher=launcher)

            self.assertEqual(result["status"], "completed")
            self.assertIn("cc:wait", events)
            self.assertEqual(result["review_status"], "changes_requested")

    def test_invoke_many_reports_timeout_without_archiving_or_deleting_active_review(self):
        events = []
        FakeProcess = self.fake_process_factory(events, should_timeout=True)

        def launcher(command, **kwargs):
            return FakeProcess(self.driver_from_command(command))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_dir = self.write_active_review(root)
            self.write_agy_metadata(root)

            result = relaypad_driver.invoke_many(root=root, drivers=["agy"], prompt="review", timeout=1, launcher=launcher)

            self.assertEqual(result["status"], "timed_out")
            self.assertEqual(result["results"]["agy"]["status"], "timed_out")
            self.assertTrue(review_dir.is_dir())

    def test_invoke_many_rejects_unsupported_driver_before_launching_anything(self):
        calls = []

        def launcher(command, **kwargs):
            calls.append(command)

        with tempfile.TemporaryDirectory() as tmp:
            result = relaypad_driver.invoke_many(
                root=Path(tmp),
                drivers=["agy", "unknown"],
                prompt="review",
                launcher=launcher,
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(calls, [])

    def test_invoke_many_persists_agy_runtime_metadata_after_completion(self):
        events = []
        FakeProcess = self.fake_process_factory(events)

        def launcher(command, **kwargs):
            return FakeProcess(self.driver_from_command(command))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = relaypad_driver.invoke_many(
                root=root,
                drivers=["agy"],
                prompt="review",
                conversation_ids={"agy": "conv-1"},
                launcher=launcher,
            )

            metadata = json.loads((root / ".agent-relaypad" / "runtimes" / "agy.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(metadata["conversation_id"], "conv-1")
            self.assertEqual(metadata["last_exit_code"], 0)

    def test_invoke_many_starts_new_agy_session_without_conversation_id(self):
        events = []
        launched_commands = []
        FakeProcess = self.fake_process_factory(events)

        def launcher(command, **kwargs):
            launched_commands.append(command)
            return FakeProcess(self.driver_from_command(command))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = relaypad_driver.invoke_many(root=root, drivers=["agy"], prompt="review", launcher=launcher)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(launched_commands[0], ["agy", "--print", "--print-timeout", "1000s"])
            self.assertFalse((root / ".agent-relaypad" / "runtimes" / "agy.json").exists())

    def test_invoke_many_persists_cc_session_id_metadata_after_completion(self):
        events = []
        FakeProcess = self.fake_process_factory(events, stdout=json.dumps({"session_id": "new-session"}))

        def launcher(command, **kwargs):
            return FakeProcess(self.driver_from_command(command))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = relaypad_driver.invoke_many(root=root, drivers=["cc"], prompt="review", launcher=launcher)

            metadata = json.loads((root / ".agent-relaypad" / "runtimes" / "cc.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(metadata["conversation_id"], "new-session")
            self.assertEqual(metadata["model"], "opus[1m]")

    def test_invoke_many_persists_codex_thread_id_metadata_after_completion(self):
        events = []
        codex_stdout = (
            '{"type":"thread.started","thread_id":"thread-from-many"}\n'
            '{"type":"item.completed"}\n'
        )
        FakeProcess = self.fake_process_factory(events, stdout=codex_stdout)

        def launcher(command, **kwargs):
            return FakeProcess(self.driver_from_command(command))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = relaypad_driver.invoke_many(
                root=root, drivers=["codex"], prompt="review", launcher=launcher
            )

            metadata = json.loads(
                (root / ".agent-relaypad" / "runtimes" / "codex.json").read_text(encoding="utf-8")
            )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(metadata["conversation_id"], "thread-from-many")
            self.assertEqual(metadata["driver"], "codex")
            self.assertEqual(metadata["conversation_source"], "codex_thread_started")
            self.assertEqual(result["results"]["codex"]["conversation_id"], "thread-from-many")
            self.assertNotIn("warning", result["results"]["codex"])

    def test_invoke_many_propagates_model_to_codex_driver(self):
        events = []
        stdouts = {
            "cc": json.dumps({"session_id": "cc-session"}),
            "codex": '{"type":"thread.started","thread_id":"codex-thread"}\n',
        }
        launched_commands = []

        def launcher(command, **kwargs):
            driver = self.driver_from_command(command)
            launched_commands.append((driver, command))
            return self.fake_process_factory(events, stdout=stdouts.get(driver, ""))(driver)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = relaypad_driver.invoke_many(
                root=root,
                drivers=["cc", "codex"],
                prompt="review",
                model="gpt-5",
                launcher=launcher,
            )

            self.assertEqual(result["status"], "completed")
            commands_by_driver = {driver: command for driver, command in launched_commands}
            self.assertIn("-m", commands_by_driver["codex"])
            self.assertIn("gpt-5", commands_by_driver["codex"])
            self.assertIn("--model", commands_by_driver["cc"])
            self.assertIn("gpt-5", commands_by_driver["cc"])
            codex_metadata = json.loads(
                (root / ".agent-relaypad" / "runtimes" / "codex.json").read_text(encoding="utf-8")
            )
            self.assertEqual(codex_metadata["model"], "gpt-5")

    def test_cli_rejects_missing_prompt_and_prompt_file(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = relaypad_driver.main(
                [
                    "invoke",
                    "--root",
                    ".",
                    "--driver",
                    "cc",
                ]
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(result, 1)
        self.assertEqual(payload["status"], "error")
        self.assertIn("prompt", payload["error"])

    def test_cli_rejects_prompt_and_prompt_file_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt_path = Path(tmp) / "prompt.txt"
            prompt_path.write_text("review prompt", encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                result = relaypad_driver.main(
                    [
                        "invoke",
                        "--root",
                        tmp,
                        "--driver",
                        "cc",
                        "--prompt",
                        "hello",
                        "--prompt-file",
                        str(prompt_path),
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(result, 1)
            self.assertEqual(payload["status"], "error")
            self.assertIn("one prompt source", payload["error"])

    def test_cc_dry_run_starts_new_session_without_conversation_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = relaypad_driver.invoke_driver(
                root=Path(tmp),
                driver="cc",
                prompt="hello",
                dry_run=True,
            )

            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(result["driver"], "cc")
            self.assertNotIn("--resume", result["command"])
            self.assertIn("opus[1m]", result["command"])
            self.assertEqual(result["stdin"], "hello")

    def test_cc_dry_run_uses_stored_session_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            relaypad_driver.write_runtime_metadata(
                root,
                "cc",
                {"version": 1, "driver": "cc", "conversation_id": "stored-session"},
            )

            result = relaypad_driver.invoke_driver(root=root, driver="cc", prompt="hello", dry_run=True)

            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(result["conversation_id"], "stored-session")
            self.assertEqual(result["command"][-2:], ["--resume", "stored-session"])

    def test_cc_invoke_passes_timeout_to_runner_and_writes_session_id_metadata(self):
        class Completed:
            returncode = 0
            stdout = json.dumps({"session_id": "new-session", "result": "ok"})
            stderr = ""

        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return Completed()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = relaypad_driver.invoke_driver(
                root=root,
                driver="cc",
                prompt="review please",
                timeout=42,
                runner=runner,
            )

            self.assertEqual(result["status"], "invoked")
            self.assertEqual(result["conversation_id"], "new-session")
            self.assertEqual(calls[0][1]["timeout"], 42)
            metadata = json.loads((root / ".agent-relaypad" / "runtimes" / "cc.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["conversation_id"], "new-session")
            self.assertEqual(metadata["model"], "opus[1m]")

    def test_cc_invalid_json_stdout_warns_and_does_not_write_new_metadata_without_session(self):
        class Completed:
            returncode = 0
            stdout = "not json"
            stderr = ""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = relaypad_driver.invoke_driver(
                root=root,
                driver="cc",
                prompt="review please",
                runner=lambda *args, **kwargs: Completed(),
            )

            self.assertEqual(result["status"], "invoked")
            self.assertIn("warning", result)
            self.assertFalse((root / ".agent-relaypad" / "runtimes" / "cc.json").exists())

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

    def test_agy_invoke_passes_process_timeout_to_runner(self):
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
            self.assertIn("1000s", calls[0][0])
            self.assertEqual(calls[0][1]["timeout"], 1000)

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

    def test_cli_invoke_many_outputs_json_from_prompt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt_path = root / "prompt.txt"
            prompt_path.write_text("review prompt", encoding="utf-8")
            calls = []

            def fake_invoke_many(**kwargs):
                calls.append(kwargs)
                return {
                    "status": "completed",
                    "timeout": kwargs["timeout"],
                    "results": {
                        "agy": {"status": "completed"},
                        "cc": {"status": "completed"},
                    },
                    "review_status": "approved",
                }

            original = relaypad_driver.invoke_many
            relaypad_driver.invoke_many = fake_invoke_many
            try:
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    result = relaypad_driver.main(
                        [
                            "invoke-many",
                            "--root",
                            str(root),
                            "--drivers",
                            "agy,cc",
                            "--prompt-file",
                            str(prompt_path),
                            "--timeout",
                            "1000",
                        ]
                    )
            finally:
                relaypad_driver.invoke_many = original

            payload = json.loads(stdout.getvalue())
            self.assertEqual(result, 0)
            self.assertEqual(calls[0]["prompt"], "review prompt")
            self.assertEqual(calls[0]["drivers"], ["agy", "cc"])
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["review_status"], "approved")
            self.assertIn("agy", payload["results"])
            self.assertIn("cc", payload["results"])

    def test_cli_invoke_many_returns_error_for_timeout(self):
        def fake_invoke_many(**kwargs):
            return {"status": "timed_out", "timeout": kwargs["timeout"], "results": {}, "review_status": None}

        original = relaypad_driver.invoke_many
        relaypad_driver.invoke_many = fake_invoke_many
        try:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = relaypad_driver.main(
                    [
                        "invoke-many",
                        "--root",
                        ".",
                        "--drivers",
                        "cc",
                        "--prompt",
                        "review",
                    ]
                )
        finally:
            relaypad_driver.invoke_many = original

        payload = json.loads(stdout.getvalue())
        self.assertEqual(result, 1)
        self.assertEqual(payload["status"], "timed_out")

    def test_parse_codex_thread_id_returns_thread_id_from_thread_started_event(self):
        stdout = (
            '{"type":"thread.started","thread_id":"019e5867-189e-7e40-b512-ae1ffb3aa304"}\n'
            '{"type":"turn.started"}\n'
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"ok"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":10}}\n'
        )

        thread_id = relaypad_driver.parse_codex_thread_id(stdout)

        self.assertEqual(thread_id, "019e5867-189e-7e40-b512-ae1ffb3aa304")

    def test_parse_codex_thread_id_returns_none_when_no_thread_started_event(self):
        stdout = (
            '{"type":"turn.started"}\n'
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"ok"}}\n'
        )

        self.assertIsNone(relaypad_driver.parse_codex_thread_id(stdout))

    def test_parse_codex_thread_id_skips_malformed_lines(self):
        stdout = (
            "not json line\n"
            "null\n"
            '{"type":"thread.started","thread_id":"abc-123"}\n'
            "another bad line\n"
        )

        self.assertEqual(relaypad_driver.parse_codex_thread_id(stdout), "abc-123")

    def test_parse_codex_thread_id_returns_none_for_empty_stdout(self):
        self.assertIsNone(relaypad_driver.parse_codex_thread_id(""))

    def test_build_codex_command_uses_exec_json_for_new_session(self):
        command = relaypad_driver.build_codex_command(thread_id=None, model=None)

        self.assertEqual(
            command,
            ["codex", "exec", "--json", "--skip-git-repo-check", "-s", "workspace-write", "-"],
        )

    def test_build_codex_command_uses_exec_resume_when_thread_id_exists(self):
        command = relaypad_driver.build_codex_command(thread_id="thread-1", model=None)

        self.assertEqual(
            command,
            [
                "codex",
                "exec",
                "resume",
                "thread-1",
                "--json",
                "--skip-git-repo-check",
                "-s",
                "workspace-write",
                "-",
            ],
        )

    def test_build_codex_command_includes_model_when_provided(self):
        command = relaypad_driver.build_codex_command(thread_id=None, model="gpt-5")

        self.assertIn("-m", command)
        self.assertIn("gpt-5", command)
        self.assertEqual(command[-1], "-")

    def test_parse_driver_list_accepts_codex_alone_and_in_mix(self):
        self.assertEqual(relaypad_driver.parse_driver_list("codex"), ["codex"])
        self.assertEqual(
            relaypad_driver.parse_driver_list("codex,cc,agy"),
            ["codex", "cc", "agy"],
        )

    def test_codex_dry_run_starts_new_session_without_thread_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = relaypad_driver.invoke_driver(
                root=Path(tmp),
                driver="codex",
                prompt="hello",
                dry_run=True,
            )

            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(result["driver"], "codex")
            self.assertNotIn("resume", result["command"])
            self.assertEqual(result["stdin"], "hello")
            self.assertEqual(result["command"][-1], "-")

    def test_codex_dry_run_uses_stored_thread_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            relaypad_driver.write_runtime_metadata(
                root,
                "codex",
                {"version": 1, "driver": "codex", "conversation_id": "stored-thread"},
            )

            result = relaypad_driver.invoke_driver(
                root=root, driver="codex", prompt="hello", dry_run=True
            )

            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(result["conversation_id"], "stored-thread")
            self.assertIn("resume", result["command"])
            self.assertIn("stored-thread", result["command"])

    def test_codex_dry_run_includes_model_flag_when_provided(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = relaypad_driver.invoke_driver(
                root=Path(tmp),
                driver="codex",
                prompt="hello",
                model="gpt-5",
                dry_run=True,
            )

            self.assertEqual(result["status"], "dry_run")
            self.assertIn("-m", result["command"])
            self.assertIn("gpt-5", result["command"])

    def test_codex_invoke_writes_thread_id_metadata_from_jsonl(self):
        class Completed:
            returncode = 0
            stdout = (
                '{"type":"thread.started","thread_id":"new-thread-7"}\n'
                '{"type":"item.completed"}\n'
            )
            stderr = ""

        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return Completed()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = relaypad_driver.invoke_driver(
                root=root,
                driver="codex",
                prompt="review please",
                timeout=42,
                runner=runner,
            )

            self.assertEqual(result["status"], "invoked")
            self.assertEqual(result["conversation_id"], "new-thread-7")
            self.assertEqual(calls[0][1]["timeout"], 42)
            metadata = json.loads(
                (root / ".agent-relaypad" / "runtimes" / "codex.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["conversation_id"], "new-thread-7")
            self.assertEqual(metadata["driver"], "codex")
            self.assertEqual(metadata["conversation_source"], "codex_thread_started")
            self.assertNotIn("model", metadata)
            self.assertNotIn("warning", result)

    def test_codex_invoke_warns_when_thread_started_missing_and_skips_metadata(self):
        class Completed:
            returncode = 0
            stdout = '{"type":"item.completed"}\n'
            stderr = ""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = relaypad_driver.invoke_driver(
                root=root,
                driver="codex",
                prompt="review please",
                runner=lambda *args, **kwargs: Completed(),
            )

            self.assertEqual(result["status"], "invoked")
            self.assertIn("warning", result)
            self.assertEqual(result["warning"], relaypad_driver.CODEX_THREAD_WARNING)
            self.assertFalse((root / ".agent-relaypad" / "runtimes" / "codex.json").exists())

    def test_codex_invoke_persists_model_when_provided(self):
        class Completed:
            returncode = 0
            stdout = '{"type":"thread.started","thread_id":"thread-with-model"}\n'
            stderr = ""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = relaypad_driver.invoke_driver(
                root=root,
                driver="codex",
                prompt="review please",
                model="gpt-5",
                runner=lambda *args, **kwargs: Completed(),
            )

            self.assertEqual(result["status"], "invoked")
            metadata = json.loads(
                (root / ".agent-relaypad" / "runtimes" / "codex.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["model"], "gpt-5")

    def test_codex_invoke_passes_prompt_to_runner_stdin(self):
        class Completed:
            returncode = 0
            stdout = '{"type":"thread.started","thread_id":"t-abc"}\n'
            stderr = ""

        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return Completed()

        with tempfile.TemporaryDirectory() as tmp:
            relaypad_driver.invoke_driver(
                root=Path(tmp),
                driver="codex",
                prompt="please review",
                runner=runner,
            )

            self.assertEqual(calls[0][1]["input"], "please review")
            self.assertEqual(calls[0][0][-1], "-")


if __name__ == "__main__":
    unittest.main()
