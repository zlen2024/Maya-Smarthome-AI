---
format: 1920x1080
duration: 224.4s
message: "Maya turns an ordinary extension socket into a family-centred AI home that saves power and keeps children safe while parents work."
arc: Hook → Title & objectives → Problem → Shortcomings → Solution concept → Product (hardware, live demo, child app) → Benefits → SDG & ESG → Market → Commercial opportunity → Evidence → IP & research → X-factor close
audience: hackathon judges
mode: collaborative
segments: "Intro 0:00–0:19 (9%) · Contents 0:19–3:26 (83%) · Conclusion 3:26–3:44 (8%)"
music: "warm, hopeful modern tech underscore; soft piano and airy synth pads; gentle pulse; rises into an uplifting final lift"
design: frame.md (Obsidian Chrome light theme — Alabaster Grey #E5E4E2 canvas, Onyx #0A0A0A ink, Blue Slate #536878 accent, soft chrome gradient)
---

## Frame 1 — Hook: 3 P.M.

- type: hook
- segment: introduction
- scene: A clock ticks to 3:00 PM; two questions snap in beside a glowing outlet and a location pin
- start: 0:00 (0.00s)
- duration: 8.24s
- transition_in: cut
- status: animated
- blueprint: kinetic-type-beats
- rules: kinetic-beat-slam, ambient-glow-bloom
- voiceover: "Three P.M. You're at work. Is the TV at home still on? And where is your child right now?"
- voice: Sulafat
- src: compositions/frames/01-hook.html

Cold open in the parent's own language, no product vocabulary. Hooks the judges inside 10s.

## Frame 2 — Title, objectives & outline

- type: product_intro
- segment: introduction
- scene: Maya logo blooms; full project title, Project ID CBN8426079 and four objective chips assemble
- start: 0:08 (7.84s)
- duration: 11.32s
- transition_in: crossfade
- status: animated
- blueprint: logo-assemble-lockup
- rules: spring-pop-entrance, waterfall-entry
- voiceover: "This is Maya — a family-centred A-I-o-T ecosystem for smarter and safer home management. One smart socket, one AI assistant, one family app."
- voice: Puck
- src: compositions/frames/02-title.html

Guideline requirement: project title, core objectives, brief outline.

## Frame 3 — The problem: parents are stretched

- type: pain_point
- segment: contents
- scene: Two hero stats count up — 56.6% women in the workforce, 80% of children 2h+ unsupervised
- start: 0:19 (18.76s)
- duration: 15.28s
- transition_in: crossfade
- status: animated
- blueprint: dataviz-countup
- rules: counting-dynamic-scale, stat-bars-and-fills
- voiceover: "Malaysian women's workforce participation just hit a record fifty-six point six percent. In our survey of seventy-three working parents, eighty percent said their children spend two hours or more a day unsupervised."
- voice: Sulafat
- src: compositions/frames/03-problem.html

Sources on screen: DOSM Q4 2025 and the project's own 73-parent survey.

## Frame 4 — The problem: app fatigue & wasted power

- type: pain_point
- segment: contents
- scene: App tiles pile up around a phone (70% app fatigue); a standby meter reads ~10%
- start: 0:34 (33.64s)
- duration: 11.64s
- transition_in: crossfade
- status: animated
- blueprint: overwhelm-surround
- rules: depth-scatter-assemble, counting-dynamic-scale
- voiceover: "Parents juggle separate apps — seventy percent feel app fatigue — while devices on standby quietly waste almost ten percent of home electricity."
- voice: Sulafat
- src: compositions/frames/04-pain.html

Second pain: fragmentation plus the energy angle that carries SDG 7 and 12 later.

## Frame 5 — Current shortcomings

- type: pain_point
- segment: contents
- scene: Comparison table assembles row by row; the MAYA row stays a question mark
- start: 0:45 (44.88s)
- duration: 12.85s
- transition_in: crossfade
- status: animated
- blueprint: grid-card-assemble
- rules: waterfall-entry, spring-pop-entrance
- voiceover: "Today's options fall short. Most smart plugs handle a single socket. Voice assistants follow commands, but aren't linked to your child's screen time or location. And parental apps rarely connect to the home."
- voice: Puck
- src: compositions/frames/05-shortcomings.html

Guideline requirement: why existing market solutions fall short.

## Frame 6 — The potential solution: one family hub

- type: product_intro
- segment: contents
- scene: Home, Parent and Child nodes connect into a glowing MAYA hub; the missing row lands ✓✓✓
- start: 0:57 (57.33s)
- duration: 9.17s
- transition_in: crossfade
- status: animated
- blueprint: constellation-hub
- rules: spring-pop-entrance, svg-path-draw
- voiceover: "Maya connects all three — home, parent and child — in one family-centred hub that can act on context."
- voice: Sulafat
- src: compositions/frames/06-concept.html

The conceptual framework, before any product detail.

## Frame 7 — Your product: the smart extension

- type: feature_showcase
- segment: contents
- scene: Block diagram assembles; three outlets switch on one by one; camera pans to setup, cloud, apps
- start: 1:06 (66.10s)
- duration: 11.29s
- transition_in: crossfade
- status: animated
- blueprint: spatial-pan-stations
- rules: viewport-change, svg-path-draw
- voiceover: "An E-S-P thirty-two, three-channel smart extension switches each outlet independently. Set it up over Bluetooth once, and it stays synced with every family phone in real time."
- voice: Puck
- src: compositions/frames/07-hardware.html

How it works: ESP32, 3-channel relay, BLE provisioning, live WebSocket sync.

## Frame 8 — Live demo: one spoken command, one outlet

- type: feature_showcase
- segment: contents
- scene: Unedited screen recording: voice command → Maya processes → lamp switches, other channel unaffected
- start: 1:17 (76.99s)
- duration: 38.50s
- transition_in: crossfade
- status: animated
- blueprint: device-surface-showcase
- rules: (real footage; caption rail on the cue beats)
- voiceover: "Here it is on the real hardware — one spoken command, one outlet."
- voice: Puck
- media: assets/media/voice-demo.mp4 (user recording, starts 0.6s into the scene)
- src: compositions/frames/08-demo.html

The real app on the real hardware (user recording, 3:37–4:15). Beat rail marks: listening, “Buka lampu”, relay click and lamp ON, “tutup lampu lepas tu buka channel no. 1”, lamp OFF, and the reply proving one outlet off while another goes on. The clip's own sound carries the scene; the music bed ducks under it.

## Frame 9 — The child companion app

- type: feature_showcase
- segment: contents
- scene: Child card: screen-time ring counts to 1h 42m, last known location, outlet permissions toggle
- start: 1:55 (115.09s)
- duration: 11.12s
- transition_in: crossfade
- status: animated
- blueprint: grid-card-assemble
- rules: stat-bars-and-fills, spring-pop-entrance
- voiceover: "That was Maya's own voice assistant. The child app adds the other half: screen time, last known location, and the outlet permissions parents set."
- voice: Sulafat
- src: compositions/frames/09-ai-child.html

The other half of the ecosystem, after the demo has proved the voice control.

## Frame 10 — User benefits

- type: benefit_highlight
- segment: contents
- scene: Five benefit cards land on their spoken phrases
- start: 2:06 (125.81s)
- duration: 10.56s
- transition_in: crossfade
- status: animated
- blueprint: grid-card-assemble
- rules: spring-pop-entrance, ambient-glow-bloom
- voiceover: "One app instead of many. Hands-free control. Peace of mind at work. Less wasted power — and no rewiring."
- voice: Sulafat
- src: compositions/frames/10-benefits.html

Guideline requirement: practical advantages for the user.

## Frame 11 — Impact: SDGs & ESG, equal weight

- type: benefit_highlight
- segment: contents
- scene: Four SDG tiles, then three ESG tiles in identical styling, side by side
- start: 2:16 (135.97s)
- duration: 16.48s
- transition_in: crossfade
- status: animated
- blueprint: grid-card-assemble
- rules: waterfall-entry, spring-pop-entrance
- voiceover: "Maya delivers on four S-D-Gs: safer communities, well-being, clean energy, responsible consumption."
- voice: Puck
- voiceover: "And on all three E-S-G pillars: less standby waste, safer children, open and secure governance."
- voice: Sulafat
- src: compositions/frames/11-sdg-esg.html

Shortened at the user's request to make room for the demo and the commercial section; ESG keeps the same tile treatment as the SDGs.

## Frame 12 — Market value & opportunity

- type: social_proof
- segment: contents
- scene: Three growth bars rise with count-up values and their sources
- start: 2:32 (152.05s)
- duration: 11.65s
- transition_in: crossfade
- status: animated
- blueprint: dataviz-countup
- rules: counting-dynamic-scale, stat-bars-and-fills
- voiceover: "The market is ready. Smart homes are heading to four hundred and fifty billion US dollars by twenty thirty-two, smart plugs to thirty billion, and parental-control software to over four billion."
- voice: Puck
- src: compositions/frames/12-market.html

Third-party market figures, one firm per claim, source on screen.

## Frame 13 — Commercial opportunity: buyers, price, channel

- type: social_proof
- segment: contents
- scene: Three cards: who buys, the kit at a proposed RM199 with an optional RM5/month plan, and the sales channels
- start: 2:43 (163.30s)
- duration: 19.32s
- transition_in: crossfade
- status: animated
- blueprint: grid-card-assemble
- rules: counting-dynamic-scale, spring-pop-entrance
- voiceover: "If we take this to market, the natural buyers would be working families with school-age children. Our suggestion is a kit — the three-channel socket with the app included — at around one hundred and ninety-nine ringgit, sold through online marketplaces and school and community partners, with an optional cloud plan at ten ringgit a month, or a hundred ringgit a year."
- voice: Puck
- src: compositions/frames/13-commercial.html

Guideline requirement: target users, proposed pricing and route to market. Pricing is labelled as a proposal and sits against the ≈RM95 hardware cost shown in the next scene.

## Frame 14 — Evidence, social proof & active development

- type: social_proof
- segment: contents
- scene: Survey rings, 40/40 tests, real cost, the prototype photo, and the iteration strip
- start: 3:02 (182.22s)
- duration: 16.85s
- transition_in: crossfade
- status: animated
- blueprint: dataviz-countup
- rules: stat-bars-and-fills, counting-dynamic-scale
- voiceover: "Eighty-four percent of parents find smart extensions useful, and eighty-two percent would install a child monitoring app. Our prototype passed all forty tests on about ninety-five ringgit of hardware — and development is active: iteration four, for sensors and hubs, is underway."
- voice: Puck
- src: compositions/frames/14-evidence.html

Guideline requirement: evidence, real-world example, implementation cost.

## Frame 15 — IP & research

- type: social_proof
- segment: contents
- scene: Apache 2.0 licence card with the repo, and the UNISEL research card
- start: 3:19 (198.68s)
- duration: 7.93s
- transition_in: crossfade
- status: animated
- blueprint: titlecard-reveal
- rules: ambient-glow-bloom, svg-path-draw
- voiceover: "Maya is open source under the Apache two point zero license, built on research at Universiti Selangor."
- voice: Sulafat
- src: compositions/frames/15-ip.html

Guideline requirement: IP status and research base. No patent claims.

## Frame 16 — Conclusion: the X-factor

- type: cta
- segment: conclusion
- scene: Statement beats, then the logo lockup with title, Project ID and thank you
- start: 3:26 (206.21s)
- duration: 18.21s
- transition_in: crossfade
- status: animated
- blueprint: kinetic-type-beats
- rules: kinetic-beat-slam, logo-assemble-lockup
- voiceover: "Other smart homes switch things on and off."
- voice: Sulafat
- voiceover: "Maya understands your family."
- voice: Puck
- voiceover: "Affordable, intelligent and open — so every working parent can breathe easy, knowing home is in good hands."
- voice: Sulafat
- voiceover: "Maya: home, handled."
- voice: Puck
- src: compositions/frames/16-close.html

The standout point: other smart homes switch things on and off; Maya understands the family.
