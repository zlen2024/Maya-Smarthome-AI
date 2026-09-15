"""Gemini TTS helper: text -> 24 kHz mono 16-bit WAV. Stdlib only.

Usage:
  python gemini_tts.py --voice Kore --out out.wav --text "Hello"
  python gemini_tts.py --voice Kore --out out.wav --text-file line.txt [--style "..."]
Reads GEMINI_API_KEY from the environment or from --key-file (KEY=VALUE lines).
"""
import argparse, base64, json, os, sys, time, urllib.error, urllib.request, wave

MODELS = ["gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts"]


def load_key(path, key_name=None):
    """Read one API key by name (default GEMINI_API_KEY; e.g. GEMINI_API_KEY2 for a second account)."""
    key_name = key_name or os.environ.get("TTS_KEY_NAME") or "GEMINI_API_KEY"
    accepted = (key_name, "GOOGLE_API_KEY") if key_name == "GEMINI_API_KEY" else (key_name,)
    if os.environ.get(key_name):
        return os.environ[key_name]
    if path and os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, value = line.split("=", 1)
                if name.strip() in accepted:
                    return value.strip().strip('"').strip("'")
    sys.exit(f"No {key_name} found (env or key file).")


def synthesize(key, model, voice, prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.load(resp)
    for part in data["candidates"][0]["content"]["parts"]:
        if "inlineData" in part:
            return base64.b64decode(part["inlineData"]["data"])
    raise RuntimeError("No audio in response")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--text")
    ap.add_argument("--text-file")
    ap.add_argument("--style", default="Read this as a confident, warm pitch presenter at a lively but clear pace:")
    ap.add_argument("--key-file", default=os.path.expanduser("~/.api-key-store.env"))
    a = ap.parse_args()
    text = a.text if a.text is not None else open(a.text_file, encoding="utf-8").read().strip()
    key = load_key(a.key_file)
    prompt = f"{a.style}\n\n{text}" if a.style else text
    last = None
    for model in MODELS:
        for attempt in range(3):
            try:
                pcm = synthesize(key, model, a.voice, prompt)
                os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
                with wave.open(a.out, "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
                print(f"OK {a.out} model={model} voice={a.voice} seconds={len(pcm)/48000:.2f}")
                return
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="replace")[:300]
                last = f"{model}: HTTP {e.code} {msg}"
                if e.code in (429, 500, 503):
                    time.sleep(4 * (attempt + 1)); continue
                break
            except Exception as e:  # noqa: BLE001
                last = f"{model}: {e}"; time.sleep(2)
    sys.exit(f"FAILED {a.out}: {last}")


if __name__ == "__main__":
    main()
