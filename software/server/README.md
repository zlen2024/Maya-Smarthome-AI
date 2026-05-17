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
- `--host 0.0.0.0 --port 8000`: (Optional) Use these flags to expose the server on a specific host and port.
