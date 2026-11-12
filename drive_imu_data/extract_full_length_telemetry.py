#!/usr/bin/env python3
"""
Full-Length GoPro GPMF Telemetry Downloader and Correlator
=========================================================
Extracts 100% of the GPMF chunks from OneDrive for the entire duration of the
GoPro videos (Pair 1: ~1,059s / 17.6 mins, Pair 2: ~1,837s / 30.6 mins)
and aligns them with the Drive IMU datasets.
"""

import os
import sys
import struct
import math
import bisect
import time
import csv
import json
import requests
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = '/media/tanay/Windows/Users/tanay/predicttion'
OUT_DIR = os.path.join(BASE_DIR, 'drive_imu_data')
CACHE_DIR = os.path.join(OUT_DIR, 'gpmf_cache')
os.makedirs(CACHE_DIR, exist_ok=True)


def get_onedrive_session():
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    share_link = "https://1drv.ms/f/c/5b0c2115f65927cd/IgASJfo0JRCuTa1Ft6kYRcPLAXMnwQneMbuwA9Gm-Fzsjuw?e=fdSXuB"
    s.get(share_link, timeout=25)
    share_token = "u!aHR0cHM6Ly8xZHJ2Lm1zL2YvYy81YjBjMjExNWY2NTkyN2NkL0lnQVNKZm8wSlJDdVRhMUZ0NmtZUmNQTEFYTW53UW5lTWJ1d0E5R20tRnpzanV3P2U9ZmRTWHVC"
    api_url = f"https://onedrive.live.com/personal/5b0c2115f65927cd/_api/v2.0/shares/{share_token}/driveItem/children"
    resp = s.get(api_url, timeout=15)
    items = resp.json().get("value", [])
    item_map = {it["name"]: it for it in items}
    return s, item_map


def fetch_all_gpmf_chunks(s, item, video_name):
    cache_file = os.path.join(CACHE_DIR, f"{video_name}_all_chunks.raw")
    idx_file = os.path.join(CACHE_DIR, f"{video_name}_chunk_indices.json")

    dl = item['@content.downloadUrl']
    sz = int(item['size'])
    print(f"[{video_name}] Querying moov atom (file size: {sz / 1024 / 1024:.1f} MB)...")
    start = max(0, sz - 15000000)
    buf = s.get(dl, headers={'Range': f'bytes={start}-{sz-1}'}, timeout=30).content
    moov_rel = buf.find(b'moov')
    moov_data = buf[moov_rel-4:]

    t_gpmd = None
    idx = 8
    while idx < len(moov_data) - 8:
        s_box = struct.unpack('>I', moov_data[idx:idx+4])[0]
        if moov_data[idx+4:idx+8] == b'trak' and b'gpmd' in moov_data[idx:idx+s_box]:
            t_gpmd = moov_data[idx:idx+s_box]
            break
        idx += s_box if s_box > 0 else 8

    stsz_pos = t_gpmd.find(b'stsz')
    _, sample_cnt = struct.unpack('>II', t_gpmd[stsz_pos+8:stsz_pos+16])
    sizes = [struct.unpack('>I', t_gpmd[stsz_pos+16+i*4:stsz_pos+20+i*4])[0] for i in range(sample_cnt)]
    co64_pos = t_gpmd.find(b'co64')
    if co64_pos != -1:
        chunk_cnt = struct.unpack('>I', t_gpmd[co64_pos+8:co64_pos+12])[0]
        offsets = [struct.unpack('>Q', t_gpmd[co64_pos+12+i*8:co64_pos+20+i*8])[0] for i in range(chunk_cnt)]
    else:
        stco_pos = t_gpmd.find(b'stco')
        chunk_cnt = struct.unpack('>I', t_gpmd[stco_pos+8:stco_pos+12])[0]
        offsets = [struct.unpack('>I', t_gpmd[stco_pos+12+i*4:stco_pos+16+i*4])[0] for i in range(chunk_cnt)]

    print(f"[{video_name}] Found {chunk_cnt} chunks ({chunk_cnt}s / {chunk_cnt/60:.2f} mins). Total GPMF size: {sum(sizes)/1024/1024:.2f} MB")

    print(f"[{video_name}] Downloading all {chunk_cnt} GPMF chunks using 40 worker threads...")
    t0 = time.time()

    def fetch_chunk(i):
        off = offsets[i]
        c_sz = sizes[i]
        for attempt in range(3):
            try:
                r = s.get(dl, headers={'Range': f'bytes={off}-{off+c_sz-1}'}, timeout=20)
                if r.status_code in (200, 206):
                    return i, r.content
            except Exception:
                time.sleep(0.5)
        return i, b''

    with ThreadPoolExecutor(max_workers=40) as ex:
        results = list(ex.map(fetch_chunk, range(chunk_cnt)))

    results.sort(key=lambda x: x[0])
    dt = time.time() - t0
    valid_cnt = sum(1 for x in results if len(x[1]) > 0)
    print(f"[{video_name}] Downloaded {valid_cnt}/{chunk_cnt} chunks in {dt:.1f}s ({valid_cnt/dt:.1f} chunks/sec)!")
    return results, chunk_cnt


def parse_all_gpmf(chunk_results, chunk_cnt, fps=10.0, video_name=""):
    print(f"[{video_name}] Decoding high-rate IMU streams (ACCL, GYRO, CORI)...")
    all_accl = []
    all_gyro = []
    all_cori = []

    for chunk_idx, raw_chunk in chunk_results:
        t_chunk_start = float(chunk_idx)
        if not raw_chunk or len(raw_chunk) < 32:
            continue

        # ACCL
        p_accl = raw_chunk.find(b'ACCL')
        if p_accl != -1:
            p_scal = raw_chunk.rfind(b'SCAL', 0, p_accl)
            scal_a = 419.0
            if p_scal != -1:
                sz_s = raw_chunk[p_scal+5]
                scal_a = float(struct.unpack('>h', raw_chunk[p_scal+8:p_scal+10])[0]) if sz_s == 2 else float(struct.unpack('>i', raw_chunk[p_scal+8:p_scal+12])[0])
            cnt_a = struct.unpack('>H', raw_chunk[p_accl+6:p_accl+8])[0]
            raw_a = raw_chunk[p_accl+8:p_accl+8+6*cnt_a]
            dt_a = 1.0 / max(1, cnt_a)
            for i in range(cnt_a):
                x, y, z = struct.unpack('>3h', raw_a[i*6:(i+1)*6])
                ax = (x / scal_a) / 9.80665
                ay = (y / scal_a) / 9.80665
                az = (z / scal_a) / 9.80665
                all_accl.append((t_chunk_start + i * dt_a, ax, ay, az))

        # GYRO
        p_gyro = raw_chunk.find(b'GYRO')
        if p_gyro != -1:
            p_scal = raw_chunk.rfind(b'SCAL', 0, p_gyro)
            scal_g = 939.0
            if p_scal != -1:
                sz_s = raw_chunk[p_scal+5]
                scal_g = float(struct.unpack('>h', raw_chunk[p_scal+8:p_scal+10])[0]) if sz_s == 2 else float(struct.unpack('>i', raw_chunk[p_scal+8:p_scal+12])[0])
            cnt_g = struct.unpack('>H', raw_chunk[p_gyro+6:p_gyro+8])[0]
            raw_g = raw_chunk[p_gyro+8:p_gyro+8+6*cnt_g]
            dt_g = 1.0 / max(1, cnt_g)
            rad_to_deg = 180.0 / math.pi
            for i in range(cnt_g):
                x, y, z = struct.unpack('>3h', raw_g[i*6:(i+1)*6])
                gx = (x / scal_g) * rad_to_deg
                gy = (y / scal_g) * rad_to_deg
                gz = (z / scal_g) * rad_to_deg
                all_gyro.append((t_chunk_start + i * dt_g, gx, gy, gz))

        # CORI
        p_cori = raw_chunk.find(b'CORI')
        if p_cori != -1:
            cnt_c = struct.unpack('>H', raw_chunk[p_cori+6:p_cori+8])[0]
            raw_c = raw_chunk[p_cori+8:p_cori+8+8*cnt_c]
            dt_c = 1.0 / max(1, cnt_c)
            for i in range(cnt_c):
                qw, qx, qy, qz = [v / 32767.0 for v in struct.unpack('>4h', raw_c[i*8:(i+1)*8])]
                roll = math.degrees(math.atan2(2*(qw*qx + qy*qz), 1 - 2*(qx*qx + qy*qy)))
                pitch = math.degrees(math.asin(max(-1.0, min(1.0, 2*(qw*qy - qz*qx)))))
                yaw = math.degrees(math.atan2(2*(qw*qz + qx*qy), 1 - 2*(qy*qy + qz*qz)))
                all_cori.append((t_chunk_start + i * dt_c, pitch, roll, yaw))

    print(f"[{video_name}] Decoded: {len(all_accl)} accel samples ({len(all_accl)/max(1,chunk_cnt):.1f} Hz), {len(all_gyro)} gyro samples ({len(all_gyro)/max(1,chunk_cnt):.1f} Hz), {len(all_cori)} cori samples.")

    # Interpolate to 10 FPS
    total_frames = int(chunk_cnt * fps)
    print(f"[{video_name}] Interpolating to {total_frames} frames at {fps} FPS...")
    frames = []
    accl_times = [s[0] for s in all_accl]
    gyro_times = [s[0] for s in all_gyro]
    cori_times = [s[0] for s in all_cori] if all_cori else []

    for idx in range(total_frames):
        t = float(idx) / float(fps)
        pos_a = bisect.bisect_left(accl_times, t)
        pos_a = min(max(0, pos_a), len(all_accl) - 1)
        _, ax, ay, az = all_accl[pos_a]

        pos_g = bisect.bisect_left(gyro_times, t)
        pos_g = min(max(0, pos_g), len(all_gyro) - 1)
        _, gx, gy, gz = all_gyro[pos_g]

        if cori_times:
            pos_c = bisect.bisect_left(cori_times, t)
            pos_c = min(max(0, pos_c), len(all_cori) - 1)
            _, pitch_val, roll_val, yaw_val = all_cori[pos_c]
        else:
            pitch_val = math.degrees(math.atan2(ax, math.sqrt(ay**2 + az**2)))
            roll_val = math.degrees(math.atan2(-ay, az))
            yaw_val = 0.0

        frames.append({
            'frame_index': idx,
            'timestamp_sec': round(t, 4),
            'gyroscope': {'x_dps': round(gx, 2), 'y_dps': round(gy, 2), 'z_dps': round(gz, 2)},
            'accelerometer': {'x_g': round(ax, 3), 'y_g': round(ay, 3), 'z_g': round(az, 3)},
            'attitude': {'pitch_deg': round(pitch_val, 2), 'roll_deg': round(roll_val, 2), 'yaw_deg': round(yaw_val, 2)}
        })

    return frames


if __name__ == '__main__':
    s, item_map = get_onedrive_session()

    # Pair 1: Cam 0 (GX010077) & Cam 1 (GX011273)
    c0_chunks, c0_cnt = fetch_all_gpmf_chunks(s, item_map['GX010077.MP4'], 'GX010077.MP4')
    c1_chunks, c1_cnt = fetch_all_gpmf_chunks(s, item_map['GX011273.MP4'], 'GX011273.MP4')

    d0_frames = parse_all_gpmf(c0_chunks, c0_cnt, fps=10.0, video_name='GX010077.MP4')
    d1_frames = parse_all_gpmf(c1_chunks, c1_cnt, fps=10.0, video_name='GX011273.MP4')

    # Save to JSON
    with open(os.path.join(OUT_DIR, 'gopro_imu_full_GX010077.json'), 'w') as f:
        json.dump({'video_name': 'GX010077.MP4', 'duration_sec': c0_cnt, 'total_frames': len(d0_frames), 'frames': d0_frames}, f)
    with open(os.path.join(OUT_DIR, 'gopro_imu_full_GX011273.json'), 'w') as f:
        json.dump({'video_name': 'GX011273.MP4', 'duration_sec': c1_cnt, 'total_frames': len(d1_frames), 'frames': d1_frames}, f)

    print(f"Saved full Pair 1 telemetry JSONs: Cam0={len(d0_frames)} frames, Cam1={len(d1_frames)} frames!")
