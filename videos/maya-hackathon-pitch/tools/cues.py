"""Duration sync + cue sheet: real voice lengths -> scene slots, audio placement, and per-phrase cue times.

Run from the project root: python tools/cues.py
Writes tools/timing.json. Missing voice lines (not generated yet) use a 2.4 words/sec estimate and are
flagged "estimated" so they can be re-synced once the audio exists.

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
LINE_GAP = {"10b-esg": 0.20, "14b-close": 0.15, "14c-close": 0.30, "14d-close": 0.30}
FINAL_HOLD = 1.5      # extra hold on the last frame (logo lockup) before the end
EST_WPS = 2.4

SLUGS = {1: "01-hook", 2: "02-title", 3: "03-problem", 4: "04-pain", 5: "05-shortcomings", 6: "06-concept",
         7: "07-hardware", 8: "08-ai-child", 9: "09-benefits", 10: "10-sdg-esg", 11: "11-market",
         12: "12-evidence", 13: "13-ip", 14: "14-close"}

CUES = {
    "01-hook": ["Three P.M.", "You're at work.", "Is the TV", "And where is your child"],
    "02-title": ["This is Maya", "family-centred", "One smart socket", "one AI assistant", "one family app"],
    "03-problem": ["Malaysian women", "fifty-six point six", "In our survey", "eighty percent", "unsupervised"],
    "04-pain": ["Parents juggle", "seventy percent", "while devices on standby", "almost ten percent"],
    "05-shortcomings": ["Today's options", "Most smart plugs", "Voice assistants", "And parental apps"],
    "06-concept": ["Maya connects", "home,", "parent", "and child", "in one family-centred hub"],
    "07-hardware": ["An E-S-P", "switches each outlet", "Set it up over Bluetooth", "and it stays synced"],
    "08-ai-child": ["Just say", "the AI agent finds", "The child app", "and parents set"],
    "09-benefits": ["One app", "Hands-free", "Peace of mind", "Less wasted power", "and no rewiring"],
    "10a-sdg": ["four S-D-Gs", "eleven", "three,", "seven,", "and twelve"],
    "10b-esg": ["E-S-G pillars", "Environmental", "Social", "Governance"],
    "11-market": ["The market is ready", "Smart homes", "smart plugs to", "and parental-control"],
    "12-evidence": ["Eighty-four percent", "eighty-two percent", "Our prototype passed", "ninety-five ringgit",
                    "and development is active", "iteration four"],
    "13-ip": ["Maya is open source", "Apache", "built on research"],
    "14a-close": ["Other smart homes"],
    "14b-close": ["Maya understands"],
    "14c-close": ["Affordable", "intelligent", "and open", "so every working parent"],
    "14d-close": ["Maya: home, handled."],
}


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
            dur = round(words / EST_WPS + 0.6, 3)
            lines.append({**l, "path": f"assets/voice/{l['id']}.wav", "seconds": dur, "lead": 0.3, "tail": 0.3,
                          "estimated": True})

    frames = []
    t_slot = 0.0
    for n in range(1, 15):
        fl = [l for l in lines if l["frame"] == n]
        local = VOICE_OFFSET
        placed = []
        for i, l in enumerate(fl):
            if i:
                local += LINE_GAP.get(l["id"], 0.2)
            speech = max(0.5, l["seconds"] - l["lead"] - l["tail"])
            cues = {}
            text = l["text"]
            for phrase in CUES.get(l["id"], []):
                idx = text.find(phrase)
                if idx < 0:
                    raise SystemExit(f"cue '{phrase}' not in {l['id']}")
                cues[phrase] = round(local + l["lead"] + idx / max(1, len(text)) * speech, 2)
            placed.append({"id": l["id"], "voice": l["voice"], "path": l["path"], "local_start": round(local, 3),
                           "seconds": l["seconds"], "estimated": l["estimated"], "cues": cues})
            local += l["seconds"]
        dur = local + TAIL_PAD + (FINAL_HOLD if n == 14 else 0.0)
        frames.append({"frame": n, "slug": SLUGS[n], "start": round(t_slot, 3), "duration": round(dur, 2),
                       "lines": placed})
        t_slot += dur - OVERLAP
    total = round(frames[-1]["start"] + frames[-1]["duration"], 2)
    out = {"total_seconds": total, "overlap": OVERLAP, "voice_offset": VOICE_OFFSET, "frames": frames}
    json.dump(out, open(os.path.join(ROOT, "tools", "timing.json"), "w", encoding="utf-8"), indent=2)

    for f in frames:
        est = " (includes ESTIMATED lines)" if any(l["estimated"] for l in f["lines"]) else ""
        print(f"F{f['frame']:>2} {f['slug']:<16} start {f['start']:7.2f}  dur {f['duration']:6.2f}{est}")
        for l in f["lines"]:
            cue_txt = ", ".join(f"{k!r}@{v}" for k, v in l["cues"].items())
            print(f"      {l['id']:<14} {l['voice']:<8} at {l['local_start']:5.2f}s len {l['seconds']:5.2f}  {cue_txt}")
    intro = frames[0]["duration"] + frames[1]["duration"] - OVERLAP
    concl = frames[-1]["duration"]
    print(f"TOTAL {total:.2f}s  intro {intro:.1f}s ({intro / total:.0%})  conclusion {concl:.1f}s ({concl / total:.0%})")


if __name__ == "__main__":
    main()
