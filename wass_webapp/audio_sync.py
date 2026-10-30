"""
WASS Stereoscopic Video Audio Synchronization Module
===================================================
Computes sub-millisecond temporal offsets between dual-camera video streams
(Cam 0 and Cam 1) via cross-correlation of embedded audio tracks.
"""

import os
import sys
import wave
import shutil
import tempfile
import subprocess
import argparse
import numpy as np
import scipy.signal


def extract_audio_from_video(video_path: str, output_wav: str, sample_rate: int = 48000, duration: float = 30.0) -> bool:
    """
    Extracts a mono 16-bit PCM WAV audio track from a video using ffmpeg.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Input video file not found: {video_path}")

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise RuntimeError("ffmpeg binary not found in PATH. Please install ffmpeg to extract audio from video containers.")

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", video_path,
        "-t", str(duration),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", "1",
        output_wav
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to extract audio from {video_path}: {res.stderr}")
    return True


def read_wav_samples(wav_path: str) -> tuple[np.ndarray, int]:
    """
    Reads 16-bit mono PCM WAV file into float32 numpy array.
    """
    with wave.open(wav_path, "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw_bytes = wf.readframes(n_frames)

    if sampwidth == 2:
        dtype = np.int16
    elif sampwidth == 4:
        dtype = np.int32
    else:
        dtype = np.uint8

    samples = np.frombuffer(raw_bytes, dtype=dtype).astype(np.float32)
    if n_channels > 1:
        samples = samples.reshape(-1, n_channels).mean(axis=1)

    # Normalize waveform
    max_val = np.max(np.abs(samples))
    if max_val > 1e-6:
        samples = samples / max_val

    return samples, framerate


def compute_audio_offset(
    stream0_path: str,
    stream1_path: str,
    sample_rate: int = 48000,
    max_duration: float = 30.0
) -> dict:
    """
    Computes temporal offset between two audio or video files using cross-correlation.
    Returns:
        dict: {
            "offset_seconds": float,
            "offset_ms": float,
            "lag_samples": int,
            "sample_rate": int,
            "confidence": float,
            "leading_camera": str (cam0 or cam1)
        }
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Determine if inputs are already WAV files or video files needing extraction
        if stream0_path.lower().endswith(".wav"):
            wav0 = stream0_path
        else:
            wav0 = os.path.join(tmp_dir, "cam0.wav")
            extract_audio_from_video(stream0_path, wav0, sample_rate=sample_rate, duration=max_duration)

        if stream1_path.lower().endswith(".wav"):
            wav1 = stream1_path
        else:
            wav1 = os.path.join(tmp_dir, "cam1.wav")
            extract_audio_from_video(stream1_path, wav1, sample_rate=sample_rate, duration=max_duration)

        s0, sr0 = read_wav_samples(wav0)
        s1, sr1 = read_wav_samples(wav1)

        # Truncate to common length
        min_len = min(len(s0), len(s1))
        if min_len < 100:
            raise ValueError("Audio streams too short or empty for cross-correlation")

        s0 = s0[:min_len]
        s1 = s1[:min_len]

        # Fast FFT-based normalized cross-correlation
        corr = scipy.signal.correlate(s0, s1, mode="full", method="fft")
        lags = scipy.signal.correlation_lags(len(s0), len(s1), mode="full")

        peak_idx = int(np.argmax(np.abs(corr)))
        lag_samples = int(lags[peak_idx])
        offset_sec = float(lag_samples / float(sample_rate))
        offset_ms = float(offset_sec * 1000.0)

        # Confidence metric (ratio of peak to median background noise)
        med_val = float(np.median(np.abs(corr)))
        peak_val = float(np.abs(corr[peak_idx]))
        confidence = round(peak_val / (med_val + 1e-6), 2)

        # Convention for correlation(s0, s1):
        # A positive lag means s1 occurs earlier than s0 (Cam 1 is ahead/leading, Cam 0 is delayed).
        # A negative lag means s0 occurs earlier than s1 (Cam 0 is ahead/leading, Cam 1 is delayed).
        leading_cam = "cam1" if lag_samples > 0 else ("cam0" if lag_samples < 0 else "synchronized")

        return {
            "offset_seconds": round(offset_sec, 6),
            "offset_ms": round(offset_ms, 3),
            "lag_samples": lag_samples,
            "sample_rate": sample_rate,
            "confidence": confidence,
            "leading_camera": leading_cam,
            "video0": stream0_path,
            "video1": stream1_path
        }


def trim_and_sync_videos(
    video0_path: str,
    video1_path: str,
    output0_path: str,
    output1_path: str,
    sample_rate: int = 48000,
    max_duration: float = 30.0
) -> dict:
    """
    Computes audio offset and trims the leading video using ffmpeg so both video streams
    begin at the exact same microsecond.
    """
    info = compute_audio_offset(video0_path, video1_path, sample_rate=sample_rate, max_duration=max_duration)
    offset_sec = info["offset_seconds"]

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise RuntimeError("ffmpeg binary required for trimming video files")

    os.makedirs(os.path.dirname(os.path.abspath(output0_path)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(output1_path)), exist_ok=True)

    if offset_sec > 0.001:
        # Cam 0 started early -> trim Cam 0 by offset_sec
        cmd0 = [ffmpeg_bin, "-y", "-ss", f"{offset_sec:.6f}", "-i", video0_path, "-avoid_negative_ts", "make_zero", "-c", "copy", output0_path]
        cmd1 = [ffmpeg_bin, "-y", "-i", video1_path, "-c", "copy", output1_path]
        subprocess.run(cmd0, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        subprocess.run(cmd1, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    elif offset_sec < -0.001:
        # Cam 1 started early -> trim Cam 1 by abs(offset_sec)
        trim_val = abs(offset_sec)
        cmd0 = [ffmpeg_bin, "-y", "-i", video0_path, "-c", "copy", output0_path]
        cmd1 = [ffmpeg_bin, "-y", "-ss", f"{trim_val:.6f}", "-i", video1_path, "-avoid_negative_ts", "make_zero", "-c", "copy", output1_path]
        subprocess.run(cmd0, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        subprocess.run(cmd1, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    else:
        # Already synchronized
        shutil.copy2(video0_path, output0_path)
        shutil.copy2(video1_path, output1_path)

    info["synced_video0"] = output0_path
    info["synced_video1"] = output1_path
    return info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WASS Sub-Millisecond Video Audio Synchronizer")
    parser.add_argument("video0", help="Path to Cam 0 video or WAV file")
    parser.add_argument("video1", help="Path to Cam 1 video or WAV file")
    parser.add_argument("--sync-out-dir", type=str, default=None, help="Directory to save synchronized trimmed videos")
    args = parser.parse_args()

    if args.sync_out_dir:
        out0 = os.path.join(args.sync_out_dir, "cam0_synced.mp4")
        out1 = os.path.join(args.sync_out_dir, "cam1_synced.mp4")
        res = trim_and_sync_videos(args.video0, args.video1, out0, out1)
        print("Synchronized videos created:")
        print(f"  Cam 0: {res['synced_video0']}")
        print(f"  Cam 1: {res['synced_video1']}")
    else:
        res = compute_audio_offset(args.video0, args.video1)
        print("Audio Synchronization Analysis:")
        print(f"  Offset: {res['offset_ms']:.2f} ms ({res['offset_seconds']:.6f} s)")
        print(f"  Lag Samples: {res['lag_samples']} @ {res['sample_rate']} Hz")
        print(f"  Leading Camera: {res['leading_camera']}")
        print(f"  Correlation Peak Confidence: {res['confidence']}")
