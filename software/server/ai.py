"""Maya AI agent — natural-language command processing via Ollama Cloud.

Pure LLM logic only: builds the prompt, calls the Ollama-hosted model, and
parses its JSON answer into {"reply": str, "actions": [...]}. Executing the
actions (with every permission check) is main.py's job — this module never
touches the database or the device connections.

Model runs on Ollama's cloud (the ``-cloud`` suffix); the client reaches it at
https://ollama.com with a bearer key. Set OLLAMA_API_KEY as an env var / Fly
secret. OLLAMA_MODEL overrides the default model.
"""
import os
import json

from fastapi import HTTPException

OLLAMA_HOST = "https://ollama.com"
DEFAULT_MODEL = "gpt-oss:20b-cloud"
VALID_CMDS = ("on", "off", "all_on", "all_off")

SYSTEM_PROMPT = """You are Maya, the AI assistant inside a family smart-home chat. Household members talk to you by mentioning @maya. You can chat and you can control smart power extension devices (each has up to 3 switchable relay channels).

Reply with ONLY a JSON object, no markdown fences, in exactly this shape:
{"reply": "<short friendly reply>", "actions": [{"device_id": "<id>", "cmd": "on", "channel": 1}]}

Rules:
- "cmd" is one of: "on", "off", "all_on", "all_off". For all_on/all_off the channel is ignored.
- "actions" is [] when the user is only chatting or asking a question.
- Only use device_ids and channels that appear in the house state below. Match the user's words ("the lamp", "channel 2") to the named devices/channels there.
- If the request is impossible (unknown device or channel), set actions to [] and say so in "reply".
- Keep "reply" to 1-3 sentences. Do not mention JSON or that you are a model."""


def build_context(devices: list, history: list) -> str:
    """Render the house's device state and recent chat into the prompt suffix.

    devices: [{"device_id","name","online","channels":[{"channel","name","is_on"}]}]
    history: [{"role":"user"/"assistant","name":str,"content":str}] oldest-first.
    """
    lines = ["Current house devices:"]
    if not devices:
        lines.append("  (no devices registered in this house)")
    for d in devices:
        state = "online" if d.get("online") else "offline"
        lines.append(f"- device_id={d['device_id']} name=\"{d.get('name','')}\" ({state})")
        for ch in d.get("channels", []):
            onoff = "on" if ch.get("is_on") else "off"
            lines.append(f"    channel {ch['channel']}: \"{ch.get('name','')}\" is {onoff}")

    lines.append("\nRecent conversation (oldest first):")
    if not history:
        lines.append("  (no earlier messages)")
    for h in history:
        who = h.get("name") or ("Maya" if h.get("role") == "assistant" else "User")
        lines.append(f"  {who}: {h.get('content','')}")
    return "\n".join(lines)


def ask_maya(message: str, devices: list, history: list) -> dict:
    """Call the model and return {"reply", "actions"}. Raises HTTPException on
    provider/config failure so callers can surface a clean message."""
    api_key = os.environ.get("OLLAMA_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503,
                            detail="AI is not configured (OLLAMA_API_KEY not set)")
    model = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)

    try:
        from ollama import Client
    except ImportError:
        raise HTTPException(status_code=503, detail="AI dependency 'ollama' not installed")

    client = Client(host=os.environ.get("OLLAMA_HOST", OLLAMA_HOST),
                    headers={"Authorization": f"Bearer {api_key}"})
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + build_context(devices, history)},
        {"role": "user", "content": message},
    ]
    try:
        resp = client.chat(model=model, messages=messages, format="json")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI provider error: {e}")

    content = getattr(resp.message, "content", "") or ""
    return parse_ai_response(content)


def parse_ai_response(content: str) -> dict:
    """Extract {"reply", "actions"} from model output. Tolerates markdown
    fences and stray prose; falls back to treating the whole text as the reply.
    Invalid actions are dropped; the list is hard-capped so a model can never
    bulk-fire the whole house from one message."""
    text = (content or "").strip()
    start, end = text.find("{"), text.rfind("}")
    data = None
    if start != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            data = None
    if not isinstance(data, dict):
        return {"reply": text or "Sorry, I didn't catch that.", "actions": []}

    reply = str(data.get("reply", "")).strip() or "Done."
    raw_actions = data.get("actions")
    actions = []
    for a in raw_actions if isinstance(raw_actions, list) else []:
        if not isinstance(a, dict):
            continue
        device_id = str(a.get("device_id", "")).strip()
        cmd = str(a.get("cmd", "")).strip()
        channel = a.get("channel", 1)
        if not device_id or cmd not in VALID_CMDS:
            continue
        if not isinstance(channel, int) or not 1 <= channel <= 3:
            channel = 1
        actions.append({"device_id": device_id, "cmd": cmd, "channel": channel})
    return {"reply": reply, "actions": actions[:5]}


if __name__ == "__main__":
    # Self-check for the parser — the only non-trivial pure logic here.
    r = parse_ai_response('{"reply": "Turning on the lamp.", "actions": [{"device_id": "MAYA-1", "cmd": "on", "channel": 2}]}')
    assert r["reply"] == "Turning on the lamp." and r["actions"] == [{"device_id": "MAYA-1", "cmd": "on", "channel": 2}]

    r = parse_ai_response('```json\n{"reply": "ok", "actions": []}\n```')
    assert r == {"reply": "ok", "actions": []}

    r = parse_ai_response("Sorry, I can't help with that.")
    assert r == {"reply": "Sorry, I can't help with that.", "actions": []}

    r = parse_ai_response('{"reply": "x", "actions": [{"device_id": "D", "cmd": "explode"}, {"device_id": "D", "cmd": "off", "channel": 99}]}')
    assert r["actions"] == [{"device_id": "D", "cmd": "off", "channel": 1}]

    ctx = build_context(
        [{"device_id": "D1", "name": "Living Room", "online": True,
          "channels": [{"channel": 1, "name": "Lamp", "is_on": False}]}],
        [{"role": "user", "name": "Ali", "content": "@maya turn on the lamp"}],
    )
    assert "device_id=D1" in ctx and "Lamp" in ctx and "Ali:" in ctx

    print("ai.py self-check OK")
