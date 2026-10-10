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

## [2026-10-10] ingest | Protocol v2 step 1: devices describe themselves

`PROTOCOL.md` had been a 999-line draft since 2026-09-08 with "not yet
implemented" in its header. Step 1 of the §10 migration order is now built, and
only step 1: the server accepts and stores what a device declares, and
synthesises a descriptor for devices that declare nothing. New page:
[device protocol](pages/device-protocol.md), which records what exists against
what is still on paper.

**Two new modules rather than more of `main.py`.** `descriptor.py` (427 lines) is
§4-§6 as validation logic with no database or socket in it; `capability_store.py`
(179) is the storage half. `main.py` still grew to 2,887 lines, but the rules
live somewhere testable.

**The shape of the data.** `device_capabilities` (one row per declaration) and
`capability_state` (one row per value, `value` as JSON text). Appendix B had
already named `Relay.is_on`'s `Boolean` type as the most load-bearing assumption
in the codebase, and recommended a new table over widening it — that advice was
taken. Both representations are now written on every device report, deliberately,
so the server could move without the app, the firmware or Maya changing in the
same commit. That duplication is step 2's to remove and is recorded in
[known-gaps](pages/known-gaps.md#codebase-gaps) so it is not mistaken for an
accident.

**Verification went beyond asserting the happy path.** `test_descriptor.py` (550
lines, 11 checks) plays two devices against the real app over a WebSocket: a
protocol-1 board that declares nothing, and the salt jar from §5.7 — the
descriptor straight out of the document, which parses exactly as written. The
`set` round trip is real: a thread drives the HTTP request while the test answers
the `set` frame with an ack. The migration was checked against a database built
before the new columns existed, by dropping them and booting (existing rows get
`proto=1`, which is correct — they predate the protocol).

**Three pre-existing bugs surfaced in the command path**, all now fixed and
covered: a v2 ack switched relays off because `ch1` was read with a default of
`"off"`; an error ack (`invalid_channel`, `bad_value`) matched no branch at all,
so the caller waited the full 5-second timeout for an answer that had already
arrived; and `wait_for_ack` registered its future *after* the send, so an ack
from a device on the same LAN could be dropped. The first two were found by
writing the test, not by reading the code.

No firmware change was needed — the ESP32 still speaks protocol 1 and is shimmed,
which is the whole point of the migration order and is what the test checks.

Graph: server 289/3727 (was 224/2797), mobile unchanged at 559/4566. Reconciled
`index.md`, `data-model.md`, `server-backend.md`, `known-gaps.md`, and marked
step 1 done in `PROTOCOL.md` §10 and Appendix B.

## [2026-10-10] ingest | Spec revision 2.1 — closed every hole step 1 exposed

Step 1 was implementable, but eight decisions had to be made in code that the
document did not cover, and a ninth where it contradicted itself. Writing those
choices into comments would have made `descriptor.py` the de facto contract, so
they went into `PROTOCOL.md` instead: §4.1 claiming, §5.10 permissions, §5.11
labels, §5.12 history, the §5.8 `status` vocabulary, §12 the public API surface,
and the smaller interop points in §5.1, §6.2 and §9. The document is now 1,373
lines; `proto` stays 2, since the only wire change is one optional ack field
(§11 classes that as free).

**The contradiction is the one worth remembering.** §5.8 declares
`_report_every` as how a sleepy device says its check-in interval is adjustable;
§5.3's reserved-key table never listed it. `descriptor.py` implements §5.3
strictly, so it dropped the capability silently — the interval would have been
unadjustable on every device that offered it, with no error anywhere. Found by
re-reading §5.8 before writing the status vocabulary, not by testing.

**Decisions worth noting**, since each had a plausible alternative:

- Permissions are per capability **key**, not per `group`. `group` is free text a
  firmware build chooses, so a grant stored against it would change meaning on a
  firmware update — a child granted "Lights" could silently acquire whatever the
  next build called lights.
- Reading state is house-wide; only writing is granted. Hiding state makes an app
  that lies by omission and protects nothing — the child is in the room with the
  heater.
- A new capability is **denied to every child** until a parent grants it, so a
  firmware update can never widen a child's reach.
- `confirm:true` is enforced **server-side**. §5.4 asked Maya and the app to do
  it, and a flag enforced only in clients is enforced nowhere: the same
  capability is reachable from REST and from a third party's key. An API key can
  never supply the evidence — it is not a person.
- History's **gap rule** matters more than its retention numbers: a gap shorter
  than two intervals means nothing changed and draws flat; a longer one means the
  device went quiet and MUST draw as a break. A flat line through an outage is a
  chart inventing data.
- `/api/open/v1/*` is **frozen, not deprecated**. A working integration in
  someone else's script is not ours to break.

Three rules were implemented in the same pass because they constrain code step 1
had just written: `confirm` enforcement in `_dispatch_set`, `failed` passed
through to the caller, and `_report_every` accepted as reserved. §4.1 was
deliberately left: `register_device` still gives every device three relay rows,
and §10 assigns that to step 2 alongside the permission and label conversions,
because converting those tables twice would be the only alternative.

All three server self-checks still pass. Reconciled
[device protocol](pages/device-protocol.md) with a revision-2.1 section and a
rewritten "what a reader will not find" — every entry there now names the section
it can be built against.

## [2026-10-10] ingest | Step 2 server half: claiming, grants, labels converted

§10 bundles three conversions into step 2 because they touch the same tables, and
all three are now done on the server: §4.1 (claiming creates the device record
and nothing else), §5.10 (`capability_grants` replaces the per-relay
`permissions`) and §5.11 (`capability_labels` replaces `Relay.name` as the
store). New page section: [device protocol](pages/device-protocol.md#step-2-2026-10-10-the-three-conversions-and-the-app).

**The data was converted, not duplicated.** The migration copies each per-relay
permission onto `(device_id, "ch<n>")`, counts what landed, then drops the
`permissions` table — and only drops it if the count holds, because a failure
that leaves both tables with nothing reading the old one is recoverable while
dropping first is not. Relay names that still read "Channel N" carry no intent,
so they are left out and the firmware's own label applies. Verified against a
database still carrying the old table: three permissions became three grants with
their allow/deny values intact, two real names became labels, the table went.

`/api/permissions` survives as a **translating facade** over the grant store so
the shipped app keeps working — a second spelling, not a second source of truth,
which is the distinction §10 draws when it says the old table converts in the
same change.

**A bug fell out of §4.1.** Re-claiming a device used to reset every channel name
back to "Channel N", silently wiping a member's "Television" on every
re-provision. The block that did it was the same block §4.1 required removing, so
the fix came free with the rule.

**Enforcement now runs through one function.** `_child_capability_denial` answers
for the v1 command endpoint, the capability endpoint and Maya alike, so a check
cannot be dropped from one path without being dropped from all three. A
capability nobody has granted is denied, which is what stops a firmware update
widening a child's reach — `test_grants.py` asserts that a key that disappears
and returns comes back denied.

**The app was written, not compiled.** There is no Flutter SDK on this machine,
so `capability_control.dart` (new, all ten kinds plus a read-only fallback for an
unknown one), the rewritten `devices_tab.dart` and the capability-based permission
sheet are reviewed rather than built. `flutter analyze` is the next step before
any APK. `home_tab.dart` and `device_management_tab.dart` still read the v1
shapes and keep working through the shim; they are recorded as remaining rather
than quietly left.

All four server self-checks pass (`test_grants.py` is new, 5 checks).

## [2026-10-10] ingest | Step 3: Maya drives any device through set_capability

`control_device` was the only one of Maya's six tools that addressed relays, so
it is the one replaced — the plan's "swaps her six fixed tools" overstates it, and
`PROTOCOL.md` §10 now says so. `set_capability(device_id, key, value, confirmed)`
addresses any control a device declares, and her house state is built from
`descriptor_payload(for_agent=True)` instead of relay rows. Details on
[Maya AI agent](pages/maya-ai-agent.md#set_capability-two-gates-a-misbehaving-model-cannot-walk-through).

**The two gates are tested against a model that misbehaves**, because they are
claims about code rather than about prompts. `test_maya.py` replaces only
`ai.call_model` with a script; everything else is the real app, reached through
`/api/maya/voice` so it runs in the app's own event loop. The script names a
capability it was never shown (`agent:"deny"` — refused with the *same* message as
a key that does not exist, so nothing leaks) and passes `confirmed:true` with
nobody having asked (`confirm:true` — refused; honoured only for the same value,
in a later run, within five minutes).

**A pre-existing bug on the path step 3 needed.** `_dispatch_set` sent a v2
`{"type":"set"}` frame to every device, including protocol-1 boards that have
never heard of one, so `POST /capability` against a v1 device would have timed
out. It now translates to the v1 command each key always mapped to. It survived
step 2 because the step-1 tests drove the v1 *command* endpoint against a v1
device and the *set* endpoint only against a v2 one — each path was covered, the
crossing was not.

**Two test-authoring slips worth recording** since both looked like app bugs
first: the confirm test hung because one scenario (confirmed:true with nothing
pending) legitimately *replaced* the pending ask for the same key, so the next
"yes" was correctly refused and the test then blocked waiting for a frame that
was never sent; and the context showed ranges as `0.0..100.0` because bounds are
stored as floats, which reads like a decimal control to a model. The first was
the test's ordering, the second was fixed in `_describe_capability`.

All five server self-checks pass. Dart unchanged by this step.
