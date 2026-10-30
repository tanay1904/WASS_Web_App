import os
import wave
import tempfile
import numpy as np
import pytest

from wass_webapp.audio_sync import compute_audio_offset, read_wav_samples


def test_audio_cross_correlation_synthetic_lag():
    """Verify compute_audio_offset calculates exact sub-millisecond lag on known signals."""
    sr = 48000
    t = np.linspace(0, 2.0, int(sr * 2.0))
    np.random.seed(42)
    # Rich signal with tones, chirp, and noise
    signal = np.sin(2 * np.pi * 440 * t) + np.sin(2 * np.pi * 880 * t**2) + 0.05 * np.random.randn(len(t))

    # Shift signal 1 by exactly 1440 samples (30.0 ms, ~1 video frame at 30fps)
    lag = 1440
    s0 = signal[lag:]
    s1 = signal[:-lag]

    with tempfile.NamedTemporaryFile(suffix=".wav") as f0, tempfile.NamedTemporaryFile(suffix=".wav") as f1:
        for filename, s in [(f0.name, s0), (f1.name, s1)]:
            with wave.open(filename, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes((s * 32767).astype(np.int16).tobytes())

        res = compute_audio_offset(f0.name, f1.name, sample_rate=sr)

        assert abs(abs(res["lag_samples"]) - lag) <= 1, f"Expected {lag} samples lag, got {res['lag_samples']}"
        assert abs(abs(res["offset_ms"]) - 30.0) <= 0.1, f"Expected 30.0 ms offset, got {res['offset_ms']}"
        assert res["confidence"] > 5.0
        assert res["leading_camera"] in ["cam0", "cam1"]


def test_audio_sync_identical_signals():
    """Verify zero lag on identical audio signals."""
    sr = 48000
    t = np.linspace(0, 1.0, int(sr * 1.0))
    signal = np.sin(2 * np.pi * 500 * t)

    with tempfile.NamedTemporaryFile(suffix=".wav") as f0, tempfile.NamedTemporaryFile(suffix=".wav") as f1:
        for filename in [f0.name, f1.name]:
            with wave.open(filename, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes((signal * 32767).astype(np.int16).tobytes())

        res = compute_audio_offset(f0.name, f1.name, sample_rate=sr)
        assert abs(res["lag_samples"]) == 0
        assert abs(res["offset_ms"]) == 0.0


def test_api_sync_check_endpoint():
    """Verify /api/sync/check endpoint performs audio cross-correlation across dual uploads."""
    from starlette.testclient import TestClient
    from wass_webapp.app import app

    client = TestClient(app)

    # 1. Missing files
    resp = client.post("/api/sync/check")
    assert resp.status_code == 400
    assert "required" in resp.json()["error"]

    # 2. Invalid extension
    files_invalid = {
        "cam0_file": ("test0.exe", b"fake binary", "application/octet-stream"),
        "cam1_file": ("test1.exe", b"fake binary", "application/octet-stream")
    }
    resp = client.post("/api/sync/check", files=files_invalid)
    assert resp.status_code == 400
    assert "Invalid audio/video file format" in resp.json()["error"]

    # 3. Successful sync check on synthetic audio signals
    sr = 48000
    t = np.linspace(0, 1.5, int(sr * 1.5))
    signal = np.sin(2 * np.pi * 440 * t) + 0.05 * np.random.randn(len(t))
    lag = 960  # 20.0 ms
    s0 = signal[lag:]
    s1 = signal[:-lag]

    import io
    def make_wav_bytes(s):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes((s * 32767).astype(np.int16).tobytes())
        return buf.getvalue()

    b0 = make_wav_bytes(s0)
    b1 = make_wav_bytes(s1)

    files_valid = {
        "cam0_file": ("cam0.wav", b0, "audio/wav"),
        "cam1_file": ("cam1.wav", b1, "audio/wav")
    }
    resp = client.post("/api/sync/check", files=files_valid)
    assert resp.status_code == 200
    data = resp.json()
    assert abs(abs(data["offset_ms"]) - 20.0) <= 0.1
    assert "lag_frames_25fps" in data
    assert "lag_frames_30fps" in data
    assert "confidence" in data
    assert data["confidence"] > 1.0

