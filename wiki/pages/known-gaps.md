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
  (`software/server/main.py:37`) issues `ALTER TABLE ... ADD COLUMN` under
  `inspect()` guards. There is no migration tool (no Alembic), no down-migration,
  and no version table — column adds only. This is the mechanism protocol v2's
  capability/state table will have to arrive through (`PROTOCOL.md` Appendix B).
- **`main.py` is 2,887 lines** (2026-10-10, after protocol step 1) and holds
  routes, WS handlers, the Maya agent loop, the automation alerts, the abuse
  limits and the migrations. It is the single largest file by a wide margin (next
  is `settings_tab.dart` at 1,109). Protocol step 1 deliberately put its logic in
  `descriptor.py` and `capability_store.py` instead of growing this file further;
  step 3 still lands here.
- **Two representations of channel state run in parallel.** `Relay.is_on` and
  `capability_state` are both written on every device report, by design, until
  step 2 moves the app onto the descriptor — see
  [device protocol](device-protocol.md). Until then a change to one write path
  that misses the other will silently desynchronise them.
- **Five self-check scripts, no test runner.** `test_screen_limit.py`,
  `test_security.py` (abuse limits, PIN rules, the join→GPS chain),
  `test_descriptor.py` (protocol 2 step 1), `test_grants.py` (step 2: claiming,
  grants, labels) and `test_maya.py` (step 3: Maya's `set_capability` against a
  scripted model), all in `software/server/`, plus a default
  `software/mobile/test/widget_test.dart` (16 lines). Each is a plain script run
  with `python <file>`; there is no pytest and no CI. The agent loop's *model*
  is only ever tested through the scripted stand-in — nothing exercises a real
  Ollama response. The app's Dart is **uncompiled and untested** (no Flutter SDK
  on the machine it was written on). Server tests need `httpx<0.28` for
  Starlette 0.36's TestClient.
- **No rate limiting outside the named guards.** `ratelimit.py` covers the
  endpoints listed in [security-notes](security-notes.md#abuse-limits-in-one-place);
  everything else — chat, device commands, the REST device API — is unmetered. The
  state is also per-process, so it would not survive horizontal scaling.
- **The old root `CODE_WIKI.md` is stale** — it documents 4 mobile screens (there
  are 14), omits `ai.py`/`auth.py`, and hardcodes paths from another machine
  (`/workspace`, `c:/dev/fyp/...`). Superseded by this wiki; see
  [decisions](decisions.md#2026-09-08--replaced-the-single-file-code_wikimd).

## Peering: everything is tested except the radio (2026-10-10)

The server (`/api/peerings`, `peer_*` frames) and the library's decisions (grants,
HMAC, replay, scope, audit) are tested, including two library devices paired
through the real server. **No frame has ever crossed an actual ESP-NOW link**: the
radio glue in `Maya.cpp` compiles and is otherwise unverified, and the tests carry
frames through Python. The hub relay's server half is built (step 7a); its library halves, a hub firmware and the app's pairing UI are not. See
[device-protocol §Step 5b](device-protocol.md#step-5b-2026-10-10-the-librarys-half-of-the-local-link).

## Device-to-Maya: no UI, and no real-model test (2026-10-10)

`PUT /api/devices/{id}/agent` is the only way to allow a device to ask Maya; the app has
no switch for it (no Flutter SDK on the machine). The scripted model proves the limits;
how the real `gpt-oss:20b` answers a hostile or garbled device request has not been run.
See [device-protocol §Step 6](device-protocol.md#step-6-2026-10-10-a-device-asks-maya-for-help).
