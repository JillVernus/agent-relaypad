#!/usr/bin/env python3
import argparse
import json
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


VERSION = 1
DEFAULT_TIMEOUT = 1000
DEFAULT_CC_MODEL = "opus[1m]"
CC_SESSION_WARNING = "Claude JSON output did not contain session_id; runtime metadata was not updated."
SUPPORTED_DRIVERS = {"agy", "cc"}


def utc_now():
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


def load_prompt(prompt=None, prompt_file=None):
    if bool(prompt) == bool(prompt_file):
        raise ValueError("Provide exactly one prompt source: --prompt or --prompt-file")
    if prompt_file:
        return Path(prompt_file).read_text(encoding="utf-8")
    return prompt


def parse_response_headers(path):
    headers = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("Status:"):
            headers["status"] = line.split(":", 1)[1].strip()
        elif line.startswith("Round:"):
            value = line.split(":", 1)[1].strip()
            try:
                headers["round"] = int(value)
            except ValueError:
                headers["round"] = None
        if "status" in headers and "round" in headers:
            break
    return headers


def active_review_context(root):
    root = Path(root)
    state_path = relaypad_dir(root) / "state.json"
    if not state_path.is_file():
        return None
    state = read_json(state_path)
    review_id = state.get("active_review_id")
    if not review_id:
        return None
    review_dir = relaypad_dir(root) / "active" / review_id
    status_path = review_dir / "status.json"
    if not status_path.is_file():
        return None
    return {
        "review_id": review_id,
        "review_dir": review_dir,
        "status": read_json(status_path),
    }


def inspect_reviewer_response(root, reviewer):
    context = active_review_context(root)
    if context is None:
        return {
            "response_exists": False,
            "response_round": None,
            "response_status": None,
        }

    response_path = context["review_dir"] / "responses" / f"{reviewer}.md"
    if not response_path.is_file():
        return {
            "response_exists": False,
            "response_round": None,
            "response_status": None,
        }

    headers = parse_response_headers(response_path)
    response_round = headers.get("round")
    response_status = headers.get("status") if response_round == context["status"].get("round") else None
    if response_status not in {"approved", "changes_requested"}:
        response_status = None
    return {
        "response_exists": True,
        "response_round": response_round,
        "response_status": response_status,
    }


def compute_review_status(root):
    context = active_review_context(root)
    if context is None:
        return None

    required_reviewers = context["status"].get("required_reviewers", [])
    responses = [inspect_reviewer_response(root, reviewer).get("response_status") for reviewer in required_reviewers]
    if any(response == "changes_requested" for response in responses):
        return "changes_requested"
    if required_reviewers and all(response == "approved" for response in responses):
        return "approved"
    return "waiting_for_review"


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
        except (OSError, json.JSONDecodeError):
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


def build_agy_command(conversation_id, timeout):
    return ["agy", "--print", "--print-timeout", f"{int(timeout)}s", "--conversation", conversation_id]


def build_cc_command(conversation_id=None, model=None):
    command = [
        "claude",
        "--print",
        "--output-format",
        "json",
        "--model",
        model or DEFAULT_CC_MODEL,
        "--permission-mode",
        "bypassPermissions",
    ]
    if conversation_id:
        command.extend(["--resume", conversation_id])
    return command


def unsupported_model_result(driver):
    return {
        "status": "unsupported",
        "driver": driver,
        "error": "Agy model override is not supported without a safe per-invocation model flag.",
        "next_step": "Use Agy's configured default model or configure Agy manually before invoking.",
    }


def invoke_agy(root, prompt, conversation_id=None, model=None, timeout=DEFAULT_TIMEOUT, dry_run=False, runner=None):
    if model:
        return unsupported_model_result("agy")

    resolved = resolve_conversation_id(root, "agy", explicit_id=conversation_id)
    if resolved.get("status") != "resolved":
        return resolved

    command = build_agy_command(resolved["conversation_id"], timeout)
    if dry_run:
        return {
            "status": "dry_run",
            "driver": "agy",
            "command": command,
            "stdin": prompt,
        }

    run = runner or subprocess.run
    completed = run(command, input=prompt, text=True, capture_output=True, cwd=str(root), timeout=timeout)
    metadata_path = write_runtime_metadata(
        root,
        "agy",
        {
            "version": VERSION,
            "driver": "agy",
            "conversation_id": resolved["conversation_id"],
            "conversation_source": resolved["conversation_source"],
            "last_invoked_at": utc_now(),
            "last_exit_code": completed.returncode,
        },
    )
    return {
        "status": "invoked",
        "driver": "agy",
        "conversation_id": resolved["conversation_id"],
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "metadata_path": str(metadata_path),
    }


def resolve_optional_cc_conversation_id(root, explicit_id=None):
    resolved = resolve_conversation_id(root, "cc", explicit_id=explicit_id)
    if resolved.get("status") == "resolved":
        return resolved
    return {
        "status": "new_session",
        "conversation_id": None,
        "conversation_source": "new_claude_session",
    }


def parse_cc_session_id(stdout):
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload.get("session_id")


def invoke_cc(root, prompt, conversation_id=None, model=None, timeout=DEFAULT_TIMEOUT, dry_run=False, runner=None):
    resolved = resolve_optional_cc_conversation_id(root, explicit_id=conversation_id)
    requested_model = model or DEFAULT_CC_MODEL
    command = build_cc_command(resolved["conversation_id"], requested_model)

    result = {
        "status": "dry_run" if dry_run else "invoked",
        "driver": "cc",
        "command": command,
        "stdin": prompt,
    }
    if resolved["conversation_id"]:
        result["conversation_id"] = resolved["conversation_id"]

    if dry_run:
        return result

    run = runner or subprocess.run
    completed = run(
        command,
        input=prompt,
        text=True,
        capture_output=True,
        cwd=str(root),
        timeout=timeout,
    )
    session_id = parse_cc_session_id(completed.stdout)
    result = {
        "status": "invoked",
        "driver": "cc",
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }

    metadata_session_id = session_id or resolved["conversation_id"]
    if metadata_session_id:
        metadata_path = write_runtime_metadata(
            root,
            "cc",
            {
                "version": VERSION,
                "driver": "cc",
                "conversation_id": metadata_session_id,
                "conversation_source": "claude_json_result" if session_id else resolved["conversation_source"],
                "last_invoked_at": utc_now(),
                "last_exit_code": completed.returncode,
                "model": requested_model,
            },
        )
        result["conversation_id"] = metadata_session_id
        result["metadata_path"] = str(metadata_path)

    if not session_id:
        result["warning"] = CC_SESSION_WARNING

    return result


def parse_driver_list(text):
    drivers = [driver.strip() for driver in str(text).split(",") if driver.strip()]
    if not drivers:
        raise ValueError("At least one driver is required")
    unsupported = [driver for driver in drivers if driver not in SUPPORTED_DRIVERS]
    if unsupported:
        raise ValueError(f"Unsupported driver: {unsupported[0]}")
    return drivers


def build_driver_invocation(root, driver, timeout=DEFAULT_TIMEOUT, conversation_id=None, model=None):
    root = Path(root)
    if driver == "agy":
        if model:
            return unsupported_model_result("agy")
        resolved = resolve_conversation_id(root, "agy", explicit_id=conversation_id)
        if resolved.get("status") != "resolved":
            return resolved
        return {
            "status": "ready",
            "driver": "agy",
            "command": build_agy_command(resolved["conversation_id"], timeout),
            "conversation_id": resolved["conversation_id"],
            "conversation_source": resolved["conversation_source"],
        }
    if driver == "cc":
        resolved = resolve_optional_cc_conversation_id(root, explicit_id=conversation_id)
        requested_model = model or DEFAULT_CC_MODEL
        return {
            "status": "ready",
            "driver": "cc",
            "command": build_cc_command(resolved["conversation_id"], requested_model),
            "conversation_id": resolved["conversation_id"],
            "conversation_source": resolved["conversation_source"],
            "model": requested_model,
        }
    return {"status": "error", "driver": driver, "error": f"Unsupported driver: {driver}"}


def drain_stream(stream, chunks):
    if stream is None:
        return
    data = stream.read()
    if data:
        chunks.append(data)


def deliver_prompt(process, prompt):
    if process.stdin is None:
        return
    process.stdin.write(prompt)
    process.stdin.flush()
    process.stdin.close()


def terminate_process(process):
    try:
        process.terminate()
    except Exception:
        return
    try:
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def persist_completed_metadata(root, invocation, stdout, exit_code):
    driver = invocation["driver"]
    if driver == "agy":
        return write_runtime_metadata(
            root,
            "agy",
            {
                "version": VERSION,
                "driver": "agy",
                "conversation_id": invocation["conversation_id"],
                "conversation_source": invocation["conversation_source"],
                "last_invoked_at": utc_now(),
                "last_exit_code": exit_code,
            },
        )

    session_id = parse_cc_session_id(stdout)
    metadata_session_id = session_id or invocation.get("conversation_id")
    if not metadata_session_id:
        return None
    return write_runtime_metadata(
        root,
        "cc",
        {
            "version": VERSION,
            "driver": "cc",
            "conversation_id": metadata_session_id,
            "conversation_source": "claude_json_result" if session_id else invocation["conversation_source"],
            "last_invoked_at": utc_now(),
            "last_exit_code": exit_code,
            "model": invocation["model"],
        },
    )


def invoke_many(
    root,
    drivers,
    prompt,
    timeout=DEFAULT_TIMEOUT,
    conversation_ids=None,
    model=None,
    launcher=None,
):
    root = Path(root)
    launcher = launcher or subprocess.Popen
    conversation_ids = conversation_ids or {}

    try:
        drivers = parse_driver_list(",".join(drivers) if isinstance(drivers, (list, tuple)) else drivers)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}

    invocations = []
    for driver in drivers:
        invocation = build_driver_invocation(
            root,
            driver,
            timeout=timeout,
            conversation_id=conversation_ids.get(driver),
            model=model if driver == "cc" else None,
        )
        if invocation.get("status") != "ready":
            return invocation
        invocations.append(invocation)

    entries = []
    for invocation in invocations:
        process = launcher(
            invocation["command"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(root),
        )
        entries.append(
            {
                "driver": invocation["driver"],
                "invocation": invocation,
                "process": process,
                "stdout_chunks": [],
                "stderr_chunks": [],
                "status": None,
                "exit_code": None,
                "started_at": time.monotonic(),
                "finished_at": None,
            }
        )

    for entry in entries:
        deliver_prompt(entry["process"], prompt)

    reader_threads = []
    for entry in entries:
        for stream_name, chunks_name in (("stdout", "stdout_chunks"), ("stderr", "stderr_chunks")):
            thread = threading.Thread(
                target=drain_stream,
                args=(getattr(entry["process"], stream_name), entry[chunks_name]),
                daemon=True,
            )
            thread.start()
            reader_threads.append(thread)

    def wait_for_entry(entry):
        try:
            entry["exit_code"] = entry["process"].wait(timeout=timeout)
            entry["status"] = "completed"
        except subprocess.TimeoutExpired:
            terminate_process(entry["process"])
            entry["status"] = "timed_out"
        entry["finished_at"] = time.monotonic()

    wait_threads = []
    for entry in entries:
        thread = threading.Thread(target=wait_for_entry, args=(entry,), daemon=True)
        thread.start()
        wait_threads.append(thread)

    for thread in wait_threads:
        thread.join(timeout + 10)
    for thread in reader_threads:
        thread.join(5)

    results = {}
    for entry in entries:
        stdout = "".join(entry["stdout_chunks"])
        stderr = "".join(entry["stderr_chunks"])
        elapsed = entry["finished_at"] - entry["started_at"] if entry["finished_at"] else timeout
        result = {
            "status": entry["status"] or "timed_out",
            "command": entry["invocation"]["command"],
            "elapsed_seconds": round(elapsed, 3),
            "stdout": stdout,
            "stderr": stderr,
            **inspect_reviewer_response(root, entry["driver"]),
        }
        if entry["exit_code"] is not None:
            result["exit_code"] = entry["exit_code"]
        if entry["status"] == "completed":
            metadata_path = persist_completed_metadata(root, entry["invocation"], stdout, entry["exit_code"])
            if metadata_path is not None:
                result["metadata_path"] = str(metadata_path)
            if entry["driver"] == "cc":
                session_id = parse_cc_session_id(stdout)
                metadata_session_id = session_id or entry["invocation"].get("conversation_id")
                if metadata_session_id:
                    result["conversation_id"] = metadata_session_id
                if not session_id:
                    result["warning"] = CC_SESSION_WARNING
        results[entry["driver"]] = result

    overall_status = "timed_out" if any(result["status"] == "timed_out" for result in results.values()) else "completed"
    return {
        "status": overall_status,
        "timeout": timeout,
        "results": results,
        "review_status": compute_review_status(root),
    }


def invoke_driver(root, driver, prompt, conversation_id=None, model=None, timeout=DEFAULT_TIMEOUT, dry_run=False, runner=None):
    root = Path(root)
    if driver == "agy":
        return invoke_agy(
            root=root,
            prompt=prompt,
            conversation_id=conversation_id,
            model=model,
            timeout=timeout,
            dry_run=dry_run,
            runner=runner,
        )
    if driver == "cc":
        return invoke_cc(
            root=root,
            prompt=prompt,
            conversation_id=conversation_id,
            model=model,
            timeout=timeout,
            dry_run=dry_run,
            runner=runner,
        )
    else:
        return {"status": "error", "driver": driver, "error": f"Unsupported driver: {driver}"}


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p_invoke = sub.add_parser("invoke")
    p_invoke.add_argument("--root", default=".")
    p_invoke.add_argument("--driver", required=True)
    p_invoke.add_argument("--prompt")
    p_invoke.add_argument("--prompt-file")
    p_invoke.add_argument("--conversation-id")
    p_invoke.add_argument("--model")
    p_invoke.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p_invoke.add_argument("--dry-run", action="store_true")
    p_many = sub.add_parser("invoke-many")
    p_many.add_argument("--root", default=".")
    p_many.add_argument("--drivers", required=True)
    p_many.add_argument("--prompt")
    p_many.add_argument("--prompt-file")
    p_many.add_argument("--model")
    p_many.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)
    try:
        if args.command == "invoke":
            prompt = load_prompt(args.prompt, args.prompt_file)
            result = invoke_driver(
                root=Path(args.root),
                driver=args.driver,
                prompt=prompt,
                conversation_id=args.conversation_id,
                model=args.model,
                timeout=args.timeout,
                dry_run=args.dry_run,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result.get("status") in {"dry_run", "invoked"} else 1
        if args.command == "invoke-many":
            prompt = load_prompt(args.prompt, args.prompt_file)
            result = invoke_many(
                root=Path(args.root),
                drivers=parse_driver_list(args.drivers),
                prompt=prompt,
                timeout=args.timeout,
                model=args.model,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result.get("status") == "completed" else 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
