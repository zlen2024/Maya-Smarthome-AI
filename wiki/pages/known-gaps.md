# Known gaps & graph blind spots

Every documented limitation in one place. A gap not written down here isn't
tracked. Two kinds live here: **graph blind spots** (things `code2graph` cannot
see, so the wiki must not be derived naively from it) and **codebase gaps**.

---

## Graph blind spots

These were each verified by running the query, not inferred from the tool's docs.

### 1. `callers` and `impact` miss FastAPI `Depends` injection

The single most dangerous blind spot in this repo. `auth.get_current_user` is
the authentication gate on ~30 endpoints, yet:

| Query (from `software/server`, tier `scope`) | Result |
|---|---|
| `code2graph callers get_current_user` | **0** |
| `code2graph impact get_current_user --depth 2` | **0** |
| `code2graph usages get_current_user` | **36** |

It is never called as `get_current_user(...)` — it is passed **by reference** to
`Depends(...)` in each route signature, e.g. `software/server/main.py:2066`.
The graph records those as `read` edges, which only `usages` reports.

> **Rule:** in this repo, "does anything depend on this?" is `usages`, never
> `callers` or `impact`. A symbol reading as zero-impact here may be gating the
> entire API. The same applies to `get_current_user_or_child`, `get_api_key_house`
> and `get_db`.

### 2. Bare `import ai` is invisible — `ai.py` is an orphan in the graph

`software/server/main.py:26` does `import ai` (module import + attribute access),
not `from ai import ...`. Consequences, both verified:

- `code2graph module-deps` for the server lists **no** `main.py -> ai.py` edge,
  though every other server module pair appears.
- `code2graph usages call_model` returns **empty**, despite a real call at
  `software/server/main.py:1578` (`ai.call_model`).

`from X import y` resolves fine — that is why `auth`, `database` and `models`
all show high import counts. So `ai.py` looks unused and isn't.

### 3. Dart resolves only at `--tier name`; `module-deps` never works for Dart

From `software/mobile/lib`, `code2graph usages ApiService` returns **nothing** at
the CLI's default `scope` tier, and rich correct results at `--tier name`.
Separately, `module-deps` returns `no matching result` for the Dart root at
**both** tiers — Dart import URIs aren't modelled as module edges. Dart
cross-file facts must come from symbol-level `usages` at `name` tier.

### 4. Maya's AI tools are string-dispatched — no edges at all

`ai.TOOLS` (`software/server/ai.py:32`) declares six tool schemas by name. They
are executed by an `if name == "..."` chain inside `_execute_maya_tool`
(`software/server/main.py:1468`), not as separate functions. So the link between
a declared tool name and the code implementing it is **string equality only** —
there is no symbol, and therefore no graph edge, for any individual tool. Adding
a tool schema without a matching branch (or renaming one) is invisible to the
graph and to `usages`.

### 5. ESP32 firmware is not indexed at all

`code2graph index .` in `hardware/smartextension` admits **0 files** — `.ino`
isn't a recognised extension. Workaround used to produce the firmware facts in
this wiki: copy to a scratch `.cpp` and index that. `build_graph.py` deliberately
does **not** include the firmware root, so `symbol_index.md` covers only server +
mobile. Firmware pages are written from source reading, not graph queries.

---

## Codebase gaps

- **No CORS middleware.** `grep 'add_middleware\|allow_origins' software/server/main.py`
  returns nothing, so browser clients on another origin cannot call the API. Fine
  for the Flutter app and server-rendered pages; a blocker for a separate web
  frontend.
- **SQLite single-file store with hand-rolled migrations.** `run_migrations()`
  (`software/server/main.py:34`) issues `ALTER TABLE ... ADD COLUMN` under
  `inspect()` guards. There is no migration tool (no Alembic), no down-migration,
  and no version table — column adds only.
- **`main.py` is 2,429 lines** and holds routes, WS handlers, the Maya agent loop,
  the automation alerts and the migrations. It is the single largest file by a
  wide margin (next is `settings_tab.dart` at 1,109).
- **One test file.** `software/server/test_screen_limit.py` (55 lines) plus a
  default `software/mobile/test/widget_test.dart` (16 lines). No test covers the
  agent loop, the WS routing, or auth.
- **The old root `CODE_WIKI.md` is stale** — it documents 4 mobile screens (there
  are 14), omits `ai.py`/`auth.py`, and hardcodes paths from another machine
  (`/workspace`, `c:/dev/fyp/...`). Superseded by this wiki; see
  [decisions](decisions.md#2026-09-08--replaced-the-single-file-code_wikimd).
