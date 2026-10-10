# Wiki log

Append-only, newest at the bottom. One entry per ingest / query / lint pass.
Greppable: `grep "^## \[" wiki/log.md`

## [2026-09-08] ingest | Initial build — indexed server + mobile, wrote all 8 pages

Seeded the wiki from a fresh code2graph index.

**Indexed:** `software/server` (6 files, 179 symbols, tier `scope`) and
`software/mobile/lib` (20 files, 558 symbols, tier `name`) — 7,025 edges total.
`hardware/smartextension` admits 0 files (`.ino` unsupported); firmware facts
were read from source instead, with a scratch `.cpp` copy used to sanity-check.

**Five graph blind spots found and verified** (all in
[known-gaps](pages/known-gaps.md)) — each by running the query, not inferring:

1. `callers get_current_user` = **0**, `impact --depth 2` = **0**, but
   `usages` = **36**. `Depends`-injected guards are passed by reference, so
   `callers`/`impact` report the repo's auth gate as having no dependents.
2. `import ai` (bare module import) produces **no** edge — `ai.py` is absent from
   `module-deps` and `usages call_model` is empty despite a real call site.
3. Dart resolves only at `--tier name`; `scope` (the CLI default) returns zero.
   `module-deps` never works for Dart at either tier.
4. Maya's six tools are string-dispatched in an `if name ==` chain — no symbol,
   no edge between a declared schema and its implementation.
5. `.ino` is not indexable.

**Two security findings** ([security-notes](pages/security-notes.md)): `SECRET_KEY`
falls back to a hardcoded literal (`auth.py:12`) and `/admin` falls back to
password `admin` (`main.py:240`) — in both cases the insecure value is what an
absent env var yields. One positive finding recorded: Maya's tool permissions are
genuinely enforced in `_execute_maya_tool`, not in the prompt.

**Decisions recovered** from git + `todos.md` ([decisions](pages/decisions.md)),
notably the reverted deferred-device-registration work (`1f86713` → `aa2a77e`) —
the stray-offline-device problem it targeted remains open.

Superseded the stale root `CODE_WIKI.md`, which documented 4 of 14 mobile
screens and carried paths from another machine.

## [2026-09-08] lint | First lint pass — 7 bad anchors, 1 orphan, 1 missing section

Wrote `wiki/graph/lint_wiki.py` (links / anchors / orphans, exit 1 on any).

The first run flagged 7 broken anchors, but **6 were the linter's own fault**: the
slug function stripped `_` as markdown emphasis (breaking `code_wikimd`) and
collapsed the double space left by an em-dash into one hyphen (breaking
`invisible--aipy`). GitHub keeps the underscore and produces two hyphens. Fixed
the linter, not the links.

Two findings were real and fixed:
- `mobile-app.md` linked a `decisions.md` section on house-switch reload that had
  never been written. Added it — the static-`ApiService` / `pushReplacement`
  trade-off, sourced from `todos.md`.
- `log.md` had no inbound link; now listed in `index.md`.

Verified the graph regenerates deterministically: deleted `graph.json` +
`symbol_index.md`, reran `build_graph.py`, got identical counts (179/2465 server,
558/4560 mobile). Gitignored `graph.json` (4.3 MB) and Obsidian's
`workspace.json` — the wiki was opened as an Obsidian vault mid-session.

## [2026-10-10] ingest | Closed the 2026-09-08 security findings; reconciled pages

The review on 2026-09-08 ended with four findings, a priority order and an
unanswered "shall I start with number one?". Nothing had been implemented since,
so this pass implemented all of it and re-read the code to confirm each finding
was still live before touching it — all four were.

**New modules.** `software/server/ratelimit.py` (`RateLimit` sliding window,
`FailureLock` with lockout, `client_ip` reading Fly's headers) and
`validators.py` (one PIN rule each for devices and children). Both are pure
logic with an injectable clock, which is what let them be tested without a
runner — matching `test_screen_limit.py`'s script style.

**The chain that mattered** — register → sequential `house_id` → brute the
6-digit `join_pin` → `GET /api/children` → a child's GPS — is closed at step 3
by two locks, a constant-time comparison and an activity-log entry per failure.
`list_children` still shows coordinates to any house member; that is now a
recorded decision rather than an oversight
([security-notes §6](pages/security-notes.md#6-a-guessable-chain-reached-a-childs-gps-coordinates--fixed-2026-10-10)).

**`"0000"` was the default at six layers at once**, and the WS identify check
read `if stored_pin and stored_pin != "0000"` — so the device PIN check never ran
in practice. Server, app and firmware now share one rule, each file pointing at
the other two.

**Verification.** `test_security.py` (274 lines, 7 checks) boots the real app
against a throwaway SQLite file: it replays the attack chain, drives three
identify attempts over a real WebSocket, and asserts `/admin` has no default
password. Both server self-checks pass. Flutter was **not** compiled — no SDK on
this machine — so the three Dart edits are reviewed, not built.

Graph rebuilt after the changes: server 224/2797 (was 179/2465 — the jump is
mostly the two new modules plus `main.py` growth), mobile 559/4566. Reconciled
`security-notes.md` (rewritten, 2 new findings), `known-gaps.md` (test census,
`main.py` now 2,541 lines, rate-limit scope), `data-model.md`, `server-backend.md`.
One anchor broke when finding 2 was retitled; the linter caught it.
