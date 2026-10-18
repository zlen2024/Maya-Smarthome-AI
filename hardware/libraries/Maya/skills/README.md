# Skills for the Maya library

Two skills, written for an AI agent (Claude Code, Codex, or any agent that reads a
`SKILL.md`) and just as readable by a person. They live inside the library so they travel
with it and carry its version.

| Skill | Use it to |
|---|---|
| [`maya-device-builder`](maya-device-builder/SKILL.md) | build any new hardware device on the library: a lamp, a scale, a valve, a sensor, a hub. Has an API cheat sheet, driver patterns, a troubleshooting table (Serial line -> cause) and three templates (always-on, battery sensor, timed actuator with on-device safety limits). |
| [`maya-library-maintainer`](maya-library-maintainer/SKILL.md) | change the library itself without breaking the app, the server or devices already flashed. What is frozen, what is additive, how to test and release. |

## Installing a skill into an agent

Copy (or link) the folder you want into the agent's skills folder, e.g. for Claude Code
`.claude/skills/maya-device-builder/`. The folder is self-contained except for the links to
the library's `README.md`, `examples/` and `PROTOCOL.md`, which are relative: keep the
library checked out beside it or the agent will not find them.

The repository ignores `.claude/skills/` and `.agents/skills/` (they hold installed
third-party skills), so these are kept here, in the library, and **not** copied there.

## Keep them true

A skill that says something the library no longer does is worse than none. When the library
changes, change the skill in the same commit: `maya-library-maintainer` lists what to touch.
