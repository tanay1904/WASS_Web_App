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


def test_extract_and_export_imu_csv(tmp_path):
    """Verify extraction of 3-axis gyro and accel scalars and single-frame CSV generation."""
    from wass_webapp.gopro_imu import extract_frame_imu_scalars, export_frame_imu_csv, export_all_frames_imu_csv

    mock_frame = {
        "frame_index": 7,
        "timestamp_sec": 0.2333,
        "gyroscope": {"x_dps": 1.25, "y_dps": -0.84, "z_dps": 0.12},
        "accelerometer": {"x_g": 0.051, "y_g": -0.032, "z_g": 1.018}
    }
    scalars = extract_frame_imu_scalars(mock_frame)
    assert scalars["frame_index"] == 7
    assert scalars["gyro_x_dps"] == 1.25
    assert scalars["accel_z_g"] == 1.018

    # Export single frame CSV
    out_csv = tmp_path / "gopro_imu_007.csv"
    export_frame_imu_csv(str(tmp_path), 7, imu_entry=mock_frame, out_csv_path=str(out_csv))
    assert out_csv.exists()
    content = out_csv.read_text(encoding="utf-8")
    lines = content.strip().split("\n")
    assert len(lines) == 2
    assert "frame_index,timestamp_sec,gyro_x_dps,gyro_y_dps,gyro_z_dps,gyro_mag_dps,accel_x_g,accel_y_g,accel_z_g,accel_mag_g" in lines[0]
    assert "7,0.2333,1.25,-0.84,0.12" in lines[1]

    # Export sequence-wide CSV
    payload = {"frames": [mock_frame, {"frame_index": 8, "timestamp_sec": 0.2667}]}
    seq_csv = tmp_path / "gopro_imu_telemetry.csv"
    export_all_frames_imu_csv(str(tmp_path), imu_payload=payload, out_csv_path=str(seq_csv))
    assert seq_csv.exists()
    s_lines = seq_csv.read_text(encoding="utf-8").strip().split("\n")
    assert len(s_lines) == 3


def test_api_imu_csv_endpoints():
    """Verify CSV text and attachment download endpoints for 3-axis IMU."""
    # 1. Inline CSV response
    resp = client.get("/api/telemetry/imu/csv/0")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    assert "gyro_x_dps" in resp.text

    # 2. Sequence-wide CSV response
    resp_all = client.get("/api/telemetry/imu/csv/all")
    assert resp_all.status_code == 200
    assert "accel_z_g" in resp_all.text

    # 3. File attachment download
    resp_dl = client.get("/api/telemetry/imu/export_csv/0")
    assert resp_dl.status_code == 200
    assert "attachment" in resp_dl.headers.get("content-disposition", "")
    assert "gopro_imu_frame_000.csv" in resp_dl.headers.get("content-disposition", "")

    # 4. All frames attachment download
    resp_all_dl = client.get("/api/telemetry/imu/export_all_csv")
    assert resp_all_dl.status_code == 200
    assert "attachment" in resp_all_dl.headers.get("content-disposition", "")
    assert "gopro_imu_telemetry_all_frames.csv" in resp_all_dl.headers.get("content-disposition", "")


def test_export_annotated_xyz_with_imu(tmp_path):
    """Verify export_annotated_xyz appends 3-axis gyro and accel columns when provided."""
    import numpy as np
    from wass_webapp.analyze_wave_xyz import export_annotated_xyz

    pts = np.array([[1.0, 10.0, 0.5]])
    dist_obs = np.array([10.0498])
    h_sea = np.array([0.05])
    mock_imu = {
        "gyroscope": {"x_dps": 2.5, "y_dps": -1.2, "z_dps": 0.3},
        "accelerometer": {"x_g": 0.04, "y_g": -0.02, "z_g": 1.05}
    }
    out_csv = tmp_path / "annotated_with_imu.csv"
    export_annotated_xyz(pts, dist_obs, h_sea, str(out_csv), imu_telemetry=mock_imu)
    assert out_csv.exists()
    content = out_csv.read_text(encoding="utf-8")
    lines = content.strip().split("\n")
    assert len(lines) == 2
    assert lines[0] == "x_camera_m,y_camera_m,z_camera_m,distance_from_observer_m,height_from_sea_level_m,gyro_x_dps,gyro_y_dps,gyro_z_dps,accel_x_g,accel_y_g,accel_z_g"
    assert "2.50,-1.20,0.30,0.040,-0.020,1.050" in lines[1]
