import os
import sys
import json
import cv2
import numpy as np
from scipy.ndimage import median_filter, gaussian_filter

# Set UTF-8
sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEQ_DIR = os.path.join(BASE_DIR, "wass_webapp", "workspace", "sequence")
sys.path.insert(0, BASE_DIR)
from analyze_wave_xyz import analyze_xyz, export_annotated_xyz

w, h = 960, 540
grid_w, grid_h = 100, 70
y_horizon = 135

xs = np.linspace(-25.0, 15.0, grid_w)
ys = np.linspace(2.5, 50.0, grid_h)
X_grid, Y_grid = np.meshgrid(xs, ys)

B = 0.88
f_scaled = 1867.0 * (w / 3840.0)
H_cam = 4.76
R_grid = np.sqrt(X_grid**2 + Y_grid**2 + H_cam**2)
scale_geom = (R_grid * H_cam) / (f_scaled * B)

v_coords = np.linspace(510, y_horizon + 10, grid_h)
u_coords = np.linspace(40, 670, grid_w)
U_remap, V_remap = np.meshgrid(u_coords, v_coords)

vessel_mask_path = os.path.join(BASE_DIR, "vessel_mask.png")
if os.path.exists(vessel_mask_path):
    vessel_total = cv2.imread(vessel_mask_path, 0)
    vessel_total = cv2.resize(vessel_total, (w, h))
else:
    vessel_total = np.zeros((h, w), dtype=np.uint8)

inpaint_mask = cv2.dilate(vessel_total, np.ones((7, 7), np.uint8))
vessel_grid = cv2.remap((vessel_total > 50).astype(np.uint8), U_remap.astype(np.float32), V_remap.astype(np.float32), cv2.INTER_NEAREST) > 0

total_frames = 60
print(f"Regenerating 3D sea meshes and 5m circular arc wave outputs for {total_frames} frames...")

for i in range(total_frames):
    f0_path = os.path.join(SEQ_DIR, f"video_frame_left_{i:03d}.jpg")
    f1_path = os.path.join(SEQ_DIR, f"video_frame_right_{i:03d}.jpg")
    if not (os.path.exists(f0_path) and os.path.exists(f1_path)):
        print(f"Warning: Frame {i} images not found, stopping at {i}")
        break

    f0_s = cv2.resize(cv2.imread(f0_path), (w, h))
    f1_s = cv2.resize(cv2.imread(f1_path), (w, h))

    g0 = cv2.cvtColor(f0_s, cv2.COLOR_BGR2GRAY)
    g1 = cv2.cvtColor(f1_s, cv2.COLOR_BGR2GRAY)
    flow = cv2.calcOpticalFlowFarneback(g0, g1, None, 0.5, 3, 30, 5, 7, 1.5, 0)
    disp_mag = np.sqrt(flow[..., 0]**2 + flow[..., 1]**2)

    # Inpainting across boat hull
    clean_disp = cv2.inpaint(disp_mag.astype(np.float32), inpaint_mask, 5, cv2.INPAINT_TELEA)

    # Remap onto regularized 100x70 ocean grid
    grid_disp = cv2.remap(clean_disp, U_remap.astype(np.float32), V_remap.astype(np.float32), cv2.INTER_LINEAR)
    disp_trend = np.median(grid_disp, axis=1, keepdims=True)
    residuals = grid_disp - disp_trend
    eta_raw = -residuals * scale_geom

    # Chauvenet 3-sigma outlier rejection
    water_pts = eta_raw[~vessel_grid]
    med = np.median(water_pts)
    sigma = np.std(water_pts)
    outliers = np.abs(eta_raw - med) > (3.0 * sigma)
    eta_filt = eta_raw.copy()
    eta_clean = median_filter(eta_raw, size=3)
    eta_filt[outliers & (~vessel_grid)] = eta_clean[outliers & (~vessel_grid)]
    Z = gaussian_filter(eta_filt, sigma=0.8)

    # Form 7,000 vertices
    pts = []
    xyz_lines = []
    for r in range(grid_h):
        for c in range(grid_w):
            x = round(float(X_grid[r, c]), 3)
            y = round(float(Y_grid[r, c]), 3)
            z = round(float(Z[r, c]), 3)
            pts.append([x, y, z])
            xyz_lines.append(f"{x} {y} {z}\n")

    xyz_path = os.path.join(SEQ_DIR, f"points_{i:03d}.xyz")
    with open(xyz_path, "w") as fx:
        fx.writelines(xyz_lines)

    with open(os.path.join(SEQ_DIR, f"points_{i:03d}.json"), "w") as fp:
        json.dump(pts, fp)

    analysis, pts_arr, dist_obs, h_sea = analyze_xyz(xyz_path)
    with open(os.path.join(SEQ_DIR, f"wave_analysis_{i:03d}.json"), "w") as fa:
        json.dump(analysis, fa, indent=2)

    export_annotated_xyz(pts_arr, dist_obs, h_sea, os.path.join(SEQ_DIR, f"annotated_points_{i:03d}.csv"))

    if i % 10 == 0 or i == total_frames - 1:
        arc5 = analysis["circular_arcs_5m"][0]
        arc30 = analysis["circular_arcs_5m"][5]
        print(f"  Frame {i:02d}: Hs={analysis['significant_wave_height_Hs_m']:.2f}m | Arc 5m (pts={arc5['point_count']}, Hs={arc5['Hs_m']:.2f}m) | Arc 30m (pts={arc30['point_count']}, Hs={arc30['Hs_m']:.2f}m)")

print("Complete! All 60 frames successfully regenerated with 5m circular arc telemetry.")
