"""Duration sync + cue sheet: real voice lengths -> scene slots, audio placement, and per-phrase cue times.

Run from the project root: python tools/cues.py
Writes tools/timing.json. Missing voice lines (not generated yet) use a 2.4 words/sec estimate and are
flagged "estimated" so they can be re-synced once the audio exists.

Scenes are an ordered list. A scene may be:
  - narrated: its lines (from tools/voice_lines.json) drive its duration, or
  - media:    a fixed-duration clip that carries its own audio (the real app demo), no TTS.

Cue times are proportional estimates inside each line's speech window (Gemini TTS returns no word
timestamps): t = line_start + lead + (char_offset / total_chars) * speech_seconds.
"""
import json
import os
import re
import subprocess
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ffmpeg", "ffmpeg-9.0.1-essentials_build", "bin", "ffmpeg.exe")

VOICE_OFFSET = 0.35   # voice starts this long after its scene slot starts (crossfade settles first)
TAIL_PAD = 0.25       # scene holds this long after its last line ends
OVERLAP = 0.40        # crossfade overlap between consecutive scene slots
LINE_GAP = {"11b-esg": 0.20, "16b-close": 0.15, "16c-close": 0.30, "16d-close": 0.30}
FINAL_HOLD = 1.5      # extra hold on the last frame (logo lockup) before the end
EST_WPS = 2.4

# The real app-demo clip: its own narration + assistant replies carry the scene.
DEMO = {"slug": "08-demo", "media": "assets/media/voice-demo.mp4", "media_seconds": 37.4,
        "lead_in": 0.6,   # our line plays over the clip's quiet opening
        "tail_pad": 0.5}

SCENES = ["01-hook", "02-title", "03-problem", "04-pain", "05-shortcomings", "06-concept", "07-hardware",
          "08-demo", "09-ai-child", "10-benefits", "11-sdg-esg", "12-market", "13-commercial",
          "14-evidence", "15-ip", "16-close"]

CUES = {
    "01-hook": ["Three P.M.", "You're at work.", "Is the TV", "And where is your child"],
    "02-title": ["This is Maya", "family-centred", "One smart socket", "one AI assistant", "one family app"],
    "03-problem": ["Malaysian women", "fifty-six point six", "In our survey", "eighty percent", "unsupervised"],
    "04-pain": ["Parents juggle", "seventy percent", "while devices on standby", "almost ten percent"],
    "05-shortcomings": ["Today's options", "Most smart plugs", "Voice assistants", "And parental apps"],
    "06-concept": ["Maya connects", "home,", "parent", "and child", "in one family-centred hub"],
    "07-hardware": ["An E-S-P", "switches each outlet", "Set it up over Bluetooth", "and it stays synced"],
    "08-demo-lead": ["Here it is", "one spoken command"],
    "09-child": ["That was Maya", "The child app", "screen time", "outlet permissions"],
    "10-benefits": ["One app", "Hands-free", "Peace of mind", "Less wasted power", "and no rewiring"],
    "11a-sdg": ["four S-D-Gs", "safer communities", "well-being", "clean energy", "responsible consumption"],
    "11b-esg": ["E-S-G pillars", "less standby waste", "safer children", "open and secure"],
    "12-market": ["The market is ready", "Smart homes", "smart plugs to", "and parental-control"],
    "13-commercial": ["working families", "a kit", "one hundred and ninety-nine", "online marketplaces",
                      "ten ringgit a month"],
    "14-evidence": ["Eighty-four percent", "eighty-two percent", "Our prototype passed", "ninety-five ringgit",
                    "and development is active", "iteration four"],
    "15-ip": ["Maya is open source", "Apache", "built on research"],
    "16a-close": ["Other smart homes"],
    "16b-close": ["Maya understands"],
    "16c-close": ["Affordable", "intelligent", "and open", "so every working parent"],
    "16d-close": ["Maya: home, handled."],
}

# Beats inside the real demo clip, in clip-local seconds (source video time minus 211.8s).
DEMO_BEATS = [
    {"t": 0.2, "label": "Voice assistant · listening"},
    {"t": 3.2, "label": "“Buka lampu” · turn on the lamp"},
    {"t": 10.2, "label": "Relay clicks · lamp ON"},
    {"t": 15.4, "label": "“Tutup lampu lepas tu buka channel no. 1”"},
    {"t": 21.4, "label": "Lamp OFF"},
    {"t": 26.9, "label": "“Lampu dimatikan dan Channel 1 dinyalakan”"},
    {"t": 32.6, "label": "One outlet off, another on · independent control"},
]

def silence(path, dur):
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", path, "-af", "silencedetect=noise=-40dB:d=0.2", "-f", "null", "-"],
                       capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", p.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", p.stderr)]
    lead = ends[0] if starts and starts[0] < 0.05 and ends else 0.0
    tail = dur - starts[-1] if starts and (len(ends) < len(starts) or ends[-1] >= dur - 0.05) else 0.0
    return round(lead, 3), round(tail, 3)


def main():
    spec = json.load(open(os.path.join(ROOT, "tools", "voice_lines.json"), encoding="utf-8"))
    lines = []
    for l in spec["lines"]:
        path = os.path.join(ROOT, "assets", "voice", f"{l['id']}.wav")
        if os.path.exists(path):
            with wave.open(path) as w:
                dur = w.getnframes() / w.getframerate()
            lead, tail = silence(path, dur)
            lines.append({**l, "path": f"assets/voice/{l['id']}.wav", "seconds": round(dur, 3), "lead": lead,
                          "tail": tail, "estimated": False})
        else:
            words = len(l["text"].split())
            lines.append({**l, "path": f"assets/voice/{l['id']}.wav", "seconds": round(words / EST_WPS + 0.6, 3),
                          "lead": 0.3, "tail": 0.3, "estimated": True})

    frames = []
    t_slot = 0.0
    for n, slug in enumerate(SCENES, start=1):
        fl = [l for l in lines if l["frame"] == slug]
        local = VOICE_OFFSET
        placed = []
        for i, l in enumerate(fl):
            if i:
                local += LINE_GAP.get(l["id"], 0.2)
            speech = max(0.5, l["seconds"] - l["lead"] - l["tail"])
            cues = {}
            for phrase in CUES.get(l["id"], []):
                idx = l["text"].find(phrase)
                if idx < 0:
                    raise SystemExit(f"cue '{phrase}' not in {l['id']}")
                cues[phrase] = round(local + l["lead"] + idx / max(1, len(l["text"])) * speech, 2)
            placed.append({"id": l["id"], "voice": l["voice"], "path": l["path"], "local_start": round(local, 3),
                           "seconds": l["seconds"], "estimated": l["estimated"], "cues": cues})
            local += l["seconds"]

        scene = {"frame": n, "slug": slug, "start": round(t_slot, 3), "lines": placed}
        if slug == DEMO["slug"]:
            # The clip runs from the top of the scene; our lead-in line plays over its quiet opening.
            scene["media"] = DEMO["media"]
            scene["media_start"] = DEMO["lead_in"]
            scene["beats"] = [{"t": round(b["t"] + DEMO["lead_in"], 2), "label": b["label"]} for b in DEMO_BEATS]
            dur = DEMO["lead_in"] + DEMO["media_seconds"] + DEMO["tail_pad"]
        else:
            dur = local + TAIL_PAD + (FINAL_HOLD if n == len(SCENES) else 0.0)
        scene["duration"] = round(dur, 2)
        frames.append(scene)
        t_slot += dur - OVERLAP

    total = round(frames[-1]["start"] + frames[-1]["duration"], 2)
    out = {"total_seconds": total, "overlap": OVERLAP, "voice_offset": VOICE_OFFSET, "frames": frames}
    json.dump(out, open(os.path.join(ROOT, "tools", "timing.json"), "w", encoding="utf-8"), indent=2)

    for f in frames:
        est = " (ESTIMATED lines)" if any(l["estimated"] for l in f["lines"]) else ""
        media = f"  media {f['media']}" if f.get("media") else ""
        print(f"F{f['frame']:>2} {f['slug']:<16} start {f['start']:7.2f}  dur {f['duration']:6.2f}{est}{media}")
        for l in f["lines"]:
            print(f"      {l['id']:<14} {l['voice']:<8} at {l['local_start']:5.2f}s len {l['seconds']:5.2f}  "
                  + ", ".join(f"{k!r}@{v}" for k, v in l["cues"].items()))
    intro = frames[1]["start"] + frames[1]["duration"]
    concl = frames[-1]["duration"]
    print(f"TOTAL {total:.2f}s ({int(total // 60)}:{total % 60:04.1f})  intro {intro:.1f}s ({intro / total:.0%})  "
          f"conclusion {concl:.1f}s ({concl / total:.0%})")


if __name__ == "__main__":
    main()
