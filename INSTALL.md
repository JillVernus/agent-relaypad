# Install Agent Relaypad Skills

Use this file as an instruction sheet for Codex, Claude Code, Antigravity CLI,
or another agent that needs to install or update the `agent-memo-review` skill.

## Source Folder

The skill source folder is:

```text
agent-memo-review/
```

Install or update the whole folder, including:

```text
agent-memo-review/
  SKILL.md
  agents/openai.yaml
  scripts/agent_memo.py
  tests/test_agent_memo.py
```

Do not copy only `SKILL.md`; the helper script is required.

## Target Folder

Install into the current agent's user skills directory.

Known Codex target:

```text
~/.codex/skills/agent-memo-review/
```

Other agents may use different skill/plugin folders. Do not guess blindly. The
installing agent should first identify its own configured user skill directory,
then copy the `agent-memo-review/` folder there.

Known or expected target patterns:

| Agent | Target |
| --- | --- |
| Codex | `~/.codex/skills/agent-memo-review/` |
| Claude Code | Use Claude Code's configured user skills/plugin directory. If unknown, ask Claude Code to report it before copying. |
| Antigravity CLI | Use Antigravity CLI's configured user skills directory. If unknown, ask Antigravity to report it before copying. |

Keep the final folder name exactly:

```text
agent-memo-review
```

If the target directory is not known, stop and ask:

```text
What user skills directory should I use for this agent runtime?
```

## Fresh Install

### Codex

If the Codex target folder does not exist:

```bash
mkdir -p ~/.codex/skills
cp -R agent-memo-review ~/.codex/skills/
```

Then verify:

```bash
test -f ~/.codex/skills/agent-memo-review/SKILL.md
test -f ~/.codex/skills/agent-memo-review/scripts/agent_memo.py
```

Restart or reload the agent after install.

### Claude Code or Antigravity CLI

First set the correct skills directory for that agent:

```bash
TARGET_SKILLS_DIR="/path/to/that-agent/skills"
```

Then install:

```bash
mkdir -p "$TARGET_SKILLS_DIR"
cp -R agent-memo-review "$TARGET_SKILLS_DIR/"
```

Then verify:

```bash
test -f "$TARGET_SKILLS_DIR/agent-memo-review/SKILL.md"
test -f "$TARGET_SKILLS_DIR/agent-memo-review/scripts/agent_memo.py"
python "$TARGET_SKILLS_DIR/agent-memo-review/scripts/agent_memo.py" --help
```

Restart or reload that agent after install.

## Update Existing Install

If the target folder already exists, replace the installed skill folder with
the source folder.

### Codex

```bash
rm -rf ~/.codex/skills/agent-memo-review
cp -R agent-memo-review ~/.codex/skills/
```

Then verify:

```bash
python ~/.codex/skills/agent-memo-review/scripts/agent_memo.py --help
```

Expected command list:

```text
init, create, check, respond, reconcile, archive
```

Restart or reload the agent after update.

### Claude Code or Antigravity CLI

First set the correct skills directory for that agent:

```bash
TARGET_SKILLS_DIR="/path/to/that-agent/skills"
```

Then update:

```bash
rm -rf "$TARGET_SKILLS_DIR/agent-memo-review"
cp -R agent-memo-review "$TARGET_SKILLS_DIR/"
```

Then verify:

```bash
python "$TARGET_SKILLS_DIR/agent-memo-review/scripts/agent_memo.py" --help
```

Restart or reload that agent after update.

## Safe Update Notes

- It is safe to replace the installed `agent-memo-review/` skill folder.
- Do not delete project-local `.agent_memo/` folders during install or update.
- Do not overwrite a project's `.agent_memo/.gitignore`; the helper preserves
  existing project overrides.
- If the agent has a marketplace/cache step for skills, run that agent's normal
  refresh or reload command after copying.
- If the agent has both a global user skill directory and a project-local skill
  directory, prefer the global user directory when you want the skill available
  in every project.

## Validate Source Before Install

From this repo, run:

```bash
PYTHONPATH=agent-memo-review/scripts python -m unittest discover -s agent-memo-review/tests -v
```

Expected:

```text
Ran 48 tests
OK
```

## Validate Installed Copy

For Codex:

```bash
python ~/.codex/skills/agent-memo-review/scripts/agent_memo.py --help
```

For another agent, replace `~/.codex/skills` with that agent's skills path.

Variable form:

```bash
TARGET_SKILLS_DIR="/path/to/that-agent/skills"
python "$TARGET_SKILLS_DIR/agent-memo-review/scripts/agent_memo.py" --help
```

## Quick Smoke Test

Use a temporary project folder:

```bash
tmpdir=$(mktemp -d)
printf '# Plan\n\nTest install.\n' > "$tmpdir/plan.md"
python ~/.codex/skills/agent-memo-review/scripts/agent_memo.py init --root "$tmpdir"
python ~/.codex/skills/agent-memo-review/scripts/agent_memo.py create --root "$tmpdir" --owner codex --phase planning --topic "install smoke" --reviewers agy --artifact-file "$tmpdir/plan.md"
python ~/.codex/skills/agent-memo-review/scripts/agent_memo.py check --root "$tmpdir" --agent agy
```

Expected:

- `init` prints JSON success.
- `create` prints JSON with `status: created`.
- `check` prints JSON with `status: active_review`.

## How To Ask An Agent To Install

Give the agent this instruction:

```text
Read INSTALL.md and install or update the agent-memo-review skill for your own
runtime. First identify the correct user skills directory for this agent. If
you cannot identify it confidently, stop and ask me for the target path. Do not
delete any project-local .agent_memo folders. Verify the installed helper with
--help after copying.
```

If the agent does not know its skills directory, ask it to report the expected
location before copying files.
