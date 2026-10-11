# Maya — code wiki

A code2graph-seeded wiki for the Maya family smart-home system (Flutter app +
FastAPI backend + ESP32 smart power extension + a tool-calling AI assistant).

**Start here:** [architecture overview](pages/architecture-overview.md).
**Before editing this wiki:** read [`CLAUDE.md`](CLAUDE.md) — it defines the
layer separation, the per-language resolution tiers, and the ingest/query/lint
operations.

## Orientation

| Page | What it covers |
|---|---|
| [Architecture overview](pages/architecture-overview.md) | The three deployables, runtime topology, the four auth surfaces, cross-cutting flows |

## Components

| Page | What it covers |
|---|---|
| [Server backend](pages/server-backend.md) | FastAPI: 69 routes, the `Depends` auth guards, both WebSocket handlers, hand-rolled migrations |
| [Mobile app](pages/mobile-app.md) | Flutter: startup and routing, the all-static `ApiService` boundary, the three-part voice stack |
| [ESP32 firmware](pages/firmware-esp32.md) | GPIO 2/4/5 relays, BLE provisioning UUIDs, connection lifecycle and BLE fallback |
| [Maya AI agent](pages/maya-ai-agent.md) | The `ai.py` / `main.py` split, the bounded tool loop, the six tools and where permissions actually live |
| [Data model](pages/data-model.md) | 16 SQLAlchemy models, the multi-house join table, sentinel and denormalised columns |
| [Device protocol v2](pages/device-protocol.md) | What of `PROTOCOL.md` is actually built: steps 1-4 of 6, the capability tables, the Arduino library, and what still only exists on paper |

## Cross-cutting

| Page | What it covers |
|---|---|
| [Known gaps](pages/known-gaps.md) | **Read before trusting any graph query.** Five verified blind spots plus codebase gaps |
| [Security notes](pages/security-notes.md) | Env-var fallbacks that default insecure, PIN storage, API-key design, and one positive finding |
| [Decision log](pages/decisions.md) | What was reversed, superseded, or deliberately not done — the graph can't show this |
| [Wiki log](log.md) | Append-only record of every ingest / query / lint pass |

## The graph

| File | |
|---|---|
| [`graph/symbol_index.md`](graph/symbol_index.md) | 737 symbols by file. Generated — never hand-edit |
| `graph/graph.json` | Full facts, 4.3 MB, **gitignored** |
| [`graph/build_graph.py`](graph/build_graph.py) | Regenerates both. Sets the tier explicitly per root |
| [`graph/lint_wiki.py`](graph/lint_wiki.py) | Checks links, anchors and orphans across the wiki |

```bash
python wiki/graph/build_graph.py     # ingest: rebuild, then reconcile pages
python wiki/graph/lint_wiki.py       # lint:   links, anchors, orphans
```

## Coverage

| Root | Files | Symbols | Tier | Indexed |
|---|---|---|---|---|
| `software/server` | 6 | 179 | `scope` | yes |
| `software/mobile/lib` | 20 | 558 | `name` | yes |
| `hardware/smartextension` | 1 (~70 lines, on the Maya library) | — | — | **no** (`.ino` unsupported) |
| `hardware/libraries/Maya` | 4 | — | — | **no** (outside both graph roots; verified by `extras/test/test_library.py`, not queried) |
