#!/usr/bin/env python3
"""
Correlate GoPro In-Camera IMU Telemetry with Drive Ground-Truth Motion Records
=============================================================================
Matches GoPro ICM-20689 IMU data (from Pair 1 & Pair 2) with high-rate Drive IMU
and motion state CSVs from Google Drive (`csv_file_26-06-26_ina` run `hms_20260626_065941`).
Streamlined Schema: Pruned repetitive unit conversions, static metadata, and duplicate metrics.
"""

import os
import csv
import json
import math
import shutil
import numpy as np

BASE_DIR = '/media/tanay/Windows/Users/tanay/predicttion'
OUT_DIR = os.path.join(BASE_DIR, 'drive_imu_data')
SEQ_DIR = os.path.join(BASE_DIR, 'wass_webapp', 'workspace', 'sequence')
DRIVE_RUN_DIR = os.path.join(OUT_DIR, 'folder2', 'hms_20260626_065941')


def load_drive_data(run_dir):
    imu_csv_p = os.path.join(run_dir, 'imu.csv')
    mot_csv_p = os.path.join(run_dir, 'motion.csv')

    print(f"Loading Drive IMU from: {imu_csv_p}")
    with open(imu_csv_p, 'r') as f:
        r = csv.reader(f)
        _h_imu = next(r)
        rows_imu = list(r)

    print(f"Loading Drive Motion from: {mot_csv_p}")
    with open(mot_csv_p, 'r') as f:
        r = csv.reader(f)
        _h_mot = next(r)
        rows_mot = list(r)

    mot_t = np.array([float(rw[0]) for rw in rows_mot])
    print(f"Loaded: imu_rows={len(rows_imu)}, motion_rows={len(rows_mot)}")
    return rows_imu, rows_mot, mot_t


def generate_correlated_csv(pair_id, cam0_feed, cam1_feed, offset_sec, start_sample_idx,
                            rows_imu, rows_mot, mot_t, out_csv_path):
    print(f"\n=== Generating Streamlined Correlated CSV for {pair_id} ===")
    p0_path = os.path.join(SEQ_DIR, f'gopro_imu_telemetry_{cam0_feed}.json')
    p1_path = os.path.join(SEQ_DIR, f'gopro_imu_telemetry_{cam1_feed}.json')

    with open(p0_path) as f0, open(p1_path) as f1:
        d0 = json.load(f0)['frames']
        d1 = json.load(f1)['frames']

    n_frames = min(len(d0), len(d1))
    print(f"Camera frames to correlate: {n_frames} ({n_frames * 0.1:.1f}s)")

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

    for idx in range(n_frames):
        c0 = d0[idx]
        c1_idx = min(idx + offset_samples, len(d1) - 1)
        c1 = d1[c1_idx]

        d_idx = min(start_sample_idx + idx, len(rows_imu) - 1)
        r_imu = rows_imu[d_idx]

        d_t = float(r_imu[0])
        m_idx = min(np.searchsorted(mot_t, d_t), len(rows_mot) - 1)
        r_mot = rows_mot[m_idx]

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

        # Drive IMU
        d_iso = r_imu[1]
        qx, qy, qz, qw = float(r_imu[4]), float(r_imu[5]), float(r_imu[6]), float(r_imu[7])
        dg_x, dg_y, dg_z = float(r_imu[8]), float(r_imu[9]), float(r_imu[10])
        dg_x_dps, dg_y_dps, dg_z_dps = dg_x * 57.2958, dg_y * 57.2958, dg_z * 57.2958
        dg_mag = math.sqrt(dg_x_dps**2 + dg_y_dps**2 + dg_z_dps**2)

        da_x, da_y, da_z = float(r_imu[11]), float(r_imu[12]), float(r_imu[13])
        da_x_g, da_y_g, da_z_g = da_x / 9.80665, da_y / 9.80665, da_z / 9.80665
        da_mag = math.sqrt(da_x_g**2 + da_y_g**2 + da_z_g**2)

        # Drive Motion
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

    print(f"Saved {len(rows_out)} correlated rows ({len(headers)} columns) to: {out_csv_path}")
    return out_csv_path


def main():
    rows_imu, rows_mot, mot_t = load_drive_data(DRIVE_RUN_DIR)

    # Pair 1: Cam 0 at t=1579.8s (sample 15798), Cam 1 lead 23.60s
    p1_csv = generate_correlated_csv(
        pair_id='pair1',
        cam0_feed='GX010077.MP4',
        cam1_feed='GX011273.MP4',
        offset_sec=23.60,
        start_sample_idx=15798,
        rows_imu=rows_imu,
        rows_mot=rows_mot,
        mot_t=mot_t,
        out_csv_path=os.path.join(OUT_DIR, 'correlated_pair1_gopro_drive_imu.csv')
    )

    # Pair 2: Cam 0 at t=2892.1s (sample 28921), Cam 1 lead 10.90s
    p2_csv = generate_correlated_csv(
        pair_id='pair2',
        cam0_feed='GX010078.MP4',
        cam1_feed='GX011274.MP4',
        offset_sec=10.90,
        start_sample_idx=28921,
        rows_imu=rows_imu,
        rows_mot=rows_mot,
        mot_t=mot_t,
        out_csv_path=os.path.join(OUT_DIR, 'correlated_pair2_gopro_drive_imu.csv')
    )

    # Mirror to sequence directory
    os.makedirs(SEQ_DIR, exist_ok=True)
    shutil.copy2(p1_csv, os.path.join(SEQ_DIR, 'correlated_pair1_gopro_drive_imu.csv'))
    shutil.copy2(p2_csv, os.path.join(SEQ_DIR, 'correlated_pair2_gopro_drive_imu.csv'))
    print("\nSuccessfully mirrored both CSVs to sequence directory.")


if __name__ == '__main__':
    main()
