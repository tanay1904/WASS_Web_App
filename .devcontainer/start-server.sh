#!/usr/bin/env bash
# ==============================================================================
# WASS 3D Sea Wave Reconstruction Web Studio - Codespaces Launch Script
# ==============================================================================
# This script ensures dependencies are satisfied, starts the Uvicorn application
# in the background with stdout/stderr redirected to /tmp/wass_webapp.log,
# and verifies server health at http://127.0.0.1:8080/api/status before exiting.
# ==============================================================================

set -euo pipefail

LOG_FILE="/tmp/wass_webapp.log"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"
HEALTH_URL="http://127.0.0.1:${PORT}/api/status"
MAX_ATTEMPTS=30

echo "[WASS Codespaces] Initializing WASS 3D Wave Studio service..."

# Detect Python & Pip commands
PYTHON_CMD="$(command -v python3 || command -v python || true)"
if [ -z "$PYTHON_CMD" ]; then
    echo "[WASS Codespaces ERROR] Python interpreter not found in PATH!" >&2
    exit 1
fi

PIP_CMD="$(command -v pip3 || command -v pip || true)"
if [ -z "$PIP_CMD" ]; then
    PIP_CMD="$PYTHON_CMD -m pip"
fi

# Ensure /tmp exists and log file is touchable
touch "$LOG_FILE" 2>/dev/null || true

# Function: Health check query
check_health() {
    if command -v curl >/dev/null 2>&1; then
        curl -s -f "$HEALTH_URL" >/dev/null 2>&1
    else
        $PYTHON_CMD -c "import urllib.request; urllib.request.urlopen('$HEALTH_URL', timeout=1)" >/dev/null 2>&1
    fi
}

# 1. Idempotency Check: Is server already running and healthy?
if check_health; then
    echo "[WASS Codespaces] Server is already running and responding at $HEALTH_URL."
    exit 0
fi

# 2. Dependency Verification: Are required packages importable?
echo "[WASS Codespaces] Verifying runtime dependencies..."
if ! $PYTHON_CMD -c "import uvicorn, fastapi, cv2, numpy, wass_webapp" >/dev/null 2>&1; then
    echo "[WASS Codespaces] Runtime dependencies missing or incomplete. Installing now..."
    echo "[WASS Codespaces] Running: $PIP_CMD install --upgrade pip && $PIP_CMD install -r requirements.txt && $PIP_CMD install -e ."
    if ! ($PIP_CMD install --upgrade pip && $PIP_CMD install -r requirements.txt && $PIP_CMD install -e .); then
        echo "[WASS Codespaces ERROR] Failed to install dependencies. Check output above." >&2
        exit 1
    fi
fi

# 3. Start Uvicorn Server in Background
echo "[WASS Codespaces] Starting Uvicorn web server on http://${HOST}:${PORT} (logging to ${LOG_FILE})..."
nohup $PYTHON_CMD -m uvicorn wass_webapp.app:app --host "$HOST" --port "$PORT" >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "[WASS Codespaces] Uvicorn process launched with PID ${SERVER_PID}."

# 4. Health Check Verification Loop
echo "[WASS Codespaces] Awaiting HTTP 200 response on ${HEALTH_URL} (timeout: ${MAX_ATTEMPTS}s)..."
for i in $(seq 1 "$MAX_ATTEMPTS"); do
    if check_health; then
        echo "[WASS Codespaces] SUCCESS: WASS 3D Wave Studio is live and responding (attempt ${i}/${MAX_ATTEMPTS})!"
        exit 0
    fi
    # Check if process died prematurely
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "[WASS Codespaces ERROR] Server process (PID ${SERVER_PID}) exited prematurely!" >&2
        echo "================ Log output (${LOG_FILE}) ================" >&2
        tail -n 25 "$LOG_FILE" >&2 || true
        echo "==========================================================" >&2
        exit 1
    fi
    sleep 1
done

echo "[WASS Codespaces ERROR] Health check timed out after ${MAX_ATTEMPTS}s without HTTP 200 response." >&2
echo "================ Log output (${LOG_FILE}) ================" >&2
tail -n 25 "$LOG_FILE" >&2 || true
echo "==========================================================" >&2
exit 1
