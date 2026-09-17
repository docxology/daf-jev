# Agent skills

Agent-facing skill documents for this repository.

## What lives here

- `daf-jev/SKILL.md` — the daf-jev skill: when to use the toolkit, install,
  the Python API surface, the CLI, the MCP server, and pitfalls. It follows
  the standard skill format (YAML frontmatter with `name` and `description`,
  then a Markdown body) used by Claude Code and other agent environments —
  see `docs/reference/agent-skill.md` for the reference pattern.

## Installing the skill into an agent

Skills are single directories of Markdown that agents load on demand. To use
this skill outside the repo, copy the whole `skills/daf-jev/` directory into
your agent's skills location:

- **Claude Code / project-local skills** — copy the directory to
  `.claude/skills/daf-jev/` in your project. The agent picks it up by the
  frontmatter `name` (`daf-jev`); invoke it by saying "use the daf-jev skill".
- **Other agents** — most skill-compatible agents watch a skills directory;
  copy `skills/daf-jev/` there (project-local by default, or globally per
  your agent's documentation). When in doubt, paste the SKILL.md path into
  your agent and ask it to read it before working on daf-jev code.
- **Inside this repo** — nothing to install: agents working in the project
  read `skills/daf-jev/SKILL.md` directly; point them at it in one line.

Choose one copy per agent to avoid duplicate skill registrations.
