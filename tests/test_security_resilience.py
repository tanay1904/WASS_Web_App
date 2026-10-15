import os
import sys
import io
import pytest
from fastapi.testclient import TestClient

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP_DIR = os.path.join(ROOT_DIR, "wass_webapp")
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if WEBAPP_DIR not in sys.path:
    sys.path.insert(0, WEBAPP_DIR)

from app import app, invalidate_caches, pipeline_state, pipeline_lock

client = TestClient(app)


def test_path_traversal_pointcloud():
    """Verify directory traversal payloads are rejected with 400 Bad Request."""
    traversal_payloads = [
        "../../etc/passwd",
        "..\\..\\windows\\system32",
        "../outside",
        "..",
        "%2e%2e%2f",
        "valid/invalid",
        "frame;rm -rf",
    ]
    for payload in traversal_payloads:
        resp = client.get(f"/api/pointcloud/{payload}")
        assert resp.status_code in [400, 404], f"Payload '{payload}' was not rejected cleanly: {resp.status_code}"


def test_path_traversal_wave_analysis():
    """Verify directory traversal in wave analysis is rejected."""
    traversal_payloads = [
        "../../etc/shadow",
        "..\\..\\boot.ini",
        "../workspace",
        "..",
        "frame_000..outside",
        "sequence_000%2e%2e",
    ]
    for payload in traversal_payloads:
        resp = client.get(f"/api/wave_analysis/{payload}")
        assert resp.status_code in [400, 404], f"Payload '{payload}' was not rejected: {resp.status_code}"


def test_path_traversal_export_csv():
    """Verify directory traversal in CSV export is rejected."""
    traversal_payloads = [
        "../../sensitive.csv",
        "..\\secret.csv",
        "../output",
    ]
    for payload in traversal_payloads:
        resp = client.get(f"/api/wave_analysis/export/{payload}")
        assert resp.status_code in [400, 404], f"Payload '{payload}' was not rejected: {resp.status_code}"


def test_path_traversal_export_arcs():
    """Verify directory traversal in export_arcs is rejected."""
    resp = client.get("/api/wave_analysis/export_arcs/../../evil")
    assert resp.status_code in [400, 404]


def test_upload_filename_traversal():
    """Verify that path traversal filenames in uploads are sanitized."""
    # Ensure state is idle
    with pipeline_lock:
        pipeline_state["status"] = "idle"

    fake_video = io.BytesIO(b"fake mp4 video content")
    resp = client.post(
        "/api/run",
        data={"video_source": "dual", "max_frames": 5, "step": 1},
        files={
            "cam0_file": ("../../evil_cam0.mp4", fake_video, "video/mp4"),
            "cam1_file": ("..\\..\\evil_cam1.mp4", fake_video, "video/mp4"),
        }
    )
    # The uploaded files must be saved cleanly inside uploads/ as sanitized names
    assert resp.status_code == 200
    upload_dir = os.path.join(WEBAPP_DIR, "uploads")
    # Traversal should not escape uploads
    assert not os.path.exists(os.path.join(WEBAPP_DIR, "evil_cam0.mp4"))
    assert not os.path.exists(os.path.join(ROOT_DIR, "evil_cam0.mp4"))

    # Cleanup state
    with pipeline_lock:
        pipeline_state["status"] = "completed"


def test_input_bounds_validation():
    """Verify bounds validation on max_frames and step parameters in /api/run."""
    # Zero and negative step
    resp = client.post("/api/run", data={"video_source": "pair1", "max_frames": 5, "step": 0})
    assert resp.status_code == 400

    resp2 = client.post("/api/run", data={"video_source": "pair1", "max_frames": 5, "step": -2})
    assert resp2.status_code == 400

    # Zero and negative max_frames
    resp3 = client.post("/api/run", data={"video_source": "pair1", "max_frames": 0, "step": 1})
    assert resp3.status_code == 400

    # Excessively large max_frames
    resp4 = client.post("/api/run", data={"video_source": "pair1", "max_frames": 99999, "step": 1})
    assert resp4.status_code == 400

    # Invalid video source
    resp5 = client.post("/api/run", data={"video_source": "unsupported_source", "max_frames": 5, "step": 1})
    assert resp5.status_code == 400


def test_concurrency_rejection():
    """Verify that multiple concurrent runs are rejected when pipeline is running."""
    with pipeline_lock:
        pipeline_state["status"] = "running"

    resp = client.post("/api/run", data={"video_source": "pair1", "max_frames": 5, "step": 1})
    assert resp.status_code == 400
    data = resp.json()
    assert "already running" in data.get("error", "").lower()

    # Reset state to completed
    with pipeline_lock:
        pipeline_state["status"] = "completed"


def test_cache_invalidation():
    """Verify that invalidate_caches purges cached bytes and responses reflect fresh data."""
    import app as app_mod

    # Populate cache by making requests
    resp = client.get("/api/sequence/all_points")
    assert resp.status_code == 200
    assert app_mod._cached_all_points_bytes is not None

    resp2 = client.get("/api/sequence/all_analysis")
    assert resp2.status_code == 200
    assert app_mod._cached_all_analysis_bytes is not None

    # Invalidate cache
    invalidate_caches()
    assert app_mod._cached_all_points_bytes is None
    assert app_mod._cached_all_analysis_bytes is None
    assert len(app_mod._cached_frames_bytes) == 0
