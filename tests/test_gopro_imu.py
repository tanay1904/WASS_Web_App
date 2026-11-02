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


def test_pure_mp4_telemetry_source():
    """Verify that the active sequence IMU telemetry reflects genuine GoPro HERO GPMF data."""
    resp = client.get("/api/telemetry/imu")
    assert resp.status_code == 200
    data = resp.json()
    assert "source" in data
    assert "GoPro HERO GPMF" in data["source"]
    assert len(data.get("frames", [])) >= 840
    f0 = data["frames"][0]
    assert "gyroscope" in f0
    assert "accelerometer" in f0
    assert "x_dps" in f0["gyroscope"]
    assert "z_g" in f0["accelerometer"]


def test_list_available_gopro_feeds():
    """Verify listing all available camera feeds (Pair 1 & Pair 2 Cam0 and Cam1)."""
    from wass_webapp.gopro_imu import list_available_gopro_feeds
    feeds = list_available_gopro_feeds()
    assert len(feeds) >= 4
    feed_ids = [f["id"] for f in feeds]
    assert "GX010077.MP4" in feed_ids
    assert "GX011273.MP4" in feed_ids
    assert "GX010078.MP4" in feed_ids
    assert "GX011274.MP4" in feed_ids


def test_api_feeds_endpoint():
    """Verify GET /api/telemetry/imu/feeds returns catalog of feeds with active marker."""
    resp = client.get("/api/telemetry/imu/feeds")
    assert resp.status_code == 200
    data = resp.json()
    assert "active_feed" in data
    assert "available_feeds" in data
    assert len(data["available_feeds"]) >= 4
    assert any(f["is_active"] for f in data["available_feeds"])


def test_api_multi_camera_feed_query():
    """Verify GET /api/telemetry/imu?feed=GX011273.MP4 returns telemetry for Cam 1."""
    resp = client.get("/api/telemetry/imu?feed=GX011273.MP4")
    assert resp.status_code == 200
    data = resp.json()
    assert data["feed_name"] == "GX011273.MP4"
    assert "GoPro HERO GPMF" in data["source"]
    assert len(data.get("frames", [])) > 0


def test_binocular_stereo_imu_structure():
    """Verify binocular stereo extraction accommodates both Cam 0 and Cam 1 with differential kinematics."""
    from wass_webapp.gopro_imu import get_or_extract_binocular_stereo_imu
    from wass_webapp.app import WORK_DIR
    seq_dir = os.path.join(WORK_DIR, "sequence")
    payload = get_or_extract_binocular_stereo_imu(seq_dir, pair="pair1", total_frames=840)
    assert payload.get("stereo_mode") is True
    assert payload.get("pair_id") == "pair1"
    assert payload.get("cam0_feed") == "GX010077.MP4"
    assert payload.get("cam1_feed") == "GX011273.MP4"
    frames = payload.get("frames", [])
    assert len(frames) >= 840

    f0 = frames[0]
    # 1. Cam 0 Left Camera
    assert "cam0" in f0
    assert f0["cam0"]["feed"] == "GX010077.MP4"
    assert "gyroscope" in f0["cam0"]
    assert "accelerometer" in f0["cam0"]

    # 2. Cam 1 Right Camera
    assert "cam1" in f0
    assert f0["cam1"]["feed"] == "GX011273.MP4"
    assert "gyroscope" in f0["cam1"]
    assert "accelerometer" in f0["cam1"]

    # 3. Baseline Differential Dynamics
    assert "baseline_differential" in f0
    diff = f0["baseline_differential"]
    assert "delta_gyro_dps" in diff
    assert "delta_accel_g" in diff
    assert "mag" in diff["delta_gyro_dps"]
    assert "mag" in diff["delta_accel_g"]

    # 4. Top-level backward compatibility
    assert "gyroscope" in f0
    assert "accelerometer" in f0
    assert "x_dps" in f0["gyroscope"]
    assert "z_g" in f0["accelerometer"]


def test_binocular_stereo_csv_export(tmp_path):
    """Verify CSV exporter produces both Cam 0 and Cam 1 columns and differential magnitudes."""
    from wass_webapp.gopro_imu import extract_frame_imu_scalars, export_frame_imu_csv, export_all_frames_imu_csv

    stereo_mock_frame = {
        "frame_index": 5,
        "timestamp_sec": 0.1667,
        "stereo_mode": True,
        "cam0": {
            "gyroscope": {"x_dps": 1.20, "y_dps": -0.80, "z_dps": 0.30},
            "accelerometer": {"x_g": 0.050, "y_g": -0.030, "z_g": 1.020}
        },
        "cam1": {
            "gyroscope": {"x_dps": 1.50, "y_dps": -0.60, "z_dps": 0.40},
            "accelerometer": {"x_g": 0.060, "y_g": -0.020, "z_g": 0.980}
        },
        "baseline_differential": {
            "delta_gyro_dps": {"x": 0.30, "y": 0.20, "z": 0.10, "mag": 0.37},
            "delta_accel_g": {"x": 0.010, "y": 0.010, "z": -0.040, "mag": 0.042}
        },
        "gyroscope": {"x_dps": 1.20, "y_dps": -0.80, "z_dps": 0.30},
        "accelerometer": {"x_g": 0.050, "y_g": -0.030, "z_g": 1.020}
    }

    s = extract_frame_imu_scalars(stereo_mock_frame)
    assert s["is_stereo"] is True
    assert s["cam0_gyro_x_dps"] == 1.20
    assert s["cam1_gyro_x_dps"] == 1.50
    assert s["delta_gyro_x_dps"] == 0.30
    assert s["cam0_accel_z_g"] == 1.020
    assert s["cam1_accel_z_g"] == 0.980

    out_csv = tmp_path / "gopro_imu_005.csv"
    export_frame_imu_csv(str(tmp_path), 5, imu_entry=stereo_mock_frame, out_csv_path=str(out_csv))
    assert out_csv.exists()
    content = out_csv.read_text(encoding="utf-8")
    lines = content.strip().split("\n")
    assert "cam0_gyro_x_dps" in lines[0]
    assert "cam1_gyro_x_dps" in lines[0]
    assert "delta_gyro_mag_dps" in lines[0]
    assert "1.20,-0.80,0.30" in lines[1]
    assert "1.50,-0.60,0.40" in lines[1]


def test_api_stereo_feed_selection():
    """Verify switching to pair1_stereo feed via POST and querying active telemetry."""
    # 1. Switch active feed to pair1_stereo
    resp = client.post("/api/telemetry/imu/select_feed", json={"feed": "pair1_stereo"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["active_feed"] == "pair1_stereo"

    # 2. Query default GET /api/telemetry/imu
    resp_get = client.get("/api/telemetry/imu")
    assert resp_get.status_code == 200
    tel = resp_get.json()
    assert tel.get("stereo_mode") is True
    assert len(tel.get("frames", [])) >= 840
    f0 = tel["frames"][0]
    assert "cam0" in f0
    assert "cam1" in f0
    assert "baseline_differential" in f0


def test_interpolate_frame_from_series():
    """Verify linear interpolation of physical IMU telemetry across arbitrary timestamps."""
    from wass_webapp.gopro_imu import interpolate_frame_from_series

    f0 = {
        "frame_index": 0,
        "timestamp_sec": 0.0,
        "gyroscope": {"x_dps": 2.0, "y_dps": 4.0, "z_dps": -1.0},
        "accelerometer": {"x_g": 0.10, "y_g": 0.20, "z_g": 0.98},
        "attitude": {"pitch_deg": 5.0, "roll_deg": -3.0, "yaw_deg": 10.0}
    }
    f1 = {
        "frame_index": 1,
        "timestamp_sec": 0.1,
        "gyroscope": {"x_dps": 4.0, "y_dps": 8.0, "z_dps": -3.0},
        "accelerometer": {"x_g": 0.30, "y_g": 0.40, "z_g": 1.02},
        "attitude": {"pitch_deg": 7.0, "roll_deg": -1.0, "yaw_deg": 12.0}
    }
    series = [f0, f1]

    # Exact boundary 0.0
    res0 = interpolate_frame_from_series(series, 0.0)
    assert res0["timestamp_sec"] == 0.0
    assert res0["gyroscope"]["x_dps"] == 2.0

    # Midpoint 0.05
    res_mid = interpolate_frame_from_series(series, 0.05)
    assert res_mid["timestamp_sec"] == 0.05
    assert res_mid["gyroscope"]["x_dps"] == 3.0
    assert res_mid["gyroscope"]["y_dps"] == 6.0
    assert res_mid["gyroscope"]["z_dps"] == -2.0
    assert res_mid["accelerometer"]["x_g"] == 0.20
    assert res_mid["attitude"]["pitch_deg"] == 6.0

    # Clamping below 0
    res_neg = interpolate_frame_from_series(series, -0.05)
    assert res_neg["timestamp_sec"] == -0.05
    assert res_neg["gyroscope"]["x_dps"] == 2.0

    # Clamping above max
    res_hi = interpolate_frame_from_series(series, 0.25)
    assert res_hi["timestamp_sec"] == 0.25
    assert res_hi["gyroscope"]["x_dps"] == 4.0


def test_get_audio_sync_offset_computation(tmp_path):
    """Verify audio sync offset calculation and JSON caching."""
    import wave
    import numpy as np
    from wass_webapp.gopro_imu import get_audio_sync_offset

    sr = 48000
    t = np.linspace(0, 1.0, sr)
    sig = np.sin(2 * np.pi * 500 * t) + 0.02 * np.random.randn(len(t))
    lag = 960  # 20.0 ms
    s0 = sig[lag:]
    s1 = sig[:-lag]

    w0 = tmp_path / "c0.wav"
    w1 = tmp_path / "c1.wav"
    for path, s in [(w0, s0), (w1, s1)]:
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes((s * 32767).astype(np.int16).tobytes())

    res = get_audio_sync_offset(str(tmp_path), pair_id="pair1", cam0_path=str(w0), cam1_path=str(w1))
    assert "offset_seconds" in res
    assert abs(abs(res["offset_ms"]) - 20.0) <= 0.2
    assert (tmp_path / "audio_sync_pair1.json").exists()


def test_binocular_stereo_audio_sync_toggle(tmp_path):
    """Verify binocular stereo IMU applies acoustic offset when enabled and nominal clocks when disabled."""
    from wass_webapp.gopro_imu import get_or_extract_binocular_stereo_imu
    from wass_webapp.app import WORK_DIR

    seq_dir = os.path.join(WORK_DIR, "sequence")

    # 1. Audio Sync ENABLED
    payload_synced = get_or_extract_binocular_stereo_imu(seq_dir, pair="pair1", enable_audio_sync=True)
    assert payload_synced.get("audio_sync", {}).get("enabled") is True
    offset_sec = payload_synced["audio_sync"]["offset_seconds"]
    assert offset_sec > 0.0
    f1_synced = payload_synced["frames"][1]
    assert f1_synced["audio_sync"]["enabled"] is True
    assert "cam1" in f1_synced

    # 2. Audio Sync DISABLED
    payload_nosync = get_or_extract_binocular_stereo_imu(seq_dir, pair="pair1", enable_audio_sync=False)
    assert payload_nosync.get("audio_sync", {}).get("enabled") is False
    assert payload_nosync["audio_sync"]["offset_seconds"] == 0.0
    f1_nosync = payload_nosync["frames"][1]
    assert f1_nosync["audio_sync"]["enabled"] is False

    # Verify that Cam 1's values or timestamps differ between synced and nosync
    assert f1_synced["cam1"]["timestamp_sec"] != f1_nosync["cam1"]["timestamp_sec"]
    assert abs(f1_synced["cam1"]["timestamp_sec"] - (f1_nosync["cam1"]["timestamp_sec"] - offset_sec)) < 1e-4


def test_api_audio_sync_endpoints():
    """Verify /api/telemetry/imu?audio_sync=true|false and /api/telemetry/imu/toggle_audio_sync."""
    # 1. Query with audio_sync=true
    r_true = client.get("/api/telemetry/imu?audio_sync=true")
    assert r_true.status_code == 200
    d_true = r_true.json()
    assert d_true.get("audio_sync", {}).get("enabled") is True
    assert d_true["audio_sync"]["offset_seconds"] > 0

    # 2. Query with audio_sync=false
    r_false = client.get("/api/telemetry/imu?audio_sync=false")
    assert r_false.status_code == 200
    d_false = r_false.json()
    assert d_false.get("audio_sync", {}).get("enabled") is False
    assert d_false["audio_sync"]["offset_seconds"] == 0.0

    # 3. Toggle audio sync via POST endpoint
    r_toggle_off = client.post("/api/telemetry/imu/toggle_audio_sync", json={"enabled": False})
    assert r_toggle_off.status_code == 200
    d_off = r_toggle_off.json()
    assert d_off["status"] == "success"
    assert d_off["audio_sync_enabled"] is False
    assert d_off["telemetry"]["audio_sync"]["enabled"] is False

    r_toggle_on = client.post("/api/telemetry/imu/toggle_audio_sync", json={"enabled": True})
    assert r_toggle_on.status_code == 200
    d_on = r_toggle_on.json()
    assert d_on["status"] == "success"
    assert d_on["audio_sync_enabled"] is True
    assert d_on["telemetry"]["audio_sync"]["enabled"] is True



