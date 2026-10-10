# Server Setup Guide

This guide provides instructions on how to set up the Python virtual environment using `uv` and how to run the `uvicorn` server.

## 1. Prerequisites

Ensure you have `uv` installed. If you don't have it installed, you can install it via:

```powershell
# On Windows
irm https://astral.sh/uv/install.ps1 | iex
```
*(For macOS/Linux, use: `curl -LsSf https://astral.sh/uv/install.sh | sh`)*

## 2. Creating a Virtual Environment

Navigate to the `software/server` directory and create a new virtual environment using `uv`:

```powershell
uv venv
```

This will create a `.venv` directory containing your isolated Python environment.

## 3. Activating the Virtual Environment

Before installing dependencies or running the server manually, you need to activate the virtual environment. 

**On Windows (PowerShell/CMD):**
```powershell
.\.venv\Scripts\activate
```

**On macOS/Linux:**
```bash
source .venv/bin/activate
```

*(You should see a `(.venv)` prefix in your terminal prompt after successful activation).*

## 4. Installing Dependencies

Once the virtual environment is activated, you can install your project dependencies (like `fastapi` and `uvicorn`) using `uv pip`:

```powershell
uv pip install -r requirements.txt
```
*(Or install them directly, e.g., `uv pip install fastapi uvicorn`)*

## 5. Running the Server

There are two ways to run the `uvicorn` server.

### Method A: Using `uvicorn` directly (Requires Activation)

If your virtual environment is **activated**, you can start the server using:

```powershell
uvicorn main:app --reload
```

### Method B: Using `uv run` (Recommended - No Activation Required)

You can use `uv run` to automatically execute the command within the virtual environment, even if you haven't activated it manually:

```powershell
uv run uvicorn main:app --reload
```

**Command Breakdown:**
- `main:app`: Refers to the `app` instance in the `main.py` file. Adjust this if your entry point is named differently (e.g., `server:app`).
- `--reload`: Enables auto-reloading so the server restarts automatically when you make code changes. (Do not use in production).
- `--host 0.0.0.0 --port 8080`: (Optional) Use these flags to expose the server on a specific host and port. You can use 8080 or any other port that you find easier to port forward.

## 6. Environment variables

The first two no longer have an insecure fallback — see
[`wiki/pages/security-notes.md`](../../wiki/pages/security-notes.md).

| Variable | Effect when set | Effect when absent |
|---|---|---|
| `SECRET_KEY` | Signs and verifies every JWT | A random key is generated per process and a warning is printed; all sessions die on restart |
| `ADMIN_PASSWORD_HASH` | bcrypt hash of the `/admin` Basic-auth password (user `admin`) | A random password is generated per process and printed to the log once |
| `DATABASE_URL` | SQLAlchemy URL | `sqlite:///./iot_data.db` |
| `OLLAMA_API_KEY` | Maya's model access (Ollama Cloud) | Maya's AI features are unavailable |
| `OLLAMA_MODEL` | Overrides the model id | Falls back to the default in `ai.py` |

Generate an admin hash with:

```powershell
uv run python -c "from auth import hash_password; print(hash_password('your-password'))"
```

On Fly these live as secrets (`fly secrets set SECRET_KEY=...`).

## 7. Self-checks

Two scripts, no test runner — run them directly:

```powershell
uv run python test_screen_limit.py   # screen-time alert fires once per day
uv run python test_security.py       # abuse limits, PIN rules, the join -> child-location chain
uv run python test_descriptor.py     # protocol 2: descriptors stored, protocol 1 shimmed
uv run python test_grants.py         # protocol 2 step 2: claiming, capability grants, labels
uv run python test_maya.py           # protocol 2 step 3: Maya's set_capability, deny + confirm gates
uv run python ../../hardware/libraries/Maya/extras/test/test_library.py   # protocol 2 step 4: the Arduino library vs this server (needs a C++ compiler)
```

`test_security.py` and `test_descriptor.py` boot the app against a throwaway
SQLite file — one replays the attack chain the limits exist to stop, the other
plays a protocol-1 and a protocol-2 device against the WebSocket. Both need
`httpx<0.28` (Starlette 0.36's TestClient is not compatible with newer httpx):

```powershell
uv pip install "httpx==0.27.2"
```

