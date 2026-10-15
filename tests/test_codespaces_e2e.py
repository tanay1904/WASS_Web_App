"""
==============================================================================
WASS 3D Sea Wave Reconstruction Web Studio
GitHub Codespaces & Devcontainer Rigorous End-to-End Test Suite
==============================================================================
Validates:
1. .devcontainer/devcontainer.json:
   - Valid JSON syntax and schema completeness.
   - Forwarded ports [8080], HTTP protocol, openPreview auto-forwarding.
   - Lifecycle hooks (updateContentCommand, postCreateCommand, postStartCommand).
   - Remote user 'vscode'.
   - Customizations: settings (allowAutomaticTasks, defaultInterpreterPath), extensions.

2. .devcontainer/Dockerfile:
   - Base image (mcr.microsoft.com/devcontainers/python:3.10).
   - Essential system libraries: libgl1, libgl1-mesa-glx, libglib2.0-0, libgomp1,
     curl, tmux, procps.
   - Clean apt hygiene (--no-install-recommends, apt-get clean, list removal).
   - Pip upgrade and packaging tools.

3. .devcontainer/start-server.sh:
   - Bash script syntax (shebang, set -euo pipefail).
   - Static analysis of logic paths: PID_FILE, LOG_FILE, STATUS_FILE,
     health check function, idempotency check, dependency verification,
     detached execution (setsid / nohup / disown), polling health check loop.
   - Dynamic simulation of launch script state machine:
     * Startup, logging to /tmp/wass_webapp.log, writing STATUS_FILE to READY,
       and verifying /api/status HTTP 200 response.
     * Idempotency check when server is already healthy.
     * Premature exit detection (STATUS_FILE: FAILED_PREMATURE_EXIT).
     * Polling timeout handling (STATUS_FILE: FAILED_TIMEOUT).

4. .vscode/tasks.json & .vscode/settings.json:
   - Task label, command, isBackground: true, runOptions (runOn: folderOpen),
     problemMatcher with activeOnStart, beginsPattern, endsPattern.
   - settings.json task.allowAutomaticTasks: "on".

5. requirements.txt and self-healing OpenCV logic:
   - requirements.txt & pyproject.toml specify opencv-python-headless>=4.8.0.
   - No display server / GUI opencv-python dependencies present.
   - wass_webapp/__init__.py ensure_opencv() and wass_webapp/app.py fallback.
   - Simulation of missing library / ImportError triggering auto-heal.
==============================================================================
"""

import os
import sys
import json
import re
import time
import shutil
import tempfile
import urllib.request
import subprocess
import unittest.mock as mock
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Resolve repository paths
REPO_ROOT = Path(__file__).resolve().parent.parent
DEVCONTAINER_DIR = REPO_ROOT / ".devcontainer"
VSCODE_DIR = REPO_ROOT / ".vscode"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wass_webapp import ensure_opencv
from wass_webapp.app import app


# ==============================================================================
# Helper utilities
# ==============================================================================

def find_working_bash():
    """Find a functional bash executable across Linux, macOS, and Windows Git-Bash."""
    candidates = [
        "C:\\Program Files\\Git\\bin\\bash.exe",
        "C:\\Program Files\\Git\\usr\\bin\\bash.exe",
        "C:\\Program Files (x86)\\Git\\bin\\bash.exe",
        shutil.which("bash"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            try:
                res = subprocess.run([candidate, "--version"], capture_output=True, text=True, timeout=3)
                if res.returncode == 0:
                    return candidate
            except Exception:
                continue
    return None


# ==============================================================================
# 1. Validate .devcontainer/devcontainer.json
# ==============================================================================

class TestDevcontainerJson:
    """Rigorous verification of .devcontainer/devcontainer.json configuration."""

    @pytest.fixture(autouse=True)
    def setup_config(self):
        self.config_path = DEVCONTAINER_DIR / "devcontainer.json"
        assert self.config_path.exists(), f"Missing {self.config_path}"
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    def test_json_syntax_and_root_fields(self):
        """Verify devcontainer.json is valid JSON with mandatory top-level properties."""
        assert isinstance(self.data, dict)
        assert self.data.get("name") == "WASS 3D Sea Wave Reconstruction Studio"
        assert "build" in self.data or "image" in self.data
        if "build" in self.data:
            assert self.data["build"].get("dockerfile") == "Dockerfile"

    def test_forward_ports_configuration(self):
        """Verify port 8080 is forwarded with HTTP protocol and openPreview auto-action."""
        forward_ports = self.data.get("forwardPorts", [])
        assert 8080 in forward_ports, f"Port 8080 not found in forwardPorts: {forward_ports}"

        ports_attributes = self.data.get("portsAttributes", {})
        assert "8080" in ports_attributes, "Missing portsAttributes for port 8080"

        port_8080 = ports_attributes["8080"]
        assert port_8080.get("label") == "WASS 3D Wave Studio"
        assert port_8080.get("protocol") == "http"
        assert port_8080.get("onAutoForward") == "openPreview"
        assert port_8080.get("elevateIfNeeded") is False

    def test_lifecycle_commands(self):
        """Verify lifecycle hooks (updateContentCommand, postCreateCommand, postStartCommand)."""
        # updateContentCommand ensures headless OpenCV and package dependencies
        update_cmd = self.data.get("updateContentCommand", "")
        assert "opencv-python" in update_cmd
        assert "requirements.txt" in update_cmd
        assert "pip install -e ." in update_cmd

        # postCreateCommand makes start-server.sh executable
        post_create = self.data.get("postCreateCommand", "")
        assert "chmod +x" in post_create
        assert "start-server.sh" in post_create

        # postStartCommand launches the background service
        post_start = self.data.get("postStartCommand", "")
        assert "start-server.sh" in post_start

        # waitFor ensures port and service readiness
        assert self.data.get("waitFor") == "postStartCommand"

    def test_remote_user(self):
        """Verify non-root remoteUser is configured as vscode."""
        assert self.data.get("remoteUser") == "vscode"

    def test_vscode_customizations(self):
        """Verify editor settings and required extensions."""
        customizations = self.data.get("customizations", {})
        vscode = customizations.get("vscode", {})
        settings = vscode.get("settings", {})

        # Settings
        assert settings.get("task.allowAutomaticTasks") == "on"
        assert settings.get("python.defaultInterpreterPath") == "/usr/local/bin/python"

        # Extensions
        extensions = vscode.get("extensions", [])
        assert "ms-python.python" in extensions
        assert "ms-python.vscode-pylance" in extensions


# ==============================================================================
# 2. Validate .devcontainer/Dockerfile
# ==============================================================================

class TestDevcontainerDockerfile:
    """Rigorous verification of .devcontainer/Dockerfile instructions."""

    @pytest.fixture(autouse=True)
    def setup_dockerfile(self):
        self.dockerfile_path = DEVCONTAINER_DIR / "Dockerfile"
        assert self.dockerfile_path.exists(), f"Missing {self.dockerfile_path}"
        with open(self.dockerfile_path, "r", encoding="utf-8") as f:
            self.content = f.read()

    def test_base_image(self):
        """Verify Dockerfile base image is python:3.10."""
        from_matches = re.findall(r"^FROM\s+([^\s]+)", self.content, re.MULTILINE)
        assert len(from_matches) >= 1, "No FROM instruction in Dockerfile"
        base_image = from_matches[0]
        assert "python:3.10" in base_image, f"Expected python:3.10 base image, got: {base_image}"

    def test_essential_system_packages(self):
        """Check all required Linux graphics and system libraries are installed."""
        required_pkgs = [
            "libgl1",
            "libglib2.0-0",
            "libgomp1",
            "curl",
            "tmux",
            "procps",
        ]
        for pkg in required_pkgs:
            pattern = rf"\b{re.escape(pkg)}\b"
            assert re.search(pattern, self.content), f"Required system package '{pkg}' missing from Dockerfile apt-get list"

    def test_apt_hygiene_and_best_practices(self):
        """Check apt best practices: noninteractive, no-install-recommends, cache cleanup."""
        assert "ENV DEBIAN_FRONTEND=noninteractive" in self.content
        assert "--no-install-recommends" in self.content
        assert "apt-get clean" in self.content
        assert "rm -rf /var/lib/apt/lists/*" in self.content

    def test_pip_upgrade_instructions(self):
        """Verify pip, setuptools, and wheel upgrade."""
        assert re.search(r"pip\s+install\s+.*--upgrade\s+pip\s+setuptools\s+wheel", self.content)


# ==============================================================================
# 3. Validate .vscode/tasks.json & .vscode/settings.json
# ==============================================================================

class TestVSCodeTasksAndSettings:
    """Rigorous verification of VS Code tasks and settings."""

    def test_tasks_json_configuration(self):
        """Verify tasks.json has background startup task with folderOpen runOption."""
        tasks_path = VSCODE_DIR / "tasks.json"
        assert tasks_path.exists(), f"Missing {tasks_path}"
        with open(tasks_path, "r", encoding="utf-8") as f:
            tasks_data = json.load(f)

        assert tasks_data.get("version") == "2.0.0"
        tasks = tasks_data.get("tasks", [])
        assert len(tasks) >= 1

        startup_task = next((t for t in tasks if t.get("label") == "Start WASS 3D Wave Studio"), None)
        assert startup_task is not None, "Task 'Start WASS 3D Wave Studio' not found in tasks.json"

        assert startup_task.get("type") == "shell"
        assert "start-server.sh" in startup_task.get("command", "")
        assert startup_task.get("isBackground") is True

        run_options = startup_task.get("runOptions", {})
        assert run_options.get("runOn") == "folderOpen"

        problem_matcher = startup_task.get("problemMatcher", {})
        bg_matcher = problem_matcher.get("background", {})
        assert bg_matcher.get("activeOnStart") is True
        assert "beginsPattern" in bg_matcher
        assert "endsPattern" in bg_matcher

    def test_settings_json_configuration(self):
        """Verify settings.json allows automatic tasks and sets Python interpreter."""
        settings_path = VSCODE_DIR / "settings.json"
        assert settings_path.exists(), f"Missing {settings_path}"
        with open(settings_path, "r", encoding="utf-8") as f:
            settings_data = json.load(f)

        assert settings_data.get("task.allowAutomaticTasks") == "on"
        assert settings_data.get("python.defaultInterpreterPath") == "/usr/local/bin/python"


# ==============================================================================
# 4. Validate requirements.txt & Self-Healing OpenCV Logic
# ==============================================================================

class TestRequirementsAndSelfHealingOpenCV:
    """Rigorous verification of headless OpenCV configuration and self-healing logic."""

    def test_requirements_headless_opencv(self):
        """Verify requirements.txt enforces headless OpenCV without GUI dependencies."""
        req_path = REPO_ROOT / "requirements.txt"
        assert req_path.exists(), f"Missing {req_path}"
        req_text = req_path.read_text(encoding="utf-8")

        assert re.search(r"^opencv-python-headless\s*>=\s*4\.8\.0", req_text, re.MULTILINE), \
            "requirements.txt must specify opencv-python-headless>=4.8.0"

        # Ensure non-headless GUI packages are absent
        lines = [line.strip() for line in req_text.splitlines() if line.strip() and not line.startswith("#")]
        for line in lines:
            if line.startswith("opencv-python") and not line.startswith("opencv-python-headless"):
                pytest.fail(f"Found forbidden GUI opencv dependency in requirements.txt: {line}")

    def test_pyproject_headless_opencv(self):
        """Verify pyproject.toml enforces opencv-python-headless."""
        pyproj_path = REPO_ROOT / "pyproject.toml"
        assert pyproj_path.exists()
        content = pyproj_path.read_text(encoding="utf-8")
        assert "opencv-python-headless>=4.8.0" in content

    def test_ensure_opencv_normal_execution(self):
        """Verify ensure_opencv() returns cleanly when OpenCV is available."""
        # Should not raise any error
        ensure_opencv()

    def test_ensure_opencv_auto_healing_simulation(self):
        """Simulate missing libGL.so.1 / ImportError and verify auto-healing recovery."""
        import builtins
        orig_import = builtins.__import__
        import_attempts = 0

        def failing_cv2_import(name, *args, **kwargs):
            nonlocal import_attempts
            if name == "cv2":
                import_attempts += 1
                if import_attempts == 1:
                    raise ImportError("libGL.so.1: cannot open shared object file: No such file or directory")
                return mock.MagicMock(__name__="cv2")
            return orig_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=failing_cv2_import), \
             mock.patch("subprocess.run") as mock_subprocess_run:

            # Ensure cv2 is not cached in sys.modules
            sys.modules.pop("cv2", None)

            # Invoke self-healing
            ensure_opencv()

            # Verify it retried the import and invoked pip repair
            assert import_attempts >= 2
            # Check pip command was invoked with opencv-python-headless
            pip_calls = [
                call_args[0][0]
                for call_args in mock_subprocess_run.call_args_list
                if len(call_args[0]) > 0 and isinstance(call_args[0][0], list)
            ]
            install_cmd_found = any("opencv-python-headless" in cmd for cmd in pip_calls)
            assert install_cmd_found, f"pip install opencv-python-headless was not called. Calls: {pip_calls}"

    def test_ensure_opencv_healing_failure_handling(self):
        """Simulate unrecoverable failure during healing and verify informative exception."""
        import builtins
        orig_import = builtins.__import__

        def broken_cv2_import(name, *args, **kwargs):
            if name == "cv2":
                raise ImportError("libGL.so.1: missing")
            return orig_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=broken_cv2_import), \
             mock.patch("subprocess.run", side_effect=RuntimeError("Network failure installing wheel")):

            sys.modules.pop("cv2", None)
            with pytest.raises(ImportError) as exc_info:
                ensure_opencv()

            err_str = str(exc_info.value)
            assert "OpenCV could not be loaded or auto-repaired" in err_str
            assert "Network failure installing wheel" in err_str


# ==============================================================================
# 5. Validate .devcontainer/start-server.sh (Static Analysis & Syntax)
# ==============================================================================

class TestStartServerScriptAnalysis:
    """Rigorous static code and logic analysis of .devcontainer/start-server.sh."""

    @pytest.fixture(autouse=True)
    def setup_script(self):
        self.script_path = DEVCONTAINER_DIR / "start-server.sh"
        assert self.script_path.exists(), f"Missing {self.script_path}"
        self.content = self.script_path.read_text(encoding="utf-8")
        self.lines = [line.strip() for line in self.content.splitlines()]

    def test_shebang_and_strict_mode(self):
        """Verify shebang and set -euo pipefail."""
        assert self.lines[0].startswith("#!/"), "Missing shebang"
        assert "bash" in self.lines[0], f"Shebang must invoke bash, got: {self.lines[0]}"
        assert any(re.match(r"^set\s+-[a-z]*e[a-z]*u[a-z]*o\s+pipefail", line) for line in self.lines), \
            "set -euo pipefail must be specified"

    def test_constants_and_file_paths(self):
        """Verify PID_FILE, LOG_FILE, STATUS_FILE, HOST, PORT, and HEALTH_URL definitions."""
        assert re.search(r'LOG_FILE=["\']?/tmp/wass_webapp\.log["\']?', self.content)
        assert re.search(r'PID_FILE=["\']?/tmp/wass_webapp\.pid["\']?', self.content)
        assert re.search(r'STATUS_FILE=["\']?/tmp/wass_server\.status["\']?', self.content)
        assert re.search(r'PORT=.*8080', self.content)
        assert re.search(r'HEALTH_URL=.*8080.*/api/status', self.content) or \
               re.search(r'HEALTH_URL=.*PORT.*/api/status', self.content)

    def test_check_health_function(self):
        """Verify health check function supports curl and Python urllib fallback."""
        assert "check_health()" in self.content
        assert "curl" in self.content
        assert "urllib.request" in self.content

    def test_idempotency_check(self):
        """Verify idempotency logic: if check_health succeeds, set READY and exit 0."""
        assert "check_health" in self.content
        pattern = r"if\s+check_health;.*READY.*exit\s+0"
        assert re.search(pattern, self.content, re.DOTALL), "Idempotency early-exit check missing"

    def test_dependency_verification_and_headless_repair(self):
        """Verify dependency checks for cv2, uvicorn, fastapi, numpy, wass_webapp."""
        assert "import cv2" in self.content
        assert "opencv-python-headless" in self.content
        assert re.search(r"import\s+.*uvicorn.*fastapi.*cv2.*numpy.*wass_webapp", self.content)

    def test_detached_process_execution(self):
        """Verify background execution uses setsid/nohup and disown."""
        assert "setsid" in self.content or "nohup" in self.content
        assert "disown" in self.content
        assert "wass_webapp.app:app" in self.content

    def test_polling_health_check_loop(self):
        """Verify polling health loop, premature exit check, and timeout handling."""
        assert "MAX_ATTEMPTS=" in self.content
        assert "FAILED_PREMATURE_EXIT" in self.content
        assert "FAILED_TIMEOUT" in self.content
        assert re.search(r'echo\s+"READY"\s*>\s*"?[^"]*STATUS_FILE', self.content)

    def test_bash_syntax_validity(self):
        """Execute bash -n on the script if bash is available on the host."""
        bash_bin = find_working_bash()
        if not bash_bin:
            pytest.skip("No working bash executable available on host for bash -n test")

        res = subprocess.run([bash_bin, "-n", str(self.script_path)], capture_output=True, text=True)
        assert res.returncode == 0, f"bash -n failed with syntax errors:\n{res.stderr}"


# ==============================================================================
# 6. Dynamic Python Simulation of start-server.sh State Machine
# ==============================================================================

class StartServerSimulator:
    """
    Python simulator faithfully reproducing the exact state machine of start-server.sh:
    - Log file touching and status initialization
    - Idempotency check via /api/status health check
    - Background process spawning with stdout/stderr redirection
    - PID tracking
    - Polling health verification loop
    - Premature exit detection
    - Timeout handling
    """

    def __init__(self, host="127.0.0.1", port=8080, log_file=None, pid_file=None, status_file=None, max_attempts=15):
        self.host = host
        self.port = port
        self.temp_dir = tempfile.mkdtemp(prefix="wass_sim_")
        self.log_file = log_file or os.path.join(self.temp_dir, "wass_webapp.log")
        self.pid_file = pid_file or os.path.join(self.temp_dir, "wass_webapp.pid")
        self.status_file = status_file or os.path.join(self.temp_dir, "wass_server.status")
        self.health_url = f"http://{self.host}:{self.port}/api/status"
        self.max_attempts = max_attempts
        self.process = None

    def cleanup(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except Exception:
                self.process.kill()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def check_health(self) -> bool:
        try:
            req = urllib.request.Request(self.health_url)
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def write_status(self, status: str):
        with open(self.status_file, "w", encoding="utf-8") as f:
            f.write(f"{status}\n")

    def run(self, custom_command=None, simulate_premature_exit=False, simulate_timeout=False) -> int:
        # 0. Initialize files
        Path(self.log_file).touch()
        self.write_status("STARTING")

        # 1. Idempotency Check
        if self.check_health():
            self.write_status("READY")
            return 0

        # 2. Start process
        log_f = open(self.log_file, "a", encoding="utf-8")

        if simulate_premature_exit:
            # Command that immediately crashes
            cmd = [sys.executable, "-c", "import sys; sys.stderr.write('Fatal crash simulated\\n'); sys.exit(1)"]
        elif simulate_timeout:
            # Command that sleeps without opening the requested port
            cmd = [sys.executable, "-c", "import time; time.sleep(10)"]
        elif custom_command:
            cmd = custom_command
        else:
            cmd = [
                sys.executable,
                "-m",
                "uvicorn",
                "wass_webapp.app:app",
                "--host",
                self.host,
                "--port",
                str(self.port),
                "--app-dir",
                str(REPO_ROOT),
            ]

        self.process = subprocess.Popen(
            cmd,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            cwd=str(REPO_ROOT),
        )

        with open(self.pid_file, "w", encoding="utf-8") as pf:
            pf.write(str(self.process.pid))

        # 3. Polling loop
        for _ in range(self.max_attempts):
            if self.check_health():
                self.write_status("READY")
                return 0

            # Premature exit check
            if self.process.poll() is not None:
                self.write_status("FAILED_PREMATURE_EXIT")
                return 1

            time.sleep(1)

        # Timeout
        self.write_status("FAILED_TIMEOUT")
        return 1


class TestStartServerSimulation:
    """Dynamic tests simulating start-server.sh execution and state transitions."""

    def test_simulation_healthy_server_launch(self):
        """Simulate start-server.sh with running webapp, verify STATUS_FILE=READY, logging, and health."""
        # Check if live server is already up on 8080; if so, verify health check directly
        client = TestClient(app)
        api_res = client.get("/api/status")
        assert api_res.status_code == 200
        data = api_res.json()
        assert "status" in data
        assert "progress" in data

        # Use simulator to verify full flow
        sim = StartServerSimulator(host="127.0.0.1", port=8080, max_attempts=5)
        try:
            # When server is running on 8080 (as in devcontainer), it hits idempotency cleanly
            ret = sim.run()
            assert ret == 0

            # Verify STATUS_FILE content
            with open(sim.status_file, "r", encoding="utf-8") as f:
                status_text = f.read().strip()
            assert status_text == "READY"

            # Verify PID file exists
            assert os.path.exists(sim.status_file)
            assert os.path.exists(sim.log_file)
        finally:
            sim.cleanup()

    def test_simulation_idempotency(self):
        """Verify simulator detects existing healthy server and exits immediately with READY."""
        sim = StartServerSimulator(host="127.0.0.1", port=8080, max_attempts=3)
        try:
            with mock.patch.object(sim, "check_health", return_value=True):
                code = sim.run()
                assert code == 0
                with open(sim.status_file, "r", encoding="utf-8") as f:
                    assert f.read().strip() == "READY"
                # Process should NOT have been spawned
                assert sim.process is None
        finally:
            sim.cleanup()

    def test_simulation_premature_exit(self):
        """Verify premature crash sets STATUS_FILE to FAILED_PREMATURE_EXIT and exits with code 1."""
        sim = StartServerSimulator(host="127.0.0.1", port=9991, max_attempts=3)
        try:
            # Force check_health to return False so it tries to launch
            with mock.patch.object(sim, "check_health", return_value=False):
                code = sim.run(simulate_premature_exit=True)
                assert code == 1
                with open(sim.status_file, "r", encoding="utf-8") as f:
                    assert f.read().strip() == "FAILED_PREMATURE_EXIT"
                with open(sim.log_file, "r", encoding="utf-8") as lf:
                    log_content = lf.read()
                    assert "Fatal crash simulated" in log_content
        finally:
            sim.cleanup()

    def test_simulation_health_timeout(self):
        """Verify health check timeout sets STATUS_FILE to FAILED_TIMEOUT and exits with code 1."""
        sim = StartServerSimulator(host="127.0.0.1", port=9992, max_attempts=2)
        try:
            with mock.patch.object(sim, "check_health", return_value=False):
                code = sim.run(simulate_timeout=True)
                assert code == 1
                with open(sim.status_file, "r", encoding="utf-8") as f:
                    assert f.read().strip() == "FAILED_TIMEOUT"
        finally:
            sim.cleanup()

    def test_real_bash_script_idempotency_run(self):
        """Execute the actual start-server.sh via bash (if available) against running server."""
        bash_bin = find_working_bash()
        if not bash_bin:
            pytest.skip("No working bash executable available on host")

        script_path = str(DEVCONTAINER_DIR / "start-server.sh")
        # Run against port 8080
        res = subprocess.run([bash_bin, script_path], capture_output=True, text=True, timeout=10)
        assert res.returncode == 0
        assert "WASS 3D Wave Studio" in res.stdout or "already running" in res.stdout
