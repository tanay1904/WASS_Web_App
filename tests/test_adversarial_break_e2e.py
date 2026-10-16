import os
import sys
import io
import json
import time
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, MagicMock
import numpy as np
import pytest
import requests
from fastapi.testclient import TestClient

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP_DIR = os.path.join(ROOT_DIR, "wass_webapp")
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if WEBAPP_DIR not in sys.path:
    sys.path.insert(0, WEBAPP_DIR)

from app import (
    app,
    pipeline_state,
    pipeline_lock,
    invalidate_caches,
    run_stereo_stream_worker,
    run_pipeline_worker,
    _cached_frames_bytes,
    _cache_frames_lock,
    WORK_DIR
)
from analyze_wave_xyz import analyze_xyz, export_annotated_xyz

client = TestClient(app)


# ==============================================================================
# 1. CONCURRENCY & RACE CONDITION BREAKER
# ==============================================================================

def test_concurrency_pipeline_lock_rejection():
    """Verify concurrent attempts to trigger pipeline return HTTP 400 when active."""
    with pipeline_lock:
        pipeline_state["status"] = "running"
        pipeline_state["progress"] = 50

    try:
        def request_run():
            return client.post("/api/run", data={"video_source": "pair1", "max_frames": 5, "step": 1})

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(request_run) for _ in range(10)]
            results = [f.result() for f in futures]

        for resp in results:
            assert resp.status_code == 400
            data = resp.json()
            assert "already running" in data.get("error", "").lower()
    finally:
        with pipeline_lock:
            pipeline_state["status"] = "completed"


def test_concurrency_race_condition_single_winner():
    """Verify that when 15 threads race to start the pipeline from idle, exactly one succeeds."""
    with pipeline_lock:
        pipeline_state["status"] = "idle"

    # Mock the background worker so it doesn't do long processing during the race test
    with patch("app.run_stereo_stream_worker") as mock_worker:
        def race_run():
            return client.post("/api/run", data={"video_source": "pair1", "max_frames": 2, "step": 1})

        with ThreadPoolExecutor(max_workers=15) as executor:
            futures = [executor.submit(race_run) for _ in range(15)]
            results = [f.result() for f in futures]

        status_codes = [r.status_code for r in results]
        assert status_codes.count(200) == 1, f"Expected exactly one 200, got: {status_codes}"
        assert status_codes.count(400) == 14, f"Expected 14 rejections (400), got: {status_codes}"

    with pipeline_lock:
        pipeline_state["status"] = "completed"


def test_concurrency_cache_invalidation_race():
    """Verify simultaneous requests to /api/sequence/frame/0 while invalidating caches never crash."""
    # Ensure cache is initially populated
    resp_init = client.get("/api/sequence/frame/0")
    assert resp_init.status_code == 200

    errors = []
    stop_event = threading.Event()

    def cache_invalidator():
        while not stop_event.is_set():
            invalidate_caches()
            time.sleep(0.001)

    def frame_reader(thread_id):
        try:
            for _ in range(25):
                # Alternate between cached and no-cache requests
                headers = {"Cache-Control": "no-cache"} if thread_id % 2 == 0 else {}
                resp = client.get("/api/sequence/frame/0", headers=headers)
                if resp.status_code != 200:
                    errors.append(f"Thread {thread_id} got status {resp.status_code}: {resp.text}")
                data = resp.json()
                if "points" not in data or data.get("frame_index") != 0:
                    errors.append(f"Thread {thread_id} received corrupted frame payload: {data}")
        except Exception as exc:
            errors.append(f"Thread {thread_id} crashed with exception: {exc}")

    inv_thread = threading.Thread(target=cache_invalidator)
    inv_thread.start()

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(frame_reader, i) for i in range(16)]
        for f in futures:
            f.result()

    stop_event.set()
    inv_thread.join()

    assert len(errors) == 0, f"Race condition errors detected during simultaneous cache invalidation:\n" + "\n".join(errors[:10])


# ==============================================================================
# 2. BOUNDARY & MALICIOUS PAYLOAD BREAKER
# ==============================================================================

@pytest.mark.parametrize("max_frames", [0, -1, -9999, 501, 1000000])
def test_boundary_max_frames(max_frames):
    """Verify max_frames outside [1, 500] is strictly rejected with HTTP 400."""
    with pipeline_lock:
        pipeline_state["status"] = "idle"
    resp = client.post("/api/run", data={"video_source": "pair1", "max_frames": max_frames, "step": 1})
    assert resp.status_code == 400
    assert "max_frames must be between 1 and 500" in resp.json().get("error", "")


@pytest.mark.parametrize("step", [0, -1, 101, 99999])
def test_boundary_step(step):
    """Verify step outside [1, 100] is strictly rejected with HTTP 400."""
    with pipeline_lock:
        pipeline_state["status"] = "idle"
    resp = client.post("/api/run", data={"video_source": "pair1", "max_frames": 5, "step": step})
    assert resp.status_code == 400
    assert "step must be between 1 and 100" in resp.json().get("error", "")


@pytest.mark.parametrize("video_source", ["evil", "../../../", "<script>", "null", ""])
def test_malicious_video_source(video_source):
    """Verify malicious or unknown video_source strings are strictly rejected with HTTP 400."""
    with pipeline_lock:
        pipeline_state["status"] = "idle"
    resp = client.post("/api/run", data={"video_source": video_source, "max_frames": 5, "step": 1})
    assert resp.status_code == 400
    assert "Invalid video_source" in resp.json().get("error", "")


def test_upload_zero_byte_file_rejected():
    """Verify 0-byte video files are rejected with HTTP 400."""
    with pipeline_lock:
        pipeline_state["status"] = "idle"

    empty_file = io.BytesIO(b"")
    resp = client.post(
        "/api/run",
        data={"video_source": "dual", "max_frames": 5, "step": 1},
        files={
            "cam0_file": ("test0.mp4", empty_file, "video/mp4"),
            "cam1_file": ("test1.mp4", empty_file, "video/mp4"),
        }
    )
    assert resp.status_code == 400
    assert "empty" in resp.json().get("error", "").lower()


@pytest.mark.parametrize("non_video_ext", [".exe", ".sh", ".bat"])
def test_upload_non_video_extension_rejected(non_video_ext):
    """Verify non-video file extensions are rejected with HTTP 400."""
    with pipeline_lock:
        pipeline_state["status"] = "idle"

    blob = io.BytesIO(b"fake binary payload")
    resp = client.post(
        "/api/run",
        data={"video_source": "dual", "max_frames": 5, "step": 1},
        files={
            "cam0_file": (f"payload{non_video_ext}", blob, "application/octet-stream"),
            "cam1_file": ("valid.mp4", blob, "video/mp4"),
        }
    )
    assert resp.status_code == 400
    assert "Invalid video file extension" in resp.json().get("error", "")


def test_upload_path_traversal_filename_sanitized():
    """Verify directory traversal in upload filenames is sanitized and never escapes uploads/."""
    with pipeline_lock:
        pipeline_state["status"] = "idle"

    with patch("app.run_pipeline_worker"):
        blob = io.BytesIO(b"dummy video data for traversal test")
        resp = client.post(
            "/api/run",
            data={"video_source": "dual", "max_frames": 2, "step": 1},
            files={
                "cam0_file": ("../../evil.mp4", blob, "video/mp4"),
                "cam1_file": ("..\\..\\evil2.mp4", blob, "video/mp4"),
            }
        )
        assert resp.status_code == 200
        # Must not write to root directory
        assert not os.path.exists(os.path.join(ROOT_DIR, "evil.mp4"))
        assert not os.path.exists(os.path.join(ROOT_DIR, "evil2.mp4"))

    with pipeline_lock:
        pipeline_state["status"] = "completed"


def test_upload_corrupt_binary_blob_handling():
    """Verify corrupt binary blob with .mp4 extension is safely uploaded and worker does not crash."""
    with pipeline_lock:
        pipeline_state["status"] = "idle"

    with patch("app.run_pipeline_worker"):
        corrupt_blob = io.BytesIO(os.urandom(1024))
        resp = client.post(
            "/api/run",
            data={"video_source": "dual", "max_frames": 2, "step": 1},
            files={
                "cam0_file": ("corrupt_cam0.mp4", corrupt_blob, "video/mp4"),
                "cam1_file": ("corrupt_cam1.mp4", corrupt_blob, "video/mp4"),
            }
        )
        assert resp.status_code == 200
        assert resp.json().get("status") == "started"

    with pipeline_lock:
        pipeline_state["status"] = "completed"


@pytest.mark.parametrize("idx,expected_status", [
    (-1, 404),
    (-100, 404),
    ("1.5", 422),
    ("abc", 422),
    ("NaN", 422),
    ("null", 422),
    (60, 404),
    (999999, 404)
])
def test_frame_endpoint_edge_indices(idx, expected_status):
    """Verify negative, float, string, and out-of-bounds indices return 404/422 and never 500."""
    resp = client.get(f"/api/sequence/frame/{idx}")
    assert resp.status_code == expected_status
    assert resp.status_code != 500


@pytest.mark.parametrize("endpoint", [
    "/api/pointcloud/",
    "/api/wave_analysis/",
    "/api/wave_analysis/export/",
    "/api/wave_analysis/export_arcs/"
])
@pytest.mark.parametrize("payload", [
    "../../etc/passwd",
    "..%2f..%2fetc%2fpasswd",
    "..\\..\\windows\\win.ini",
    "../outside",
    "..",
    "%2e%2e%2f",
    "<script>",
    "evil/../../something",
    "null"
])
def test_path_traversal_all_endpoints(endpoint, payload):
    """Verify path traversal payloads across all data endpoints are safely rejected."""
    url = f"{endpoint}{payload}"
    resp = client.get(url)
    assert resp.status_code in [400, 404, 403, 422], f"URL {url} returned unexpected status {resp.status_code}"
    assert resp.status_code != 500


# ==============================================================================
# 3. CORRUPTED POINT CLOUD & MATHEMATICAL SINGULARITIES
# ==============================================================================

def test_analyze_xyz_empty(tmp_path):
    """Test analyze_xyz on 0 points (empty file)."""
    p = tmp_path / "empty.xyz"
    p.write_text("", encoding="utf-8")
    res, pts, dist_obs, h_sea = analyze_xyz(str(p))
    assert res["total_points"] == 0
    assert res["significant_wave_height_Hs_m"] == 0.0
    s = json.dumps(res)
    assert "NaN" not in s and "Infinity" not in s


def test_analyze_xyz_one_and_two_points(tmp_path):
    """Test analyze_xyz with 1 and 2 points."""
    p1 = tmp_path / "p1.xyz"
    p1.write_text("1.0 10.0 0.2\n", encoding="utf-8")
    res1, _, _, _ = analyze_xyz(str(p1))
    assert res1["total_points"] == 1
    assert res1["significant_wave_height_Hs_m"] == 0.0

    p2 = tmp_path / "p2.xyz"
    p2.write_text("1.0 10.0 0.2\n2.0 12.0 0.4\n", encoding="utf-8")
    res2, _, _, _ = analyze_xyz(str(p2))
    assert res2["total_points"] == 2
    assert res2["significant_wave_height_Hs_m"] == 0.0


def test_analyze_xyz_collinear_points(tmp_path):
    """Test analyze_xyz with 1,000 collinear points (all X=0, Y=0)."""
    p = tmp_path / "collinear_1000.xyz"
    lines = [f"0.0 0.0 {float(i)*0.05}\n" for i in range(1000)]
    p.write_text("".join(lines), encoding="utf-8")

    res, pts, dist_obs, h_sea = analyze_xyz(str(p))
    assert res["total_points"] == 1000
    assert res["significant_wave_height_Hs_m"] == 0.0
    s = json.dumps(res)
    assert "NaN" not in s and "Infinity" not in s


def test_analyze_xyz_identical_points(tmp_path):
    """Test analyze_xyz with 500 identical points."""
    p = tmp_path / "identical.xyz"
    lines = ["5.0 20.0 0.35\n"] * 500
    p.write_text("".join(lines), encoding="utf-8")

    res, pts, dist_obs, h_sea = analyze_xyz(str(p))
    assert res["total_points"] == 500
    assert res["significant_wave_height_Hs_m"] == 0.0
    s = json.dumps(res)
    assert "NaN" not in s and "Infinity" not in s


def test_analyze_xyz_nan_inf_mixed(tmp_path):
    """Test analyze_xyz with NaN, Inf, -Inf, and invalid tokens."""
    content = """
    1.0 10.0 0.5
    NaN 15.0 0.0
    2.0 Inf 0.7
    3.0 18.0 -Inf
    bad_line_text
    4.0 20.0 0.6
    5.0 25.0 0.4
    6.0 30.0 0.3
    """
    p = tmp_path / "nan_inf.xyz"
    p.write_text(content, encoding="utf-8")

    res, pts, dist_obs, h_sea = analyze_xyz(str(p))
    assert res["total_points"] == 4
    assert np.all(np.isfinite(pts))
    s = json.dumps(res)
    assert "NaN" not in s and "Infinity" not in s


def test_analyze_xyz_negative_coordinates_behind_camera(tmp_path):
    """Test analyze_xyz with points behind observer (Y < 0)."""
    p = tmp_path / "behind_camera.xyz"
    lines = [f"{float(i)*0.5} -{float(i+5)*1.0} 0.5\n" for i in range(50)]
    p.write_text("".join(lines), encoding="utf-8")

    res, pts, dist_obs, h_sea = analyze_xyz(str(p))
    assert res["total_points"] == 50
    # Since Y < 0, all forward circular arcs should report point_count == 0
    for arc in res["circular_arcs_5m"]:
        assert arc["point_count"] == 0
    s = json.dumps(res)
    assert "NaN" not in s and "Infinity" not in s


def test_analyze_xyz_extreme_coordinates(tmp_path):
    """Test analyze_xyz with extreme coordinate values (1e12, -1e12, 1e200)."""
    p = tmp_path / "extreme.xyz"
    content = """
    1e12 1e12 1e12
    -1e12 -1e12 -1e12
    1e200 1e200 0.0
    -1e200 0.0 -1e200
    """
    p.write_text(content, encoding="utf-8")

    res, pts, dist_obs, h_sea = analyze_xyz(str(p))
    # Extreme non-physical coordinates are safely sanitized/filtered
    assert res["significant_wave_height_Hs_m"] == 0.0
    s = json.dumps(res)
    assert "NaN" not in s and "Infinity" not in s


# ==============================================================================
# 4. CLOUD ONEDRIVE INGESTION FAILURE BREAKER
# ==============================================================================

@pytest.mark.parametrize("simulated_error", [
    requests.HTTPError("401 Client Error: Unauthorized for url"),
    requests.HTTPError("404 Client Error: Not Found for url"),
    requests.HTTPError("500 Server Error: Internal Server Error for url"),
    json.JSONDecodeError("Expecting value", "Invalid JSON Content", 0),
    requests.exceptions.Timeout("Connection to OneDrive timed out"),
    requests.exceptions.ConnectionError("Failed to establish network connection")
])
def test_onedrive_failure_graceful_sequence_fallback(simulated_error):
    """Verify run_stereo_stream_worker handles all simulated OneDrive failures by falling back gracefully."""
    import shutil
    import app as app_module

    with tempfile.TemporaryDirectory() as tmp_work:
        orig_work = app_module.WORK_DIR
        try:
            app_module.WORK_DIR = tmp_work
            seq_dir = os.path.join(tmp_work, "sequence")
            os.makedirs(seq_dir, exist_ok=True)
            orig_seq = os.path.join(orig_work, "sequence")
            for f in ["video_frame_left_000.jpg", "video_frame_left_001.jpg", "video_frame_right_000.jpg", "video_frame_right_001.jpg"]:
                src = os.path.join(orig_seq, f)
                if os.path.exists(src):
                    shutil.copy2(src, seq_dir)

            with patch("requests.Session.get", side_effect=simulated_error):
                with pipeline_lock:
                    pipeline_state["status"] = "idle"

                run_stereo_stream_worker("pair1", max_frames=2, step=1)

                assert pipeline_state["status"] == "completed"
                assert pipeline_state["progress"] == 100
                logs_joined = " ".join(pipeline_state["logs"])
                assert "OneDrive Note" in logs_joined
                assert "utilizing ingested GoPro stereo sequence frames" in logs_joined
                assert len(pipeline_state["reconstructed_frames"]) == 2
        finally:
            app_module.WORK_DIR = orig_work
            invalidate_caches()


# ==============================================================================
# 5. C++ BINARY ABSENCE BREAKER
# ==============================================================================

@pytest.mark.parametrize("binary_exception", [
    FileNotFoundError("WASS C++ binary wass_prepare not found in PATH or WASS_BIN_DIR"),
    RuntimeError("WASS C++ binaries failed to execute on current platform architecture")
])
def test_binary_absence_engine_delegation(binary_exception):
    """Verify run_pipeline_worker seamlessly delegates to Python stereo engine when binaries are absent."""
    with patch("app.get_wass_binaries", side_effect=binary_exception):
        with patch("app.run_stereo_stream_worker") as mock_stream_worker:
            with pipeline_lock:
                pipeline_state["status"] = "idle"

            run_pipeline_worker(
                video0="fake0.mp4",
                video1="fake1.mp4",
                video_sbs=None,
                max_frames=2,
                step=1
            )

            # Check that notice was logged
            logs_joined = " ".join(pipeline_state["logs"])
            assert "WASS Engine Notice" in logs_joined
            assert "Cloud Optical Stereo Reconstruction engine" in logs_joined
            # Verify delegation
            mock_stream_worker.assert_called_once_with("pair1", 2, 1, custom_cam0="fake0.mp4", custom_cam1="fake1.mp4")
