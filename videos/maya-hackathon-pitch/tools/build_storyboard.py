"""Generate STORYBOARD.md from tools/timing.json + tools/voice_lines.json + the notes below.

Run from the project root: python tools/build_storyboard.py
Durations, voices and voiceover text are taken from the timing/voice files, so the board can never
drift from the cut. Scene intent lives in NOTES here.
"""
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HEAD_FIELDS = {
    "format": "1920x1080",
    "message": '"Maya turns an ordinary extension socket into a family-centred AI home that saves power and keeps children safe while parents work."',
    "arc": "Hook → Title & objectives → Problem → Shortcomings → Solution concept → Product (hardware, live demo, child app) → Benefits → SDG & ESG → Market → Commercial opportunity → Evidence → IP & research → X-factor close",
    "audience": "hackathon judges",
    "mode": "collaborative",
    "music": '"warm, hopeful modern tech underscore; soft piano and airy synth pads; gentle pulse; rises into an uplifting final lift"',
    "design": "frame.md (Obsidian Chrome light theme — Alabaster Grey #E5E4E2 canvas, Onyx #0A0A0A ink, Blue Slate #536878 accent, soft chrome gradient)",
}

# slug: (title, type, segment, scene caption, blueprint, rules, narrative)
NOTES = {
    "01-hook": ("Hook: 3 P.M.", "hook", "introduction",
                "A clock ticks to 3:00 PM; two questions snap in beside a glowing outlet and a location pin",
                "kinetic-type-beats", "kinetic-beat-slam, ambient-glow-bloom",
                "Cold open in the parent's own language, no product vocabulary. Hooks the judges inside 10s."),
    "02-title": ("Title, objectives & outline", "product_intro", "introduction",
                 "Maya logo blooms; full project title, Project ID CBN8426079 and four objective chips assemble",
                 "logo-assemble-lockup", "spring-pop-entrance, waterfall-entry",
                 "Guideline requirement: project title, core objectives, brief outline."),
    "03-problem": ("The problem: parents are stretched", "pain_point", "contents",
                   "Two hero stats count up — 56.6% women in the workforce, 80% of children 2h+ unsupervised",
                   "dataviz-countup", "counting-dynamic-scale, stat-bars-and-fills",
                   "Sources on screen: DOSM Q4 2025 and the project's own 73-parent survey."),
    "04-pain": ("The problem: app fatigue & wasted power", "pain_point", "contents",
                "App tiles pile up around a phone (70% app fatigue); a standby meter reads ~10%",
                "overwhelm-surround", "depth-scatter-assemble, counting-dynamic-scale",
                "Second pain: fragmentation plus the energy angle that carries SDG 7 and 12 later."),
    "05-shortcomings": ("Current shortcomings", "pain_point", "contents",
                        "Comparison table assembles row by row; the MAYA row stays a question mark",
                        "grid-card-assemble", "waterfall-entry, spring-pop-entrance",
                        "Guideline requirement: why existing market solutions fall short."),
    "06-concept": ("The potential solution: one family hub", "product_intro", "contents",
                   "Home, Parent and Child nodes connect into a glowing MAYA hub; the missing row lands ✓✓✓",
                   "constellation-hub", "spring-pop-entrance, svg-path-draw",
                   "The conceptual framework, before any product detail."),
    "07-hardware": ("Your product: the smart extension", "feature_showcase", "contents",
                    "Block diagram assembles; three outlets switch on one by one; camera pans to setup, cloud, apps",
                    "spatial-pan-stations", "viewport-change, svg-path-draw",
                    "How it works: ESP32, 3-channel relay, BLE provisioning, live WebSocket sync."),
    "08-demo": ("Live demo: one spoken command, one outlet", "feature_showcase", "contents",
                "Unedited screen recording: voice command → Maya processes → lamp switches, other channel unaffected",
                "device-surface-showcase", "(real footage; caption rail on the cue beats)",
                "The real app on the real hardware (user recording, 3:37–4:15). Beat rail marks: listening, "
                "“Buka lampu”, relay click and lamp ON, “tutup lampu lepas tu buka channel no. 1”, "
                "lamp OFF, and the reply proving one outlet off while another goes on. The clip's own sound carries "
                "the scene; the music bed ducks under it."),
    "09-ai-child": ("The child companion app", "feature_showcase", "contents",
                    "Child card: screen-time ring counts to 1h 42m, last known location, outlet permissions toggle",
                    "grid-card-assemble", "stat-bars-and-fills, spring-pop-entrance",
                    "The other half of the ecosystem, after the demo has proved the voice control."),
    "10-benefits": ("User benefits", "benefit_highlight", "contents",
                    "Five benefit cards land on their spoken phrases",
                    "grid-card-assemble", "spring-pop-entrance, ambient-glow-bloom",
                    "Guideline requirement: practical advantages for the user."),
    "11-sdg-esg": ("Impact: SDGs & ESG, equal weight", "benefit_highlight", "contents",
                   "Four SDG tiles, then three ESG tiles in identical styling, side by side",
                   "grid-card-assemble", "waterfall-entry, spring-pop-entrance",
                   "Shortened at the user's request to make room for the demo and the commercial section; "
                   "ESG keeps the same tile treatment as the SDGs."),
    "12-market": ("Market value & opportunity", "social_proof", "contents",
                  "Three growth bars rise with count-up values and their sources",
                  "dataviz-countup", "counting-dynamic-scale, stat-bars-and-fills",
                  "Third-party market figures, one firm per claim, source on screen."),
    "13-commercial": ("Commercial opportunity: buyers, price, channel", "social_proof", "contents",
                      "Three cards: who buys, the kit at a proposed RM199 with an optional RM5/month plan, and the sales channels",
                      "grid-card-assemble", "counting-dynamic-scale, spring-pop-entrance",
                      "Guideline requirement: target users, proposed pricing and route to market. Pricing is "
                      "labelled as a proposal and sits against the ≈RM95 hardware cost shown in the next scene."),
    "14-evidence": ("Evidence, social proof & active development", "social_proof", "contents",
                    "Survey rings, 40/40 tests, real cost, the prototype photo, and the iteration strip",
                    "dataviz-countup", "stat-bars-and-fills, counting-dynamic-scale",
                    "Guideline requirement: evidence, real-world example, implementation cost."),
    "15-ip": ("IP & research", "social_proof", "contents",
              "Apache 2.0 licence card with the repo, and the UNISEL research card",
              "titlecard-reveal", "ambient-glow-bloom, svg-path-draw",
              "Guideline requirement: IP status and research base. No patent claims."),
    "16-close": ("Conclusion: the X-factor", "cta", "conclusion",
                 "Statement beats, then the logo lockup with title, Project ID and thank you",
                 "kinetic-type-beats", "kinetic-beat-slam, logo-assemble-lockup",
                 "The standout point: other smart homes switch things on and off; Maya understands the family."),
}


def mmss(sec):
    return f"{int(sec // 60)}:{int(round(sec % 60)):02d}"


def main():
    timing = json.load(open(os.path.join(ROOT, "tools", "timing.json"), encoding="utf-8"))
    spec = json.load(open(os.path.join(ROOT, "tools", "voice_lines.json"), encoding="utf-8"))
    text_of = {l["id"]: l["text"] for l in spec["lines"]}
    total = timing["total_seconds"]
    by_slug = {f["slug"]: f for f in timing["frames"]}
    intro = by_slug["02-title"]["start"] + by_slug["02-title"]["duration"]
    concl = by_slug["16-close"]["start"]

    out = ["---\n"]
    out.append(f"format: {HEAD_FIELDS['format']}\n")
    out.append(f"duration: {total:.1f}s\n")
    out.append(f"message: {HEAD_FIELDS['message']}\n")
    out.append(f"arc: {HEAD_FIELDS['arc']}\n")
    out.append(f"audience: {HEAD_FIELDS['audience']}\n")
    out.append(f"mode: {HEAD_FIELDS['mode']}\n")
    out.append(f'segments: "Intro 0:00–{mmss(intro)} ({intro / total:.0%}) · Contents {mmss(intro)}–{mmss(concl)} '
               f'({(concl - intro) / total:.0%}) · Conclusion {mmss(concl)}–{mmss(total)} '
               f'({(total - concl) / total:.0%})"\n')
    out.append(f"music: {HEAD_FIELDS['music']}\n")
    out.append(f"design: {HEAD_FIELDS['design']}\n")
    out.append("---\n")

    for f in timing["frames"]:
        title, ftype, segment, scene, blueprint, rules, narrative = NOTES[f["slug"]]
        out.append(f"\n## Frame {f['frame']} — {title}\n\n")
        out.append(f"- type: {ftype}\n- segment: {segment}\n- scene: {scene}\n")
        out.append(f"- start: {mmss(f['start'])} ({f['start']:.2f}s)\n- duration: {f['duration']:.2f}s\n")
        out.append(f"- transition_in: {'cut' if f['frame'] == 1 else 'crossfade'}\n- status: animated\n")
        out.append(f"- blueprint: {blueprint}\n- rules: {rules}\n")
        for l in f["lines"]:
            out.append(f'- voiceover: "{text_of[l["id"]]}"\n- voice: {l["voice"]}\n')
        if f.get("media"):
            out.append(f"- media: {f['media']} (user recording, starts {f['media_start']}s into the scene)\n")
        out.append(f"- src: compositions/frames/{f['slug']}.html\n\n")
        out.append(narrative + "\n")

    path = os.path.join(ROOT, "STORYBOARD.md")
    io.open(path, "w", encoding="utf-8", newline="\n").write("".join(out))
    print(f"STORYBOARD.md written: {len(timing['frames'])} frames, total {total:.2f}s ({mmss(total)})")


if __name__ == "__main__":
    main()
