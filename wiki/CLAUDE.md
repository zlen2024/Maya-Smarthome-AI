# Wiki schema & operating rules

This directory is a **code2graph-seeded wiki** for the Maya smart-home repo.
Read this file before adding or editing anything under `wiki/`.

## The three layers — keep them separate

| Layer | Lives in | Who writes it |
|---|---|---|
| **Raw source** | `software/`, `hardware/` | The project. **Read-only from the wiki's perspective** — never edit source as part of wiki maintenance. |
| **The graph** | `wiki/graph/graph.json` + `wiki/graph/symbol_index.md` | `wiki/graph/build_graph.py`. **Regenerable cache — never hand-edit.** `graph.json` is gitignored (4.3 MB); `symbol_index.md` is committed. |
| **The wiki** | `wiki/pages/*.md`, `wiki/index.md`, `wiki/log.md`, this file | Written by hand. Narrative, cross-references, judgment calls. |

## Page conventions

- **One topic per page.** Markdown links between pages, relative paths.
- **Cite the graph, don't restate it from memory.** A claim like "N call sites"
  must come from an actual query run in that session — verify before writing it
  down, the same discipline as writing code. Note the tier used.
- **Source references use `path:line`** so they stay clickable and checkable.
- These get their **own page**, never buried inside whichever module page was
  open when they were noticed:
  - a decision that was reversed or superseded → `pages/decisions.md`
  - a limitation, gap, or blind spot → `pages/known-gaps.md`
  - anything security-relevant → `pages/security-notes.md`

## Resolution tiers — the thing to get right here

The correct tier **differs by language in this repo**. Getting it wrong looks
like "the symbol has no usages" rather than like an error:

| Root | Language | Tier | Why |
|---|---|---|---|
| `software/server` | Python | `scope` | Resolves cleanly; the CLI default. |
| `software/mobile/lib` | Dart | **`name`** | `scope` returns **zero** edges for Dart. Always pass `--tier name`. |

The CLI defaults to `--tier scope`; the Python binding's `build_graph` defaults
to `tier="name"`. `build_graph.py` sets tier **explicitly** for both roots —
keep it that way.

## Query rules

- **Prefer `usages` over `callers`.** `callers` only sees literal `name(...)`
  syntax. In this repo that gap is severe and load-bearing — see
  [known-gaps](pages/known-gaps.md#1-callers-and-impact-miss-fastapi-depends-injection).
- Read [`index.md`](index.md) to find the relevant page **before** querying the
  graph directly. The wiki should usually answer faster — that is the point.

## Operations

**Ingest** (after code changes)
```bash
python wiki/graph/build_graph.py          # rebuild graph.json + symbol_index.md
git diff -- wiki/graph/symbol_index.md    # what structurally changed
```
Reconcile changed symbols against the module pages, update them, append to `log.md`.

**Query** — `index.md` first, then the graph. The CLI needs `~/.cargo/bin` on PATH
and must be run from a source root (never the repo root — it would walk
`android/`, `build/`, `.dart_tool/`, the pub cache):
```bash
export PATH="$PATH:$HOME/.cargo/bin"
cd software/server        && code2graph index . && code2graph usages <sym>
cd software/mobile/lib    && code2graph index . && code2graph --tier name usages <sym>
```

**Lint** (periodic)
```bash
python wiki/graph/lint_wiki.py    # broken links, broken anchors, orphan pages; exit 1 on any
```
The script covers the mechanical checks. Still do by hand:
- Any `known-gaps.md` entry now fixed in the code?
- Any module page whose claims `symbol_index.md` no longer supports?

> Anchor slugs follow GitHub's rule, and two subtleties bite: `_` is a word
> character and survives, and an em-dash between spaces leaves **two** hyphens
> (`invisible--aipy`). `lint_wiki.py` implements this correctly — trust it over
> a hand-rolled slug.

## Log format

`log.md` is append-only, newest at the bottom, one entry per pass:
`## [YYYY-MM-DD] <ingest|query|lint> | <description>` — greppable with
`grep "^## \[" wiki/log.md`.
