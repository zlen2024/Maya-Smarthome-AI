"""Maya AI agent — a tool-using assistant backed by an Ollama Cloud model.

This module is deliberately thin and DB-free: it holds the system prompt and the
tool schemas, and makes the single model call (`call_model`). The agent loop —
executing tool calls with every permission/privacy check, and looping until the
model stops asking for tools — lives in main.py, which owns the database, the
device connections, and the caller's identity.

Model runs on Ollama's cloud (the ``-cloud`` suffix); the client reaches it at
https://ollama.com with a bearer key. Set OLLAMA_API_KEY (Fly secret).
OLLAMA_MODEL / OLLAMA_HOST override the defaults.
"""
import os
import json

from fastapi import HTTPException

OLLAMA_HOST = "https://ollama.com"
DEFAULT_MODEL = "gpt-oss:20b-cloud"

SYSTEM_PROMPT = """You are Maya, the AI assistant inside a family smart-home chat. Household members talk to you by mentioning @maya. You can chat, control the smart devices in the house, and look up household info using the provided tools. Each device lists the controls it reports (a switch, a speed slider, a mode, a button...) with a key, a type, its current value and its limits.

Guidelines:
- Use a tool when the user asks you to DO something (switch a device, assign homework) or asks for live info (a child's location, homework, screen-time, recent activity). Chat directly when no tool is needed.
- Match the user's words ("the TV", "the fan speed", "Ali") to the device_ids, control keys and names in the house state below. Use a control's key exactly as listed, and a value of the control's own type.
- A control marked "needs confirmation" is never set on the first ask: tell the user what you are about to do and ask. Only after they clearly say yes, call the tool again with confirmed=true.
- Controls marked "read-only" can be reported but not changed.
- Never claim you did something unless the tool result confirms it. If a tool returns an error or refusal, tell the user plainly.
- Keep replies to 1-3 short sentences. Never mention tools, JSON, or that you are a model.
- Permission and privacy are enforced by the tools, not by you: just call the tool and report what it returns."""

# Ollama tool schemas. The agent loop in main.py dispatches by function name and
# enforces who may call what — these descriptions only guide the model.
TOOLS = [
    {"type": "function", "function": {
        "name": "set_capability",
        "description": "Change one control on a device: switch a channel on or off, set a speed or mode, press a button. Use the device_id and key exactly as listed in the house state.",
        "parameters": {"type": "object", "properties": {
            "device_id": {"type": "string", "description": "Device id from the house state."},
            "key": {"type": "string", "description": "The control's key, e.g. ch1 or speed."},
            "value": {"description": "New value in the control's own type: \"on\" or \"off\" for a switch, a number for a slider or number, text for a mode or text control, null to press a button."},
            "confirmed": {"type": "boolean", "description": "true only after the user has clearly said yes to a control marked as needing confirmation."},
        }, "required": ["device_id", "key"]},
    }},
    {"type": "function", "function": {
        "name": "get_child_location",
        "description": "Last-known location and time for a child in the house.",
        "parameters": {"type": "object", "properties": {
            "child_name": {"type": "string", "description": "The child's name."},
        }, "required": ["child_name"]},
    }},
    {"type": "function", "function": {
        "name": "list_homework",
        "description": "List a child's homework tasks with due dates and completion.",
        "parameters": {"type": "object", "properties": {
            "child_name": {"type": "string"},
        }, "required": ["child_name"]},
    }},
    {"type": "function", "function": {
        "name": "get_screen_time",
        "description": "Today's screen-time used, limit, and remaining minutes for a child.",
        "parameters": {"type": "object", "properties": {
            "child_name": {"type": "string"},
        }, "required": ["child_name"]},
    }},
    {"type": "function", "function": {
        "name": "add_homework",
        "description": "Create a homework task for a child. Parents only.",
        "parameters": {"type": "object", "properties": {
            "child_name": {"type": "string"},
            "title": {"type": "string"},
            "due_date": {"type": "string", "description": "Optional due date, YYYY-MM-DD."},
        }, "required": ["child_name", "title"]},
    }},
    {"type": "function", "function": {
        "name": "read_activity_log",
        "description": "Recent house activity (device switches, homework, joins, logins).",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer", "description": "How many recent entries (default 15, max 50).", "minimum": 1, "maximum": 50},
        }},
    }},
]

TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


def _client():
    api_key = os.environ.get("OLLAMA_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="AI is not configured (OLLAMA_API_KEY not set)")
    try:
        from ollama import Client
    except ImportError:
        raise HTTPException(status_code=503, detail="AI dependency 'ollama' not installed")
    return Client(host=os.environ.get("OLLAMA_HOST", OLLAMA_HOST),
                  headers={"Authorization": f"Bearer {api_key}"})


def call_model(messages: list):
    """One model turn. Returns the response .message (has .content and, when the
    model wants a tool, .tool_calls). Raises HTTPException on provider/config
    failure. Synchronous network IO — call via asyncio.to_thread from the loop."""
    model = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
    client = _client()
    try:
        resp = client.chat(model=model, messages=messages, tools=TOOLS)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI provider error: {e}")
    return resp.message


def tool_call_dict(tool_call) -> dict:
    """Normalise an Ollama ToolCall into {"name", "arguments": {...}}.
    Arguments may arrive as a dict or a JSON string depending on the model."""
    fn = tool_call.function
    args = fn.arguments
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return {"name": fn.name, "arguments": args if isinstance(args, dict) else {}}


if __name__ == "__main__":
    # Self-check for the pure normalisation logic.
    class _FakeFn:
        def __init__(self, name, args): self.name, self.arguments = name, args
    class _FakeTC:
        def __init__(self, name, args): self.function = _FakeFn(name, args)

    d = tool_call_dict(_FakeTC("set_capability", {"device_id": "D", "key": "ch2", "value": "on"}))
    assert d == {"name": "set_capability", "arguments": {"device_id": "D", "key": "ch2", "value": "on"}}

    d = tool_call_dict(_FakeTC("list_homework", '{"child_name": "Ali"}'))
    assert d == {"name": "list_homework", "arguments": {"child_name": "Ali"}}

    d = tool_call_dict(_FakeTC("x", "not json"))
    assert d == {"name": "x", "arguments": {}}

    assert TOOL_NAMES == {"set_capability", "get_child_location", "list_homework",
                          "get_screen_time", "add_homework", "read_activity_log"}
    print("ai.py self-check OK")
