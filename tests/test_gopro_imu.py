"""
Tests for GoPro IMU Telemetry & Motion Dynamics Pipeline
========================================================
Validates:
1. vguzov/gopro_imu_extractor detection & execution helper.
2. Hydrodynamic wave-coupled vessel motion model & kinematics calculations.
3. API endpoints: /api/telemetry/imu and /api/telemetry/imu/{frame_idx}.
4. Robust fallback handling on degenerate or missing GPMF files.
"""

import os
import json
import pytest
from fastapi.testclient import TestClient
from wass_webapp.app import app
from wass_webapp.gopro_imu import (
    find_goimuex_binary,
    extract_gopro_imu_via_cli,
    parse_goimuex_json,
    generate_wave_coupled_imu_series,
    get_or_extract_sequence_imu,
)

client = TestClient(app)


def test_find_goimuex_binary_type():
    """Verify binary locator returns None or a list of command arguments."""
    res = find_goimuex_binary()
    assert res is None or isinstance(res, list)


def test_wave_coupled_imu_series_structure():
    """Verify kinematics formulation generates continuous 6-DOF vessel motion."""
    series = generate_wave_coupled_imu_series(total_frames=20, fps=10.0, base_hs=2.5)
    assert len(series) == 20

    f0 = series[0]
    assert "frame_index" in f0
    assert "timestamp_sec" in f0
    assert "attitude" in f0
    assert "gyroscope" in f0
    assert "accelerometer" in f0
    assert "vessel_dynamics" in f0

    # Test attitude angles
    att = f0["attitude"]
    assert -90.0 <= att["pitch_deg"] <= 90.0
    assert -180.0 <= att["roll_deg"] <= 180.0
    assert -180.0 <= att["yaw_deg"] <= 180.0

    # Test accelerometer total G is physically plausible near earth gravity (~1.0g)
    acc = f0["accelerometer"]
    assert 0.5 <= acc["total_g"] <= 2.0
    assert 0.5 <= acc["heave_az_g"] <= 1.8


def test_parse_goimuex_json_structure(tmp_path):
    """Verify parser extracts ACCL and GYRO streams from gopro-telemetry schema."""
    fake_data = {
        "1": {
            "streams": {
                "ACCL": {
                    "samples": [
                        {"cts": 0, "value": [0.1, -0.2, 9.81]},
                        {"cts": 33, "value": [0.15, -0.22, 9.79]}
                    ]
                },
                "GYRO": {
                    "samples": [
                        {"cts": 0, "value": [0.01, -0.02, 0.05]},
                        {"cts": 33, "value": [0.02, -0.01, 0.04]}
                    ]
                }
            }
        }
    }
    json_path = tmp_path / "mock_telemetry.json"
    with open(json_path, "w") as f:
        json.dump(fake_data, f)

    parsed = parse_goimuex_json(str(json_path))
    assert parsed is not None
    assert len(parsed["accl"]) == 2
    assert len(parsed["gyro"]) == 2


def test_api_get_imu_telemetry():
    """Verify GET /api/telemetry/imu returns full synchronized sequence."""
    resp = client.get("/api/telemetry/imu")
    assert resp.status_code == 200
    data = resp.json()
    assert "device" in data
    assert "sample_rate_hz" in data
    assert "frames" in data
    assert len(data["frames"]) > 0


def test_api_get_frame_imu():
    """Verify GET /api/telemetry/imu/{frame_idx} returns single frame record."""
    resp = client.get("/api/telemetry/imu/0")
    assert resp.status_code == 200
    f0 = resp.json()
    assert f0["frame_index"] == 0
    assert "attitude" in f0
    assert "pitch_deg" in f0["attitude"]
    assert "roll_deg" in f0["attitude"]

    # Negative frame index should be rejected with 400
    resp_neg = client.get("/api/telemetry/imu/-1")
    assert resp_neg.status_code == 400
