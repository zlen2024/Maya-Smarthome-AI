"""Generate narration lines with Gemini TTS and keep assets/voice/manifest.json in sync.

Run from the project root:
  python tools/gen_voice.py                                  # every line, default key + model order
  python tools/gen_voice.py --only 14c-close,14d-close --key-name GEMINI_API_KEY2 \
      --models gemini-2.5-flash-preview-tts
  python tools/gen_voice.py --only 01-hook --models gemini-2.5-flash-preview-tts --out-dir assets/voice/alt-2.5

Keys come from the environment or ~/.api-key-store.env (KEY=VALUE lines); --key-name picks which one.
The manifest is only written for the default output directory (assets/voice); alternates are side files.
"""
import argparse, json, os, re, sys, time, urllib.error, wave

sys.path.insert(0, os.path.dirname(__file__))
import gemini_tts  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = "assets/voice"


def seconds(path):
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


def retry_delay(body, attempt):
    """Seconds to wait after a 429: the API's retryDelay when given, else exponential backoff."""
    m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', body)
    return float(m.group(1)) + 2 if m else min(120, 15 * (2 ** attempt))


def run_line(key, styles, line, models, out_rel, attempts=6):
    out = os.path.join(ROOT, out_rel, f"{line['id']}.wav")
    prompt = f"{styles[line['voice']]}\n\n{line['text']}"
    last = None
    for model in models:
        for attempt in range(attempts):
            try:
                pcm = gemini_tts.synthesize(key, model, line["voice"], prompt)
                with wave.open(out, "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
                return {**line, "path": f"{out_rel}/{line['id']}.wav", "model": model,
                        "seconds": round(seconds(out), 3)}
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                last = f"{model}: HTTP {e.code} {body[:400]}"
                if e.code == 429 and "PerDay" in body:
                    print(f"{line['id']}: daily quota exhausted on {model}", flush=True)
                    break
                if e.code in (429, 500, 503):
                    wait = retry_delay(body, attempt)
                    print(f"{line['id']}: HTTP {e.code} on {model}, retrying in {wait:.0f}s", flush=True)
                    time.sleep(wait)
                    continue
                break
            except Exception as e:  # noqa: BLE001
                last = f"{model}: {e}"
                time.sleep(5)
    return {**line, "error": last}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--key-name", default="GEMINI_API_KEY")
    ap.add_argument("--models", default="", help="comma list; default tries gemini_tts.MODELS in order")
    ap.add_argument("--out-dir", default=DEFAULT_OUT)
    a = ap.parse_args()
    spec = json.load(open(os.path.join(ROOT, "tools", "voice_lines.json"), encoding="utf-8"))
    key = gemini_tts.load_key(os.path.expanduser("~/.api-key-store.env"), a.key_name)
    models = [m for m in a.models.split(",") if m] or list(gemini_tts.MODELS)
    out_rel = a.out_dir.strip("/").replace("\\", "/")
    os.makedirs(os.path.join(ROOT, out_rel), exist_ok=True)
    wanted = set(filter(None, a.only.split(",")))
    lines = [l for l in spec["lines"] if not wanted or l["id"] in wanted]
    results = []
    for i, l in enumerate(lines):
        if i:
            time.sleep(8)  # stay under the TTS per-minute limit
        results.append(run_line(key, spec["styles"], l, models, out_rel))
        print(f"done {l['id']}", flush=True)

    for r in results:
        print(f"{r['id']:<16} {r['voice']:<8} " + (f"{r['seconds']:6.2f}s  {r['model']}" if "seconds" in r else f"ERROR {r['error']}"))

    if out_rel == DEFAULT_OUT:
        manifest_path = os.path.join(ROOT, DEFAULT_OUT, "manifest.json")
        merged = {}
        if os.path.exists(manifest_path) and wanted:
            merged = {r["id"]: r for r in json.load(open(manifest_path, encoding="utf-8"))["lines"]}
        merged.update({r["id"]: r for r in results if "seconds" in r or r["id"] not in merged})
        ordered = [merged[l["id"]] for l in spec["lines"] if l["id"] in merged]
        per_frame = {}
        for r in ordered:
            if "seconds" in r:
                per_frame[r["frame"]] = round(per_frame.get(r["frame"], 0) + r["seconds"], 3)
        total = round(sum(per_frame.values()), 3)
        json.dump({"lines": ordered, "per_frame_seconds": per_frame, "total_voice_seconds": total},
                  open(manifest_path, "w", encoding="utf-8"), indent=2)
        print("per frame:", per_frame)
        print("total voice seconds:", total)
    if any("error" in r for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
