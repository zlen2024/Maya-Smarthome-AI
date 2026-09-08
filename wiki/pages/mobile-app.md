# Mobile app (Flutter)

`software/mobile/lib` — 20 Dart files, 558 symbols.

> **Query note:** every graph fact on this page came from `--tier name`.
> The CLI's default `scope` tier returns **zero** edges for Dart, and
> `module-deps` returns nothing at either tier.
> See [known-gaps §3](known-gaps.md#3-dart-resolves-only-at---tier-name-module-deps-never-works-for-dart).

## Startup and routing

`main()` (`main.dart:12`) initialises three things before `runApp`:

```dart
VoiceTrigger.instance.init();      // Quick Settings tile launches
await VoiceService.loadSettings(); // voice language + Groq settings
await ThemeController.instance.load();
```

`MayaSmartHomeApp` is dark-only by deliberate design — `themeMode:
ThemeMode.dark` with `theme` and `darkTheme` both set to `buildGlassTheme(accent)`.
The comment at `main.dart:25` states the intent: *"glassmorphism is the fixed
brand, the accent is the variable."* Every screen is wrapped in `AuroraBackground`
so frosted surfaces have something to blur over.

`_AuthGate` (`main.dart:55`) checks saved credentials on startup and routes to
`ParentShell`, `ChildShell`, `OnboardingScreen` or `LoginScreen`.

## Structure

| Group | Files |
|---|---|
| `screens/` (14) | `parent_shell`, `child_shell` (the two role shells); tabs `home_tab`, `devices_tab`, `chat_tab`, `children_tab`, `settings_tab`, `child_tasks_tab`, `device_management_tab`; plus `login_screen`, `onboarding_screen`, `provision_screen`, `voice_overlay_screen` |
| `services/` (4) | `api_service`, `voice_service`, `groq_stt`, `voice_trigger` |
| `theme/` (1) | `accents.dart` — `ThemeController`, `buildGlassTheme`, `AuroraBackground` |
| `widgets/` (1) | `glass.dart` — shared frosted-glass primitives |

Largest files: `settings_tab.dart` (1,109), `provision_screen.dart` (1,067),
`children_tab.dart` (785), `parent_shell.dart` (755).

## `ApiService` — the single backend boundary

`services/api_service.dart:9`, an **all-static** class: no instances, module-level
state. It is the most-referenced symbol in the app, used from `main.dart` and
essentially every screen (`code2graph --tier name usages ApiService`).

Static state worth knowing about, because it is effectively app-wide globals:

```dart
static String token   = '';   // api_service.dart:15
static int?   houseId;        // :16
static bool   isChild = false;// :17
static String userRole = 'parent'; // :19
static int?   accId;          // :20
static List<Map<String, dynamic>> houses = [];      // :23
static Map<String, dynamic>? activeHouse;           // :24
static WebSocketChannel? activeChannel;             // :27
```

Three broadcast streams fan realtime events out to screens without a state
management package:

- `broadcasts` / `emitBroadcast` (`:33`, `:36`) — general WS traffic
- `chatBroadcasts` / `emitChat` (`:44`, `:47`) — chat messages
- `mentionEvents` / `emitMentionsChanged` (`:54`, `:56`) — unread `@`-mention badge

Below those sit thin `get`/`post`/`put`/`delete` helpers (`:143`–`:163`) that
attach the bearer token, and ~35 typed wrappers mirroring the server's routes
(`login`, `childLogin`, `getHouses`, `joinHouse`, `switchHouse`, `sendCommand`,
`reportLocation`, `reportScreenTime`, `getMyScreenTime`, …).

Because state is static, **switching houses requires a reload** — a constraint
recorded in [decisions](decisions.md#house-switching-reloads-rather-than-re-resolving-state).

## Voice stack

Three cooperating services:

- **`VoiceTrigger`** (`services/voice_trigger.dart`, 53 lines) — smallest and
  most load-bearing. Owns `VoiceTrigger.navigatorKey`, which `MaterialApp`
  consumes at `main.dart:33`, so a Quick Settings tile press can push the voice
  overlay from outside the widget tree. Referenced from `main.dart:14`, `:33`
  and `child_shell.dart:188`.
- **`VoiceService`** (205 lines) — capture orchestration and persisted settings
  (language, Groq key). Configured from `settings_tab.dart:250`–`:263`.
- **`GroqStt`** (87 lines) — speech-to-text transport. Used **only** by
  `VoiceService` (`_groqCapture()` `:158`/`:161`, `stop()` `:171`, `cancel()` `:176`) —
  a clean single-consumer boundary, so swapping the STT provider touches one file.

`voice_overlay_screen.dart` (330 lines) is the UI; transcribed text goes to the
server's `POST /api/maya/voice`, which returns Maya's reply privately rather than
posting it to house chat ([Maya AI agent](maya-ai-agent.md)).

`software/tools/convert_malaysian_whisper_tiny_to_sherpa.ipynb` suggests an
on-device Malaysian-Whisper path was explored alongside the Groq cloud route.
