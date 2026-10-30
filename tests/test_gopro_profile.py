"""
Unit and Integration Tests for WASS GoPro Multi-Generation Optical Suite
========================================================================
Validates sensor models, optical matrices, distortion polynomials,
automated MP4/GPMF metadata extraction, and XML serialization.
"""

import os
import cv2
import tempfile
import numpy as np
import pytest

from wass_webapp.gopro_profile import (
    GOPRO_MODELS,
    detect_gopro_metadata,
    get_gopro_profile,
    compute_gopro_intrinsics,
    write_wass_calibration_xmls
)


def test_gopro_models_registry():
    """Verify all major GoPro generations exist in the registry with valid physics."""
    expected_models = ["hero5_6_7", "hero8", "hero9_10", "hero11_12_13", "max"]
    for m in expected_models:
        assert m in GOPRO_MODELS, f"Model {m} missing from registry"
        profile = GOPRO_MODELS[m]
        assert profile["sensor_width_mm"] > 5.0
        assert profile["sensor_height_mm"] > 4.0
        assert profile["physical_focal_mm"] > 1.5
        assert len(profile["fov_modes"]) >= 2
        for fov_name, fov_spec in profile["fov_modes"].items():
            assert fov_spec["f_4k_pixels"] > 1000.0
            assert len(fov_spec["distortion"]) == 5


def test_compute_intrinsics_scaling():
    """Verify focal length and optical center scale correctly across resolutions."""
    # 4K UHD
    K_4k, D_4k = compute_gopro_intrinsics(3840, 2160, fov_mode="wide", model="hero9_10")
    assert np.isclose(K_4k[0, 2], 1920.0)
    assert np.isclose(K_4k[1, 2], 1080.0)
    assert np.isclose(K_4k[0, 0], 1890.0)

    # 1080p FHD (exactly 0.5x scale)
    K_1080, D_1080 = compute_gopro_intrinsics(1920, 1080, fov_mode="wide", model="hero9_10")
    assert np.isclose(K_1080[0, 2], 960.0)
    assert np.isclose(K_1080[1, 2], 540.0)
    assert np.isclose(K_1080[0, 0], 1890.0 * 0.5)

    # Distortion coefficients are dimensionless and invariant to scaling
    assert np.allclose(D_4k, D_1080)


def test_fov_modes_optical_properties():
    """Verify optical characteristics of Wide (fisheye barrel) vs Linear (rectilinear)."""
    # Wide mode has barrel distortion (negative k1)
    _, D_wide = compute_gopro_intrinsics(3840, 2160, fov_mode="wide", model="hero11_12_13")
    assert D_wide[0, 0] < 0.0  # k1 < 0 for barrel

    # Linear mode has zero radial distortion (hardware dewarped)
    K_lin, D_lin = compute_gopro_intrinsics(3840, 2160, fov_mode="linear", model="hero11_12_13")
    assert np.allclose(D_lin, 0.0)
    # Linear has narrower FOV -> longer effective focal length
    K_wide, _ = compute_gopro_intrinsics(3840, 2160, fov_mode="wide", model="hero11_12_13")
    assert K_lin[0, 0] > K_wide[0, 0]

    # HyperView (ultra-wide 12mm on HERO11) has shortest focal length
    K_hyper, D_hyper = compute_gopro_intrinsics(3840, 2160, fov_mode="hyperview", model="hero11_12_13")
    assert K_hyper[0, 0] < K_wide[0, 0]
    assert D_hyper[0, 0] < D_wide[0, 0]


def test_auto_detect_from_synthetic_gpmf_metadata(tmp_path):
    """Verify automatic detection of camera model, firmware, and lens mode from MP4 byte streams."""
    # 1. HERO 11 with HyperView
    p11 = tmp_path / "GX010042.MP4"
    p11.write_bytes(b"\x00\x00\x00 ftypmp42\x00\x00\x00\x00moov udta FIRM HD11.01.02.10.00 MINF HERO11 Black LENS HyperView")
    meta11 = detect_gopro_metadata(str(p11))
    assert meta11["detected"] is True
    assert meta11["model_key"] == "hero11_12_13"
    assert meta11["fov_mode"] == "hyperview"
    assert meta11["firmware"] == "HD11.01.02.10.00"

    # 2. HERO 10 with Linear
    p10 = tmp_path / "GX019999.MP4"
    p10.write_bytes(b"\x00\x00\x00 ftypqt  \x00\x00\x00\x00moov udta FIRM HD10.01.01.40.00 MINF HERO10 Black LENS Linear")
    meta10 = detect_gopro_metadata(str(p10))
    assert meta10["detected"] is True
    assert meta10["model_key"] == "hero9_10"
    assert meta10["fov_mode"] == "linear"

    # 3. HERO 8 with Narrow
    p8 = tmp_path / "GX018888.MP4"
    p8.write_bytes(b"moov udta FIRM HD8.01.02.50.00 MINF HERO8 Black LENS Narrow")
    meta8 = detect_gopro_metadata(str(p8))
    assert meta8["detected"] is True
    assert meta8["model_key"] == "hero8"
    assert meta8["fov_mode"] == "narrow"

    # 4. GoPro MAX 360
    pmax = tmp_path / "GS010001.MP4"
    pmax.write_bytes(b"moov trak gpmd DEVC MINF GoPro MAX")
    meta_max = detect_gopro_metadata(str(pmax))
    assert meta_max["detected"] is True
    assert meta_max["model_key"] == "max"

    # 5. Non-GoPro generic video
    pgen = tmp_path / "webcam.mp4"
    pgen.write_bytes(b"\x00\x00\x00 ftypisom generic video container")
    meta_gen = detect_gopro_metadata(str(pgen))
    assert meta_gen["detected"] is False


def test_write_wass_calibration_xmls(tmp_path):
    """Verify OpenCV FileStorage writes and reads back identical calibration matrices."""
    out_dir = str(tmp_path / "calib_xml")
    files = write_wass_calibration_xmls(
        config_dir=out_dir,
        width=3840,
        height=2160,
        fov_mode="linear",
        model="hero10",
        baseline_meters=2.000
    )

    for k in ["intrinsics_00", "intrinsics_01", "distortion_00", "distortion_01", "ext_R", "ext_T"]:
        assert k in files
        assert os.path.exists(files[k])

    # Read back with OpenCV FileStorage
    fs_intr = cv2.FileStorage(files["intrinsics_00"], cv2.FILE_STORAGE_READ)
    K_read = fs_intr.getNode("camera_matrix").mat()
    fs_intr.release()

    fs_dist = cv2.FileStorage(files["distortion_00"], cv2.FILE_STORAGE_READ)
    D_read = fs_dist.getNode("distortion_coefficients").mat()
    fs_dist.release()

    fs_t = cv2.FileStorage(files["ext_T"], cv2.FILE_STORAGE_READ)
    T_read = fs_t.getNode("ext_T").mat()
    fs_t.release()

    assert K_read.shape == (3, 3)
    assert np.isclose(K_read[0, 2], 1920.0)
    assert np.isclose(K_read[1, 2], 1080.0)
    assert np.allclose(D_read, 0.0)  # Linear mode has 0 distortion
    assert np.isclose(T_read[0, 0], -2.000)  # 2.0m baseline


def test_api_run_with_gopro_options():
    """Verify /api/run endpoint accepts explicit and auto gopro_model and gopro_fov parameters."""
    from unittest.mock import patch
    from starlette.testclient import TestClient
    from wass_webapp.app import app

    client = TestClient(app)
    with patch("wass_webapp.app.run_pipeline_worker") as mock_worker:
        resp = client.post("/api/run", data={
            "video_source": "sample",
            "max_frames": 2,
            "step": 1,
            "gopro_model": "hero11_12_13",
            "gopro_fov": "hyperview"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        mock_worker.assert_called_once()
        _, kwargs = mock_worker.call_args
        assert kwargs["gopro_model"] == "hero11_12_13"
        assert kwargs["gopro_fov"] == "hyperview"
