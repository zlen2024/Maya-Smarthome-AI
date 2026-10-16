"""Duration sync: write real voice-driven scene durations from tools/timing.json into STORYBOARD.md.

Run from the project root: python tools/sync_storyboard.py [--status animated]
Synced durations come from the audio (and, for the demo scene, the clip length); never hand-edit them.
Frames are matched by their `- src:` slug, so scene order can change without breaking the mapping.
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
    by_slug = {f["slug"]: f for f in timing["frames"]}
    total = timing["total_seconds"]
    path = os.path.join(ROOT, "STORYBOARD.md")
    text = io.open(path, encoding="utf-8").read()

    intro = by_slug["02-title"]["start"] + by_slug["02-title"]["duration"]
    concl = by_slug["16-close"]["start"]
    seg = (f'segments: "Intro 0:00–{mmss(intro)} ({intro / total:.0%}) · Contents {mmss(intro)}–{mmss(concl)} '
           f'({(concl - intro) / total:.0%}) · Conclusion {mmss(concl)}–{mmss(total)} ({(total - concl) / total:.0%})"')
    text = re.sub(r"(?m)^duration: .*$", f"duration: {total:.1f}s", text, count=1)
    text = re.sub(r"(?m)^segments: .*$", lambda m: seg, text, count=1)

    parts = re.split(r"(?m)^(?=## Frame )", text)
    out = [parts[0]]
    missed = []
    for part in parts[1:]:
        m = re.search(r"(?m)^- src: compositions/frames/([\w.-]+)\.html\s*$", part)
        f = by_slug.get(m.group(1)) if m else None
        if f:
            part = re.sub(r"(?m)^- duration: .*$", f"- duration: {f['duration']:.2f}s", part, count=1)
            if a.status:
                part = re.sub(r"(?m)^- status: .*$", f"- status: {a.status}", part, count=1)
        else:
            missed.append(m.group(1) if m else part.splitlines()[0])
        out.append(part)
    io.open(path, "w", encoding="utf-8", newline="\n").write("".join(out))
    print(f"storyboard synced: {len(by_slug)} scenes, total {total:.2f}s ({mmss(total)})")
    print(seg)
    if missed:
        print("WARNING — storyboard frames with no timing match:", ", ".join(missed))
    listed = {re.search(r"([\w.-]+)\.html", p).group(1) for p in re.findall(r"- src: compositions/frames/[\w.-]+\.html", text)}
    absent = [s for s in by_slug if s not in listed]
    if absent:
        print("WARNING — timed scenes missing from STORYBOARD.md:", ", ".join(absent))


if __name__ == "__main__":
    main()
