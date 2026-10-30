"""
WASS GoPro Optical Specifications & Calibration Generator
=========================================================
Generates metric-accurate WASS intrinsics and distortion XML files directly from
GoPro physical sensor dimensions, pixel pitch, and lens field-of-view modes across
all GoPro generations (HERO 5/6/7, HERO 8, HERO 9/10, HERO 11/12/13, and MAX).
Supports automatic metadata extraction directly from MP4 containers and GPMF tracks.
"""

import os
import re
import cv2
import numpy as np


# ==============================================================================
# 1. PHYSICAL GOPRO SENSOR & OPTICAL REGISTRY (ACROSS ALL GENERATIONS)
# ==============================================================================

GOPRO_MODELS = {
    "hero5_6_7": {
        "name": "GoPro HERO 5 / 6 / 7 Black",
        "sensor_format": '1/2.3" Sony IMX117/IMX377 CMOS',
        "sensor_width_mm": 6.17,
        "sensor_height_mm": 4.55,
        "pixel_pitch_4k_um": 1.55,
        "physical_focal_mm": 3.00,
        "native_aspect": "4:3",
        "fov_modes": {
            "wide": {
                "description": "GoPro Wide (Raw Barrel Fisheye, ~16.5mm equiv)",
                "f_equiv_35mm": 16.5,
                "f_4k_pixels": 1867.0,
                "distortion": [-0.245, 0.075, 0.0, 0.0, 0.0]  # k1, k2, p1, p2, k3
            },
            "linear": {
                "description": "GoPro Linear (Internal Hardware Dewarped, ~19.5mm equiv)",
                "f_equiv_35mm": 19.5,
                "f_4k_pixels": 2400.0,
                "distortion": [0.0, 0.0, 0.0, 0.0, 0.0]
            },
            "superview": {
                "description": "GoPro SuperView (Dynamic 4:3 -> 16:9 Stretch, ~15.0mm equiv)",
                "f_equiv_35mm": 15.0,
                "f_4k_pixels": 1600.0,
                "distortion": [-0.320, 0.120, 0.0, 0.0, 0.0]
            }
        }
    },
    "hero8": {
        "name": "GoPro HERO 8 Black",
        "sensor_format": '1/2.3" Sony CMOS',
        "sensor_width_mm": 6.17,
        "sensor_height_mm": 4.55,
        "pixel_pitch_4k_um": 1.55,
        "physical_focal_mm": 3.00,
        "native_aspect": "4:3",
        "fov_modes": {
            "wide": {
                "description": "GoPro HERO 8 Wide (16mm equiv)",
                "f_equiv_35mm": 16.0,
                "f_4k_pixels": 1867.0,
                "distortion": [-0.245, 0.075, 0.0, 0.0, 0.0]
            },
            "linear": {
                "description": "GoPro HERO 8 Linear (19mm equiv)",
                "f_equiv_35mm": 19.0,
                "f_4k_pixels": 2400.0,
                "distortion": [0.0, 0.0, 0.0, 0.0, 0.0]
            },
            "superview": {
                "description": "GoPro HERO 8 SuperView (15mm equiv)",
                "f_equiv_35mm": 15.0,
                "f_4k_pixels": 1600.0,
                "distortion": [-0.320, 0.120, 0.0, 0.0, 0.0]
            },
            "narrow": {
                "description": "GoPro HERO 8 Narrow (27mm Digital Crop)",
                "f_equiv_35mm": 27.0,
                "f_4k_pixels": 3700.0,
                "distortion": [0.0, 0.0, 0.0, 0.0, 0.0]
            }
        }
    },
    "hero9_10": {
        "name": "GoPro HERO 9 / 10 Black",
        "sensor_format": '1/2.3" Sony IMX677 CMOS (23.6 MP)',
        "sensor_width_mm": 6.40,
        "sensor_height_mm": 4.80,
        "pixel_pitch_4k_um": 1.12,
        "physical_focal_mm": 2.92,
        "native_aspect": "4:3",
        "fov_modes": {
            "wide": {
                "description": "GoPro HERO 9/10 Wide (16mm equiv)",
                "f_equiv_35mm": 16.0,
                "f_4k_pixels": 1890.0,
                "distortion": [-0.250, 0.080, 0.0, 0.0, 0.0]
            },
            "linear": {
                "description": "GoPro HERO 9/10 Linear + Horizon Leveling (19.5mm equiv)",
                "f_equiv_35mm": 19.5,
                "f_4k_pixels": 2430.0,
                "distortion": [0.0, 0.0, 0.0, 0.0, 0.0]
            },
            "superview": {
                "description": "GoPro HERO 9/10 SuperView (16mm Dynamic Stretch)",
                "f_equiv_35mm": 16.0,
                "f_4k_pixels": 1650.0,
                "distortion": [-0.310, 0.110, 0.0, 0.0, 0.0]
            },
            "narrow": {
                "description": "GoPro HERO 9/10 Narrow (34mm Digital Crop)",
                "f_equiv_35mm": 34.0,
                "f_4k_pixels": 3750.0,
                "distortion": [0.0, 0.0, 0.0, 0.0, 0.0]
            }
        }
    },
    "hero11_12_13": {
        "name": "GoPro HERO 11 / 12 / 13 Black",
        "sensor_format": '1/1.9" Tall CMOS (27.6 MP, 8:7 Aspect)',
        "sensor_width_mm": 6.40,
        "sensor_height_mm": 5.60,
        "pixel_pitch_4k_um": 1.12,
        "physical_focal_mm": 2.92,
        "native_aspect": "8:7",
        "fov_modes": {
            "hyperview": {
                "description": "GoPro HyperView (12mm Ultra-Wide POV from 8:7 sensor)",
                "f_equiv_35mm": 12.0,
                "f_4k_pixels": 1380.0,
                "distortion": [-0.360, 0.150, 0.0, 0.0, 0.0]
            },
            "superview": {
                "description": "GoPro SuperView (16mm Dynamic Stretch)",
                "f_equiv_35mm": 16.0,
                "f_4k_pixels": 1750.0,
                "distortion": [-0.290, 0.095, 0.0, 0.0, 0.0]
            },
            "wide": {
                "description": "GoPro Wide (16mm Traditional Barrel)",
                "f_equiv_35mm": 16.0,
                "f_4k_pixels": 1875.0,
                "distortion": [-0.240, 0.070, 0.0, 0.0, 0.0]
            },
            "linear": {
                "description": "GoPro Linear + 360 Horizon Lock (19mm)",
                "f_equiv_35mm": 19.0,
                "f_4k_pixels": 2420.0,
                "distortion": [0.0, 0.0, 0.0, 0.0, 0.0]
            }
        }
    },
    "max": {
        "name": "GoPro MAX 360",
        "sensor_format": '1/2.3" Dual Spherical Sensors',
        "sensor_width_mm": 6.17,
        "sensor_height_mm": 4.55,
        "pixel_pitch_4k_um": 1.55,
        "physical_focal_mm": 1.80,
        "native_aspect": "4:3",
        "fov_modes": {
            "max_superview": {
                "description": "Max SuperView (13mm, 149° Ultra-Wide)",
                "f_equiv_35mm": 13.0,
                "f_4k_pixels": 1420.0,
                "distortion": [-0.380, 0.160, 0.0, 0.0, 0.0]
            },
            "wide": {
                "description": "Max Wide (16mm, 115° FOV)",
                "f_equiv_35mm": 16.0,
                "f_4k_pixels": 1867.0,
                "distortion": [-0.245, 0.075, 0.0, 0.0, 0.0]
            },
            "linear": {
                "description": "Max Linear (19mm Horizon Leveling)",
                "f_equiv_35mm": 19.0,
                "f_4k_pixels": 2400.0,
                "distortion": [0.0, 0.0, 0.0, 0.0, 0.0]
            },
            "narrow": {
                "description": "Max Narrow (27mm, 80° FOV)",
                "f_equiv_35mm": 27.0,
                "f_4k_pixels": 3300.0,
                "distortion": [0.0, 0.0, 0.0, 0.0, 0.0]
            }
        }
    }
}

# Backward compatibility alias
GOPRO_FOV_PRESETS = GOPRO_MODELS["hero9_10"]["fov_modes"]
GOPRO_SENSOR_WIDTH_MM = GOPRO_MODELS["hero9_10"]["sensor_width_mm"]
GOPRO_SENSOR_HEIGHT_MM = GOPRO_MODELS["hero9_10"]["sensor_height_mm"]
GOPRO_PIXEL_PITCH_UM = GOPRO_MODELS["hero9_10"]["pixel_pitch_4k_um"]
GOPRO_PHYSICAL_FOCAL_MM = GOPRO_MODELS["hero9_10"]["physical_focal_mm"]


# ==============================================================================
# 2. AUTOMATIC GOPRO CONTAINER & GPMF TELEMETRY DETECTOR
# ==============================================================================

def detect_gopro_metadata(video_path: str) -> dict:
    """
    Auto-detects GoPro camera model, firmware version, and lens FOV mode directly
    from MP4 container metadata (moov/udta atoms) and GPMF telemetry tracks without
    external dependencies.
    """
    res = {
        "detected": False,
        "camera_model": "Unknown / Generic Camera",
        "model_key": "hero9_10",
        "fov_mode": "wide",
        "firmware": None,
        "confidence": "default",
        "file": os.path.basename(video_path) if video_path else ""
    }

    if not video_path or not os.path.exists(video_path):
        return res

    filename = os.path.basename(video_path)
    # 1. Filename heuristic: GoPro HERO 6-13 clips start with GX (HEVC) or GH (AVC)
    is_gopro_filename = bool(re.match(r'^(?:GX|GH|GOPR|GP)\d+', filename, re.IGNORECASE))
    if is_gopro_filename:
        res["detected"] = True
        res["confidence"] = "medium"
        res["camera_model"] = "GoPro HERO Series (Filename Signature)"

    # 2. Scan file header and footer (where moov and GPMF atoms reside)
    try:
        file_size = os.path.getsize(video_path)
        with open(video_path, "rb") as f:
            head = f.read(min(file_size, 512 * 1024))
            tail = b""
            if file_size > 512 * 1024:
                f.seek(max(0, file_size - 1024 * 1024))
                tail = f.read()
            content = head + b" " + tail
    except Exception:
        content = b""

    if not content:
        return res

    # 3. Detect Firmware version (e.g., HD10.01.01.40.00, H24.01.02.10.70, HD8.01.02.50.00)
    m_fw = re.search(rb'H[D]?(\d+)(?:\.\d+)+', content)
    if m_fw:
        res["firmware"] = m_fw.group(0).decode("latin1", errors="ignore")
        res["detected"] = True
        fw_ver = int(m_fw.group(1))
        if fw_ver in [11, 12, 13]:
            res["model_key"] = "hero11_12_13"
            res["camera_model"] = f"GoPro HERO {fw_ver} Black"
            res["confidence"] = "high"
        elif fw_ver in [9, 10]:
            res["model_key"] = "hero9_10"
            res["camera_model"] = f"GoPro HERO {fw_ver} Black"
            res["confidence"] = "high"
        elif fw_ver == 8:
            res["model_key"] = "hero8"
            res["camera_model"] = "GoPro HERO 8 Black"
            res["confidence"] = "high"
        elif fw_ver in [5, 6, 7]:
            res["model_key"] = "hero5_6_7"
            res["camera_model"] = f"GoPro HERO {fw_ver} Black"
            res["confidence"] = "high"

    # 4. Detect Camera Model Name from GPMF MINF / DVNM tags
    m_mod = re.search(rb'(?:HERO\s*(\d+)|(GoPro\s*MAX))', content, re.IGNORECASE)
    if m_mod:
        res["detected"] = True
        res["confidence"] = "high"
        if m_mod.group(2):
            res["model_key"] = "max"
            res["camera_model"] = "GoPro MAX 360"
        elif m_mod.group(1):
            h_num = int(m_mod.group(1))
            res["camera_model"] = f"GoPro HERO {h_num} Black"
            if h_num >= 11:
                res["model_key"] = "hero11_12_13"
            elif h_num >= 9:
                res["model_key"] = "hero9_10"
            elif h_num == 8:
                res["model_key"] = "hero8"
            else:
                res["model_key"] = "hero5_6_7"

    # 5. Detect Lens FOV Mode from LENS tag or content tokens
    content_lower = content.lower()
    for fov_cand in ["hyperview", "superview", "linear", "narrow", "wide"]:
        if fov_cand.encode("latin1") in content_lower:
            res["fov_mode"] = fov_cand
            break

    # 6. Cross-reference with resolution aspect ratio if available
    try:
        cap = cv2.VideoCapture(video_path)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            cap.release()
            res["width"] = w
            res["height"] = h
            res["fps"] = fps
            # 8:7 Aspect ratio indicates native HERO 11/12/13 tall sensor
            if w > 0 and h > 0 and abs((w / float(h)) - (8.0 / 7.0)) < 0.05:
                res["model_key"] = "hero11_12_13"
                res["camera_model"] = "GoPro HERO 11/12/13 Black (8:7 Native)"
                res["confidence"] = "high"
    except Exception:
        pass

    return res


# ==============================================================================
# 3. PROFILE RESOLUTION & INTRINSICS COMPUTATION
# ==============================================================================

def get_gopro_profile(
    model: str = "auto",
    fov_mode: str = "auto",
    video_path: str = None
) -> tuple[dict, str, str]:
    """
    Resolves active GoPro hardware profile, model key, and FOV mode key.
    If 'auto' is specified, auto-detects from video container metadata.
    """
    model_req = (model or "auto").lower().strip()
    fov_req = (fov_mode or "auto").lower().strip()

    detected_info = None
    if (model_req == "auto" or fov_req == "auto") and video_path:
        detected_info = detect_gopro_metadata(video_path)

    # Resolve model key
    if model_req in GOPRO_MODELS:
        model_key = model_req
    elif detected_info and detected_info.get("detected"):
        model_key = detected_info["model_key"]
    else:
        # Check alias keys
        if "8" in model_req:
            model_key = "hero8"
        elif "11" in model_req or "12" in model_req or "13" in model_req:
            model_key = "hero11_12_13"
        elif "7" in model_req or "6" in model_req or "5" in model_req:
            model_key = "hero5_6_7"
        elif "max" in model_req:
            model_key = "max"
        else:
            model_key = "hero9_10"

    model_profile = GOPRO_MODELS[model_key]

    # Resolve FOV mode key
    available_fovs = model_profile["fov_modes"]
    if fov_req in available_fovs:
        fov_key = fov_req
    elif detected_info and detected_info.get("fov_mode") in available_fovs:
        fov_key = detected_info["fov_mode"]
    else:
        fov_key = "wide" if "wide" in available_fovs else list(available_fovs.keys())[0]

    return model_profile, model_key, fov_key


def compute_gopro_intrinsics(
    width: int,
    height: int,
    fov_mode: str = "auto",
    model: str = "auto",
    video_path: str = None
) -> tuple[np.ndarray, np.ndarray]:
    """
    Computes metric 3x3 camera matrix and 5x1 distortion vector from GoPro specifications.
    Automatically scales focal length to any resolution (4K, 2.7K, 1080p, 720p).
    """
    profile, model_key, fov_key = get_gopro_profile(model, fov_mode, video_path)
    fov_spec = profile["fov_modes"][fov_key]
    base_f = fov_spec["f_4k_pixels"]

    # Scale focal length to input resolution relative to 4K UHD width (3840 px)
    scale = float(width) / 3840.0
    fx = base_f * scale
    fy = base_f * scale

    # Principal point (cx, cy) is optical sensor center
    cx = float(width) / 2.0
    cy = float(height) / 2.0

    camera_matrix = np.array([
        [fx, 0.0, cx],
        [0.0, fy, cy],
        [0.0, 0.0, 1.0]
    ], dtype=np.float64)

    dist_coeffs = np.array(fov_spec["distortion"], dtype=np.float64).reshape(5, 1)

    return camera_matrix, dist_coeffs


def write_wass_calibration_xmls(
    config_dir: str,
    width: int,
    height: int,
    fov_mode: str = "auto",
    model: str = "auto",
    baseline_meters: float = 2.000,
    video_path: str = None
) -> dict:
    """
    Generates and saves the full WASS calibration XML suite:
      - intrinsics_00.xml / intrinsics_01.xml
      - distortion_00.xml / distortion_01.xml
      - ext_R.xml (identity orientation)
      - ext_T.xml (stereo baseline translation)
    """
    os.makedirs(config_dir, exist_ok=True)
    K, dist = compute_gopro_intrinsics(width, height, fov_mode=fov_mode, model=model, video_path=video_path)

    ext_R = np.eye(3, dtype=np.float64)
    ext_T = np.array([[-baseline_meters], [0.0], [0.0]], dtype=np.float64)

    files_written = {}
    for cam in ["00", "01"]:
        intr_path = os.path.join(config_dir, f"intrinsics_{cam}.xml")
        dist_path = os.path.join(config_dir, f"distortion_{cam}.xml")

        fs_intr = cv2.FileStorage(intr_path, cv2.FILE_STORAGE_WRITE)
        fs_intr.write("camera_matrix", K)
        fs_intr.release()

        fs_dist = cv2.FileStorage(dist_path, cv2.FILE_STORAGE_WRITE)
        fs_dist.write("distortion_coefficients", dist)
        fs_dist.release()

        files_written[f"intrinsics_{cam}"] = intr_path
        files_written[f"distortion_{cam}"] = dist_path

    r_path = os.path.join(config_dir, "ext_R.xml")
    t_path = os.path.join(config_dir, "ext_T.xml")

    fs_r = cv2.FileStorage(r_path, cv2.FILE_STORAGE_WRITE)
    fs_r.write("ext_R", ext_R)
    fs_r.release()

    fs_t = cv2.FileStorage(t_path, cv2.FILE_STORAGE_WRITE)
    fs_t.write("ext_T", ext_T)
    fs_t.release()

    files_written["ext_R"] = r_path
    files_written["ext_T"] = t_path

    return files_written


# ==============================================================================
# 4. CLI INTERFACE
# ==============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="WASS GoPro Multi-Generation Specifications & Calibration Generator")
    parser.add_argument("--video", type=str, default=None, help="Path to video file for automatic metadata extraction")
    parser.add_argument("--model", type=str, default="auto", choices=["auto", "hero11_12_13", "hero9_10", "hero8", "hero5_6_7", "max"])
    parser.add_argument("--fov", type=str, default="auto", choices=["auto", "wide", "linear", "superview", "hyperview", "narrow", "max_superview"])
    parser.add_argument("--width", type=int, default=3840, help="Video width in pixels")
    parser.add_argument("--height", type=int, default=2160, help="Video height in pixels")
    parser.add_argument("--baseline", type=float, default=2.000, help="Stereo baseline in meters")
    parser.add_argument("--out-dir", type=str, default="./calib_out", help="Output directory for XML files")
    args = parser.parse_args()

    if args.video and os.path.exists(args.video):
        meta = detect_gopro_metadata(args.video)
        print("Detected Video Metadata:")
        for k, v in meta.items():
            print(f"  {k}: {v}")

    profile, m_key, f_key = get_gopro_profile(args.model, args.fov, args.video)
    print(f"\nActive Configuration:")
    print(f"  Camera Model: {profile['name']} ({m_key})")
    print(f"  Sensor Format: {profile['sensor_format']}")
    print(f"  Lens FOV Mode: {profile['fov_modes'][f_key]['description']} ({f_key})")

    files = write_wass_calibration_xmls(
        config_dir=args.out_dir,
        width=args.width,
        height=args.height,
        fov_mode=f_key,
        model=m_key,
        baseline_meters=args.baseline,
        video_path=args.video
    )
    print(f"\nGenerated WASS Calibration XMLs saved to {args.out_dir}:")
    for k, v in files.items():
        print(f"  {k}: {v}")
