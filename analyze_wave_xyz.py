import os
import sys
import json
import numpy as np

def analyze_xyz(xyz_path, plane_path=None):
    """
    Analyzes 3D sea wave point cloud from an .xyz file.
    Computes:
      - Distance from observer (origin [0, 0, 0])
      - Height from mean sea level (elevation relative to sea plane)
      - Oceanographic wave statistics (Hs, Hmax, Hmin, skewness, kurtosis)
      - Binned distance vs. wave elevation profiles
    """
    if not os.path.exists(xyz_path):
        raise FileNotFoundError(f"XYZ file not found: {xyz_path}")

    pts = []
    with open(xyz_path, "r") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 3:
                try:
                    pts.append([float(parts[0]), float(parts[1]), float(parts[2])])
                except ValueError:
                    continue
    pts = np.array(pts)
    if len(pts) == 0:
        raise ValueError("No valid 3D points in XYZ file")

    # Determine whether points are already in oriented sea coordinates (Z = wave elevation)
    # or in raw camera frame (where Y is down, Z is optical depth away from camera).
    is_sea_coords = (
        np.abs(np.mean(pts[:, 2])) < 2.5 and
        np.std(pts[:, 2]) < 4.0 and
        np.max(pts[:, 1]) > np.max(pts[:, 2])
    )

    if is_sea_coords:
        # Z is already wave elevation relative to the mean sea plane (Z = 0.00m)
        height_sea_level = pts[:, 2]
        n = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        d = 0.0
        if plane_path and os.path.exists(plane_path):
            try:
                plane = np.loadtxt(plane_path)
                observer_height = round(float(abs(plane[3])), 2)
            except Exception:
                observer_height = 4.76
        else:
            observer_height = 4.76
    else:
        # Raw camera coordinates: fit or load mean sea plane in camera frame
        if plane_path and os.path.exists(plane_path):
            plane = np.loadtxt(plane_path)
            a, b, c, d = plane[:4]
        else:
            # Robust SVD/RANSAC plane estimation
            centroid = np.median(pts, axis=0)
            u, s, vh = np.linalg.svd(pts - centroid)
            normal = vh[2] # Smallest singular value eigenvector
            a, b, c = normal
            d = -np.dot(normal, centroid)

        # Normalize plane equation: ||n|| = 1
        n = np.array([a, b, c], dtype=np.float64)
        norm_n = np.linalg.norm(n)
        n /= norm_n
        d /= norm_n

        # Ensure plane normal points towards camera/observer (origin [0,0,0])
        # The observer is at distance -d > 0 above sea level
        if d > 0:
            n = -n
            d = -d

        observer_height = round(abs(d), 2)
        height_sea_level = pts @ n + d

    # 1. Distance from observer for each point
    dist_observer = np.linalg.norm(pts, axis=1)

    # 3. Wave statistics
    sigma_eta = float(np.std(height_sea_level))
    Hs = 4.0 * sigma_eta # Significant wave height (standard oceanographic definition)
    h_min = float(np.min(height_sea_level))
    h_max = float(np.max(height_sea_level))
    h_mean = float(np.mean(height_sea_level))
    skewness = float(np.mean(((height_sea_level - h_mean) / (sigma_eta + 1e-9))**3))
    kurtosis = float(np.mean(((height_sea_level - h_mean) / (sigma_eta + 1e-9))**4))

    # 4. Distance distribution
    dist_min = float(np.min(dist_observer))
    dist_max = float(np.max(dist_observer))
    dist_mean = float(np.mean(dist_observer))
    dist_median = float(np.median(dist_observer))

    # 5. Distance bins and elevation profile
    bin_edges = np.linspace(dist_min, min(dist_max, 50.0), 10)
    distance_profile = []
    for i in range(len(bin_edges) - 1):
        r_start, r_end = bin_edges[i], bin_edges[i+1]
        mask = (dist_observer >= r_start) & (dist_observer < r_end)
        if np.sum(mask) > 10:
            sub_h = height_sea_level[mask]
            sub_hs = round(float(4.0 * np.std(sub_h)), 3)
            distance_profile.append({
                "range_m": f"{r_start:.1f} - {r_end:.1f}m",
                "center_dist_m": round(float((r_start + r_end) / 2.0), 2),
                "point_count": int(np.sum(mask)),
                "mean_elevation_m": round(float(np.mean(sub_h)), 3),
                "std_elevation_m": round(float(np.std(sub_h)), 3),
                "crest_m": round(float(np.max(sub_h)), 3),
                "trough_m": round(float(np.min(sub_h)), 3),
                "significant_height_m": sub_hs,
                "Hs_m": sub_hs
            })

    # 5b. Fixed 5m Circular Arcs around the vessel (R = sqrt(X^2 + Y^2))
    # Concentric rings centered at vessel: 5m, 10m, 15m, 20m, 25m, 30m, 35m, 40m, 45m, 50m
    r_horiz = np.sqrt(pts[:, 0]**2 + pts[:, 1]**2)
    azimuth_deg = np.degrees(np.arctan2(pts[:, 0], pts[:, 1]))  # 0 deg = forward

    arc_centers = [5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0]
    circular_arcs = []
    for r_c in arc_centers:
        r_start = r_c - 2.5
        r_end = r_c + 2.5
        mask = (r_horiz >= r_start) & (r_horiz < r_end)
        count = int(np.sum(mask))
        if count >= 3:
            sub_h = height_sea_level[mask]
            sub_hs = round(float(4.0 * np.std(sub_h)), 3)
            sub_crest = round(float(np.max(sub_h)), 3)
            sub_trough = round(float(np.min(sub_h)), 3)
            sub_amp = round(float(sub_crest - sub_trough), 3)
            sub_mean = round(float(np.mean(sub_h)), 3)
            sub_sigma = round(float(np.std(sub_h)), 3)
            sub_az = azimuth_deg[mask]
            az_min = round(float(np.min(sub_az)), 1)
            az_max = round(float(np.max(sub_az)), 1)
        else:
            sub_hs = 0.0
            sub_crest = 0.0
            sub_trough = 0.0
            sub_amp = 0.0
            sub_mean = 0.0
            sub_sigma = 0.0
            az_min = 0.0
            az_max = 0.0

        circular_arcs.append({
            "radius_m": r_c,
            "band_m": f"{r_start:.1f} - {r_end:.1f}m",
            "point_count": count,
            "significant_height_Hs_m": sub_hs,
            "Hs_m": sub_hs,
            "crest_m": sub_crest,
            "trough_m": sub_trough,
            "amplitude_m": sub_amp,
            "mean_elevation_m": sub_mean,
            "std_elevation_m": sub_sigma,
            "azimuth_min_deg": az_min,
            "azimuth_max_deg": az_max
        })

    # 6. Elevation histogram & distribution
    counts_raw, bin_edges_raw = np.histogram(height_sea_level, bins=30)
    hist_counts, hist_bins = np.histogram(height_sea_level, bins=30, density=True)
    hist_data = {
        "bin_centers": [round(float((hist_bins[i] + hist_bins[i+1])/2.0), 3) for i in range(len(hist_counts))],
        "densities": [round(float(c), 4) for c in hist_counts]
    }
    dist_data = {
        "counts": [int(c) for c in counts_raw],
        "bin_edges_m": [round(float(b), 3) for b in bin_edges_raw],
        "bin_centers_m": [round(float((bin_edges_raw[i] + bin_edges_raw[i+1])/2.0), 3) for i in range(len(counts_raw))]
    }

    result = {
        "total_points": int(len(pts)),
        "observer_height_m": round(float(observer_height), 2),
        "significant_wave_height_Hs_m": round(float(Hs), 3),
        "peak_crest_m": round(float(h_max), 3),
        "deepest_trough_m": round(float(h_min), 3),
        "mean_elevation_m": round(float(h_mean), 4),
        "elevation_std_sigma_m": round(float(sigma_eta), 3),
        "elevation_skewness": round(float(skewness), 3),
        "elevation_kurtosis": round(float(kurtosis), 3),
        "distance": {
            "min_m": round(float(dist_min), 2),
            "max_m": round(float(dist_max), 2),
            "mean_m": round(float(dist_mean), 2),
            "median_m": round(float(dist_median), 2)
        },
        "distance_profile": distance_profile,
        "circular_arcs_5m": circular_arcs,
        "elevation_histogram": hist_data,
        "elevation_distribution": dist_data,
        "plane_coefficients": {
            "a": round(float(n[0]), 5),
            "b": round(float(n[1]), 5),
            "c": round(float(n[2]), 5),
            "d": round(float(d), 5)
        }
    }
    return result, pts, dist_observer, height_sea_level


def export_annotated_xyz(pts, dist_observer, height_sea_level, out_csv_path):
    """
    Exports point cloud with distance from observer and height from sea level.
    Columns: X, Y, Z, distance_from_observer_m, height_from_sea_level_m
    """
    header = "x_camera_m,y_camera_m,z_camera_m,distance_from_observer_m,height_from_sea_level_m\n"
    with open(out_csv_path, "w") as f:
        f.write(header)
        for i in range(len(pts)):
            f.write(f"{pts[i,0]:.4f},{pts[i,1]:.4f},{pts[i,2]:.4f},{dist_observer[i]:.4f},{height_sea_level[i]:.4f}\n")
    print(f"Exported annotated dataset to {out_csv_path}")


if __name__ == "__main__":
    test_xyz = r"C:\Users\tanay\.gemini\antigravity\scratch\wass_video_workspace\output\000000_wd\plane_refinement_inliers.xyz"
    test_plane = r"C:\Users\tanay\.gemini\antigravity\scratch\wass_video_workspace\output\000000_wd\plane.txt"
    if os.path.exists(test_xyz):
        res, pts, dist, h_sea = analyze_xyz(test_xyz, test_plane)
        print("Analysis completed successfully:")
        print(json.dumps(res, indent=2))
        out_csv = r"C:\Users\tanay\.gemini\antigravity\scratch\annotated_wave_points_sample.csv"
        export_annotated_xyz(pts[:1000], dist[:1000], h_sea[:1000], out_csv)
