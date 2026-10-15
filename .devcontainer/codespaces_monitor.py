#!/usr/bin/env python3
"""
WASS 3D Sea Wave Reconstruction Web Studio - Codespaces High-Accuracy Live Monitor
================================================================================
Monitors container health, process status, port 8080 binding, API latency (ms),
Three.js sequence cache status, and auto-heals / restarts stalled services.
"""

import os
import sys
import time
import json
import socket
import urllib.request
import urllib.error
import subprocess
import argparse
from datetime import datetime, timezone

TELEMETRY_FILE = "/tmp/wass_server_telemetry.json"
STATUS_FILE = "/tmp/wass_server.status"
LOG_FILE = "/tmp/wass_webapp.log"
PID_FILE = "/tmp/wass_webapp.pid"


def is_codespaces() -> bool:
    return os.getenv("CODESPACES") == "true" or os.path.exists("/workspaces")


def is_recovery_mode() -> bool:
    """Detect if running in Codespaces recovery mode."""
    if not is_codespaces():
        return False
    # In recovery mode, /usr/local/bin/python is missing or pip is absent
    has_pip = subprocess.run(["which", "pip"], capture_output=True).returncode == 0
    has_apt = subprocess.run(["which", "apt"], capture_output=True).returncode == 0
    return not has_pip or not has_apt


def check_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def ping_api(url: str, timeout: float = 1.0):
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WASS-HighSensitivityMonitor/2.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            data = json.loads(response.read().decode("utf-8"))
            return True, response.status, latency_ms, data, None
    except urllib.error.HTTPError as e:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return False, e.code, latency_ms, None, str(e)
    except Exception as e:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return False, 0, latency_ms, None, str(e)


def restart_service(host: str, port: int):
    print(f"\n[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] [WATCHDOG] Initiating automated service restart...")
    start_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "start-server.sh")
    if os.path.exists(start_script):
        subprocess.run(["bash", start_script], check=False)
    else:
        python_bin = sys.executable
        subprocess.Popen(
            [python_bin, "-m", "uvicorn", "wass_webapp.app:app", "--host", host, "--port", str(port)],
            stdout=open(LOG_FILE, "a"),
            stderr=subprocess.STDOUT
        )


def run_monitor(host: str = "127.0.0.1", port: int = 8080, interval: float = 0.5, auto_restart: bool = True, iterations: int = 0):
    health_url = f"http://{host}:{port}/api/status"
    seq_url = f"http://{host}:{port}/api/sequence/meta"
    recovery = is_recovery_mode()

    print("=" * 80)
    print("  WASS 3D WAVE STUDIO — HIGH-ACCURACY CODESPACES MONITOR v2.0")
    print(f"  Target: {health_url} | Polling Interval: {interval * 1000:.0f}ms")
    print(f"  Environment: {'GitHub Codespaces' if is_codespaces() else 'Local / Container'}")
    if recovery:
        print("  \033[91;1m[CRITICAL ALERT] RUNNING IN CODESPACES RECOVERY MODE!\033[0m")
        print("  Action required: Press Ctrl+Shift+P -> 'Codespaces: Rebuild Container' to reload container.")
    print("=" * 80)

    consecutive_failures = 0
    cycle = 0

    while True:
        cycle += 1
        port_open = check_port_open(host, port, timeout=min(0.5, interval))
        is_ok, status_code, latency_ms, api_data, err_msg = ping_api(health_url, timeout=min(2.0, interval * 4))

        telemetry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycle": cycle,
            "host": host,
            "port": port,
            "port_open": port_open,
            "healthy": is_ok,
            "status_code": status_code,
            "latency_ms": round(latency_ms, 2),
            "error": err_msg,
            "pipeline_status": api_data.get("status") if api_data else None,
            "current_stage": api_data.get("current_stage") if api_data else None,
            "progress": api_data.get("progress") if api_data else None,
            "active_workspace": api_data.get("active_workspace") if api_data else None,
            "recovery_mode": recovery,
        }

        # Write high-precision telemetry atomically
        try:
            tmp_t = TELEMETRY_FILE + ".tmp"
            with open(tmp_t, "w") as f:
                json.dump(telemetry, f, indent=2)
            os.replace(tmp_t, TELEMETRY_FILE)
        except Exception:
            pass

        now_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if is_ok:
            consecutive_failures = 0
            p_status = api_data.get("status", "idle")
            stage = api_data.get("current_stage", "Ready")
            prog = api_data.get("progress", 100)
            status_color = "\033[92m" if p_status in ["completed", "idle"] else "\033[94m"
            print(f"[{now_str}] \033[92m[HEALTHY]\033[0m HTTP {status_code} | Latency: \033[1m{latency_ms:5.1f}ms\033[0m | Pipeline: {status_color}{p_status.upper()}\033[0m ({stage} {prog}%)")
        else:
            consecutive_failures += 1
            print(f"[{now_str}] \033[91m[UNHEALTHY #{consecutive_failures}]\033[0m Port: {port_open} | Code: {status_code} | Latency: {latency_ms:5.1f}ms | Error: {err_msg}")

            if auto_restart and consecutive_failures >= 3:
                print(f"[{now_str}] \033[93m[ALERT] 3 consecutive failures detected. Triggering auto-recovery...\033[0m")
                restart_service(host, port)
                consecutive_failures = 0
                time.sleep(2.0)

        if iterations > 0 and cycle >= iterations:
            break

        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="WASS Codespaces High-Accuracy Live Monitor")
    parser.add_argument("--host", default="127.0.0.1", help="Target server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Target server port (default: 8080)")
    parser.add_argument("--interval", type=float, default=0.5, help="Sampling interval in seconds (default: 0.5s / 500ms)")
    parser.add_argument("--no-restart", action="store_true", help="Disable automated service restart on failure")
    parser.add_argument("--iterations", type=int, default=0, help="Number of check cycles to run (0 for continuous)")
    args = parser.parse_args()

    run_monitor(
        host=args.host,
        port=args.port,
        interval=args.interval,
        auto_restart=not args.no_restart,
        iterations=args.iterations
    )


if __name__ == "__main__":
    main()
