#!/usr/bin/env python3
"""
Generate Full-Length Correlated Datasets for Entire GoPro Video Duration
========================================================================
Aligns 100% of the GoPro video frames (Pair 1: 10,590 frames / 17.65 mins,
Pair 2: 18,370 frames / 30.62 mins) with the multi-run Drive IMU records.
Streamlined Schema: Pruned repetitive unit conversions, static metadata, and duplicate metrics.
"""

import os
import sys
import csv
import json
import math
import shutil
import numpy as np

BASE_DIR = '/media/tanay/Windows/Users/tanay/predicttion'
OUT_DIR = os.path.join(BASE_DIR, 'drive_imu_data')
SEQ_DIR = os.path.join(BASE_DIR, 'wass_webapp', 'workspace', 'sequence')
RUN_DIRS = [
    os.path.join(OUT_DIR, 'folder2', 'hms_20260626_065941'),
    os.path.join(OUT_DIR, 'folder2', 'hms_20260626_080146'),
    os.path.join(OUT_DIR, 'folder2', 'hms_20260626_081306')
]


def load_all_drive_data(run_dirs):
    print("Loading multi-run Drive datasets...")
    all_imu = []
    all_mot = []
    for r_dir in run_dirs:
        print(f"  Reading {os.path.basename(r_dir)}...")
        with open(os.path.join(r_dir, 'imu.csv')) as f:
            r = csv.reader(f)
            _ = next(r)
            all_imu.extend(list(r))
        with open(os.path.join(r_dir, 'motion.csv')) as f:
            r = csv.reader(f)
            _ = next(r)
            all_mot.extend(list(r))

    # Sort strictly by timestamp_ns
    all_imu.sort(key=lambda rw: int(rw[2]))
    all_mot.sort(key=lambda rw: int(rw[2]))

    mot_ns = np.array([int(rw[2]) for rw in all_mot])
    print(f"Combined Drive records: {len(all_imu)} IMU rows, {len(all_mot)} motion rows.")
    return all_imu, all_mot, mot_ns


def build_full_length_csv(pair_id, cam0_feed, cam1_feed, offset_sec, start_sample_idx,
                          g0_path, g1_path, all_imu, all_mot, mot_ns, out_csv_path):
    print(f"\n==================================================")
    print(f" Generating Streamlined Full-Length Dataset for {pair_id.upper()}")
    print(f" Cam 0: {cam0_feed}, Cam 1: {cam1_feed}")
    print(f" Shutter Offset: {offset_sec:.2f}s")
    print(f"==================================================")

    with open(g0_path) as f0, open(g1_path) as f1:
        d0_raw = json.load(f0)
        d1_raw = json.load(f1)

    d0_frames = d0_raw['frames']
    d1_frames = d1_raw['frames']

    total_frames = len(d0_frames)
    duration_sec = total_frames * 0.1
    print(f"Total synchronized output frames: {total_frames} ({duration_sec:.1f}s / {duration_sec/60:.2f} mins)")

    headers = [
        # 1. Timing & Indexing
        'frame_index', 'timestamp_sec', 'drive_timestamp_iso',
        # 2. Cam 0 (Left GoPro)
        'cam0_gyro_x_dps', 'cam0_gyro_y_dps', 'cam0_gyro_z_dps', 'cam0_gyro_mag_dps',
        'cam0_accel_x_g', 'cam0_accel_y_g', 'cam0_accel_z_g', 'cam0_accel_mag_g',
        'cam0_pitch_deg', 'cam0_roll_deg',
        # 3. Cam 1 (Right GoPro, time-aligned with audio sync lag applied)
        'cam1_gyro_x_dps', 'cam1_gyro_y_dps', 'cam1_gyro_z_dps', 'cam1_gyro_mag_dps',
        'cam1_accel_x_g', 'cam1_accel_y_g', 'cam1_accel_z_g', 'cam1_accel_mag_g',
        'cam1_pitch_deg', 'cam1_roll_deg',
        # 4. Drive IMU (Vessel Reference, identical engineering units: dps & g)
        'drive_quat_w', 'drive_quat_x', 'drive_quat_y', 'drive_quat_z',
        'drive_gyro_x_dps', 'drive_gyro_y_dps', 'drive_gyro_z_dps', 'drive_gyro_mag_dps',
        'drive_accel_x_g', 'drive_accel_y_g', 'drive_accel_z_g', 'drive_accel_mag_g',
        # 5. Vessel Hydrodynamic Motion & Safety State
        'drive_roll_phi_deg', 'drive_pitch_theta_deg',
        'drive_heave_z_m', 'drive_heave_velocity_zd_m_s', 'drive_heave_accel_az_hp_m_s2',
        'drive_severity_S', 'drive_severity_S_bar', 'drive_light_name',
        # 6. Cross-Validation Residuals
        'delta_gyro_mag_dps', 'delta_accel_mag_g'
    ]

    offset_samples = int(round(offset_sec * 10.0))
    rows_out = []

    for idx in range(total_frames):
        c0 = d0_frames[idx]
        c1_idx = min(idx + offset_samples, len(d1_frames) - 1)
        c1 = d1_frames[c1_idx]

        d_idx = min(start_sample_idx + idx, len(all_imu) - 1)
        r_imu = all_imu[d_idx]

        cur_ns = int(r_imu[2])
        m_idx = min(np.searchsorted(mot_ns, cur_ns), len(all_mot) - 1)
        r_mot = all_mot[m_idx]

        # Cam 0
        c0_gx, c0_gy, c0_gz = c0['gyroscope']['x_dps'], c0['gyroscope']['y_dps'], c0['gyroscope']['z_dps']
        c0_gmag = math.sqrt(c0_gx**2 + c0_gy**2 + c0_gz**2)
        c0_ax, c0_ay, c0_az = c0['accelerometer']['x_g'], c0['accelerometer']['y_g'], c0['accelerometer']['z_g']
        c0_amag = math.sqrt(c0_ax**2 + c0_ay**2 + c0_az**2)
        c0_p, c0_r = c0['attitude']['pitch_deg'], c0['attitude']['roll_deg']

        # Cam 1
        c1_gx, c1_gy, c1_gz = c1['gyroscope']['x_dps'], c1['gyroscope']['y_dps'], c1['gyroscope']['z_dps']
        c1_gmag = math.sqrt(c1_gx**2 + c1_gy**2 + c1_gz**2)
        c1_ax, c1_ay, c1_az = c1['accelerometer']['x_g'], c1['accelerometer']['y_g'], c1['accelerometer']['z_g']
        c1_amag = math.sqrt(c1_ax**2 + c1_ay**2 + c1_az**2)
        c1_p, c1_r = c1['attitude']['pitch_deg'], c1['attitude']['roll_deg']

        # Drive IMU (convert rad/s to dps and m/s2 to g for 1:1 unit compatibility)
        d_iso = r_imu[1]
        qx, qy, qz, qw = float(r_imu[4]), float(r_imu[5]), float(r_imu[6]), float(r_imu[7])
        dg_x, dg_y, dg_z = float(r_imu[8]), float(r_imu[9]), float(r_imu[10])
        dg_x_dps, dg_y_dps, dg_z_dps = dg_x * 57.2958, dg_y * 57.2958, dg_z * 57.2958
        dg_mag = math.sqrt(dg_x_dps**2 + dg_y_dps**2 + dg_z_dps**2)

        da_x, da_y, da_z = float(r_imu[11]), float(r_imu[12]), float(r_imu[13])
        da_x_g, da_y_g, da_z_g = da_x / 9.80665, da_y / 9.80665, da_z / 9.80665
        da_mag = math.sqrt(da_x_g**2 + da_y_g**2 + da_z_g**2)

        # Drive Motion / Vessel State
        m_phi = float(r_mot[28]) if len(r_mot) > 28 and r_mot[28] else 0.0
        m_theta = float(r_mot[29]) if len(r_mot) > 29 and r_mot[29] else 0.0
        m_z = float(r_mot[19]) if len(r_mot) > 19 and r_mot[19] else 0.0
        m_zd = float(r_mot[22]) if len(r_mot) > 22 and r_mot[22] else 0.0
        m_az_hp = float(r_mot[32]) if len(r_mot) > 32 and r_mot[32] else 0.0
        m_S = float(r_mot[13]) if len(r_mot) > 13 and r_mot[13] else 0.0
        m_S_bar = float(r_mot[14]) if len(r_mot) > 14 and r_mot[14] else 0.0
        m_light = r_mot[4] if len(r_mot) > 4 else 'UNKNOWN'

        d_g_diff = round(abs(c0_gmag - dg_mag), 2)
        d_a_diff = round(abs(c0_amag - da_mag), 3)

        row = [
            # 1. Timing
            idx, round(float(idx) * 0.1, 4), d_iso,
            # 2. Cam 0
            round(c0_gx, 2), round(c0_gy, 2), round(c0_gz, 2), round(c0_gmag, 2),
            round(c0_ax, 3), round(c0_ay, 3), round(c0_az, 3), round(c0_amag, 3),
            round(c0_p, 2), round(c0_r, 2),
            # 3. Cam 1
            round(c1_gx, 2), round(c1_gy, 2), round(c1_gz, 2), round(c1_gmag, 2),
            round(c1_ax, 3), round(c1_ay, 3), round(c1_az, 3), round(c1_amag, 3),
            round(c1_p, 2), round(c1_r, 2),
            # 4. Drive IMU
            round(qw, 4), round(qx, 4), round(qy, 4), round(qz, 4),
            round(dg_x_dps, 2), round(dg_y_dps, 2), round(dg_z_dps, 2), round(dg_mag, 2),
            round(da_x_g, 3), round(da_y_g, 3), round(da_z_g, 3), round(da_mag, 3),
            # 5. Vessel State
            round(m_phi, 2), round(m_theta, 2),
            round(m_z, 3), round(m_zd, 3), round(m_az_hp, 3),
            round(m_S, 3), round(m_S_bar, 3), m_light,
            # 6. Residuals
            d_g_diff, d_a_diff
        ]
        rows_out.append(row)

    with open(out_csv_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows_out)

    print(f"SUCCESS: Saved {len(rows_out)} rows ({len(headers)} columns) to {out_csv_path} (size: {os.path.getsize(out_csv_path)/1024/1024:.2f} MB)")
    return out_csv_path


def main():
    all_imu, all_mot, mot_ns = load_all_drive_data(RUN_DIRS)

    # 1. Pair 1 (GX010077 & GX011273): starts at sample 15,798 in Run 1 (t = 1579.8s)
    p1_csv = build_full_length_csv(
        pair_id='pair1',
        cam0_feed='GX010077.MP4',
        cam1_feed='GX011273.MP4',
        offset_sec=23.60,
        start_sample_idx=15798,
        g0_path=os.path.join(OUT_DIR, 'gopro_imu_full_GX010077.json'),
        g1_path=os.path.join(OUT_DIR, 'gopro_imu_full_GX011273.json'),
        all_imu=all_imu,
        all_mot=all_mot,
        mot_ns=mot_ns,
        out_csv_path=os.path.join(OUT_DIR, 'correlated_pair1_gopro_drive_imu.csv')
    )

    # 2. Pair 2 (GX010078 & GX011274): starts at sample 28,921 in Run 1 (t = 2892.1s)
    p2_csv = build_full_length_csv(
        pair_id='pair2',
        cam0_feed='GX010078.MP4',
        cam1_feed='GX011274.MP4',
        offset_sec=10.90,
        start_sample_idx=28921,
        g0_path=os.path.join(OUT_DIR, 'gopro_imu_full_GX010078.json'),
        g1_path=os.path.join(OUT_DIR, 'gopro_imu_full_GX011274.json'),
        all_imu=all_imu,
        all_mot=all_mot,
        mot_ns=mot_ns,
        out_csv_path=os.path.join(OUT_DIR, 'correlated_pair2_gopro_drive_imu.csv')
    )

    # Mirror to sequence directory
    os.makedirs(SEQ_DIR, exist_ok=True)
    shutil.copy2(p1_csv, os.path.join(SEQ_DIR, 'correlated_pair1_gopro_drive_imu.csv'))
    shutil.copy2(p2_csv, os.path.join(SEQ_DIR, 'correlated_pair2_gopro_drive_imu.csv'))
    print("\nMirrored both streamlined full-length CSV datasets to sequence workspace directory.")


if __name__ == '__main__':
    main()
