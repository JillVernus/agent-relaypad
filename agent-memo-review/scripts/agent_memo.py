#!/usr/bin/env python3
import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


VERSION = 1
AGENT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
REVIEW_ID_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}-(plan|impl)-[a-z0-9][a-z0-9-]*")


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def memo_dir(root):
    return Path(root) / ".agent_memo"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_agent_id(agent):
    if not isinstance(agent, str) or not AGENT_ID_PATTERN.fullmatch(agent):
        raise ValueError(f"Invalid agent id: {agent!r}")
    return agent


def validate_review_id(review_id):
    if not isinstance(review_id, str) or not REVIEW_ID_PATTERN.fullmatch(review_id):
        raise ValueError(f"Invalid active review id: {review_id!r}")
    return review_id


def read_json_or_error(path):
    try:
        return read_json(path), None
    except json.JSONDecodeError:
        return None, {"status": "invalid_json", "path": str(path)}


def slug_text(text):
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return slug or "review"


def phase_token(phase):
    tokens = {
        "planning": "plan",
        "implementation_review": "impl",
    }
    if phase not in tokens:
        raise ValueError(f"Unsupported phase: {phase}")
    return tokens[phase]


def active_review_dirs(root):
    active = memo_dir(root) / "active"
    if not active.exists():
        return []
    return sorted(path for path in active.iterdir() if path.is_dir() and not path.name.startswith("."))


def archive_review_dirs(root):
    archive = memo_dir(root) / "archive"
    if not archive.exists():
        return []
    return sorted(path for path in archive.iterdir() if path.is_dir() and not path.name.startswith("."))


def valid_review_dirs_by_id(paths):
    by_id = {}
    for path in paths:
        try:
            review_id = validate_review_id(path.name)
        except ValueError:
            continue
        by_id[review_id] = path
    return by_id


def interrupted_archive_state(root, review_id=None):
    active_by_id = valid_review_dirs_by_id(active_review_dirs(root))
    archive_by_id = valid_review_dirs_by_id(archive_review_dirs(root))
    if review_id is None:
        duplicate_ids = sorted(set(active_by_id) & set(archive_by_id))
    elif review_id in active_by_id and review_id in archive_by_id:
        duplicate_ids = [review_id]
    else:
        duplicate_ids = []
    if len(duplicate_ids) != 1:
        return None
    review_id = duplicate_ids[0]
    return {
        "status": "archive_interrupted",
        "review_id": review_id,
        "active_path": str(active_by_id[review_id]),
        "archive_path": str(archive_by_id[review_id]),
    }


def build_request(review_id, owner, phase, topic, reviewers, created_at, artifact_text):
    reviewer_list = ", ".join(reviewers)
    body = artifact_text.rstrip()
    return (
        "# Review Request\n\n"
        f"Review ID: {review_id}\n"
        f"Owner: {owner}\n"
        f"Phase: {phase}\n"
        f"Topic: {topic}\n"
        f"Reviewers: {reviewer_list}\n"
        f"Created at: {created_at}\n\n"
        "## Artifact\n\n"
        f"{body}\n"
    )


def init_memo(root):
    root = Path(root)
    memo = memo_dir(root)
    (memo / "active").mkdir(parents=True, exist_ok=True)
    (memo / "archive").mkdir(parents=True, exist_ok=True)
    gitignore_path = memo / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text("active/\nstate.json\n", encoding="utf-8")
    state_path = memo / "state.json"
    if state_path.exists():
        state = read_json(state_path)
        return {"status": "exists", "updated_at": state.get("updated_at")}
    updated_at = utc_now()
    write_json(state_path, {"version": VERSION, "active_review_id": None, "updated_at": updated_at})
    return {"status": "initialized", "updated_at": updated_at}


def update_state_with_guard(state_path, expected_updated_at, review_id):
    state = read_json(state_path)
    if state.get("updated_at") != expected_updated_at or state.get("active_review_id") is not None:
        raise RuntimeError("state.json changed while creating review")
    updated_at = utc_now()
    state["active_review_id"] = review_id
    state["updated_at"] = updated_at
    write_json(state_path, state)
    return updated_at


def clear_state_with_guard(state_path, expected_updated_at, review_id):
    state = read_json(state_path)
    if state.get("updated_at") != expected_updated_at or state.get("active_review_id") != review_id:
        raise RuntimeError("state.json changed while archiving review")
    updated_at = utc_now()
    state["active_review_id"] = None
    state["updated_at"] = updated_at
    write_json(state_path, state)
    return updated_at


def create_review(root, owner, phase, topic, reviewers, artifact_text):
    reviewers = [validate_agent_id(reviewer) for reviewer in reviewers]
    if not reviewers:
        raise ValueError("At least one reviewer is required")

    init_memo(root)
    root = Path(root)
    memo = memo_dir(root)
    state_path = memo / "state.json"
    token = phase_token(phase)
    lock_dir = memo / "active" / ".create.lock"
    lock_dir.mkdir()
    review_dir = None
    try:
        state = read_json(state_path)
        if state.get("active_review_id") is not None:
            raise ValueError("An active review already exists")
        if active_review_dirs(root):
            raise ValueError("An active review folder already exists")

        review_id = f"{utc_now()[:10]}-{token}-{slug_text(topic)}"
        review_dir = memo / "active" / review_id
        if review_dir.exists():
            raise ValueError(f"Review already exists: {review_id}")

        created_at = utc_now()
        review_dir.mkdir(parents=True)
        (review_dir / "responses").mkdir()
        (review_dir / "request.md").write_text(
            build_request(review_id, owner, phase, topic, reviewers, created_at, artifact_text),
            encoding="utf-8",
        )
        write_json(
            review_dir / "status.json",
            {
                "version": VERSION,
                "review_id": review_id,
                "owner": owner,
                "phase": phase,
                "topic": topic,
                "required_reviewers": reviewers,
                "round": 1,
                "status": "waiting_for_review",
                "created_at": created_at,
                "updated_at": created_at,
            },
        )
        updated_at = update_state_with_guard(state_path, state.get("updated_at"), review_id)
    except Exception:
        if review_dir is not None and review_dir.exists():
            shutil.rmtree(review_dir)
        raise
    finally:
        shutil.rmtree(lock_dir)
    return {"status": "created", "review_id": review_id, "updated_at": updated_at}


def active_review_context(root):
    root = Path(root)
    memo = memo_dir(root)
    state_path = memo / "state.json"
    if not memo.is_dir() or not state_path.is_file():
        return None, {"status": "not_initialized"}

    state, error = read_json_or_error(state_path)
    if error is not None:
        return None, error

    review_id = state.get("active_review_id")
    if review_id is None:
        interrupted = interrupted_archive_state(root)
        if interrupted is not None:
            return None, interrupted
        active_dirs = active_review_dirs(root)
        if len(active_dirs) > 1:
            return None, {
                "status": "multiple_active_reviews",
                "active_review_id": None,
                "review_ids": [path.name for path in active_dirs],
            }
        if active_dirs:
            return None, {
                "status": "broken_state",
                "error": f"Stray active review folder exists while state is idle: {active_dirs[0]}",
                "review_ids": [path.name for path in active_dirs],
            }
        return None, {"status": "no_active_review"}
    try:
        review_id = validate_review_id(review_id)
    except ValueError as exc:
        return None, {"status": "broken_state", "error": str(exc), "review_id": review_id}

    active_dirs = active_review_dirs(root)
    if len(active_dirs) > 1:
        return None, {
            "status": "multiple_active_reviews",
            "active_review_id": state.get("active_review_id"),
            "review_ids": [path.name for path in active_dirs],
        }

    review_dir = memo / "active" / review_id
    if not review_dir.is_dir():
        return None, {"status": "broken_state", "error": f"Active review folder is missing: {review_dir}"}

    status_path = review_dir / "status.json"
    request_path = review_dir / "request.md"
    responses_dir = review_dir / "responses"
    if not request_path.is_file():
        return None, {"status": "broken_state", "error": f"Active review request is missing: {request_path}"}
    if not status_path.is_file():
        return None, {"status": "broken_state", "error": f"Active review status is missing: {status_path}"}
    if not responses_dir.is_dir():
        return None, {"status": "broken_state", "error": f"Active review responses folder is missing: {responses_dir}"}

    status, error = read_json_or_error(status_path)
    if error is not None:
        return None, error

    return {
        "root": root,
        "review_dir": review_dir,
        "status": status,
        "review_id": review_id,
        "state_updated_at": state.get("updated_at"),
    }, None


def check_review(root, agent):
    agent = validate_agent_id(agent)
    root = Path(root)
    memo = memo_dir(root)
    state_path = memo / "state.json"
    if not memo.is_dir() or not state_path.is_file():
        return {"status": "not_initialized"}

    state, error = read_json_or_error(state_path)
    if error is not None:
        return error

    active_review_id = state.get("active_review_id")
    if active_review_id is None:
        interrupted = interrupted_archive_state(root)
        if interrupted is not None:
            return interrupted
        active_dirs = active_review_dirs(root)
        if len(active_dirs) > 1:
            return {
                "status": "multiple_active_reviews",
                "active_review_id": None,
                "review_ids": [path.name for path in active_dirs],
            }
        if active_dirs:
            return {
                "status": "broken_state",
                "error": f"Stray active review folder exists while state is idle: {active_dirs[0]}",
                "review_ids": [path.name for path in active_dirs],
            }
        return {"status": "no_active_review"}

    try:
        review_id = validate_review_id(active_review_id)
    except ValueError as exc:
        return {"status": "broken_state", "error": str(exc), "review_id": active_review_id}

    interrupted = interrupted_archive_state(root, review_id)
    if interrupted is not None:
        return interrupted

    context, error = active_review_context(root)
    if error is not None:
        return error

    response_path = context["review_dir"] / "responses" / f"{agent}.md"
    response_exists = response_path.is_file()
    review_round = context["status"].get("round")
    response_round = None
    if response_exists:
        response_round = parse_response_headers(response_path).get("round")
    return {
        "status": "active_review",
        "review_id": context["review_id"],
        "round": review_round,
        "required_reviewers": context["status"].get("required_reviewers", []),
        "response_exists": response_exists,
        "missing_response": not response_exists or response_round != review_round,
        "response_round": response_round,
    }


def write_response(root, agent, response_status, body):
    agent = validate_agent_id(agent)
    if response_status not in {"approved", "changes_requested"}:
        raise ValueError(f"Unsupported response status: {response_status}")

    context, error = active_review_context(root)
    if error is not None:
        raise ValueError(f"Cannot write response: {error['status']}")

    review_round = context["status"].get("round")
    responses_dir = context["review_dir"] / "responses"
    responses_dir.mkdir(exist_ok=True)
    response_path = responses_dir / f"{agent}.md"
    response_path.write_text(
        (
            f"Status: {response_status}\n"
            f"Round: {review_round}\n"
            f"Reviewed at: {utc_now()}\n\n"
            f"{body.rstrip()}\n"
        ),
        encoding="utf-8",
    )
    return {
        "status": "written",
        "review_id": context["review_id"],
        "round": review_round,
        "path": str(response_path),
    }


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


def rollup_status(root):
    context, error = active_review_context(root)
    if error is not None:
        raise ValueError(f"Cannot roll up review: {error['status']}")

    status = dict(context["status"])
    review_round = status.get("round")
    required_reviewers = status.get("required_reviewers", [])
    responses_dir = context["review_dir"] / "responses"

    current_responses = {}
    for reviewer in required_reviewers:
        reviewer = validate_agent_id(reviewer)
        response_path = responses_dir / f"{reviewer}.md"
        if not response_path.is_file():
            continue
        headers = parse_response_headers(response_path)
        if headers.get("round") != review_round:
            continue
        if headers.get("status") in {"approved", "changes_requested"}:
            current_responses[reviewer] = headers["status"]

    if any(response == "changes_requested" for response in current_responses.values()):
        next_status = "changes_requested"
    elif required_reviewers and all(current_responses.get(reviewer) == "approved" for reviewer in required_reviewers):
        next_status = "approved"
    else:
        next_status = "waiting_for_review"

    updated_at = utc_now()
    status["status"] = next_status
    status["updated_at"] = updated_at
    write_json(context["review_dir"] / "status.json", status)
    return {
        "status": next_status,
        "review_id": context["review_id"],
        "round": review_round,
        "updated_at": updated_at,
    }


def reconcile_review(root, owner, decisions_text, next_round):
    context, error = active_review_context(root)
    if error is not None:
        raise ValueError(f"Cannot reconcile review: {error['status']}")

    status = dict(context["status"])
    if owner != status.get("owner"):
        raise ValueError("Owner does not match active review owner")
    if next_round:
        rollup_status(root)
        status = read_json(context["review_dir"] / "status.json")
    if next_round and status.get("status") not in {"changes_requested", "waiting_for_owner"}:
        raise ValueError("Next round requires a changes_requested or waiting_for_owner review")

    decisions_path = context["review_dir"] / "decisions.md"
    decisions_path.write_text(decisions_text.rstrip() + "\n", encoding="utf-8")

    if status.get("status") == "changes_requested":
        status["status"] = "waiting_for_owner"

    if next_round:
        status["round"] = int(status.get("round", 0)) + 1
        status["status"] = "waiting_for_review"
    else:
        rolled = rollup_status(root)
        status = read_json(context["review_dir"] / "status.json")
        if rolled["status"] == "changes_requested":
            status["status"] = "waiting_for_owner"

    updated_at = utc_now()
    status["updated_at"] = updated_at
    write_json(context["review_dir"] / "status.json", status)
    return {
        "status": status["status"],
        "review_id": context["review_id"],
        "round": status.get("round"),
        "updated_at": updated_at,
        "decisions_path": str(decisions_path),
    }


def verify_archive_copy(archive_dir):
    required_files = ["request.md", "status.json", "final.md"]
    missing = [name for name in required_files if not (archive_dir / name).is_file()]
    if not (archive_dir / "responses").is_dir():
        missing.append("responses/")
    if missing:
        raise RuntimeError(f"Archive copy is missing required files: {', '.join(missing)}")


def archive_review(root, owner, final_text):
    context, error = active_review_context(root)
    if error is not None:
        raise ValueError(f"Cannot archive review: {error['status']}")
    if not final_text.strip():
        raise ValueError("Final text must not be empty")

    status = dict(context["status"])
    if owner != status.get("owner"):
        raise ValueError("Owner does not match active review owner")
    if status.get("status") != "approved":
        raise ValueError("Archive requires an approved review")

    root = context["root"]
    memo = memo_dir(root)
    archive_dir = memo / "archive" / context["review_id"]
    if archive_dir.exists():
        raise ValueError(f"Archive already exists: {archive_dir}")

    final_path = context["review_dir"] / "final.md"
    final_path.write_text(final_text.rstrip() + "\n", encoding="utf-8")

    updated_at = utc_now()
    try:
        shutil.copytree(context["review_dir"], archive_dir)
        verify_archive_copy(archive_dir)
    except Exception:
        if archive_dir.exists():
            shutil.rmtree(archive_dir)
        raise

    archived_status = read_json(archive_dir / "status.json")
    archived_status["status"] = "archived"
    archived_status["updated_at"] = updated_at
    write_json(archive_dir / "status.json", archived_status)

    state_path = memo / "state.json"
    state_updated_at = clear_state_with_guard(state_path, context.get("state_updated_at"), context["review_id"])
    shutil.rmtree(context["review_dir"])
    return {
        "status": "archived",
        "review_id": context["review_id"],
        "updated_at": updated_at,
        "state_updated_at": state_updated_at,
        "archive_path": str(archive_dir),
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init")
    p_init.add_argument("--root", default=".")
    p_create = sub.add_parser("create")
    p_create.add_argument("--root", default=".")
    p_create.add_argument("--owner", required=True)
    p_create.add_argument("--phase", required=True)
    p_create.add_argument("--topic", required=True)
    p_create.add_argument("--reviewers", required=True)
    p_create.add_argument("--artifact-file", required=True)
    p_check = sub.add_parser("check")
    p_check.add_argument("--root", default=".")
    p_check.add_argument("--agent", required=True)
    p_respond = sub.add_parser("respond")
    p_respond.add_argument("--root", default=".")
    p_respond.add_argument("--agent", required=True)
    p_respond.add_argument("--status", required=True)
    p_respond.add_argument("--body-file", required=True)
    p_reconcile = sub.add_parser("reconcile")
    p_reconcile.add_argument("--root", default=".")
    p_reconcile.add_argument("--owner", required=True)
    p_reconcile.add_argument("--decisions-file", required=True)
    p_reconcile.add_argument("--next-round", action="store_true")
    p_archive = sub.add_parser("archive")
    p_archive.add_argument("--root", default=".")
    p_archive.add_argument("--owner", required=True)
    p_archive.add_argument("--final-file", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            print(json.dumps(init_memo(Path(args.root)), indent=2, sort_keys=True))
        elif args.command == "create":
            reviewers = [reviewer.strip() for reviewer in args.reviewers.split(",") if reviewer.strip()]
            artifact_text = Path(args.artifact_file).read_text(encoding="utf-8")
            result = create_review(Path(args.root), args.owner, args.phase, args.topic, reviewers, artifact_text)
            print(json.dumps({"review_id": result["review_id"], "status": result["status"]}, indent=2, sort_keys=True))
        elif args.command == "check":
            print(json.dumps(check_review(Path(args.root), args.agent), indent=2, sort_keys=True))
        elif args.command == "respond":
            body = Path(args.body_file).read_text(encoding="utf-8")
            result = write_response(Path(args.root), args.agent, args.status, body)
            print(json.dumps(result, indent=2, sort_keys=True))
        elif args.command == "reconcile":
            decisions_text = Path(args.decisions_file).read_text(encoding="utf-8")
            result = reconcile_review(Path(args.root), args.owner, decisions_text, args.next_round)
            print(json.dumps(result, indent=2, sort_keys=True))
        elif args.command == "archive":
            final_text = Path(args.final_file).read_text(encoding="utf-8")
            result = archive_review(Path(args.root), args.owner, final_text)
            print(json.dumps(result, indent=2, sort_keys=True))
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
