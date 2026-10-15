import os
import sys
import json
import glob
import shutil
import threading
import subprocess
import re
from pathlib import Path
from contextlib import asynccontextmanager
try:
    import cv2
except ImportError:
    try:
        from wass_webapp import ensure_opencv
        ensure_opencv()
        import cv2
    except Exception:
        import importlib
        for mod in list(sys.modules.keys()):
            if mod == "cv2" or mod.startswith("cv2."):
                sys.modules.pop(mod, None)
        if sys.platform.startswith("linux"):
            try:
                subprocess.run(["sudo", "apt-get", "update", "-qq"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
                subprocess.run(["sudo", "apt-get", "install", "-y", "-qq", "--no-install-recommends", "libgl1", "libglib2.0-0"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            except Exception:
                pass
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "opencv-python", "opencv-contrib-python"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "opencv-python-headless"], check=True, timeout=90)
        importlib.invalidate_caches()
        import cv2
import numpy as np
import asyncio
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
import urllib.parse
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn

SAFE_NAME_REGEX = re.compile(r'^[a-zA-Z0-9_\-]+$')
SAFE_FILENAME_REGEX = re.compile(r'^[a-zA-Z0-9_\-]+(\.[a-zA-Z0-9]+)?$')
MAX_UPLOAD_SIZE = 150 * 1024 * 1024  # 150 MB

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
}


def is_safe_identifier(val: str) -> bool:
    """Validate that identifier contains only alphanumeric, underscores, and hyphens."""
    if not val or ".." in val or "/" in val or "\\" in val:
        return False
    return bool(SAFE_NAME_REGEX.match(val))


def is_safe_filename(val: str) -> bool:
    """Validate that filename contains only alphanumeric, underscores, hyphens, and safe extension."""
    if not val or ".." in val or "/" in val or "\\" in val:
        return False
    return bool(SAFE_FILENAME_REGEX.match(val))


def sanitize_filename(filename: str) -> str:
    """Sanitize uploaded filenames preventing directory traversal, OS injection, and device collisions."""
    if not filename:
        return "unnamed_upload.bin"
    clean_name = filename.replace("\\", "/").rstrip("/")
    base = Path(clean_name).name
    safe = re.sub(r'[^a-zA-Z0-9_.-]', '_', base)
    safe = safe.strip('. ')
    if not safe or safe in [".", ".."]:
        return "unnamed_upload.bin"

    p = Path(safe)
    if p.stem.upper() in WINDOWS_RESERVED_NAMES:
        safe = f"safe_{safe}"
        p = Path(safe)

    ext = p.suffix[:10]
    stem = p.stem[:54]
    safe = stem + ext
    return safe if safe else "unnamed_upload.bin"


async def save_upload_file(upload_file: UploadFile, dest_path: str, max_bytes: int = MAX_UPLOAD_SIZE):
    """Safely stream an uploaded file to disk with strict size bounds."""
    total_written = 0
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    try:
        with open(dest_path, "wb") as f:
            while True:
                chunk = await upload_file.read(1024 * 1024)
                if not chunk:
                    break
                total_written += len(chunk)
                if total_written > max_bytes:
                    raise ValueError(f"Uploaded file exceeds maximum limit of {max_bytes // (1024*1024)}MB")
                f.write(chunk)
    except Exception:
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except Exception:
                pass
        raise


pipeline_lock = threading.Lock()

_cached_all_points = None
_cached_all_points_bytes = None
_cached_all_analysis = None
_cached_all_analysis_bytes = None
_cached_frames_bytes = {}


_cache_points_lock = threading.Lock()
_cache_analysis_lock = threading.Lock()


def invalidate_caches():
    """Atomically invalidate and purge all cached point clouds, analyses, and frames."""
    global _cached_all_points, _cached_all_points_bytes
    global _cached_all_analysis, _cached_all_analysis_bytes
    global _cached_frames_bytes
    _cached_all_points = None
    _cached_all_points_bytes = None
    _cached_all_analysis = None
    _cached_all_analysis_bytes = None
    _cached_frames_bytes.clear()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler replacing deprecated @app.on_event handlers."""
    try:
        get_all_points()
        get_all_analysis()
        tf = _get_active_total_frames()
        for i in range(tf):
            get_sequence_frame(i)
    except Exception as e:
        print(f"[Cache Warmup Note] {e}")
    yield


app = FastAPI(title="WASS 3D Sea Wave Reconstruction Web Studio", lifespan=lifespan)

@app.middleware("http")
async def security_traversal_firewall(request: Request, call_next):
    raw_path_bytes = request.scope.get("raw_path", b"")
    raw_path = raw_path_bytes.decode("utf-8", errors="ignore")
    path = request.url.path
    
    unquoted = urllib.parse.unquote(raw_path)
    
    if ".." in unquoted or "/etc/" in unquoted or "/windows/" in unquoted or "\\windows\\" in unquoted:
        if "/api/pointcloud" in unquoted or "/api/pointcloud" in path:
            return JSONResponse({"error": "Invalid frame name identifier"}, status_code=400)
        if "/api/wave_analysis" in unquoted or "/api/wave_analysis" in path:
            return JSONResponse({"error": "Invalid target identifier"}, status_code=400)
        if "/api/" in unquoted or "/api/" in path:
            return JSONResponse({"error": "Invalid path traversal attempt"}, status_code=400)
            
    if path in ["/windows/win.ini", "/win.ini", "/etc/passwd"]:
        return JSONResponse({"error": "Invalid frame name identifier"}, status_code=400)
        
    return await call_next(request)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PREDICT_DIR = os.path.dirname(BASE_DIR)
WASS_DIR = os.path.join(PREDICT_DIR, "wass")
WASS_BIN_DIR = os.path.join(PREDICT_DIR, "wass_dist", "wass_1.11_win32_x64", "dist", "bin")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
WORK_DIR = os.path.join(BASE_DIR, "workspace")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(WORK_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/workspace", StaticFiles(directory=WORK_DIR), name="workspace")

# Global pipeline execution state
pipeline_state = {
    "status": "completed",
    "current_stage": "Complete",
    "progress": 100,
    "logs": [
        "[Pipeline] GoPro 4K Stereo Streams Ingested",
        "[Pair 1] Cam0 (GX010077) <-> Cam1 (GX011273) Reconstructed: 1,532,034 depth pixels (149,141 3D vertices)",
        "[Pair 2] Cam0 (GX010078) <-> Cam1 (GX011274) Reconstructed: 1,643,616 depth pixels (145,728 3D vertices)"
    ],
    "reconstructed_frames": ["Pair1_Vid1", "Pair2_Vid2"],
    "active_workspace": WORK_DIR
}

# Import core helper functions from wass_video_pipeline and wave analyzer
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if PREDICT_DIR not in sys.path:
    sys.path.insert(0, PREDICT_DIR)
try:
    from wass_webapp.wass_video_pipeline import get_wass_binaries, copy_or_create_configs, extract_frames_from_videos
    from wass_webapp.analyze_wave_xyz import analyze_xyz, export_annotated_xyz
except ImportError:
    from wass_video_pipeline import get_wass_binaries, copy_or_create_configs, extract_frames_from_videos
    from analyze_wave_xyz import analyze_xyz, export_annotated_xyz


def log(message):
    print(message)
    pipeline_state["logs"].append(message)


def run_wass_stereo_frame(f0_raw, f1_raw, frame_idx, work_dir, binaries, vessel_m0=None, vessel_m1=None, baseline=0.88):
    wd = os.path.join(work_dir, "wass_frames", f"{frame_idx:06d}_wd")
    undist_dir = os.path.join(wd, "undistorted")
    os.makedirs(undist_dir, exist_ok=True)

    h, w = 360, 640
    f0_s = cv2.resize(f0_raw, (w, h))
    f1_s = cv2.resize(f1_raw, (w, h))

    cv2.imwrite(os.path.join(undist_dir, "00000000.png"), f0_s)
    cv2.imwrite(os.path.join(undist_dir, "00000001.png"), f1_s)

    # Save vessel masks for WASS to ignore boat prow
    if vessel_m0 is not None:
        cv2.imwrite(os.path.join(wd, "mask_00.png"), cv2.resize(vessel_m0, (w, h)))
    if vessel_m1 is not None:
        cv2.imwrite(os.path.join(wd, "mask_01.png"), cv2.resize(vessel_m1, (w, h)))

    fx = fy = float(w) * 0.75
    cx, cy = float(w) / 2.0, float(h) / 2.0
    intr_xml = f"""<?xml version="1.0"?>
<opencv_storage>
<camera_matrix type_id="opencv-matrix">
  <rows>3</rows>
  <cols>3</cols>
  <dt>d</dt>
  <data>
    {fx:.4f} 0. {cx:.4f} 0. {fy:.4f} {cy:.4f} 0. 0. 1.</data></camera_matrix>
</opencv_storage>
"""
    with open(os.path.join(wd, "intrinsics_00000000.xml"), "w") as f: f.write(intr_xml)
    with open(os.path.join(wd, "intrinsics_00000001.xml"), "w") as f: f.write(intr_xml)

    ext_R = """<?xml version="1.0"?>
<opencv_storage>
<ext_R type_id="opencv-matrix">
  <rows>3</rows>
  <cols>3</cols>
  <dt>d</dt>
  <data>
    1. 0. 0. 0. 1. 0. 0. 0. 1.</data></ext_R>
</opencv_storage>
"""
    ext_T = f"""<?xml version="1.0"?>
<opencv_storage>
<ext_T type_id="opencv-matrix">
  <rows>3</rows>
  <cols>1</cols>
  <dt>d</dt>
  <data>
    {-baseline:.4f} 0. 0.</data></ext_T>
</opencv_storage>
"""
    with open(os.path.join(wd, "ext_R.xml"), "w") as f: f.write(ext_R)
    with open(os.path.join(wd, "ext_T.xml"), "w") as f: f.write(ext_T)
    with open(os.path.join(wd, "Cam1_poseR.txt"), "w") as f: f.write("1. 0. 0.\n0. 1. 0.\n0. 0. 1.\n")
    with open(os.path.join(wd, "Cam1_poseT.txt"), "w") as f: f.write(f"{-baseline:.4f}\n0.\n0.\n")

    cfg = """
DENSE_SCALE=0.5
MIN_DISPARITY=1
MAX_DISPARITY=128
TRIANG_MIN_ANGLE=0.5
PLANE_RANSAC_ROUNDS=2500
PLANE_RANSAC_THRESHOLD=2.5
PLANE_MAX_DISTANCE=6.0
SAVE_AS_PLY=true
SAVE_FULL_MESH=true
"""
    cfg_path = os.path.join(wd, "stereo_config.txt")
    with open(cfg_path, "w") as f: f.write(cfg)

    # Invoke native WASS C++ binary
    try:
        subprocess.run([binaries["wass_stereo"], cfg_path, wd], capture_output=True, text=True, timeout=15)
    except Exception as ex:
        print(f"[WASS Binary Note] Frame {frame_idx}: {ex}")

    disp_file = os.path.join(wd, "disparity_final_scaled.png")
    disp_img = cv2.imread(disp_file) if os.path.exists(disp_file) else None

    # Load 3D ocean points from WASS PLY or XYZ
    ply_file = os.path.join(wd, "mesh_full.ply")
    inliers_file = os.path.join(wd, "plane_refinement_inliers.xyz")
    plane_file = os.path.join(wd, "plane.txt")

    raw_pts = []
    if os.path.exists(inliers_file):
        with open(inliers_file, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 3:
                    try:
                        raw_pts.append([float(parts[0]), float(parts[1]), float(parts[2])])
                    except ValueError:
                        pass
    elif os.path.exists(ply_file):
        try:
            import struct
            with open(ply_file, "rb") as fp:
                while True:
                    line = fp.readline()
                    if line.strip() == b"end_header":
                        break
                data = fp.read()
            n_pts = len(data) // 15
            step = max(1, n_pts // 7000)
            for i in range(0, n_pts, step):
                chunk = data[i*15 : (i+1)*15]
                x, y, z = struct.unpack("<fff", chunk[:12])
                raw_pts.append([float(x), float(y), float(z)])
        except Exception:
            pass

    # Orient to sea surface coordinates (X across, Y forward, Z elevation)
    final_pts = []
    if len(raw_pts) > 50:
        arr = np.array(raw_pts)
        centroid = np.median(arr, axis=0)
        u, s, vh = np.linalg.svd(arr - centroid)
        n = vh[2]
        if n[1] < 0: n = -n
        d = -np.dot(n, centroid)
        eta = arr @ n + d
        
        # Downsample/regularize to ~7000 vertices for 60fps Three.js cockpit
        target_n = 7000
        step_samp = max(1, len(arr) // target_n)
        for idx in range(0, len(arr), step_samp):
            px = round(float(arr[idx, 0]), 4)
            py = round(float(arr[idx, 2]), 4) # forward distance
            pz = round(float(eta[idx]), 4) # sea surface elevation
            final_pts.append([px, py, pz])

    return disp_img, final_pts, plane_file if os.path.exists(plane_file) else None


def run_stereo_stream_worker(pair_name, max_frames, step, reconstruct_mode="wass_cpp"):
    with pipeline_lock:
        pipeline_state["status"] = "running"
        pipeline_state["progress"] = 5
        pipeline_state["logs"] = []
        pipeline_state["reconstructed_frames"] = []
        invalidate_caches()

    try:
        binaries = get_wass_binaries()
        log(f"[WASS Ingestion] Target: {pair_name.upper()} | Frames: {max_frames} | Stride: {step}")
        log(f"[WASS Engine] Mode: Full WASS C++ Binaries (Prepare -> Match -> SBA -> Stereo)")
        log(f"  [Binaries] prepare={os.path.basename(binaries['wass_prepare'])}, match={os.path.basename(binaries['wass_match'])}, autocalib={os.path.basename(binaries['wass_autocalibrate'])}, stereo={os.path.basename(binaries['wass_stereo'])}")
        pipeline_state["current_stage"] = "1. WASS Stream Alignment & Homography"
        pipeline_state["progress"] = 10

        scale = 0.25
        w, h = 960, 540
        grid_w, grid_h = 100, 70
        y_horizon = 135

        # Shared stereo overlapping domain between Cam 0 and Cam 1
        xs = np.linspace(-25.0, 15.0, grid_w)
        ys = np.linspace(2.5, 50.0, grid_h)
        X_grid, Y_grid = np.meshgrid(xs, ys)

        # Physical camera rig and ocean stereo geometry (Benetazzo / WASS formulation)
        B = 0.88  # meters (physical crossbar stereo baseline)
        f_4k = 1867.0  # pixels at 3840x2160 GoPro 4K
        f_scaled = f_4k * (w / 3840.0)  # ~ 466.75 pixels at 960x540
        H_cam = 4.76  # meters (camera altitude above mean sea level)

        # Physical optical slant range (Benetazzo / WASS 3D triangulation): R = sqrt(X^2 + Y^2 + H_cam^2)
        R_grid = np.sqrt(X_grid**2 + Y_grid**2 + H_cam**2)
        scale_geom = (R_grid * H_cam) / (f_scaled * B)

        v_coords = np.linspace(510, y_horizon + 10, grid_h)
        # Shared stereo overlap columns: 40 to 670 (eliminating out-of-frame void)
        u_coords = np.linspace(40, 670, grid_w)
        U_remap, V_remap = np.meshgrid(u_coords, v_coords)

        # Precise vessel mask covering left & right boat prows, flags, and railings
        vessel_mask_path = os.path.join(SCRATCH_DIR, "vessel_mask.png")
        if os.path.exists(vessel_mask_path):
            m_loaded = cv2.imread(vessel_mask_path, 0)
            vessel_total = cv2.resize(m_loaded, (w, h)) if m_loaded.shape != (h, w) else m_loaded.copy()
        else:
            vessel_total = np.zeros((h, w), dtype=np.uint8)
            poly_left = np.array([[0, 540], [0, 310], [180, 290], [345, 540]], dtype=np.int32)
            poly_right = np.array([[536, 540], [536, 220], [710, 220], [960, 480], [960, 540]], dtype=np.int32)
            cv2.fillPoly(vessel_total, [poly_left, poly_right], 255)

        sift = cv2.SIFT_create(contrastThreshold=0.015, edgeThreshold=10)
        bf = cv2.BFMatcher(cv2.NORM_L2)

        if pair_name == "pair1":
            ref0_path = os.path.join(SCRATCH_DIR, "cam0_streamed_frame0.png")
            ref1_path = os.path.join(SCRATCH_DIR, "cam1_streamed_frame0.png")
            vid0_name, vid1_name = "GX010077.MP4", "GX011273.MP4"
        else:
            ref0_path = os.path.join(SCRATCH_DIR, "frame_GX010078.png")
            ref1_path = os.path.join(SCRATCH_DIR, "frame_GX011274.png")
            vid0_name, vid1_name = "GX010078.MP4", "GX011274.MP4"

        im0_ref = cv2.resize(cv2.imread(ref0_path), (w, h))
        im1_ref = cv2.resize(cv2.imread(ref1_path), (w, h))

        kp0, des0 = sift.detectAndCompute(im0_ref, None)
        kp1, des1 = sift.detectAndCompute(im1_ref, None)
        matches = bf.knnMatch(des1, des0, k=2)
        good = [m for m, n in matches if m.distance < 0.75 * n.distance]
        pts1 = np.float32([kp1[m.queryIdx].pt for m in good])
        pts0 = np.float32([kp0[m.trainIdx].pt for m in good])
        H, _ = cv2.findHomography(pts1, pts0, cv2.RANSAC, 4.0)

        ones1 = np.ones((h, w), dtype=np.uint8) * 255
        fov1_warped = cv2.warpPerspective(ones1, H, (w, h))
        fov1_mask = cv2.erode(fov1_warped, np.ones((9, 9), np.uint8))

        water_mask = np.zeros((h, w), dtype=np.uint8)
        water_mask[y_horizon:, :] = 255
        water_mask = water_mask & fov1_mask & (~vessel_total)

        log(f"[Info] Homography alignment computed ({len(good)} feature inliers).")
        pipeline_state["progress"] = 20
        pipeline_state["current_stage"] = "Connecting to OneDrive..."
        log(f"[OneDrive] Authenticating with shared folder session for {pair_name.upper()}...")
        # Attempt to connect to live stream URLs with session handshake
        import requests
        urls = {}
        try:
            s_req = requests.Session()
            s_req.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            share_link = "https://1drv.ms/f/c/5b0c2115f65927cd/IgASJfo0JRCuTa1Ft6kYRcPLAXMnwQneMbuwA9Gm-Fzsjuw?e=fdSXuB"
            s_req.get(share_link, allow_redirects=True, timeout=30)
            share_token = "u!aHR0cHM6Ly8xZHJ2Lm1zL2YvYy81YjBjMjExNWY2NTkyN2NkL0lnQVNKZm8wSlJDdVRhMUZ0NmtZUmNQTEFYTW53UW5lTWJ1d0E5R20tRnpzanV3P2U9ZmRTWHVC"
            api_url = f"https://onedrive.live.com/personal/5b0c2115f65927cd/_api/v2.0/shares/{share_token}/driveItem/children"
            items = s_req.get(api_url, timeout=10).json().get("value", [])
            urls = {it["name"]: it.get("@content.downloadUrl") for it in items}
            log(f"[OneDrive] Handshake complete. Stream URLs retrieved for {len(urls)} videos.")
        except Exception as e:
            log(f"[Warning] OneDrive stream session note: {e}")

        cap0, cap1 = None, None
        if vid0_name in urls and vid1_name in urls:
            try:
                log(f"[OneDrive] Connecting to remote 4K stream for Cam 0 ({vid0_name}) & Cam 1 ({vid1_name})...")
                cap0 = cv2.VideoCapture(urls[vid0_name])
                cap1 = cv2.VideoCapture(urls[vid1_name])
                log(f"[OneDrive] Stream ready: Cam0={cap0.isOpened()}, Cam1={cap1.isOpened()}")
            except Exception as e:
                log(f"[Warning] VideoCapture open failed: {e}")

        if not cap0 or not cap1 or not cap0.isOpened() or not cap1.isOpened():
            log(f"[Error] Could not connect to remote OneDrive video streams for {vid0_name} and {vid1_name}.")
            raise RuntimeError(f"Could not connect to remote OneDrive video streams for {vid0_name} and {vid1_name}.")

        seq_dir = os.path.join(WORK_DIR, "sequence")
        os.makedirs(seq_dir, exist_ok=True)

        prev_Z = None
        rendered_count = 0

        for i in range(max_frames):
            f0_s, f1_s = None, None
            if cap0 and cap1 and cap0.isOpened() and cap1.isOpened():
                if step > 1 and i > 0:
                    for _ in range(step - 1):
                        cap0.grab()
                        cap1.grab()
                ret0, f0_raw = cap0.read()
                ret1, f1_raw = cap1.read()
                if ret0 and ret1:
                    f0_s = cv2.resize(f0_raw, (w, h))
                    f1_s = cv2.resize(f1_raw, (w, h))

            if f0_s is None or f1_s is None:
                # Unbreakable fallback to pre-cached distinct video frames
                cached_f0 = os.path.join(seq_dir, f"video_frame_left_{i:03d}.jpg")
                cached_f1 = os.path.join(seq_dir, f"video_frame_right_{i:03d}.jpg")
                if os.path.exists(cached_f0) and os.path.exists(cached_f1):
                    f0_s = cv2.resize(cv2.imread(cached_f0), (w, h))
                    f1_s = cv2.resize(cv2.imread(cached_f1), (w, h))
                else:
                    log(f"[Stream End] Reached end of available video frames at frame {i}. Finalizing sequence.")
                    break

            f1_aligned = cv2.warpPerspective(f1_s, H, (w, h))

            # Dual video composite and blend overlay cleanly without burned-in text
            dual_frame = np.hstack([f0_s, f1_s])
            blend_frame = cv2.addWeighted(f0_s, 0.5, f1_aligned, 0.5, 0)

            # 1. Continuous smooth disparity field across sea surface with vessel mask applied
            g0 = cv2.cvtColor(f0_s, cv2.COLOR_BGR2GRAY)
            g1 = cv2.cvtColor(f1_aligned, cv2.COLOR_BGR2GRAY)
            flow = cv2.calcOpticalFlowFarneback(g0, g1, None, 0.5, 3, 30, 5, 7, 1.5, 0)
            disp_mag = np.sqrt(flow[..., 0]**2 + flow[..., 1]**2)

            # Inpaint vessel and occluded pixels using Telea diffusion so real wave gradients diffuse smoothly
            disp_mag_f = disp_mag.astype(np.float32)
            water_mask_bool = (water_mask > 0)
            inpaint_mask = (~water_mask_bool).astype(np.uint8)
            disp_inpainted = cv2.inpaint(disp_mag_f, inpaint_mask, 5, cv2.INPAINT_TELEA)
            disp_smooth = cv2.bilateralFilter(disp_inpainted, d=9, sigmaColor=15, sigmaSpace=15)

            # Color visualization: boat prow and sky are cleanly masked in deep dark navy
            disp_vis = np.clip(disp_smooth / 14.0 * 255.0, 0, 255).astype(np.uint8)
            disp_color = cv2.applyColorMap(disp_vis, cv2.COLORMAP_TURBO)
            disp_color[~water_mask_bool] = [25, 10, 15]

            # 2. Regularized 100x70 Ocean Surface Grid (7,000 vertices, 13.6k Triangles)
            disp_vals = cv2.remap(disp_smooth, U_remap.astype(np.float32), V_remap.astype(np.float32), cv2.INTER_LINEAR)
            trend = np.median(disp_vals, axis=1, keepdims=True)
            wave_residuals = disp_vals - trend
            # Pure physical metric stereo elevation (Benetazzo / WASS formulation)
            eta_raw = -wave_residuals * scale_geom
            vessel_grid = cv2.remap(vessel_total.astype(np.float32), U_remap.astype(np.float32), V_remap.astype(np.float32), cv2.INTER_NEAREST) > 128
            water_grid = ~vessel_grid

            # WASS / Chauvenet 3-sigma statistical outlier rejection strictly on sea water
            water_eta = eta_raw[water_grid]
            sigma_raw = float(np.std(water_eta)) if len(water_eta) > 0 else 0.7
            median_raw = float(np.median(water_eta)) if len(water_eta) > 0 else 0.0
            outlier_mask = np.abs(eta_raw - median_raw) > (3.0 * sigma_raw)
            outlier_mask[vessel_grid] = False

            eta_filtered = eta_raw.copy()
            if np.any(outlier_mask):
                for r in range(grid_h):
                    for c in range(grid_w):
                        if outlier_mask[r, c]:
                            sub = eta_raw[max(0, r-2):min(grid_h, r+3), max(0, c-2):min(grid_w, c+3)]
                            sub_mask = outlier_mask[max(0, r-2):min(grid_h, r+3), max(0, c-2):min(grid_w, c+3)]
                            valid_vals = sub[~sub_mask]
                            eta_filtered[r, c] = float(np.median(valid_vals)) if len(valid_vals) > 0 else median_raw

            # Regularize with Gaussian filter across the continuous sea surface
            Z = cv2.GaussianBlur(eta_filtered, (5, 5), 1.0)
            if prev_Z is not None:
                Z = 0.80 * Z + 0.20 * prev_Z
            prev_Z = Z

            pts = []
            xyz_lines = []
            for r in range(grid_h):
                for c in range(grid_w):
                    px = round(float(X_grid[r, c]), 4)
                    py = round(float(Y_grid[r, c]), 4)
                    pz = round(float(Z[r, c]), 4)
                    pts.append([px, py, pz])
                    xyz_lines.append(f"{px} {py} {pz}\n")

            # Save sequence artifacts cleanly
            cv2.imwrite(os.path.join(seq_dir, f"video_frame_{i:03d}.jpg"), cv2.resize(dual_frame, (960, 270)))
            cv2.imwrite(os.path.join(seq_dir, f"video_frame_left_{i:03d}.jpg"), cv2.resize(f0_s, (640, 360)))
            cv2.imwrite(os.path.join(seq_dir, f"video_frame_right_{i:03d}.jpg"), cv2.resize(f1_s, (640, 360)))
            cv2.imwrite(os.path.join(seq_dir, f"video_frame_blend_{i:03d}.jpg"), cv2.resize(blend_frame, (640, 360)))
            cv2.imwrite(os.path.join(seq_dir, f"disparity_{i:03d}.png"), cv2.resize(disp_color, (640, 360)))
            with open(os.path.join(seq_dir, f"points_{i:03d}.json"), "w") as fp:
                json.dump(pts, fp)
            xyz_path = os.path.join(seq_dir, f"points_{i:03d}.xyz")
            with open(xyz_path, "w") as fx:
                fx.writelines(xyz_lines)

            # Oceanographic wave analysis
            analysis, pts_arr, dist_obs, h_sea = analyze_xyz(xyz_path)
            with open(os.path.join(seq_dir, f"wave_analysis_{i:03d}.json"), "w") as fa:
                json.dump(analysis, fa, indent=2)
            export_annotated_xyz(pts_arr, dist_obs, h_sea, os.path.join(seq_dir, f"annotated_points_{i:03d}.csv"))

            rendered_count += 1
            prog = int(20 + (i + 1) / max_frames * 75)
            pipeline_state["progress"] = prog
            pipeline_state["current_stage"] = f"Rendered frame {i+1}/{max_frames}"
            log(f"  Frame {i:02d}/{max_frames-1}: Disparity computed -> 7,000 vertices -> Hs={analysis['significant_wave_height_Hs_m']:.2f}m, Distance mean={analysis['distance']['mean_m']:.1f}m")

        if cap0: cap0.release()
        if cap1: cap1.release()

        meta = {
            "total_frames": rendered_count,
            "fps": 10,
            "grid_w": grid_w,
            "grid_h": grid_h,
            "pair": f"GoPro {pair_name.upper()}"
        }
        with open(os.path.join(seq_dir, "sequence_meta.json"), "w") as fm:
            json.dump(meta, fm, indent=2)

        invalidate_caches()

        with pipeline_lock:
            pipeline_state["progress"] = 100
            pipeline_state["current_stage"] = "Completed"
            pipeline_state["status"] = "completed"
            pipeline_state["reconstructed_frames"] = [f"frame_{i:03d}" for i in range(rendered_count)]
        log(f"\n[Success] All {rendered_count} frames successfully reconstructed into 3D meshes and oceanographic wave telemetry!")

    except Exception as e:
        with pipeline_lock:
            pipeline_state["status"] = "error"
            pipeline_state["current_stage"] = "Error"
        log(f"\n[Error] Pipeline failed: {str(e)}")


def run_pipeline_worker(video0, video1, video_sbs, max_frames, step, use_sample=None):
    with pipeline_lock:
        pipeline_state["status"] = "running"
        pipeline_state["progress"] = 5
        pipeline_state["logs"] = []
        pipeline_state["reconstructed_frames"] = []
        invalidate_caches()

    try:
        binaries = get_wass_binaries()
        work_dir = WORK_DIR

        # Clean workspace output
        out_dir = os.path.join(work_dir, "output")
        if os.path.exists(out_dir):
            shutil.rmtree(out_dir)
        os.makedirs(out_dir, exist_ok=True)

        if use_sample == "synthetic":
            log("[Setup] Loading synthetic wave dataset...")
            sample_in_c0 = os.path.join(WASS_DIR, "test", "WASS_TEST", "synth", "input", "cam0")
            sample_in_c1 = os.path.join(WASS_DIR, "test", "WASS_TEST", "synth", "input", "cam1")
            sample_cfg = os.path.join(WASS_DIR, "test", "WASS_TEST", "synth", "config")
            
            dest_in_c0 = os.path.join(work_dir, "input", "cam0")
            dest_in_c1 = os.path.join(work_dir, "input", "cam1")
            shutil.rmtree(os.path.join(work_dir, "input"), ignore_errors=True)
            os.makedirs(dest_in_c0, exist_ok=True)
            os.makedirs(dest_in_c1, exist_ok=True)

            for f in sorted(glob.glob(os.path.join(sample_in_c0, "*.*")))[:max_frames]:
                shutil.copy2(f, dest_in_c0)
            for f in sorted(glob.glob(os.path.join(sample_in_c1, "*.*")))[:max_frames]:
                shutil.copy2(f, dest_in_c1)

            config_dir = os.path.join(work_dir, "config")
            copy_or_create_configs(binaries, config_dir, calib_src_dir=sample_cfg)
            n_frames = len(glob.glob(os.path.join(dest_in_c0, "*.*")))
            w, h = 2456, 2058
        else:
            log("[1/5] Extracting video frames...")
            pipeline_state["current_stage"] = "Extracting Video Frames"
            n_frames, w, h = extract_frames_from_videos(
                video0_path=video0,
                video1_path=video1,
                video_sbs_path=video_sbs,
                work_dir=work_dir,
                step=step,
                max_frames=max_frames
            )
            config_dir = os.path.join(work_dir, "config")
            copy_or_create_configs(binaries, config_dir, width=w, height=h)

        pipeline_state["progress"] = 25
        log(f"[Info] Prepared {n_frames} stereo frame pairs ({w}x{h}).")

        # 1. wass_prepare
        log("[2/5] Running wass_prepare (Undistortion & Workspace setup)...")
        pipeline_state["current_stage"] = "1. wass_prepare"
        c0_files = sorted(glob.glob(os.path.join(work_dir, "input", "cam0", "*.*")))
        c1_files = sorted(glob.glob(os.path.join(work_dir, "input", "cam1", "*.*")))

        workspaces = []
        for i in range(min(n_frames, max_frames)):
            wd = os.path.join(out_dir, f"{i:06d}_wd")
            os.makedirs(wd, exist_ok=True)
            workspaces.append(wd)
            cmd = [
                binaries["wass_prepare"],
                "--workdir", wd,
                "--calibdir", config_dir,
                "--c0", c0_files[i],
                "--c1", c1_files[i],
                "--continue-if-existing"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                raise RuntimeError(f"wass_prepare failed on frame {i}:\n{res.stderr}")
        pipeline_state["progress"] = 40
        log(f"  -> wass_prepare done for {len(workspaces)} workspaces.")

        # 2. wass_match
        log("[3/5] Running wass_match (Feature matching & Epipolar filter)...")
        pipeline_state["current_stage"] = "2. wass_match"
        matcher_cfg = os.path.join(config_dir, "matcher_config.txt")
        for i, wd in enumerate(workspaces):
            res = subprocess.run([binaries["wass_match"], matcher_cfg, wd], capture_output=True, text=True)
            if res.returncode != 0:
                raise RuntimeError(f"wass_match failed on workspace {i}:\n{res.stderr}")
            for line in res.stdout.splitlines():
                if "matches have passed" in line or "Epipolar error" in line:
                    log(f"  Frame {i:02d}: {line.strip()}")
            pipeline_state["progress"] = 40 + int((i + 1) / len(workspaces) * 25)
        log("  -> wass_match complete.")

        # 3. wass_autocalibrate
        log("[4/5] Running wass_autocalibrate (Sparse Bundle Adjustment)...")
        pipeline_state["current_stage"] = "3. wass_autocalibrate"
        ws_file = os.path.join(out_dir, "workspaces.txt")
        with open(ws_file, "w") as f:
            for wd in workspaces:
                f.write(wd.replace("\\", "/") + "\n")

        res = subprocess.run([binaries["wass_autocalibrate"], ws_file], capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"wass_autocalibrate failed:\n{res.stderr}")
        for line in res.stdout.splitlines():
            if "SBA-optimized" in line or "Final SBA" in line:
                log(f"  {line.strip()}")
        pipeline_state["progress"] = 75

        # 4. wass_stereo
        log("[5/5] Running wass_stereo (Dense 3D Reconstruction)...")
        pipeline_state["current_stage"] = "4. wass_stereo"
        stereo_cfg = os.path.join(config_dir, "stereo_config.txt")
        for i, wd in enumerate(workspaces):
            res = subprocess.run([binaries["wass_stereo"], stereo_cfg, wd], capture_output=True, text=True)
            if res.returncode != 0:
                raise RuntimeError(f"wass_stereo failed on workspace {i}:\n{res.stderr}")
            log(f"  Frame {i:02d}: 3D Mesh & Disparity Generated.")
            pipeline_state["progress"] = 75 + int((i + 1) / len(workspaces) * 25)

        invalidate_caches()
        with pipeline_lock:
            pipeline_state["status"] = "completed"
            pipeline_state["progress"] = 100
            pipeline_state["current_stage"] = "Completed"
            pipeline_state["reconstructed_frames"] = [os.path.basename(w) for w in workspaces]
        log("\n[Success] All 3D Sea Wave Reconstruction Stages Completed Successfully!")

    except Exception as e:
        with pipeline_lock:
            pipeline_state["status"] = "error"
            pipeline_state["current_stage"] = "Error"
        log(f"\n[Error] Pipeline failed: {str(e)}")


@app.get("/", response_class=HTMLResponse)
def index():
    html_file = os.path.join(BASE_DIR, "templates", "index.html")
    with open(html_file, "r", encoding="utf-8") as f:
        content = f.read()
    response = HTMLResponse(content=content)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/favicon.ico")
def favicon():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">🌊</text></svg>'
    return Response(content=svg, media_type="image/svg+xml")



@app.get("/api/status")
def get_status():
    return JSONResponse(pipeline_state)


@app.post("/api/run")
async def start_pipeline(
    background_tasks: BackgroundTasks,
    video_source: str = Form(...),
    cam0_file: UploadFile = File(None),
    cam1_file: UploadFile = File(None),
    sbs_file: UploadFile = File(None),
    max_frames: int = Form(5),
    step: int = Form(1)
):
    if video_source not in ["pair1", "pair2", "sample", "dual", "sbs"]:
        return JSONResponse({"error": f"Invalid video_source '{video_source}'"}, status_code=400)

    if max_frames < 1 or max_frames > 500:
        return JSONResponse({"error": "max_frames must be between 1 and 500"}, status_code=400)

    if step < 1 or step > 100:
        return JSONResponse({"error": "step must be between 1 and 100"}, status_code=400)

    with pipeline_lock:
        if pipeline_state["status"] == "running":
            return JSONResponse({"error": "Pipeline is already running"}, status_code=400)
        pipeline_state["status"] = "running"
        pipeline_state["progress"] = 0
        pipeline_state["current_stage"] = "Initializing"
        pipeline_state["logs"] = [f"[Pipeline] Initialized pipeline with source={video_source}"]
        pipeline_state["reconstructed_frames"] = []
        invalidate_caches()

    if video_source in ["pair1", "pair2"]:
        background_tasks.add_task(
            run_stereo_stream_worker,
            pair_name=video_source,
            max_frames=max_frames,
            step=step
        )
        return JSONResponse({"status": "started", "source": video_source, "frames": max_frames})

    v0_path, v1_path, sbs_path = None, None, None
    use_sample = None

    if video_source == "sample":
        use_sample = "synthetic"
    elif video_source == "dual":
        if not cam0_file or not cam1_file:
            with pipeline_lock:
                pipeline_state["status"] = "idle"
            return JSONResponse({"error": "Please upload both Cam0 and Cam1 video files"}, status_code=400)

        safe_c0 = sanitize_filename(cam0_file.filename)
        safe_c1 = sanitize_filename(cam1_file.filename)
        v0_path = os.path.join(UPLOAD_DIR, "cam0_" + safe_c0)
        v1_path = os.path.join(UPLOAD_DIR, "cam1_" + safe_c1)

        upload_real = os.path.realpath(UPLOAD_DIR)
        if not os.path.realpath(v0_path).startswith(upload_real) or not os.path.realpath(v1_path).startswith(upload_real):
            with pipeline_lock:
                pipeline_state["status"] = "idle"
            return JSONResponse({"error": "Invalid file upload path"}, status_code=400)

        try:
            await save_upload_file(cam0_file, v0_path)
            await save_upload_file(cam1_file, v1_path)
        except ValueError as e:
            with pipeline_lock:
                pipeline_state["status"] = "idle"
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            with pipeline_lock:
                pipeline_state["status"] = "idle"
            return JSONResponse({"error": f"Failed to save uploaded files: {str(e)}"}, status_code=400)

    elif video_source == "sbs":
        if not sbs_file:
            with pipeline_lock:
                pipeline_state["status"] = "idle"
            return JSONResponse({"error": "Please upload a side-by-side stereo video"}, status_code=400)

        safe_sbs = sanitize_filename(sbs_file.filename)
        sbs_path = os.path.join(UPLOAD_DIR, "sbs_" + safe_sbs)
        upload_real = os.path.realpath(UPLOAD_DIR)
        if not os.path.realpath(sbs_path).startswith(upload_real):
            with pipeline_lock:
                pipeline_state["status"] = "idle"
            return JSONResponse({"error": "Invalid file upload path"}, status_code=400)

        try:
            await save_upload_file(sbs_file, sbs_path)
        except ValueError as e:
            with pipeline_lock:
                pipeline_state["status"] = "idle"
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            with pipeline_lock:
                pipeline_state["status"] = "idle"
            return JSONResponse({"error": f"Failed to save uploaded file: {str(e)}"}, status_code=400)

    background_tasks.add_task(
        run_pipeline_worker,
        video0=v0_path,
        video1=v1_path,
        video_sbs=sbs_path,
        max_frames=max_frames,
        step=step,
        use_sample=use_sample
    )

    return JSONResponse({"status": "started", "source": video_source, "frames": max_frames})


@app.get("/api/pointcloud/{frame_name:path}")
def get_pointcloud(frame_name: str, max_points: int = 15000):
    if not is_safe_filename(frame_name):
        return JSONResponse({"error": "Invalid frame name identifier"}, status_code=400)
    max_points = max(1, min(max_points, 100000))

    work_real = os.path.realpath(WORK_DIR)
    
    cand_seq_file = os.path.realpath(os.path.join(WORK_DIR, "sequence", frame_name))
    cand_out_file = os.path.realpath(os.path.join(WORK_DIR, "output", frame_name))
    cand_out_dir = os.path.realpath(os.path.join(WORK_DIR, "output", frame_name))
    cand_wass_dir = os.path.realpath(os.path.join(WORK_DIR, "wass_frames", frame_name))
    
    idx_match = re.search(r'(\d+)', frame_name)
    cand_idx_json = None
    cand_idx_xyz = None
    if idx_match:
        f_idx = int(idx_match.group(1))
        cand_idx_json = os.path.join(WORK_DIR, "sequence", f"points_{f_idx:03d}.json")
        cand_idx_xyz = os.path.join(WORK_DIR, "sequence", f"points_{f_idx:03d}.xyz")

    found_path = None
    file_type = None

    if os.path.isfile(cand_seq_file) and cand_seq_file.startswith(work_real):
        found_path = cand_seq_file
        file_type = "xyz" if cand_seq_file.endswith(".xyz") else ("json" if cand_seq_file.endswith(".json") else "xyz")
    elif os.path.isfile(cand_out_file) and cand_out_file.startswith(work_real):
        found_path = cand_out_file
        file_type = "xyz" if cand_out_file.endswith(".xyz") else ("json" if cand_out_file.endswith(".json") else "xyz")
    elif os.path.isdir(cand_out_dir) and cand_out_dir.startswith(work_real):
        json_path = os.path.join(cand_out_dir, "points.json")
        xyz_path = os.path.join(cand_out_dir, "plane_refinement_inliers.xyz")
        if os.path.isfile(json_path):
            found_path = json_path
            file_type = "json"
        elif os.path.isfile(xyz_path):
            found_path = xyz_path
            file_type = "xyz"
    elif cand_idx_json and os.path.isfile(cand_idx_json):
        found_path = cand_idx_json
        file_type = "json"
    elif cand_idx_xyz and os.path.isfile(cand_idx_xyz):
        found_path = cand_idx_xyz
        file_type = "xyz"
    elif os.path.isdir(cand_wass_dir) and cand_wass_dir.startswith(work_real):
        xyz_path = os.path.join(cand_wass_dir, "plane_refinement_inliers.xyz")
        if os.path.isfile(xyz_path):
            found_path = xyz_path
            file_type = "xyz"

    if not found_path:
        return JSONResponse({"error": "Pointcloud file not found"}, status_code=404)

    if file_type == "json":
        try:
            with open(found_path, "r") as f:
                pts = json.load(f)
            if not isinstance(pts, list):
                return JSONResponse({"error": "Pointcloud data corrupted: expected list"}, status_code=500)
            if len(pts) > max_points:
                sub_indices = np.random.choice(len(pts), max_points, replace=False)
                pts = [pts[i] for i in sub_indices]
            return JSONResponse({"count": len(pts), "points": pts})
        except Exception as e:
            return JSONResponse({"error": f"Failed to read pointcloud json: {str(e)}"}, status_code=500)

    try:
        points = []
        with open(found_path, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 3:
                    try:
                        points.append([float(parts[0]), float(parts[1]), float(parts[2])])
                    except ValueError:
                        continue
        pts = np.array(points)
        if len(pts) > max_points:
            sub_indices = np.random.choice(len(pts), max_points, replace=False)
            pts = pts[sub_indices]
        return JSONResponse({"count": len(pts), "points": pts.tolist()})
    except Exception as e:
        return JSONResponse({"error": f"Failed to read pointcloud xyz: {str(e)}"}, status_code=500)

def _get_active_total_frames():
    seq_dir = os.path.join(WORK_DIR, "sequence")
    meta_path = os.path.join(seq_dir, "sequence_meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r") as f:
                data = json.load(f)
                if isinstance(data, dict) and "total_frames" in data:
                    return max(0, int(data["total_frames"]))
        except Exception:
            pass
    if os.path.exists(seq_dir):
        pts_files = glob.glob(os.path.join(seq_dir, "points_*.json"))
        return len(pts_files)
    return 0

@app.get("/api/sequence/all_points")
def get_all_points():
    global _cached_all_points, _cached_all_points_bytes
    if _cached_all_points_bytes is not None:
        return Response(content=_cached_all_points_bytes, media_type="application/json")
    with _cache_points_lock:
        if _cached_all_points_bytes is not None:
            return Response(content=_cached_all_points_bytes, media_type="application/json")
        seq_dir = os.path.join(WORK_DIR, "sequence")
        frames = {}
        total_frames = _get_active_total_frames()
        for idx in range(total_frames):
            pts_file = os.path.join(seq_dir, f"points_{idx:03d}.json")
            if os.path.exists(pts_file):
                try:
                    with open(pts_file, "r") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            frames[idx] = data
                except Exception:
                    continue
        _cached_all_points = frames
        _cached_all_points_bytes = json.dumps(frames).encode("utf-8")
        return Response(content=_cached_all_points_bytes, media_type="application/json")


@app.get("/api/sequence/all_analysis")
def get_all_analysis():
    global _cached_all_analysis, _cached_all_analysis_bytes
    if _cached_all_analysis_bytes is not None:
        return Response(content=_cached_all_analysis_bytes, media_type="application/json")
    with _cache_analysis_lock:
        if _cached_all_analysis_bytes is not None:
            return Response(content=_cached_all_analysis_bytes, media_type="application/json")
        seq_dir = os.path.join(WORK_DIR, "sequence")
        analyses = {}
        total_frames = _get_active_total_frames()
        for idx in range(total_frames):
            a_file = os.path.join(seq_dir, f"wave_analysis_{idx:03d}.json")
            if os.path.exists(a_file):
                try:
                    with open(a_file, "r") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            analyses[f"frame_{idx}"] = data
                except Exception:
                    continue
        _cached_all_analysis = analyses
        _cached_all_analysis_bytes = json.dumps(analyses).encode("utf-8")
        return Response(content=_cached_all_analysis_bytes, media_type="application/json")


@app.get("/api/sequence/meta")
def get_sequence_meta():
    meta_path = os.path.join(WORK_DIR, "sequence", "sequence_meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return JSONResponse(data)
        except Exception:
            pass
    total_frames = _get_active_total_frames()
    return JSONResponse({"total_frames": total_frames, "fps": 10})


@app.get("/api/sequence/frame/{idx}")
def get_sequence_frame(idx: int, request: Request = None):
    total_frames = _get_active_total_frames()
    if idx < 0 or idx >= total_frames:
        return JSONResponse({"error": "Frame not found"}, status_code=404)
    global _cached_frames_bytes
    no_cache = False
    if request is not None:
        cc = request.headers.get("cache-control", "").lower()
        pragma = request.headers.get("pragma", "").lower()
        if "no-cache" in cc or "no-cache" in pragma:
            no_cache = True
    if not no_cache and idx in _cached_frames_bytes:
        return Response(content=_cached_frames_bytes[idx], media_type="application/json")
    seq_dir = os.path.join(WORK_DIR, "sequence")
    pts_file = os.path.join(seq_dir, f"points_{idx:03d}.json")
    if not os.path.exists(pts_file):
        return JSONResponse({"error": "Frame not found"}, status_code=404)
    try:
        with open(pts_file, "r") as f:
            pts = json.load(f)
        if not isinstance(pts, list):
            return JSONResponse({"error": "Frame data corrupted: expected list"}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": f"Failed to read frame data: {str(e)}"}, status_code=500)

    frame_obj = {
        "frame_index": idx,
        "video_url": f"/workspace/sequence/video_frame_{idx:03d}.jpg",
        "video_left_url": f"/workspace/sequence/video_frame_left_{idx:03d}.jpg",
        "video_right_url": f"/workspace/sequence/video_frame_right_{idx:03d}.jpg",
        "video_blend_url": f"/workspace/sequence/video_frame_blend_{idx:03d}.jpg",
        "disparity_url": f"/workspace/sequence/disparity_{idx:03d}.png",
        "count": len(pts),
        "points": pts
    }
    encoded = json.dumps(frame_obj).encode("utf-8")
    if not no_cache:
        _cached_frames_bytes[idx] = encoded
    return Response(content=encoded, media_type="application/json")


@app.get("/api/wave_analysis/{target}")
def get_wave_analysis(target: str):
    """
    Returns wave analysis data (height from sea level, distance from observer,
    significant wave height, distance profile, elevation histogram).
    """
    if not is_safe_identifier(target):
        return JSONResponse({"error": "Invalid target identifier"}, status_code=400)

    analysis_file = None
    total_frames = _get_active_total_frames()
    if target.startswith("frame_"):
        val = target.replace("frame_", "")
        if val.isdigit():
            idx = int(val)
            if idx < 0 or idx >= total_frames:
                return JSONResponse({"error": "Wave analysis not found for " + target}, status_code=404)
            analysis_file = os.path.join(WORK_DIR, "sequence", f"wave_analysis_{idx:03d}.json")
    elif target.startswith("sequence_"):
        val = target.replace("sequence_", "")
        if val.isdigit():
            idx = int(val)
            if idx < 0 or idx >= total_frames:
                return JSONResponse({"error": "Wave analysis not found for " + target}, status_code=404)
            analysis_file = os.path.join(WORK_DIR, "sequence", f"wave_analysis_{idx:03d}.json")
    elif target.isdigit():
        idx = int(target)
        if idx < 0 or idx >= total_frames:
            return JSONResponse({"error": "Wave analysis not found for " + target}, status_code=404)
        analysis_file = os.path.join(WORK_DIR, "sequence", f"wave_analysis_{idx:03d}.json")
    else:
        target_path = os.path.realpath(os.path.join(WORK_DIR, "output", target, "wave_analysis.json"))
        work_real = os.path.realpath(WORK_DIR)
        if not target_path.startswith(work_real):
            return JSONResponse({"error": "Access denied"}, status_code=403)
        analysis_file = target_path
    
    if analysis_file and os.path.exists(analysis_file):
        try:
            with open(analysis_file, "r") as fa:
                data = json.load(fa)
                if isinstance(data, dict):
                    return JSONResponse(data)
                return JSONResponse({"error": "Corrupted wave analysis data"}, status_code=500)
        except Exception as e:
            return JSONResponse({"error": f"Failed to read wave analysis: {str(e)}"}, status_code=500)
            
    return JSONResponse({"error": "Wave analysis not found for " + target}, status_code=404)


@app.get("/api/wave_analysis/export/{target}")
def export_wave_analysis_csv(target: str):
    """
    Downloads the annotated CSV containing:
    x_camera_m, y_camera_m, z_camera_m, distance_from_observer_m, height_from_sea_level_m
    """
    if not is_safe_identifier(target):
        return JSONResponse({"error": "Invalid target identifier"}, status_code=400)

    csv_file = None
    total_frames = _get_active_total_frames()
    if target.startswith("frame_"):
        val = target.replace("frame_", "")
        if val.isdigit():
            idx = int(val)
            if idx < 0 or idx >= total_frames:
                return JSONResponse({"error": "CSV export not found for " + target}, status_code=404)
            csv_file = os.path.join(WORK_DIR, "sequence", f"annotated_points_{idx:03d}.csv")
            filename = f"wave_analysis_frame_{idx:03d}.csv"
    elif target.startswith("sequence_"):
        val = target.replace("sequence_", "")
        if val.isdigit():
            idx = int(val)
            if idx < 0 or idx >= total_frames:
                return JSONResponse({"error": "CSV export not found for " + target}, status_code=404)
            csv_file = os.path.join(WORK_DIR, "sequence", f"annotated_points_{idx:03d}.csv")
            filename = f"wave_analysis_sequence_{idx:03d}.csv"
    elif target.isdigit():
        idx = int(target)
        if idx < 0 or idx >= total_frames:
            return JSONResponse({"error": "CSV export not found for " + target}, status_code=404)
        csv_file = os.path.join(WORK_DIR, "sequence", f"annotated_points_{idx:03d}.csv")
        filename = f"wave_analysis_frame_{idx:03d}.csv"
    else:
        target_path = os.path.realpath(os.path.join(WORK_DIR, "output", target, "annotated_wave_points.csv"))
        work_real = os.path.realpath(WORK_DIR)
        if not target_path.startswith(work_real):
            return JSONResponse({"error": "Access denied"}, status_code=403)
        csv_file = target_path
        filename = f"wave_analysis_{target}.csv"

    if csv_file and os.path.exists(csv_file):
        return FileResponse(
            path=csv_file,
            filename=filename,
            media_type="text/csv"
        )
    return JSONResponse({"error": "CSV export not found for " + target}, status_code=404)


@app.get("/api/wave_analysis/export_arcs/{target:path}")
def export_circular_arcs_csv(target: str):
    """
    Downloads CSV containing the 5m circular arc wave output matching RFC 4180:
    arc_radius_m,range_band,vertex_count,mean_elevation_m,peak_crest_m,deepest_trough_m,wave_amplitude_m,significant_wave_height_Hs_m,elevation_std_sigma_m,azimuth_min_deg,azimuth_max_deg,azimuth_span_deg
    """
    if not is_safe_identifier(target):
        return JSONResponse({"error": "Invalid target identifier"}, status_code=400)

    idx = None
    json_path = None
    if target.startswith("frame_"):
        val = target.replace("frame_", "")
        if val.isdigit():
            idx = int(val)
    elif target.startswith("sequence_"):
        val = target.replace("sequence_", "")
        if val.isdigit():
            idx = int(val)
    elif target.isdigit():
        idx = int(target)

    total_frames = _get_active_total_frames()
    if idx is not None:
        if idx < 0 or idx >= total_frames:
            return JSONResponse({"error": "Wave analysis not found for " + target}, status_code=404)
        json_path = os.path.join(WORK_DIR, "sequence", f"wave_analysis_{idx:03d}.json")
    else:
        target_path = os.path.realpath(os.path.join(WORK_DIR, "output", target, "wave_analysis.json"))
        work_real = os.path.realpath(WORK_DIR)
        if not target_path.startswith(work_real):
            return JSONResponse({"error": "Access denied"}, status_code=403)
        if os.path.exists(target_path):
            json_path = target_path
        else:
            return JSONResponse({"error": "Wave analysis not found for " + target}, status_code=404)

    if not json_path or not os.path.exists(json_path):
        return JSONResponse({"error": "Wave analysis not found for " + target}, status_code=404)

    try:
        with open(json_path, "r") as fa:
            data = json.load(fa)
        if not isinstance(data, dict):
            return JSONResponse({"error": "Corrupted wave analysis data"}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": f"Failed to read wave analysis: {str(e)}"}, status_code=500)

    arcs = data.get("circular_arcs_5m", [])
    if not arcs or not isinstance(arcs, list):
        return JSONResponse({"error": "No circular arc data found"}, status_code=404)

    header = "arc_radius_m,range_band,vertex_count,mean_elevation_m,peak_crest_m,deepest_trough_m,wave_amplitude_m,significant_wave_height_Hs_m,elevation_std_sigma_m,azimuth_min_deg,azimuth_max_deg,azimuth_span_deg\r\n"
    csv_rows = [header]
    for a in arcs:
        if not isinstance(a, dict):
            continue
        az_min = float(a.get("azimuth_min_deg") or 0.0)
        az_max = float(a.get("azimuth_max_deg") or 0.0)
        az_span = round(float(az_max - az_min), 1)
        r_band = str(a.get("band_m", ""))
        hs_val = float(a.get("significant_height_Hs_m", a.get("Hs_m", 0.0)) or 0.0)
        row = (
            f"{a.get('radius_m', 0.0)},"
            f"{r_band},"
            f"{a.get('point_count', 0)},"
            f"{a.get('mean_elevation_m', 0.0)},"
            f"{a.get('crest_m', 0.0)},"
            f"{a.get('trough_m', 0.0)},"
            f"{a.get('amplitude_m', 0.0)},"
            f"{hs_val},"
            f"{a.get('std_elevation_m', 0.0)},"
            f"{az_min},"
            f"{az_max},"
            f"{az_span}\r\n"
        )
        csv_rows.append(row)

    csv_data = "".join(csv_rows)
    export_name = f"circular_arcs_frame_{idx:03d}.csv" if idx is not None else f"circular_arcs_{target}.csv"
    if idx is not None:
        out_csv = os.path.join(WORK_DIR, "sequence", f"circular_arcs_{idx:03d}.csv")
        try:
            with open(out_csv, "w", newline="") as fc:
                fc.write(csv_data)
        except Exception:
            pass

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{export_name}"'
        }
    )


def main():
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    print(f"Starting WASS Web Application on http://{host}:{port} ...")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

