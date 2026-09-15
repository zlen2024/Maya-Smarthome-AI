"""Duration sync: write real voice-driven scene durations from tools/timing.json into STORYBOARD.md.

Run from the project root: python tools/sync_storyboard.py [--status animated]
Synced durations come from the audio; do not hand-edit them in the storyboard.
"""
import argparse
import io
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def mmss(sec):
    return f"{int(sec // 60)}:{int(round(sec % 60)):02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", default="")
    a = ap.parse_args()
    timing = json.load(open(os.path.join(ROOT, "tools", "timing.json"), encoding="utf-8"))
    frames = {f["frame"]: f for f in timing["frames"]}
    total = timing["total_seconds"]
    path = os.path.join(ROOT, "STORYBOARD.md")
    text = io.open(path, encoding="utf-8").read()

    intro_end = frames[2]["start"] + frames[2]["duration"]
    concl_start = frames[14]["start"]
    seg = (f'segments: "Intro 0:00–{mmss(intro_end)} ({intro_end / total:.0%}) · Contents {mmss(intro_end)}–'
           f'{mmss(concl_start)} ({(concl_start - intro_end) / total:.0%}) · Conclusion {mmss(concl_start)}–'
           f'{mmss(total)} ({(total - concl_start) / total:.0%})"')
    text = re.sub(r"(?m)^duration: .*$", f"duration: {total:.1f}s", text, count=1)
    text = re.sub(r"(?m)^segments: .*$", lambda m: seg, text, count=1)

    parts = re.split(r"(?m)^(?=## Frame \d+ — )", text)
    out = [parts[0]]
    for part in parts[1:]:
        n = int(re.match(r"## Frame (\d+)", part).group(1))
        f = frames[n]
        part = re.sub(r"(?m)^- duration: .*$", f"- duration: {f['duration']:.2f}s", part, count=1)
        if a.status:
            part = re.sub(r"(?m)^- status: .*$", f"- status: {a.status}", part, count=1)
        out.append(part)
    io.open(path, "w", encoding="utf-8", newline="\n").write("".join(out))
    print(f"storyboard synced: total {total:.2f}s; {seg}")


if __name__ == "__main__":
    main()
