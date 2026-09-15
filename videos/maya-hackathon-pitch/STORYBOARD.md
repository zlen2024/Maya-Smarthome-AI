---
format: 1920x1080
duration: 174.6s
message: "Maya turns an ordinary extension socket into a family-centred AI home that saves power and keeps children safe while parents work."
arc: Hook → Title & objectives → Problem → Shortcomings → Solution concept → Product (hardware, AI + child app) → Benefits → SDG & ESG → Market → Evidence → IP & research → X-factor close
audience: hackathon judges
mode: collaborative
segments: "Intro 0:00–0:19 (11%) · Contents 0:19–2:36 (79%) · Conclusion 2:36–2:55 (10%)"
music: "warm, hopeful modern tech underscore; soft piano and airy synth pads; gentle pulse; rises into an uplifting final lift"
design: frame.md (Obsidian Chrome light theme — Alabaster Grey #E5E4E2 canvas, Onyx #0A0A0A ink, Blue Slate #536878 accent, soft chrome gradient; user feedback 2026-09-15)
---

## Frame 1 — Hook: 3 P.M.

- type: hook
- segment: introduction
- scene: A clock ticks to 3:00 PM; two questions snap in beside a glowing outlet and a location pin
- duration: 8.24s
- poster: 6s
- transition_in: cut
- status: animated
- blueprint: kinetic-type-beats
- rules: kinetic-beat-slam, ambient-glow-bloom
- voiceover: "Three P.M. You're at work. Is the TV at home still on? And where is your child right now?"
- voice: Sulafat
- src: compositions/frames/01-hook.html

Cold open in the parent's own language, no product vocabulary. Beat 1 "3:00 PM" huge
monospace clock; beat 2 "Is the TV still on?" with an outlet glyph glowing cyan; beat 3
"Where is your child?" with a pulsing map pin. Hooks the judges in under 10s.

## Frame 2 — Title, objectives & outline

- type: product_intro
- segment: introduction
- scene: Maya logo blooms; full project title, Project ID CBN8426079 and four objective chips assemble
- duration: 11.32s
- poster: 9s
- transition_in: crossfade
- status: animated
- blueprint: logo-assemble-lockup
- rules: spring-pop-entrance, waterfall-entry
- voiceover: "This is MAYA — a family-centred AIoT ecosystem for smarter and safer home management. One smart socket, one AI assistant, one family app."
- voice: Puck
- src: compositions/frames/02-title.html

States the official title verbatim (guideline: title, core objectives, brief outline).
Objective chips from the report: ① independent outlet control ② AI voice & chat assistant
③ child location & screen-time tracking ④ secure Open API. A thin outline rail along the
bottom: Problem · Solution · Impact · Proof.

## Frame 3 — The problem: parents are stretched

- type: pain_point
- segment: contents
- scene: Two hero stats count up — 56.6% women in the workforce, 80% of children 2h+ unsupervised
- duration: 15.28s
- poster: 10s
- transition_in: wipe
- status: animated
- blueprint: dataviz-countup
- rules: counting-dynamic-scale, stat-bars-and-fills
- voiceover: "Malaysian women's workforce participation just hit a record 56.6 percent. In our survey of 73 working parents, 80 percent said their children spend two hours or more a day unsupervised."
- voice: Sulafat
- src: compositions/frames/03-problem.html

Sources on screen: "DOSM, Q4 2025" and "MAYA survey, n=73 working parents, Klang Valley".
Split frame: stat left, stat right; a day-timeline bar fills to show the unsupervised window.

## Frame 4 — The problem: app fatigue & wasted power

- type: pain_point
- segment: contents
- scene: App icons pile up around a phone (70% app fatigue); a standby meter glows at ~10%
- duration: 11.64s
- poster: 8s
- transition_in: crossfade
- status: animated
- blueprint: overwhelm-surround
- rules: depth-scatter-assemble, counting-dynamic-scale
- voiceover: "Parents juggle separate apps — 70 percent feel app fatigue — while devices on standby quietly waste almost ten percent of home electricity."
- voice: Sulafat
- src: compositions/frames/04-pain.html

Sources: "MAYA survey, n=73" and "Lawrence Berkeley National Laboratory, cited by US DOE".
Generic app tiles (plug, map, chat, camera, timer) — no real brand logos.

## Frame 5 — Current shortcomings

- type: pain_point
- segment: contents
- scene: Comparison table assembles row by row — smart plugs, voice assistants, parental apps vs what families need
- duration: 12.85s
- poster: 11s
- transition_in: crossfade
- status: animated
- blueprint: grid-card-assemble
- rules: waterfall-entry, css-marker-patterns
- voiceover: "Today's options fall short. Most smart plugs handle a single socket. Voice assistants follow commands, but aren't linked to your child's screen time or location. And parental apps rarely connect to the home."
- voice: Puck
- src: compositions/frames/05-shortcomings.html

Columns: Per-outlet control · AI understanding · Parental tools. Rows: Smart plugs (SHAS-style),
Voice assistants (Alexa), LLM agents (IoTGPT), Parental apps — ✗/partial marks from the
report's case-study comparison. The MAYA row stays hidden here; it lands in Frame 6.

## Frame 6 — The potential solution: one family hub

- type: product_intro
- segment: contents
- scene: Home, Parent and Child nodes orbit and connect into a glowing MAYA hub
- duration: 9.17s
- poster: 8s
- transition_in: crossfade
- status: animated
- blueprint: constellation-hub
- rules: orbit-3d-entry, svg-path-draw
- voiceover: "MAYA connects all three — home, parent and child — in one family-centred hub that can act on context."
- voice: Sulafat
- src: compositions/frames/06-concept.html

The conceptual framework before the product: context flows (screen time, location, device
state) drawn as lines into the hub; the comparison table's missing MAYA row ✓✓✓ flashes in.

## Frame 7 — Your product: the smart extension

- type: feature_showcase
- segment: contents
- scene: The 3-channel ESP32 socket; outlets light one by one; BLE setup → cloud → family phones pan
- duration: 11.29s
- poster: 9s
- transition_in: crossfade
- status: animated
- blueprint: spatial-pan-stations
- rules: svg-path-draw, press-release-spring
- voiceover: "An ESP32 three-channel smart extension switches each outlet independently. Set it up over Bluetooth once, and it stays synced with every family phone in real time."
- voice: Puck
- src: compositions/frames/07-hardware.html

Stations: [Smart Extension — CH1 TV · CH2 Decoder · CH3 Wi-Fi] → [Bluetooth setup] →
[Cloud server — FastAPI on Fly.io] → [Parent & Child apps]. Built from the report's
hardware block diagram and architecture diagram.

## Frame 8 — Your product: @maya AI + child app

- type: feature_showcase
- segment: contents
- scene: Chat types "@maya turn off the TV" → agent tool call → CH1 switches off; child app shows screen time, location, permissions
- duration: 11.05s
- poster: 7s
- transition_in: crossfade
- status: animated
- blueprint: prompt-type-submit-generate
- rules: discrete-text-sequence, video-text-pivot
- voiceover: "Just say, 'Maya, turn off the TV' — the AI agent finds the right outlet and switches it. The child app shares screen time and location, and parents set which outlets each child may use."
- voice: Puck
- src: compositions/frames/08-ai-child.html
- asset: assets/media/ui-dashboard.png (real app Home screens, user-supplied)

Left: phone with the real app demo (assets/media/app-demo.mp4) or chat recreation; the
agent reply "Done — I turned off the TV." Right: child card — screen time 1h 42m / 2h limit
ring, last location pin, outlet permission toggles.

## Frame 9 — User benefits

- type: benefit_highlight
- segment: contents
- scene: Five benefit cards stack in: one app, hands-free, peace of mind, less wasted power, no rewiring
- duration: 10.56s
- poster: 8s
- transition_in: crossfade
- status: animated
- blueprint: grid-card-assemble
- rules: spring-pop-entrance, ambient-glow-bloom
- voiceover: "One app instead of many. Hands-free control. Peace of mind at work. Less wasted power — and no rewiring."
- voice: Sulafat
- src: compositions/frames/09-benefits.html

Each card lands on its spoken phrase.

## Frame 10 — Impact: SDGs & ESG, equal weight

- type: benefit_highlight
- segment: contents
- scene: Split stage of equal halves — four SDG tiles (11, 3, 7, 12) left, three ESG pillar tiles (E, S, G) right, same card style, each landing on its spoken word
- duration: 23.74s
- poster: 13s
- transition_in: wipe
- status: animated
- blueprint: grid-card-assemble
- rules: waterfall-entry, spring-pop-entrance
- voiceover: "MAYA delivers on four SDGs: 11, safer communities; 3, well-being; 7, clean energy; and 12, responsible consumption. And on all three ESG pillars: Environmental, less standby waste; Social, safer children; Governance, secure and open by design."
- voice: Puck (SDGs) + Sulafat (ESG)
- src: compositions/frames/10-sdg-esg.html

ESG is treated exactly like the SDGs (storyboard feedback): two matching panels with
identical headers ("UN Sustainable Development Goals" · "ESG Pillars"), identical tile size,
glow and entrance, and equal screen time in the voiceover. SDG tiles in official goal colours
with number + short name (no UN emblem): SDG 11 Sustainable Cities & Communities (primary,
marked "Primary") · SDG 3 Good Health & Well-being · SDG 7 Affordable & Clean Energy ·
SDG 12 Responsible Consumption & Production. ESG tiles, letter + name + one proof line:
E — Environmental: cuts standby power, responsible energy use · S — Social: child safety,
working-parent well-being, affordable access · G — Governance: Apache 2.0 open source,
JWT + bcrypt + hashed API keys, parent-set permissions.

## Frame 11 — Market value & opportunity

- type: social_proof
- segment: contents
- scene: Three growth bars rise with count-up values — smart homes, smart plugs, parental-control software
- duration: 11.65s
- poster: 11s
- transition_in: crossfade
- status: animated
- blueprint: dataviz-countup
- rules: counting-dynamic-scale, stat-bars-and-fills
- voiceover: "The market is ready. Smart homes are heading to 450 billion US dollars by 2032, smart plugs to 30 billion, and parental-control software to over 4 billion."
- voice: Puck
- src: compositions/frames/11-market.html

On screen with sources: Global smart home US$213.7B (2025) → US$450.2B (2032), CAGR 11.8%,
APAC fastest (~17%) — MarketsandMarkets 2026 · Smart plugs US$3.5B (2024) → US$30.5B (2034),
CAGR 24.1% — Market.us 2025 · Parental control software US$1.57B (2025) → US$4.12B (2034),
CAGR 11.2% — Fortune Business Insights 2026 · footnote: ASEAN smart homes US$5.29B → US$12.56B
(2031) — Mordor Intelligence 2026.

## Frame 12 — Evidence, social proof & active development

- type: social_proof
- segment: contents
- scene: Survey rings (84%, 82%), a 40/40 tests-passed badge, a cost card, then an iteration timeline lights up to "Iteration 4 — in progress"
- duration: 16.85s
- poster: 15s
- transition_in: crossfade
- status: animated
- blueprint: dataviz-countup
- rules: stat-bars-and-fills, counting-dynamic-scale, svg-path-draw
- voiceover: "84 percent of parents find smart extensions useful, and 82 percent would install a child monitoring app. Our prototype passed all 40 tests on about 95 ringgit of hardware — and development is active: iteration four, for sensors and hubs, is underway."
- voice: Puck
- src: compositions/frames/12-evidence.html
- asset: assets/media/user-photo-2026-09-15.jpeg (prototype at UNISEL showcase, user-supplied)

Also on screen: "62% prefer AI automation", "≈RM2/month hosting · live on Fly.io (Singapore)",
"UAT with a real client user". Active-development strip (storyboard feedback), drawn left to
right as a progress line: Iteration 1 Hardware control ✓ · 2 Profiles & permissions ✓ ·
3 AI agent & Open API ✓ · 3.5 Voice assistant & screen-time automation ✓ ·
4 Device Protocol v2 — self-describing devices, sensors, hubs (ESP-NOW) — in progress (pulsing).

## Frame 13 — IP & research

- type: social_proof
- segment: contents
- scene: Apache 2.0 license card with the GitHub repo; UNISEL research badge
- duration: 7.93s
- poster: 5s
- transition_in: crossfade
- status: animated
- blueprint: titlecard-reveal
- rules: ambient-glow-bloom
- voiceover: "MAYA is open source under the Apache 2.0 license, built on research at Universiti Selangor."
- voice: Sulafat
- src: compositions/frames/13-ip.html

Card text: "Open source · Apache License 2.0 · github.com/zlen2024/Maya-Smarthome-AI" and
"Research: Final Year Project, Universiti Selangor (UNISEL) · survey of 73 working parents".
No patent claims.

## Frame 14 — Conclusion: the X-factor

- type: cta
- segment: conclusion
- scene: The whole family hub glows; three words land — Affordable · Intelligent · Open; Maya logo lockup with title and Project ID
- duration: 18.21s
- poster: 14s
- transition_in: crossfade
- status: animated
- blueprint: kinetic-type-beats
- rules: kinetic-beat-slam, logo-assemble-lockup
- voiceover: "Other smart homes switch things on and off. MAYA understands your family. Affordable, intelligent and open — so every working parent can breathe easy, knowing home is in good hands. MAYA: home, handled."
- voice: Sulafat + Puck, alternating
- src: compositions/frames/14-close.html

X-factor: the only smart home here that joins per-outlet power, an AI agent and child safety.
Ends on the logo, full title, Project ID CBN8426079 and "Thank you" — music lifts and resolves.
