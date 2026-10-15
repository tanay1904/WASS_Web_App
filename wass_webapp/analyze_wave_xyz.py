import os
import sys
import json
import numpy as np


def _empty_analysis_fallback(total_points=0):
    """Returns a schema-compliant fallback dictionary for degenerate or empty point clouds."""
    arc_centers = [5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0]
    circular_arcs = [
        {
            "radius_m": r_c,
            "band_m": f"{r_c - 2.5:.1f} - {r_c + 2.5:.1f}m",
            "point_count": 0,
            "significant_height_Hs_m": 0.0,
            "Hs_m": 0.0,
            "crest_m": 0.0,
            "trough_m": 0.0,
            "amplitude_m": 0.0,
            "mean_elevation_m": 0.0,
            "std_elevation_m": 0.0,
            "azimuth_min_deg": 0.0,
            "azimuth_max_deg": 0.0
        }
        for r_c in arc_centers
    ]
    return {
        "total_points": int(total_points),
        "observer_height_m": 4.76,
        "significant_wave_height_Hs_m": 0.0,
        "peak_crest_m": 0.0,
        "deepest_trough_m": 0.0,
        "crest_elevation_max_m": 0.0,
        "trough_depth_min_m": 0.0,
        "wave_amplitude_m": 0.0,
        "wave_amplitude_total_m": 0.0,
        "elevation_std_sigma_m": 0.0,
        "mean_elevation_m": 0.0,
        "elevation_skewness": 0.0,
        "elevation_kurtosis": 3.0,
        "wave_parameters": {
            "mean_elevation_m": 0.0,
            "elevation_std_sigma_m": 0.0,
            "significant_wave_height_Hs_m": 0.0,
            "peak_crest_m": 0.0,
            "deepest_trough_m": 0.0,
            "crest_elevation_max_m": 0.0,
            "trough_depth_min_m": 0.0,
            "wave_amplitude_m": 0.0,
            "wave_amplitude_total_m": 0.0,
            "skewness": 0.0,
            "kurtosis": 3.0
        },
        "distance": {
            "min_m": 0.0,
            "max_m": 0.0,
            "mean_m": 0.0,
            "median_m": 0.0
        },
        "distance_profile": [],
        "circular_arcs_5m": circular_arcs,
        "elevation_histogram": {
            "bin_centers": [0.0] * 30,
            "densities": [0.0] * 30
        },
        "elevation_distribution": {
            "counts": [0] * 30,
            "bin_edges_m": [0.0] * 31,
            "bin_centers_m": [0.0] * 30
        },
        "plane_coefficients": {
            "a": 0.0,
            "b": 0.0,
            "c": 1.0,
            "d": 0.0
        }
    }


def analyze_xyz(xyz_path, plane_path=None):
    """
    Analyzes 3D sea wave point cloud from an .xyz file.
    Computes:
      - Distance from observer (origin [0, 0, 0])
      - Height from mean sea level (elevation relative to sea plane)
      - Oceanographic wave statistics (Hs, Hmax, Hmin, skewness, kurtosis)
      - Binned distance vs. wave elevation profiles
      - 10 concentric 5m radar arcs centered at vessel
    """
    if not os.path.exists(xyz_path):
        raise FileNotFoundError(f"XYZ file not found: {xyz_path}")

    pts = []
    with open(xyz_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 3:
                try:
                    p0 = float(parts[0])
                    p1 = float(parts[1])
                    p2 = float(parts[2])
                    if np.isfinite(p0) and np.isfinite(p1) and np.isfinite(p2):
                        pts.append([p0, p1, p2])
                except (ValueError, OverflowError):
                    continue

    pts = np.array(pts, dtype=np.float64)
    if len(pts) < 3:
        return _empty_analysis_fallback(len(pts)), pts, np.array([], dtype=np.float64), np.array([], dtype=np.float64)

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
                plane = np.loadtxt(plane_path).flatten()
                if len(plane) >= 4 and np.isfinite(plane[3]):
                    observer_height = round(float(abs(plane[3])), 2)
                else:
                    observer_height = 4.76
            except Exception:
                observer_height = 4.76
        else:
            observer_height = 4.76
    else:
        # Raw camera coordinates: fit or load mean sea plane in camera frame
        plane_loaded = False
        if plane_path and os.path.exists(plane_path):
            try:
                plane = np.loadtxt(plane_path).flatten()
                if len(plane) >= 4 and np.all(np.isfinite(plane[:4])):
                    a, b, c, d = float(plane[0]), float(plane[1]), float(plane[2]), float(plane[3])
                    plane_loaded = True
            except Exception:
                plane_loaded = False

        if not plane_loaded:
            centroid = np.median(pts, axis=0)
            cov = np.cov(pts - centroid, rowvar=False)
            if cov.shape == (3, 3) and np.all(np.isfinite(cov)):
                try:
                    u, s, vh = np.linalg.svd(cov)
                    normal = vh[2]  # Smallest singular value eigenvector
                except Exception:
                    normal = np.array([0.0, 0.0, 1.0])
            else:
                normal = np.array([0.0, 0.0, 1.0])
            a, b, c = float(normal[0]), float(normal[1]), float(normal[2])
            d = -float(np.dot(normal, centroid))

        # Normalize plane equation: ||n|| = 1
        n = np.array([a, b, c], dtype=np.float64)
        norm_n = float(np.linalg.norm(n))
        if norm_n > 1e-7 and np.isfinite(norm_n):
            n /= norm_n
            d /= norm_n
        else:
            n = np.array([0.0, 0.0, 1.0], dtype=np.float64)
            d = -4.76

        # Ensure plane normal points towards camera/observer (origin [0,0,0])
        if d > 0:
            n = -n
            d = -d

        observer_height = round(float(abs(d)), 2)
        height_sea_level = pts @ n + d

    # 1. Distance from observer for each point
    dist_observer = np.linalg.norm(pts, axis=1)

    # 3. Wave statistics
    sigma_eta = float(np.std(height_sea_level))
    sigma_rounded = round(float(np.nan_to_num(sigma_eta, nan=0.0)), 3)
    hs_rounded = round(float(4.0 * sigma_rounded), 3)
    h_min = float(np.min(height_sea_level))
    h_max = float(np.max(height_sea_level))
    h_mean = float(np.mean(height_sea_level))
    crest_rounded = round(float(np.nan_to_num(h_max, nan=0.0)), 3)
    trough_rounded = round(float(np.nan_to_num(h_min, nan=0.0)), 3)
    amp_rounded = round(float(crest_rounded - trough_rounded), 3)

    if sigma_eta > 1e-6:
        skewness = float(np.mean(((height_sea_level - h_mean) / sigma_eta)**3))
        kurtosis = float(np.mean(((height_sea_level - h_mean) / sigma_eta)**4))
    else:
        skewness = 0.0
        kurtosis = 3.0

    # 4. Distance distribution
    dist_min = float(np.min(dist_observer))
    dist_max = float(np.max(dist_observer))
    dist_mean = float(np.mean(dist_observer))
    dist_median = float(np.median(dist_observer))

    # 5. Distance bins and elevation profile (strictly guarded against inverted boundaries)
    if dist_min >= 50.0:
        max_bound = dist_max if dist_max > dist_min else dist_min + 10.0
    else:
        max_bound = min(dist_max, 50.0) if dist_max > dist_min else dist_min + 1.0

    if max_bound <= dist_min:
        max_bound = dist_min + 10.0
    bin_edges = np.linspace(dist_min, max_bound, 10)
    distance_profile = []
    for i in range(len(bin_edges) - 1):
        r_start, r_end = bin_edges[i], bin_edges[i+1]
        mask = (dist_observer >= r_start) & (dist_observer < r_end)
        if np.sum(mask) >= 3:
            sub_h = height_sea_level[mask]
            sub_sigma = round(float(np.nan_to_num(np.std(sub_h), nan=0.0)), 3)
            sub_hs = round(float(4.0 * sub_sigma), 3)
            sub_crest = round(float(np.nan_to_num(np.max(sub_h), nan=0.0)), 3)
            sub_trough = round(float(np.nan_to_num(np.min(sub_h), nan=0.0)), 3)
            sub_amp = round(float(sub_crest - sub_trough), 3)
            distance_profile.append({
                "range_m": f"{r_start:.1f} - {r_end:.1f}m",
                "range_start_m": round(float(r_start), 2),
                "range_end_m": round(float(r_end), 2),
                "center_dist_m": round(float((r_start + r_end) / 2.0), 2),
                "point_count": int(np.sum(mask)),
                "mean_elevation_m": round(float(np.mean(sub_h)), 3),
                "std_elevation_m": sub_sigma,
                "crest_m": sub_crest,
                "trough_m": sub_trough,
                "amplitude_m": sub_amp,
                "significant_height_m": sub_hs,
                "Hs_m": sub_hs
            })

    # 5b. Fixed 5m Circular Arcs around the vessel (R = sqrt(X^2 + Y^2))
    # Concentric rings centered at vessel: 5m, 10m, 15m, 20m, 25m, 30m, 35m, 40m, 45m, 50m
    r_horiz = np.sqrt(pts[:, 0]**2 + pts[:, 1]**2)
    # Azimuth: 0 deg = forward (positive Y)
    azimuth_deg = np.degrees(np.arctan2(pts[:, 0], np.maximum(pts[:, 1], 1e-6)))

    arc_centers = [5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0]
    circular_arcs = []
    for r_c in arc_centers:
        r_start = r_c - 2.5
        r_end = r_c + 2.5
        # Confine to forward field of view (Y >= 0)
        mask = (r_horiz >= r_start) & (r_horiz < r_end) & (pts[:, 1] >= 0.0)
        count = int(np.sum(mask))
        if count >= 3:
            sub_h = height_sea_level[mask]
            sub_sigma = round(float(np.nan_to_num(np.std(sub_h), nan=0.0)), 3)
            sub_hs = round(float(4.0 * sub_sigma), 3)
            sub_crest = round(float(np.nan_to_num(np.max(sub_h), nan=0.0)), 3)
            sub_trough = round(float(np.nan_to_num(np.min(sub_h), nan=0.0)), 3)
            sub_amp = round(float(sub_crest - sub_trough), 3)
            sub_mean = round(float(np.mean(sub_h)), 3)
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

    # 6. Elevation histogram & distribution (safe against uniform values)
    if len(height_sea_level) >= 2 and (np.max(height_sea_level) > np.min(height_sea_level)):
        counts_raw, bin_edges_raw = np.histogram(height_sea_level, bins=30)
        hist_counts, hist_bins = np.histogram(height_sea_level, bins=30, density=True)
    else:
        val = float(height_sea_level[0]) if len(height_sea_level) > 0 else 0.0
        counts_raw = np.array([len(height_sea_level)] + [0]*29)
        bin_edges_raw = np.linspace(val - 1.0, val + 1.0, 31)
        hist_counts = np.array([1.0] + [0.0]*29)
        hist_bins = bin_edges_raw

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
        "observer_height_m": round(float(np.nan_to_num(observer_height, nan=4.76)), 2),
        "significant_wave_height_Hs_m": hs_rounded,
        "peak_crest_m": crest_rounded,
        "deepest_trough_m": trough_rounded,
        "crest_elevation_max_m": crest_rounded,
        "trough_depth_min_m": trough_rounded,
        "wave_amplitude_m": amp_rounded,
        "wave_amplitude_total_m": amp_rounded,
        "elevation_std_sigma_m": sigma_rounded,
        "mean_elevation_m": round(float(np.nan_to_num(h_mean, nan=0.0)), 4),
        "elevation_skewness": round(float(np.nan_to_num(skewness, nan=0.0)), 3),
        "elevation_kurtosis": round(float(np.nan_to_num(kurtosis, nan=3.0)), 3),
        "wave_parameters": {
            "mean_elevation_m": round(float(np.nan_to_num(h_mean, nan=0.0)), 4),
            "elevation_std_sigma_m": sigma_rounded,
            "significant_wave_height_Hs_m": hs_rounded,
            "peak_crest_m": crest_rounded,
            "deepest_trough_m": trough_rounded,
            "crest_elevation_max_m": crest_rounded,
            "trough_depth_min_m": trough_rounded,
            "wave_amplitude_m": amp_rounded,
            "wave_amplitude_total_m": amp_rounded,
            "skewness": round(float(np.nan_to_num(skewness, nan=0.0)), 3),
            "kurtosis": round(float(np.nan_to_num(kurtosis, nan=3.0)), 3)
        },
        "distance": {
            "min_m": round(float(np.nan_to_num(dist_min, nan=0.0)), 2),
            "max_m": round(float(np.nan_to_num(dist_max, nan=0.0)), 2),
            "mean_m": round(float(np.nan_to_num(dist_mean, nan=0.0)), 2),
            "median_m": round(float(np.nan_to_num(dist_median, nan=0.0)), 2)
        },
        "distance_profile": distance_profile,
        "circular_arcs_5m": circular_arcs,
        "elevation_histogram": hist_data,
        "elevation_distribution": dist_data,
        "plane_coefficients": {
            "a": round(float(np.nan_to_num(n[0], nan=0.0)), 5),
            "b": round(float(np.nan_to_num(n[1], nan=0.0)), 5),
            "c": round(float(np.nan_to_num(n[2], nan=1.0)), 5),
            "d": round(float(np.nan_to_num(d, nan=0.0)), 5)
        }
    }
    return result, pts, dist_observer, height_sea_level


def export_annotated_xyz(pts, dist_observer, height_sea_level, out_csv_path):
    """
    Exports point cloud with distance from observer and height from sea level.
    Columns: X, Y, Z, distance_from_observer_m, height_from_sea_level_m
    """
    out_dir = os.path.dirname(os.path.abspath(out_csv_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    header = "x_camera_m,y_camera_m,z_camera_m,distance_from_observer_m,height_from_sea_level_m\n"
    pts_arr = np.atleast_2d(pts) if (hasattr(pts, 'size') and pts.size > 0) else np.empty((0, 3))
    with open(out_csv_path, "w", encoding="utf-8") as f:
        f.write(header)
        for i in range(len(pts_arr)):
            d_val = dist_observer[i] if i < len(dist_observer) else 0.0
            h_val = height_sea_level[i] if i < len(height_sea_level) else 0.0
            f.write(f"{pts_arr[i,0]:.4f},{pts_arr[i,1]:.4f},{pts_arr[i,2]:.4f},{d_val:.4f},{h_val:.4f}\n")
    print(f"Exported annotated dataset to {out_csv_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="WASS 3D Ocean Wave Point Cloud & 5m Radar Arc Analyzer")
    parser.add_argument("xyz_path", nargs="?", default=None, help="Path to input .xyz point cloud file")
    parser.add_argument("--plane", type=str, default=None, help="Path to mean sea plane.txt (optional)")
    parser.add_argument("--export-csv", type=str, default=None, help="Path to export annotated CSV with distance and MSL height")
    args = parser.parse_args()

    if args.xyz_path is not None:
        if not os.path.exists(args.xyz_path):
            parser.error(f"XYZ file not found: {args.xyz_path}")
        if args.plane and not os.path.exists(args.plane):
            parser.error(f"Plane file not found: {args.plane}")
        res, pts, dist, h_sea = analyze_xyz(args.xyz_path, args.plane)
        print("Analysis completed successfully:")
        print(json.dumps(res, indent=2))
        if args.export_csv:
            export_annotated_xyz(pts, dist, h_sea, args.export_csv)
    else:
        # Default fallback check for benchmark dataset
        default_xyz = os.path.join(os.path.dirname(__file__), "wass_webapp", "workspace", "sequence", "pointcloud_000.xyz")
        if os.path.exists(default_xyz):
            res, pts, dist, h_sea = analyze_xyz(default_xyz)
            print("Analyzed default benchmark frame (pointcloud_000.xyz):")
            print(json.dumps(res, indent=2))
        else:
            parser.print_help()
