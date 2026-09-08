# Maya AI agent

The tool-calling assistant. Split deliberately across two files, and the split is
the main thing to understand.

## The split: `ai.py` is thin and DB-free

`software/server/ai.py` (142 lines) holds **only** the system prompt, the tool
schemas, and the single model call. Its module docstring states the rule:

> *"This module is deliberately thin and DB-free: it holds the system prompt and
> the tool schemas, and makes the single model call (`call_model`). The agent
> loop — executing tool calls with every permission/privacy check, and looping
> until the model stops asking for tools — lives in main.py, which owns the
> database, the device connections, and the caller's identity."*

That is a real architectural boundary, not aspiration: `ai.py` imports only `os`,
`json` and `fastapi.HTTPException`.

**Model:** `gpt-oss:20b-cloud` on Ollama Cloud (`https://ollama.com`), reached
with a bearer `OLLAMA_API_KEY`. `OLLAMA_MODEL` and `OLLAMA_HOST` override
(`ai.py:18`–`:19`, `:84`–`:94`). Missing key → HTTP 503, not a crash.

> ⚠ `ai.py` is invisible to the graph — `main.py` uses `import ai`, so no
> `main.py → ai.py` edge exists and `usages call_model` is empty despite the real
> call at `main.py:1578`.
> [known-gaps §2](known-gaps.md#2-bare-import-ai-is-invisible--aipy-is-an-orphan-in-the-graph)

## The loop

`run_maya_agent` (`main.py:1570`) is the whole agent, and it is short:

```python
for _ in range(MAYA_MAX_STEPS):
    msg = await asyncio.to_thread(ai.call_model, messages)  # sync IO off the loop
    if getattr(msg, "tool_calls", None):
        messages.append(msg)
        for tc in msg.tool_calls:
            call = ai.tool_call_dict(tc)
            result = await _execute_maya_tool(..., call["name"], call["arguments"])
            messages.append({"role": "tool", "content": result, "tool_name": call["name"]})
        continue
    reply = (msg.content or "").strip()
    break
```

Three details worth keeping:

1. **The Ollama client is synchronous**, so it is pushed to a thread with
   `asyncio.to_thread` rather than blocking the event loop.
2. **Bounded** by `MAYA_MAX_STEPS = 5` (`main.py:1394`, commented *"cap tool-call
   rounds so a loop can't run forever"*); on exhaustion it returns
   `"Sorry, I couldn't finish that."`
3. **Tool side effects still happen** even on the voice path — noted in the
   docstring.

### Two entry points, one loop

`code2graph usages run_maya_agent` returns exactly two call sites:

| Caller | Path | Behaviour |
|---|---|---|
| `_run_maya()` `main.py:1601` | Chat — someone `@maya`s in house chat | Posts the reply to chat via `_maya_say` |
| `maya_voice()` `main.py:1704` | `POST /api/maya/voice` from the voice overlay | Returns the reply privately |

`_run_maya` is a background task that owns its own `SessionLocal()` and is
written to **never raise into the WS loop** — `HTTPException` becomes a chat
apology, any other exception becomes a generic one, and `db.close()` is in a
`finally`.

`_maya_say` calls `db.rollback()` before writing "to clear any half-done tool
transaction before writing the reply" — i.e. a tool that failed mid-transaction
must not poison Maya's own message.

## Tools

Six, declared in `ai.TOOLS` (`ai.py:32`) and executed by `_execute_maya_tool`
(`main.py:1468`):

| Tool | Who may call it |
|---|---|
| `control_device` | Anyone in the house; child commands pass `_child_command_denial` |
| `get_child_location` | Parents; a child asking about anyone else gets *"You can only ask about yourself."* |
| `list_homework` | ditto |
| `get_screen_time` | ditto |
| `add_homework` | **Parents only** |
| `read_activity_log` | House members (limit 1–50, default 15) |

### Permissions live in the code, not the prompt

`_resolve_child_for` (`main.py`) is the privacy boundary for the three child-data
tools: a child sender is pinned to their own record and any other name is
refused; a parent with one child gets that child by default, and with several is
asked *"Which child? Please name them."* `add_homework` returns *"Only a parent
can assign homework."* before it resolves anything.

The system prompt tells the model *"Permission and privacy are enforced by the
tools, not by you: just call the tool and report what it returns."* This is
correct and matches the implementation — `_execute_maya_tool` re-checks device
existence and house scope, `device.blocked`, `_child_command_denial`, and
parent-only guards, then logs to the activity log via `log_activity`. The model
is never trusted with authorization.

### The dispatch has no graph edges

`_execute_maya_tool` is an `if name == "..."` chain over the string from the
model. Tools are **not** separate functions, so no symbol and no edge links a
declared schema to its implementation — the connection is string equality alone.
A renamed schema, or a permission check dropped from one branch, is invisible to
every graph query. Review this function by reading it.
[known-gaps §4](known-gaps.md#4-mayas-ai-tools-are-string-dispatched--no-edges-at-all) ·
[security notes §5](security-notes.md#5-mayas-tool-permissions-are-enforced-server-side--correctly)

## Automation: the screen-limit alert

`_notify_screen_limit` fires when a child's reported screen time crosses their
limit. It posts a Maya chat message, `@`-mentions **every parent and the child**,
writes an activity-log entry and broadcasts to the house — all wrapped
best-effort so *"a failed alert never breaks the report request."* This is the
one place Maya speaks without being addressed.
