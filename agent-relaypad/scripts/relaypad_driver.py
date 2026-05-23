#!/usr/bin/env python3
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


VERSION = 1


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
        return {
            "status": "dry_run",
            "driver": driver,
            "command": command,
            "stdin": prompt,
        }

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
