# Agent Memo Review Skill Design

Date: 2026-05-22
Status: Draft

## Goal

Create a portable skill workflow that lets Codex, Claude Code, and
Antigravity CLI coordinate plan reviews and implementation reviews through
project-local files instead of manual copy-paste between agents.

The first version supports one active review thread per project. The file
layout should still make a later upgrade to multiple parallel review threads
straightforward.

## Scope

In scope:

- Create and manage a project-local `.agent_memo/` folder.
- Create a review request for planning or implementation review.
- Let each agent discover active review work.
- Let each reviewing agent write feedback to its own response file.
- Let the coordinating agent read feedback, respond, record decisions, and
  archive the thread with a final approved result when complete.
- Use a layout that avoids multiple agents editing the same response file.

Out of scope for the first version:

- Automatic background hooks.
- Multiple active reviews at the same time.
- Network sync, server processes, or external databases.
- Deep integration with each agent's native task planner.

## Users and Agents

The intended users are developers who switch between multiple agent CLIs while
working in one project checkout.

Supported initial agent IDs:

- `codex`
- `cc`
- `agy`

The workflow should not hard-code only these three forever. New agent IDs
should be easy to add later.

## Folder Layout

The shared folder lives inside the project repo:

```text
.agent_memo/
  state.json
  .gitignore
  active/
    REVIEW_ID/
      request.md
      decisions.md
      final.md
      status.json
      responses/
        codex.md
        cc.md
        agy.md
  archive/
    REVIEW_ID/
```

For version 1, `.agent_memo/active/` must contain at most one `REVIEW_ID`
folder. The nested `REVIEW_ID` folder is still required so that version 2 can allow
multiple active reviews without changing the thread structure.

`request.md` and `status.json` are created when a review is opened.
`decisions.md` is created during the first owner reconciliation. `final.md` is
created only after approval, before archiving.

Default `.gitignore` policy:

```gitignore
active/
state.json
```

This keeps transient active-review state out of git while allowing archived
reviews to be committed as a durable project record. Teams may override this
if they want reviews to remain entirely local or entirely committed.

## Review ID

Each review gets a stable, human-readable ID:

```text
YYYY-MM-DD-<phase-token>-<short-topic>
```

Allowed phase tokens:

- `plan` maps to `phase: "planning"`
- `impl` maps to `phase: "implementation_review"`

Examples:

```text
2026-05-22-plan-auth-flow
2026-05-22-impl-upload-fix
```

The ID identifies the issue being reviewed and appears in `state.json`,
`status.json`, and archive paths.

## State Files

`.agent_memo/state.json` tracks project-level coordination state:

```json
{
  "version": 1,
  "active_review_id": null,
  "updated_at": "2026-05-22T00:00:00Z"
}
```

`active_review_id: null` is the normal state when there is no active review.

`active/REVIEW_ID/status.json` tracks the review thread:

```json
{
  "version": 1,
  "review_id": "2026-05-22-plan-auth-flow",
  "phase": "planning",
  "topic": "auth flow",
  "owner": "codex",
  "required_reviewers": ["agy", "cc"],
  "status": "waiting_for_review",
  "round": 1,
  "created_at": "2026-05-22T00:00:00Z",
  "updated_at": "2026-05-22T00:00:00Z"
}
```

Allowed `phase` values for version 1:

- `planning`
- `implementation_review`

Allowed `status` values for version 1:

- `draft`
- `waiting_for_review`
- `changes_requested`
- `waiting_for_owner`
- `approved`
- `archived`

The `owner` is set at review creation and does not change during the review.
The `round` counter starts at `1` and increments each time the owner moves from
`waiting_for_owner` back to `waiting_for_review`.

Thread status transitions:

| Current status | Trigger | Next status |
| --- | --- | --- |
| `draft` | Owner publishes `request.md` | `waiting_for_review` |
| `waiting_for_review` | At least one required reviewer requests changes | `changes_requested` |
| `waiting_for_review` | All required reviewers approve | `approved` |
| `waiting_for_review` | Some required reviewers have not responded | `waiting_for_review` |
| `changes_requested` | Owner starts reconciling feedback | `waiting_for_owner` |
| `waiting_for_owner` | Owner updates the artifact, increments `round`, and asks for another review | `waiting_for_review` |
| `approved` | Owner archives the review | `archived` |

Allowed reviewer response statuses:

- `approved`
- `changes_requested`

Reviewer responses should identify the review round they apply to. The owner
rolls current-round responses up into `status.json`: any required reviewer
response with `changes_requested` for the current round makes the thread
`changes_requested`; all required reviewer responses with `approved` for the
current round makes the thread `approved`; missing required reviewer responses
for the current round keep the thread `waiting_for_review`.

## Markdown Files

`request.md` contains the artifact to review and instructions for reviewers:

```markdown
# Review Request: 2026-05-22-plan-auth-flow

Owner: codex
Phase: planning
Reviewers: agy, cc
Status: waiting_for_review

## Context

...

## Artifact To Review

...

## Review Questions

- Does this plan miss important risks?
- Are the implementation steps clear and testable?
- Is anything overbuilt?
```

Each agent writes only to its own file under `responses/`:

```markdown
# agy Review: 2026-05-22-plan-auth-flow

Status: changes_requested
Round: 1
Reviewed at: 2026-05-22T00:00:00Z

## Findings

- ...

## Questions

- ...

## Recommendation

...
```

`decisions.md` records resolved issues and final agreement:

```markdown
# Decisions: 2026-05-22-plan-auth-flow

## Resolved

- ...

## Changes Since Last Round

- ...

## Final Agreement

- codex: approved
- agy: approved
- cc: approved
```

`final.md` records the approved result and becomes the first file future
agents should read when they need the outcome of an archived review:

```markdown
# Final Result: 2026-05-22-plan-auth-flow

Status: approved
Finalized at: 2026-05-22T00:00:00Z

## Approved Outcome

...

## Verification

...

## Follow-Up

...
```

For planning reviews, `final.md` should contain the approved plan or a concise
pointer to the approved spec or plan file. For implementation reviews, it
should contain what was approved, what verification was run, and any known
follow-up. Archived response files remain the audit trail, not the primary
source of truth.

## Workflow

### Create Review

The coordinating agent:

1. Finds the project root.
2. Creates `.agent_memo/` if missing.
3. Checks that no active review exists.
4. Creates `active/REVIEW_ID/`.
5. Writes `request.md`, `status.json`, and `state.json`.
6. Does not create reviewer response files. Reviewers create their own
   `responses/<agent-id>.md` on demand.

If an active review already exists, the skill should show the current review
ID and ask the user whether to read it, continue it, archive it, or stop.

When creating or updating `.agent_memo/state.json`, the skill should use a
lightweight optimistic guard: read the current `updated_at`, prepare the new
state, re-read `state.json`, and abort if `updated_at` changed before writing.
This is not full locking, but it prevents common split-terminal races.

### Check Review

Any agent:

1. Reads `.agent_memo/state.json`.
2. If `active_review_id` is `null`, reports that there is no active review.
3. Opens the active review folder.
4. Reads `request.md`, `status.json`, `decisions.md` if present, and its own
   response file if present.
5. Summarizes what action is needed from the current agent.

### Write Feedback

A reviewing agent:

1. Reviews the immutable `request.md` snapshot and any external artifact path
   it references.
2. Writes or updates only `responses/<agent-id>.md`.
3. Sets its response status to either `approved` or `changes_requested` and
   records the current review round.
4. Does not directly edit another agent's response.

### Owner Reconcile

The owner agent:

1. Reads all response files.
2. Applies changes to the plan or implementation outside `.agent_memo/`.
3. Creates or updates `decisions.md` with answers, accepted decisions, and a
   "Changes Since Last Round" section.
4. Updates `status.json`.
5. Requests another review round if needed by incrementing `round` and moving
   status back to `waiting_for_review`.

`request.md` is immutable after creation. It is the original review snapshot.
If the reviewed artifact changes, the owner records what changed in
`decisions.md` and points reviewers to the updated source artifact outside
`.agent_memo/`.

### Archive

When all required reviewers agree, the owner agent:

1. Writes `final.md` with the approved outcome.
2. Verifies `final.md` exists and is non-empty.
3. Sets the thread status to `archived`.
4. Copies `active/REVIEW_ID/` to `archive/REVIEW_ID/`.
5. Verifies the archive copy contains `request.md`, `status.json`,
   `final.md`, and `responses/`.
6. Updates `.agent_memo/state.json` so `active_review_id` is `null` using the
   optimistic `updated_at` guard.
7. Deletes `active/REVIEW_ID/`.

After a review is archived, agents should read `archive/REVIEW_ID/final.md`
first to recover the approved result. They should read `decisions.md` and
`responses/` only when they need history or rationale.

If archiving is interrupted, the recovery preference is to keep the active copy
as authoritative until `state.json` is cleared. If both active and archived
copies exist, report the duplicate and ask the user whether to finish archive
cleanup.

## Skill Behavior

The skill should support natural-language invocations rather than requiring
exact command syntax.

Useful intents:

- "Create a shared memo for plan review."
- "Check whether there is a memo for me."
- "Review the active memo as agy."
- "Read review comments and reconcile them."
- "Archive the active memo."

The skill should infer the current agent when possible. If it cannot infer the
agent ID, it should ask the user for one.

Agent ID inference order:

1. An explicit user phrase, such as "as agy" or "for cc".
2. A direct skill or script argument, such as `--agent agy`.
3. The known host agent runtime, when the skill host exposes it reliably.
4. If none of the above are available, ask the user and use the answer only for
   the current action.

The skill must not guess the current agent from the owner, the last response
file edited, or the first missing reviewer.

The skill should prefer concise summaries in chat while writing the durable
details to `.agent_memo/`.

## Delivery Format

The behavior above is the product contract. The implementation phase should
decide the packaging details, likely a portable skill folder with concise
`SKILL.md` instructions and helper scripts for deterministic file operations.
The helper scripts should be usable by Codex, Claude Code, and Antigravity CLI
without requiring a server.

## Error Handling

If `.agent_memo/` does not exist during a check, report that no shared memo has
been initialized.

If `.agent_memo/state.json` exists with `active_review_id: null`, report that
the memo system is initialized and there is no active review.

If `state.json` points to a missing active review folder, report the broken
state and recommend either repairing the path or clearing `active_review_id`.

If more than one active review folder exists in version 1, report that multiple
active reviews are not supported yet and ask the user which one to continue.

If JSON is invalid, avoid overwriting it blindly. Report the file path and ask
the user whether to repair it.

## Testing Strategy

Use fixture directories to test the deterministic parts of the skill:

- Initialize `.agent_memo/`.
- Create a planning review.
- Prevent creating a second active review.
- Check active review state.
- Write separate reviewer response files.
- Reconcile response summaries.
- Increment review rounds.
- Preserve `request.md` as immutable after creation.
- Require non-empty `final.md` before archive.
- Archive active review.
- Detect interrupted archive state.
- Detect broken or invalid state.

If helper scripts are included, they should have CLI-level tests using
temporary directories.

## Future Extensions

- Multiple active reviews by allowing several folders under `active/`.
- Per-review locks or optimistic update checks for shared state files.
- Optional hooks that check for active memos when an agent starts.
- Agent-specific metadata for installed agents and preferred reviewer sets.
- A compact status command that prints only pending action.
- Integration with git branches or commit hashes for implementation reviews.
