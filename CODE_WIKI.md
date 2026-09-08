# Code Wiki → moved to [`wiki/`](wiki/index.md)

This file was a single hand-maintained document that had drifted from the code:
it described 4 mobile screens (there are now 14), omitted `ai.py` and `auth.py`
entirely, and contained absolute paths from a different machine.

It has been replaced by a **code2graph-seeded wiki**:

- **[`wiki/index.md`](wiki/index.md)** — start here
- **[`wiki/CLAUDE.md`](wiki/CLAUDE.md)** — how to maintain it (layer separation,
  per-language resolution tiers, ingest/query/lint)
- **[`wiki/pages/`](wiki/pages/)** — architecture, server, mobile, firmware, AI
  agent, data model, plus known-gaps / security-notes / decisions
- **`wiki/graph/`** — the regenerable structural graph
  (`python wiki/graph/build_graph.py`)

The previous content remains in git history (`git show HEAD~1:CODE_WIKI.md`).
