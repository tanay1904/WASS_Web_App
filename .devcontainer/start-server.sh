#!/usr/bin/env bash
# ==============================================================================
# WASS 3D Sea Wave Reconstruction Web Studio - Codespaces Launch Script
# ==============================================================================
# This script ensures dependencies are satisfied, starts the Uvicorn application
# in the background with stdout/stderr redirected to /tmp/wass_webapp.log,
# fully detaches the session (setsid + disown), and verifies server health
# at http://127.0.0.1:8080/api/status before exiting.
# ==============================================================================

set -euo pipefail

LOG_FILE="/tmp/wass_webapp.log"
PID_FILE="/tmp/wass_webapp.pid"
STATUS_FILE="/tmp/wass_server.status"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"
HEALTH_URL="http://127.0.0.1:${PORT}/api/status"
HEALTH_URL_LOCAL="http://localhost:${PORT}/api/status"
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
echo "STARTING" > "$STATUS_FILE" 2>/dev/null || true

# Function: Health check query
check_health() {
    if command -v curl >/dev/null 2>&1; then
        curl -s -f "$HEALTH_URL" >/dev/null 2>&1 || curl -s -f "$HEALTH_URL_LOCAL" >/dev/null 2>&1
    else
        $PYTHON_CMD -c "import urllib.request; urllib.request.urlopen('$HEALTH_URL', timeout=1)" >/dev/null 2>&1 || \
        $PYTHON_CMD -c "import urllib.request; urllib.request.urlopen('$HEALTH_URL_LOCAL', timeout=1)" >/dev/null 2>&1
    fi
}

# 1. Idempotency Check: Is server already running and healthy?
if check_health; then
    echo "[WASS Codespaces] Server is already running and responding at $HEALTH_URL."
    echo "READY" > "$STATUS_FILE" 2>/dev/null || true
    exit 0
fi

# 2. Dependency Verification: Are required packages importable?
echo "[WASS Codespaces] Verifying runtime dependencies..."
export PYTHONPATH=".:${PYTHONPATH:-}"

# Check specifically for OpenCV importability (repair libGL.so.1 / headless issue if needed)
if ! $PYTHON_CMD -c "import cv2" >/dev/null 2>&1; then
    echo "[WASS Codespaces] Repairing OpenCV headless / Linux graphics library dependencies..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -qq 2>/dev/null && sudo apt-get install -y -qq --no-install-recommends libgl1 libglib2.0-0 2>/dev/null || true
    fi
    $PIP_CMD uninstall -y opencv-python opencv-contrib-python 2>/dev/null || true
    $PIP_CMD install --no-cache-dir opencv-python-headless 2>/dev/null || true
fi

if ! $PYTHON_CMD -c "import uvicorn, fastapi, cv2, numpy, wass_webapp" >/dev/null 2>&1; then
    echo "[WASS Codespaces] Runtime dependencies missing or incomplete. Installing now..."
    echo "[WASS Codespaces] Running: $PIP_CMD install --upgrade pip && $PIP_CMD install -r requirements.txt && $PIP_CMD install -e ."
    if ! ($PIP_CMD install --upgrade pip && $PIP_CMD install -r requirements.txt && $PIP_CMD install -e .); then
        echo "[WASS Codespaces ERROR] Failed to install dependencies. Check output above." >&2
        echo "FAILED_DEPENDENCIES" > "$STATUS_FILE" 2>/dev/null || true
        exit 1
    fi
fi

# 3. Start Uvicorn Server in Background (Fully Detached Session)
echo "[WASS Codespaces] Starting Uvicorn web server on http://${HOST}:${PORT} (logging to ${LOG_FILE})..."
if command -v setsid >/dev/null 2>&1; then
    setsid $PYTHON_CMD -m uvicorn wass_webapp.app:app --host "$HOST" --port "$PORT" --app-dir . < /dev/null >> "$LOG_FILE" 2>&1 &
    SERVER_PID=$!
else
    nohup $PYTHON_CMD -m uvicorn wass_webapp.app:app --host "$HOST" --port "$PORT" --app-dir . < /dev/null >> "$LOG_FILE" 2>&1 &
    SERVER_PID=$!
fi

# Disown from shell to prevent SIGHUP/SIGTERM on shell exit
disown "$SERVER_PID" 2>/dev/null || true
echo "$SERVER_PID" > "$PID_FILE" 2>/dev/null || true
echo "[WASS Codespaces] Uvicorn process launched with PID ${SERVER_PID}."

# 4. Health Check Verification Loop
echo "[WASS Codespaces] Awaiting HTTP 200 response on ${HEALTH_URL} (timeout: ${MAX_ATTEMPTS}s)..."
for i in $(seq 1 "$MAX_ATTEMPTS"); do
    if check_health; then
        echo "[WASS Codespaces] SUCCESS: WASS 3D Wave Studio is live and responding (attempt ${i}/${MAX_ATTEMPTS})!"
        echo "READY" > "$STATUS_FILE" 2>/dev/null || true
        exit 0
    fi
    # Check if process died prematurely
    if ! kill -0 "$SERVER_PID" 2>/dev/null && ! pgrep -f "uvicorn wass_webapp.app:app" >/dev/null 2>&1; then
        echo "[WASS Codespaces ERROR] Server process exited prematurely!" >&2
        echo "FAILED_PREMATURE_EXIT" > "$STATUS_FILE" 2>/dev/null || true
        echo "================ Log output (${LOG_FILE}) ================" >&2
        tail -n 35 "$LOG_FILE" >&2 || true
        echo "==========================================================" >&2
        exit 1
    fi
    sleep 1
done

echo "[WASS Codespaces ERROR] Health check timed out after ${MAX_ATTEMPTS}s without HTTP 200 response." >&2
echo "FAILED_TIMEOUT" > "$STATUS_FILE" 2>/dev/null || true
echo "================ Log output (${LOG_FILE}) ================" >&2
tail -n 35 "$LOG_FILE" >&2 || true
echo "==========================================================" >&2
exit 1
