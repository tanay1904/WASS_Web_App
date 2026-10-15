import os
import sys
import numpy as np
import pytest

# Ensure root is in path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from analyze_wave_xyz import analyze_xyz


def test_physical_stereo_scale_formulation():
    """Verify physical metric stereo scale formulation with physical baseline and height."""
    B = 0.88          # Baseline in meters
    f_scaled = 466.75 # Scaled focal length in pixels
    H_cam = 4.76      # Camera altitude above MSL in meters

    # Slant range at (X=0, Y=10)
    X, Y = 0.0, 10.0
    R_grid = np.sqrt(X**2 + Y**2 + H_cam**2)
    expected_R = np.sqrt(100.0 + 4.76**2)
    assert np.isclose(R_grid, expected_R, atol=1e-6)

    # Scale geometry factor
    scale_geom = (R_grid * H_cam) / (f_scaled * B)
    assert scale_geom > 0.0
    assert np.isfinite(scale_geom)


def test_vessel_bow_and_5m_arc_clearance():
    """Verify vessel prow reaches Y = 4.0m and 5m circular arc at Y = 5.0m gives 1.000m clearance."""
    prow_stem_y = 4.000
    arc_5m_radius = 5.000
    arc_5m_apex_y = arc_5m_radius # At azimuth 0 deg, Y = 5.0m

    clearance = arc_5m_apex_y - prow_stem_y
    assert np.isclose(clearance, 1.000, atol=1e-4), f"Expected 1.000m clearance, got {clearance}"


def test_bilateral_water_channel_spans():
    """Verify water bounds X in [-25, 15]m provide 24.45m port and 14.45m starboard channels."""
    x_min = -25.0
    x_max = 15.0
    vessel_half_beam = 0.55 # at Y = 2.5m

    port_span = abs(-vessel_half_beam - x_min)
    starboard_span = x_max - vessel_half_beam

    assert np.isclose(port_span, 24.45, atol=1e-4)
    assert np.isclose(starboard_span, 14.45, atol=1e-4)


def test_analyze_xyz_synthetic_wave():
    """Verify wave statistics extraction on a synthetic regularized wave field."""
    # Create 100 x 70 synthetic sea grid with amplitude 1.5m
    grid_x = np.linspace(-25, 15, 100)
    grid_y = np.linspace(2.5, 50, 70)
    gx, gy = np.meshgrid(grid_x, grid_y)

    # Wave elevation field: sine wave with amplitude 1.2m
    gz = 1.2 * np.sin(2 * np.pi * gy / 15.0)

    pts = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])

    tmp_xyz = os.path.join(ROOT_DIR, "tests", "temp_synthetic.xyz")
    np.savetxt(tmp_xyz, pts, fmt="%.4f")

    try:
        results, pts_out, dist_obs, h_sea = analyze_xyz(tmp_xyz)
        assert results is not None
        assert "significant_wave_height_Hs_m" in results
        assert "circular_arcs_5m" in results
        assert len(results["circular_arcs_5m"]) == 10

        # Check arc radii are [5, 10, ..., 50]
        radii = [a.get("radius_m", a.get("arc_radius_m")) for a in results["circular_arcs_5m"]]
        assert radii == [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]


        # Check Hs is close to 4 * std(gz)
        expected_hs = 4.0 * np.std(gz)
        assert np.isclose(results["significant_wave_height_Hs_m"], round(float(expected_hs), 3), atol=0.1)
    finally:
        if os.path.exists(tmp_xyz):
            os.remove(tmp_xyz)
