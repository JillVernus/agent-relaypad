import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

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

    def test_resolve_conversation_id_handles_unreadable_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing.json"

            result = relaypad_driver.resolve_conversation_id(root, "agy", agy_cache_path=missing)

            self.assertEqual(result["status"], "error")
            self.assertIn("conversation ID", result["error"])
            self.assertIn("--conversation-id", result["next_step"])

    def test_build_agy_command_uses_conversation_and_no_prompt_argument(self):
        command = relaypad_driver.build_agy_command("conv-1", timeout=300)

        self.assertEqual(command, ["agy", "--print", "--print-timeout", "300s", "--conversation", "conv-1"])

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


if __name__ == "__main__":
    unittest.main()
