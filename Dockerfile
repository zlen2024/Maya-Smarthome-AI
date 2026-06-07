# ==========================================
# Builder Stage
# ==========================================
FROM python:3.12-slim AS builder

WORKDIR /app

# Copy uv binary from its official image for fast dependency installation
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy the requirements file from the server directory
COPY software/server/requirements.txt ./

# Create a virtual environment and install the dependencies
RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN uv pip install --no-cache -r requirements.txt

# ==========================================
# Runner Stage
# ==========================================
FROM python:3.12-slim

WORKDIR /app

# Copy the virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy the server source files into the container working directory
COPY software/server/ /app/

# Expose the default Fly.io port
EXPOSE 8080

# Configure Python environment variables
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

# Command to start the FastAPI application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
