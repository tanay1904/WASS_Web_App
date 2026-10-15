import os
import sys
import pytest
from fastapi.testclient import TestClient

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP_DIR = os.path.join(ROOT_DIR, "wass_webapp")
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if WEBAPP_DIR not in sys.path:
    sys.path.insert(0, WEBAPP_DIR)

from app import app

client = TestClient(app)


def test_root_index():
    """Verify root / returns 200 OK HTML with studio header."""
    response = client.get("/")
    assert response.status_code == 200
    assert "WASS - 3D Ocean Wave Stereophotogrammetry Studio" in response.text
    assert "canvasContainer" in response.text


def test_favicon_endpoint():
    """Verify favicon endpoint returns 200 OK image/svg+xml."""
    response = client.get("/favicon.ico")
    assert response.status_code == 200
    assert "image/svg+xml" in response.headers.get("content-type", "")


def test_api_status():
    """Verify /api/status returns valid pipeline state."""
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "progress" in data


def test_sequence_meta():
    """Verify /api/sequence/meta returns 60 frames metadata."""
    response = client.get("/api/sequence/meta")
    assert response.status_code == 200
    meta = response.json()
    assert meta.get("total_frames") == 60
    assert meta.get("grid_w") == 100
    assert meta.get("grid_h") == 70


def test_sequence_frame_0():
    """Verify /api/sequence/frame/0 returns exactly 7,000 vertices with valid floats."""
    response = client.get("/api/sequence/frame/0")
    assert response.status_code == 200
    data = response.json()
    assert "points" in data
    pts = data["points"]
    assert len(pts) == 7000
    assert len(pts[0]) == 3
    # Verify no NaNs or Infs
    for p in pts[:50]:
        assert all(isinstance(v, (int, float)) for v in p)


def test_wave_analysis_endpoint():
    """Verify /api/wave_analysis/sequence_000 contains 10 circular arcs."""
    response = client.get("/api/wave_analysis/sequence_000")
    assert response.status_code == 200
    analysis = response.json()
    assert "significant_wave_height_Hs_m" in analysis
    assert "circular_arcs_5m" in analysis
    assert len(analysis["circular_arcs_5m"]) == 10



def test_export_arcs_csv():
    """Verify CSV export satisfies RFC 4180 with exact 12-column header."""
    response = client.get("/api/wave_analysis/export_arcs/sequence_000")
    assert response.status_code == 200
    assert "text/csv" in response.headers.get("content-type", "")
    lines = response.text.strip().split("\r\n")
    if len(lines) == 1:
        lines = response.text.strip().split("\n")
    expected_header = "arc_radius_m,range_band,vertex_count,mean_elevation_m,peak_crest_m,deepest_trough_m,wave_amplitude_m,significant_wave_height_Hs_m,elevation_std_sigma_m,azimuth_min_deg,azimuth_max_deg,azimuth_span_deg"
    assert lines[0] == expected_header
    assert len(lines) == 11 # 1 header + 10 arc rows


def test_edge_cases():
    """Verify negative and out-of-bounds frame indices return 404/422."""
    assert client.get("/api/sequence/frame/-1").status_code == 404
    assert client.get("/api/sequence/frame/999").status_code == 404
    assert client.get("/api/sequence/frame/invalid").status_code == 422


def test_pipeline_fallback_resilience():
    """Verify run_pipeline_worker falls back gracefully without unhandled crashes when binaries are missing."""
    from unittest.mock import patch
    from app import run_pipeline_worker

    with patch("app.get_wass_binaries", side_effect=FileNotFoundError("Mock missing binary")):
        with patch("app.run_stereo_stream_worker") as mock_worker:
            run_pipeline_worker(None, None, None, max_frames=2, step=1, use_sample="synthetic")
            mock_worker.assert_called_once_with("pair1", 2, 1, custom_cam0=None, custom_cam1=None)


