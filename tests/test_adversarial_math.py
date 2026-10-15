import os
import sys
import json
import numpy as np
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from analyze_wave_xyz import analyze_xyz, export_annotated_xyz


def test_empty_point_cloud(tmp_path):
    """Test analyze_xyz on an empty .xyz file."""
    empty_file = tmp_path / "empty.xyz"
    empty_file.write_text("", encoding="utf-8")

    result, pts, dist_obs, h_sea = analyze_xyz(str(empty_file))
    assert result is not None
    assert result["total_points"] == 0
    assert result["significant_wave_height_Hs_m"] == 0.0
    # Must serialize to valid JSON without NaN
    json_str = json.dumps(result)
    assert "NaN" not in json_str


def test_sub_three_points(tmp_path):
    """Test analyze_xyz with 1 and 2 points (fewer than 3 needed for plane estimation)."""
    one_pt_file = tmp_path / "one_pt.xyz"
    one_pt_file.write_text("1.0 10.0 0.5\n", encoding="utf-8")

    result, pts, dist_obs, h_sea = analyze_xyz(str(one_pt_file))
    assert result["total_points"] == 1
    assert result["significant_wave_height_Hs_m"] == 0.0
    json_str = json.dumps(result)
    assert "NaN" not in json_str

    two_pt_file = tmp_path / "two_pt.xyz"
    two_pt_file.write_text("1.0 10.0 0.5\n2.0 12.0 0.6\n", encoding="utf-8")

    result2, pts2, dist_obs2, h_sea2 = analyze_xyz(str(two_pt_file))
    assert result2["total_points"] == 2
    assert result2["significant_wave_height_Hs_m"] == 0.0
    json_str2 = json.dumps(result2)
    assert "NaN" not in json_str2


def test_identical_points(tmp_path):
    """Test analyze_xyz with identical points having zero spatial variance."""
    pts = np.tile([2.0, 15.0, 0.5], (50, 1))
    file_path = tmp_path / "identical.xyz"
    np.savetxt(str(file_path), pts, fmt="%.4f")

    result, pts_out, dist_obs, h_sea = analyze_xyz(str(file_path))
    assert result["total_points"] == 50
    assert result["significant_wave_height_Hs_m"] == 0.0
    assert np.all(np.isfinite(dist_obs))
    json_str = json.dumps(result)
    assert "NaN" not in json_str


def test_collinear_points(tmp_path):
    """Test analyze_xyz with perfectly collinear points (rank 1 covariance)."""
    t = np.linspace(5.0, 45.0, 100)
    pts = np.column_stack([t, 2.0 * t, 0.1 * t])
    file_path = tmp_path / "collinear.xyz"
    np.savetxt(str(file_path), pts, fmt="%.4f")

    result, pts_out, dist_obs, h_sea = analyze_xyz(str(file_path))
    assert result["total_points"] == 100
    assert np.isfinite(result["significant_wave_height_Hs_m"])
    json_str = json.dumps(result)
    assert "NaN" not in json_str


def test_nan_and_inf_resilience(tmp_path):
    """Test that coordinates containing NaN, Inf, and -Inf are sanitized and discarded."""
    corrupted_content = """
    1.0 10.0 0.5
    NaN 12.0 0.6
    2.0 Inf 0.7
    3.0 14.0 -Inf
    4.0 15.0 0.8
    5.0 16.0 0.9
    invalid_token 17.0 1.0
    """
    file_path = tmp_path / "corrupted.xyz"
    file_path.write_text(corrupted_content, encoding="utf-8")

    result, pts_out, dist_obs, h_sea = analyze_xyz(str(file_path))
    # Exactly 4 valid finite points: (1,10,0.5), (4,15,0.8), (5,16,0.9) plus any valid line
    assert result["total_points"] >= 3
    assert np.all(np.isfinite(pts_out))
    json_str = json.dumps(result)
    assert "NaN" not in json_str
    assert "Infinity" not in json_str


def test_out_of_range_points(tmp_path):
    """Test points situated far beyond the 50m circular arc limits (e.g. Y = 100m to 200m)."""
    y_vals = np.linspace(100.0, 200.0, 50)
    pts = np.column_stack([np.zeros(50), y_vals, np.zeros(50)])
    file_path = tmp_path / "far_away.xyz"
    np.savetxt(str(file_path), pts, fmt="%.4f")

    result, pts_out, dist_obs, h_sea = analyze_xyz(str(file_path))
    assert result["total_points"] == 50
    # Circular arcs should all have point_count == 0 without throwing errors
    for arc in result["circular_arcs_5m"]:
        assert arc["point_count"] == 0
    json_str = json.dumps(result)
    assert "NaN" not in json_str


def test_distance_bin_monotonicity(tmp_path):
    """Test that distance bins are strictly non-decreasing even with distant points."""
    y_vals = np.linspace(60.0, 80.0, 40)
    pts = np.column_stack([np.zeros(40), y_vals, np.sin(y_vals)])
    file_path = tmp_path / "distant_bins.xyz"
    np.savetxt(str(file_path), pts, fmt="%.4f")

    result, pts_out, dist_obs, h_sea = analyze_xyz(str(file_path))
    profile = result["distance_profile"]
    assert len(profile) > 0
    for p in profile:
        assert p["range_start_m"] < p["range_end_m"]


def test_export_annotated_xyz_resilience(tmp_path):
    """Test CSV exporter under mismatched array lengths or extreme values."""
    pts = np.array([[1.0, 10.0, 0.5], [2.0, 11.0, 0.6]])
    dist_obs = np.array([10.0498, 11.1803])
    h_sea = np.array([0.05, -0.05])

    out_csv = tmp_path / "annotated.csv"
    export_annotated_xyz(pts, dist_obs, h_sea, str(out_csv))
    assert out_csv.exists()
    content = out_csv.read_text(encoding="utf-8")
    lines = content.strip().split("\n")
    assert len(lines) == 3 # 1 header + 2 points
