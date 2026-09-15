---
workflow: general-video
flow: automation
storyboard: yes
message: "Maya turns an ordinary extension socket into a family-centred AI home that saves power and keeps children safe while parents work."
destination: hackathon-submission
aspect: 1920x1080
language: en
audience: hackathon judges (innovation, impact, market, feasibility)
length: 175s
angle: hackathon-pitch
voice: gemini-tts
narration: yes
---

## Intent

Hackathon video presentation for **MAYA: A FAMILY-CENTRED AIoT ECOSYSTEM FOR SMARTER
AND SAFER HOME MANAGEMENT** — Project ID **CBN8426079**. Brief, clear, concise. Hook the
judges inside the first 15 seconds and leave them feeling their time was well spent.

Mandatory segment order from the hackathon guidelines (max 3:00, overruns penalised):

1. **Introduction (10–15%)** — project title, core objectives, brief outline; hook in ≤15s.
2. **Contents (~75%)** — the problem → current shortcomings → the potential solution
   (conceptual framework) → your product and how it works → user benefits → market value &
   opportunity (real data) → evidence & social proof (experience, real-world examples,
   production/implementation cost, social proof) → IP & research.
3. **Conclusion (~10%)** — the X-factor, key takeaways, core message, inspiring positive close.

Target ~2:55 (revised after storyboard feedback) to keep a safety margin under the 3:00 cap;
real voice durations decide the final cut.

## Assets

- ../../software/server/static/media/maya-logo.png — Maya logo; title card and closing lockup.
- ../../software/mobile/assets/brand/maya_logo.png — app icon variant of the logo.
- ../../software/server/static/media/hero-phone.png — phone mockup of the app; product scene.
- ../../software/server/static/media/app-demo.mp4 — real app screen recording; "how it works" scene.
- ../../software/server/static/media/app-poster.jpg — still from the demo; fallback frame.
- ../../POSTER.pdf — app screens (login, dashboard, AI chat, voice orb, settings, web and admin
  dashboards), architecture diagram, hardware block diagram, comparison table.
- ../../MUHAMAD_DANIEL_HAKIMI_(4233006571D)_FYP2Report.pdf — source of all project facts,
  survey results, testing and costing.
- ../../software/mobile/DESIGN.md — app brand reference (Aurora glassmorphism). Its dark colours
  are superseded for this video by frame.md (user feedback 2026-09-15, see Customizations).
- assets/media/user-photo-2026-09-15.jpeg — user-supplied photo: the creator with the working
  MAYA prototype (extension powering a desk fan and LED light) in front of the MAYA poster at
  the UNISEL showcase; real-world proof in Frame 12 (portrait column).
- assets/media/ui-dashboard.png — user-supplied real app screenshots: Home dashboard, Smart
  Socket D82C34C with Ps5 / Tv / Channel 3 toggles and "Ask Maya…" bar, cyan and pink themes;
  the product surface in Frame 8.

## Customizations

- Look (user feedback on sketches, 2026-09-15): content approved; colours changed to a **light
  theme with a soft gradient**, from the user's "Obsidian Chrome" reference — Onyx #0A0A0A,
  Blue Slate #536878, Alabaster Grey #E5E4E2; misty chrome gradient washing from slate/onyx
  into alabaster. Written to frame.md, which takes precedence over DESIGN.md.

- Narration: Gemini TTS (user choice), generated per line (`tools/voice_lines.json` →
  `assets/voice/`). User chose a **Puck + Sulafat combo**: Sulafat (warm) carries the human
  beats — hook, problem, concept, benefits, ESG half of frame 10, IP; Puck (upbeat) carries
  the energy/data beats — title, shortcomings, product, SDG half of frame 10, market,
  evidence; the close alternates both voices. TTS text spells acronyms for pronunciation
  (A-I-o-T, E-S-P thirty-two, S-D-G, E-S-G) and says "Maya" in title case.
- Review: sketches first (user confirmed) before the full build.
- Voice run 1 (2026-09-15): 16/18 lines generated, then the key's free-tier daily TTS quota
  (10 requests/model) ran out; 14c-close and 14d-close missing, and 11 lines fell back to
  gemini-2.5-flash-preview-tts. User will supply a key from a different Google account next —
  when it arrives, finish/redo the lines (prefer regenerating on gemini-3.1-flash-tts-preview
  for one consistent sound).
- Frame 10 pace (user decision): keep the slower SDG/ESG read (~23s) and re-time frame 10 to
  the real voice rather than speeding it up; total still lands under 3:00.
- Voice run 2 (2026-09-15, user-supplied GEMINI_API_KEY2): 14c-close and 14d-close generated on
  gemini-2.5-flash-preview-tts to match frame 14's other lines. Model mix in the cut: 01–04 and 09
  on gemini-3.1-flash-tts-preview, all others on gemini-2.5. Comparison takes of 01–04 and 09 on
  gemini-2.5 saved to assets/voice/alt-2.5/ (not used unless the user picks them — swapping
  changes those frames' durations, so re-run tools/cues.py and re-sync).
- Assembly: real-voice duration sync via tools/cues.py → tools/timing.json; scenes overlap 0.4s
  (incoming scene fades in over the outgoing); total 174.59s (2:55). Music bed carved under the
  narration with hyperframes-audio carve (strength 0.8).
- Background music: Google Lyria via the same Gemini key, carved under the narration.
- SDGs: primary **SDG 11** (Sustainable Cities & Communities); supporting **SDG 3** (Good
  Health & Well-being), **SDG 7** (Affordable & Clean Energy), **SDG 12** (Responsible
  Consumption & Production).
- ESG element: Environmental (cut standby power, responsible energy use), Social (child
  safety, working-parent well-being, affordable access), Governance (open source Apache 2.0,
  JWT/bcrypt/hashed API keys, parent-controlled permissions, data privacy by design).
- IP & research: mention the **Apache License 2.0** open-source release; the UNISEL FYP
  research (73-respondent survey) as the research base. No patent claims.
- Market value slide uses verified third-party figures, each with its source on screen.
- Storyboard feedback (frame 10): ESG pillars get the same treatment as the SDGs — equal
  panels, identical tiles, equal voiceover weight.
- Storyboard feedback (frame 12): state that MAYA is in active development — iterations 1–3.5
  shipped, iteration 4 (Device Protocol v2: self-describing devices, sensors, hubs over
  ESP-NOW) in progress.

## Notes

Verified market and context data (source on screen, one firm per claim):

- Global smart home: US$213.73B (2025) → US$450.20B by 2032, CAGR 11.8%; Asia Pacific highest
  CAGR ~17% — MarketsandMarkets, Mar 2026.
- ASEAN smart homes: US$5.29B (2025) → US$12.56B (2031), CAGR 15.51% — Mordor Intelligence, Aug 2026.
- Smart plug: US$3.52B (2024) → US$30.50B by 2034, CAGR 24.1% — Market.us, May 2025.
- Parental control software: US$1.57B (2025) → US$4.12B by 2034, CAGR 11.2%; APAC 24.1% share —
  Fortune Business Insights, Aug 2026.
- Malaysia female labour force participation record 56.6% (Q4 2025) — DOSM, via RinggitPlus.
- Standby ("phantom") power ≈ almost 10% of residential electricity — LBNL, cited by US DOE.

Project facts (from the FYP2 report):

- Survey n=73 working parents (Klang Valley): 80% of children spend ≥2h/day unsupervised;
  55% of children own a smart device; 70% of parents feel app fatigue often/very often;
  84% concerned about tracking child location/safety; adoption barriers high cost 39% +
  technical complexity 27%; 62% definitely prefer AI automation over manual rules;
  84% find smart extension wires useful; 82% willing to install a child monitoring app.
- 40 documented test cases (5 unit, 3 integration, 4 functional, 8 UAT, 20 detailed
  specifications) — 100% pass.
- Prototype hardware ≈ RM95 (ESP32 RM30, 3-ch relay RM20, 5V adapter RM15, casing & wires
  RM30); cloud hosting Fly.io ≈ RM2/month; deployed in Singapore region.
- Development: iterative; iterations 1 (hardware), 2 (profiles & permissions), 3 (AI agent &
  Open API), 3.5 (voice assistant, screen-time automation, branding) shipped; iteration 4
  (Device Protocol v2 draft) in design on branch dev-itteration-4.
- Stack: ESP32 3-channel relay socket + BLE provisioning + WebSocket; Flutter Parent/Child
  app; FastAPI + SQLite on Fly.io; @maya agent on Ollama Cloud (gpt-oss:20b-cloud) with
  tools control_device, get_child_location, get_screen_time, list_homework, add_homework,
  read_activity_log; voice via STT + TTS; Open API v1 with SHA-256-hashed X-API-Keys.

Avoid:

- The poster's "84% Want MAYA" — the survey did not ask that. Say "84% find smart
  extensions useful".
- Latency claims ("under two seconds") — not measured.
- Mixing firms' numbers inside one claim; invented statistics of any kind.
