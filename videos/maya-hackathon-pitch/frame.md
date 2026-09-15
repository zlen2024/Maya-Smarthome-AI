---
name: MAYA Obsidian Chrome (light)
source: user reference "Obsidian Chrome" palette, 2026-09-15 — supersedes DESIGN.md colours for this video
colors:
  canvas: "#E5E4E2"        # Alabaster Grey — the ground of every frame
  ink: "#0A0A0A"           # Onyx — headlines, body, numbers
  accent: "#536878"        # Blue Slate — focal element, display-size accent text, key rules
  accent-deep: "#3E4F5C"   # derived darker Blue Slate — accent text under 48px (AA on canvas)
  mist-slate: "rgba(83, 104, 120, 0.48)"   # gradient wash
  mist-onyx: "rgba(10, 10, 10, 0.38)"      # gradient cap, top-right corner only
  highlight: "rgba(255, 255, 255, 0.75)"   # soft light bloom, bottom-left
  surface: "rgba(255, 255, 255, 0.45)"     # frosted chrome card fill
  hairline: "rgba(10, 10, 10, 0.14)"       # card borders, table rules
  ink-muted: "rgba(10, 10, 10, 0.62)"      # labels, sources
  on-accent: "#FFFFFF"     # text on Blue Slate blocks, toggle knobs (small UI only)
  sdg-exception:           # official UN goal colours, Frame 10 tiles only
    sdg3: "#4C9F38"
    sdg7: "#FCC30B"
    sdg11: "#FD9D24"
    sdg12: "#BF8B2E"
typography:
  display: { family: "Montserrat", weights: [900, 700], tracking: "-0.03em" }
  body: { family: "Montserrat", weights: [400] }
  data: { family: "JetBrains Mono", weights: [400, 700], use: "numbers in stats, labels, sources, device IDs, tool calls" }
  sizes: { hero: "120-180px", headline: "64-96px", subhead: "44-56px", body: "28-40px", label: "22-26px" }
spacing:
  frame-padding: "90px 120px"
  gap: "24-48px"
  card-radius: "24px"
  pill-radius: "999px"
components:
  canvas-gradient: >
    radial-gradient(42% 48% at 96% -6%, mist-onyx, transparent 70%),
    radial-gradient(62% 62% at 80% 0%, mist-slate, transparent 72%),
    radial-gradient(55% 60% at 0% 100%, highlight, transparent 70%), canvas
  card: "surface fill, 3px hairline border, 24px radius, backdrop blur 18px, soft shadow 0 24px 60px rgba(10,10,10,0.10)"
  focal-card: "card with a 3px accent border and a slow accent glow"
  stat: "JetBrains Mono 700 number with tabular-nums, Montserrat 400 caption, JetBrains Mono source line in ink-muted"
  phone-media: "dark app screenshots sit in a rounded Onyx device frame with a soft shadow, never full-bleed"
---

## Overview

A light, misty chrome look taken from the user's Obsidian Chrome reference: an Alabaster Grey
ground with a soft Blue Slate and Onyx haze drifting in from the top-right corner, like light
on brushed metal. Calm, premium, trustworthy — the opposite of the app's dark aurora UI, which
appears only inside device frames.

## The Frame

- Every frame shares the canvas gradient; the haze may drift slowly but always stays in the
  top-right quadrant so text zones stay light.
- Onyx ink on Alabaster for all copy. Blue Slate is the one accent per frame — the focal number,
  the focal card border, a key rule. Use accent-deep for accent text below 48px.
- Frosted white chrome cards with hairline borders carry grouped content.
- Radial gradients only — no full-screen linear gradients (they band under H.264).

## Composition Rules

- Anchor content to the left/top; let the haze own the top-right.
- One expressive voice per frame: Montserrat 900 for statements, JetBrains Mono for data and
  attribution.
- Real media (app screenshots, the showcase photo) is framed, never stretched full-bleed.
- Frame 10 may use the official SDG goal colours on its number blocks only; ESG tiles mirror
  them in Blue Slate tints so both panels carry equal weight.

## Do / Don't

- Do keep contrast AA: never place ink text over the densest part of the haze.
- Do keep sources visible on every data frame.
- Don't reintroduce the dark aurora background, neon cyan, or magenta.
- Don't use gradient text or left-edge accent stripes.
