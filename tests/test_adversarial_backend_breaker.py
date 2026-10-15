import os
import sys
import io
import json
import tempfile
import subprocess
import pytest
from fastapi.testclient import TestClient

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP_DIR = os.path.join(ROOT_DIR, "wass_webapp")
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if WEBAPP_DIR not in sys.path:
    sys.path.insert(0, WEBAPP_DIR)

import app as app_module
from app import app, invalidate_caches, pipeline_state, pipeline_lock, sanitize_filename

client = TestClient(app)


def test_cli_wass_video_pipeline_invalid_args():
    """Verify wass_video_pipeline.py rejects invalid step and max-frames CLI arguments."""
    script_path = os.path.join(WEBAPP_DIR, "wass_video_pipeline.py")

    res_frames = subprocess.run(
        [sys.executable, script_path, "--max-frames", "-1"],
        capture_output=True,
        text=True
    )
    assert res_frames.returncode != 0
    assert "--max-frames must be a positive integer" in res_frames.stderr

    res_step = subprocess.run(
        [sys.executable, script_path, "--step", "0"],
        capture_output=True,
        text=True
    )
    assert res_step.returncode != 0
    assert "--step must be a positive integer" in res_step.stderr


def test_cli_analyze_wave_xyz_invalid_args():
    """Verify analyze_wave_xyz.py rejects nonexistent files with clean CLI error."""
    script_path = os.path.join(WEBAPP_DIR, "analyze_wave_xyz.py")

    res_missing = subprocess.run(
        [sys.executable, script_path, "completely_nonexistent_points.xyz"],
        capture_output=True,
        text=True
    )
    assert res_missing.returncode != 0
    assert "XYZ file not found" in res_missing.stderr


def test_upload_filename_sanitization_and_reserved_names():
    """Verify sanitize_filename neutralizes reserved device names, path traversal, and long names."""
    assert sanitize_filename("CON.mp4") == "safe_CON.mp4"
    assert sanitize_filename("prn.txt") == "safe_prn.txt"
    assert sanitize_filename("NUL.dat") == "safe_NUL.dat"
    assert sanitize_filename("....") == "unnamed_upload.bin"
    assert sanitize_filename("../../etc/passwd") == "passwd"

    long_input = "a" * 200 + ".mp4"
    sanitized = sanitize_filename(long_input)
    assert len(sanitized) <= 64
    assert sanitized.endswith(".mp4")


def test_corrupted_frame_points_handling():
    """Verify /api/sequence/frame/{idx} cleanly handles corrupted and empty points JSON."""
    with tempfile.TemporaryDirectory() as tmp_work:
        orig_work = app_module.WORK_DIR
        try:
            app_module.WORK_DIR = tmp_work
            seq_dir = os.path.join(tmp_work, "sequence")
            os.makedirs(seq_dir, exist_ok=True)
            with open(os.path.join(seq_dir, "sequence_meta.json"), "w") as f:
                json.dump({"total_frames": 1}, f)

            # 0-byte points_000.json
            with open(os.path.join(seq_dir, "points_000.json"), "w") as f:
                f.write("")
            invalidate_caches()

            resp = client.get("/api/sequence/frame/0")
            assert resp.status_code == 500
            assert "error" in resp.json()

            # Syntax error points_000.json
            with open(os.path.join(seq_dir, "points_000.json"), "w") as f:
                f.write("{invalid_json:")
            invalidate_caches()

            resp2 = client.get("/api/sequence/frame/0")
            assert resp2.status_code == 500
            assert "error" in resp2.json()
        finally:
            app_module.WORK_DIR = orig_work
            invalidate_caches()


def test_corrupted_wave_analysis_handling():
    """Verify wave analysis endpoints return clean error responses when json files are corrupted."""
    with tempfile.TemporaryDirectory() as tmp_work:
        orig_work = app_module.WORK_DIR
        try:
            app_module.WORK_DIR = tmp_work
            seq_dir = os.path.join(tmp_work, "sequence")
            os.makedirs(seq_dir, exist_ok=True)
            with open(os.path.join(seq_dir, "sequence_meta.json"), "w") as f:
                json.dump({"total_frames": 1}, f)

            # Corrupted wave_analysis_000.json
            with open(os.path.join(seq_dir, "wave_analysis_000.json"), "w") as f:
                f.write("corrupt")
            invalidate_caches()

            resp_wa = client.get("/api/wave_analysis/sequence_000")
            assert resp_wa.status_code == 500
            assert "error" in resp_wa.json()

            resp_arcs = client.get("/api/wave_analysis/export_arcs/sequence_000")
            assert resp_arcs.status_code == 500
            assert "error" in resp_arcs.json()
        finally:
            app_module.WORK_DIR = orig_work
            invalidate_caches()
