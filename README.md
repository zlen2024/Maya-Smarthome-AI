# MAYA — A Family-Centred AIoT Ecosystem for Smarter and Safer Home Management

**Maya** is a personal home assistant for working parents. It joins three things
that usually live in separate apps: control of individual power outlets, an AI
assistant you can talk to, and child supervision (screen time and location).

- **Smart Extension**: an ESP32-based 3-channel extension socket. Each outlet
  (TV, decoder, Wi-Fi router, gaming console) switches on and off independently.
- **@maya AI agent**: a tool-calling assistant on Ollama Cloud (`gpt-oss:20b-cloud`).
  Say *"@maya turn off the TV"* in family chat or through the voice orb, and the
  agent resolves the device and switches the relay.
- **Parent and Child apps**: one Flutter app with Parent and Child modes. Parents
  grant per-outlet permissions, set daily screen-time limits and see the child's
  last known location. The child app reports screen time and GPS in the foreground.
- **Open API v1**: an `X-API-Key` secured REST API (keys stored as SHA-256 hashes),
  so households can connect Maya to their own scripts and tools.

## Architecture

```
 Parent app (Flutter) ─┐                     ┌─ Ollama Cloud (tool-calling LLM)
 Child app  (Flutter) ─┼─ HTTPS / WSS ─ FastAPI backend (Fly.io, Singapore) ─┤
 ESP32 Smart Extension ┘        (JWT, bcrypt, device PIN)  │  └─ Groq Whisper (optional STT)
        ▲                                              SQLite (persistent volume)
        └── BLE provisioning (Wi-Fi SSID, password, server URL, PIN) from the Parent app
```

| Layer | Technology |
|---|---|
| Mobile | Flutter (Dart), Android. `web_socket_channel`, `flutter_blue_plus`, `mobile_scanner`, native STT/TTS |
| Backend | FastAPI (Python), SQLAlchemy, SQLite, JWT + bcrypt, WebSockets, Docker on Fly.io |
| AI | Ollama Cloud `gpt-oss:20b-cloud` agent. Tools: `set_capability`, `get_child_location`, `get_screen_time`, `list_homework`, `add_homework`, `read_activity_log` |
| Firmware | C++ (Arduino core for ESP32), relays on GPIO 2/4/5, BLE provisioning, WebSocket client with watchdog reconnect |

## Repository layout

| Path | What's inside |
|---|---|
| [`software/server`](software/server) | FastAPI backend, AI agent loop, data models, web portals ([setup](software/server/README.md)) |
| [`software/mobile`](software/mobile) | Flutter Parent/Child app ([design system](software/mobile/DESIGN.md)) |
| [`hardware/smartextension`](hardware/smartextension) | The 3-channel Smart Extension firmware, a ~70-line sketch on the Maya library ([setup](hardware/smartextension/SETUP.md), [wiring](hardware/smartextension/WIRING.md)) |
| [`hardware/libraries/Maya`](hardware/libraries/Maya) | Arduino library for building your own Maya device: declare what it can do, the library speaks the protocol ([README](hardware/libraries/Maya/README.md)) |
| [`software/skills/maya-open-api`](software/skills/maya-open-api) | Agent skill for driving Maya through the Open API |
| [`wiki/`](wiki/index.md) | Code wiki: architecture, server, mobile, firmware, AI agent, data model, known gaps |
| [`PROTOCOL.md`](PROTOCOL.md) | Maya Device Protocol v2 draft (self-describing devices, sensors, hubs) |

## Getting started

1. **Backend**: follow [`software/server/README.md`](software/server/README.md)
   (`uv venv`, `uv pip install -r requirements.txt`, `uv run uvicorn main:app --reload`).
   Production deploys use the root [`Dockerfile`](Dockerfile) and [`fly.toml`](fly.toml).
2. **Firmware**: install the [Maya library](hardware/libraries/Maya/README.md) and flash
   `smartextension.ino` with the Arduino IDE per
   [`SETUP.md`](hardware/smartextension/SETUP.md). With no saved Wi-Fi, the
   device advertises over BLE as `Maya-<device id>`.
3. **Mobile app**: `cd software/mobile && flutter pub get && flutter run`,
   then provision the Smart Extension from the Parent app.

## Project status

Iterations 1–3.5 are implemented: hardware control, multi-user profiles and
permissions, the conversational AI agent, voice assistant, screen-time
automation and the Open API. Testing covered 40 documented cases (unit,
integration, functional, UAT and detailed test-case specifications), all
passing. Iteration 4 (Device Protocol v2) is in design.

## Research

Maya began as a Final Year Project for the Bachelor of Software Engineering at
Universiti Selangor (UNISEL), Faculty of Communication, Visual Art & Computing,
supervised by Puan Norhayati binti Mohd Amin. Requirements were validated with a
73-respondent survey of working parents in the Klang Valley.

## License

Maya is open source under the **[Apache License, Version 2.0](LICENSE)**.

You may use, modify and distribute this work, including commercially, provided
you keep the license and copyright notices and state your changes. Apache 2.0
also includes an express patent grant from contributors to users, and it gives
no right to use the project's name or trademarks.

Copyright 2026 Muhamad Daniel Hakimi bin Khairuzaman.
