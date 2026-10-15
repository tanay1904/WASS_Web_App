"""
WASS Video Bypass and 3D Reconstruction Pipeline
=================================================
Feeds pre-recorded stereo video files (dual camera or side-by-side) directly into
the WASS pipeline (wass_prepare -> wass_match -> wass_autocalibrate -> wass_stereo).
"""

import os
import sys
import glob
import shutil
import argparse
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


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PREDICT_DIR = os.path.dirname(BASE_DIR)
_LOCAL_DIST = os.path.join(PREDICT_DIR, "wass_dist", "wass_1.11_win32_x64", "dist", "bin")
_WEBAPP_DIST = os.path.join(BASE_DIR, "wass_dist", "wass_1.11_win32_x64", "dist", "bin")
_PREDICT_DIST = r"C:\Users\tanay\predicttion\wass_dist\wass_1.11_win32_x64\dist\bin"
_SCRATCH_DIST = r"C:\Users\tanay\.gemini\antigravity\scratch\wass_dist\wass_1.11_win32_x64\dist\bin"
WASS_BIN_DIR = _LOCAL_DIST if os.path.exists(_LOCAL_DIST) else (_WEBAPP_DIST if os.path.exists(_WEBAPP_DIST) else (_PREDICT_DIST if os.path.exists(_PREDICT_DIST) else _SCRATCH_DIST))



def get_wass_binaries():
    """Locate WASS binaries."""
    binaries = {
        "wass_prepare": os.path.join(WASS_BIN_DIR, "wass_prepare.exe"),
        "wass_match": os.path.join(WASS_BIN_DIR, "wass_match.exe"),
        "wass_autocalibrate": os.path.join(WASS_BIN_DIR, "wass_autocalibrate.exe"),
        "wass_stereo": os.path.join(WASS_BIN_DIR, "wass_stereo.exe"),
    }
    for name, path in binaries.items():
        if not os.path.exists(path):
            raise FileNotFoundError(f"WASS binary {name} not found at {path}")
    return binaries


def generate_default_calibration(config_dir, width, height, f_factor=1.0):
    """Generate default pinhole calibration XML files if none provided."""
    os.makedirs(config_dir, exist_ok=True)
    fx = float(width) * f_factor
    fy = float(width) * f_factor
    cx = float(width) / 2.0
    cy = float(height) / 2.0

    intrinsics_tmpl = f"""<?xml version="1.0"?>
<opencv_storage>
<camera_matrix type_id="opencv-matrix">
  <rows>3</rows>
  <cols>3</cols>
  <dt>d</dt>
  <data>
    {fx:.6f} 0. {cx:.6f} 0. {fy:.6f} {cy:.6f} 0. 0. 1.</data></camera_matrix>
</opencv_storage>
"""

    distortion_tmpl = """<?xml version="1.0"?>
<opencv_storage>
<distortion_coefficients type_id="opencv-matrix">
  <rows>5</rows>
  <cols>1</cols>
  <dt>d</dt>
  <data>
    0. 0. 0. 0. 0.</data></distortion_coefficients>
</opencv_storage>
"""

    for cam in ["00", "01"]:
        intr_path = os.path.join(config_dir, f"intrinsics_{cam}.xml")
        dist_path = os.path.join(config_dir, f"distortion_{cam}.xml")
        if not os.path.exists(intr_path):
            with open(intr_path, "w") as f:
                f.write(intrinsics_tmpl)
        if not os.path.exists(dist_path):
            with open(dist_path, "w") as f:
                f.write(distortion_tmpl)


def copy_or_create_configs(binaries, config_dir, calib_src_dir=None, width=None, height=None):
    """Copy calibration files or generate default configs."""
    os.makedirs(config_dir, exist_ok=True)

    if calib_src_dir and os.path.exists(calib_src_dir):
        for f in glob.glob(os.path.join(calib_src_dir, "*")):
            shutil.copy2(f, config_dir)
        print(f"[Config] Copied calibration files from {calib_src_dir}")
    else:
        if width and height:
            generate_default_calibration(config_dir, width, height)
            print(f"[Config] Generated default calibration for resolution {width}x{height}")

    # Generate config files if missing
    matcher_cfg = os.path.join(config_dir, "matcher_config.txt")
    stereo_cfg = os.path.join(config_dir, "stereo_config.txt")
    prepare_cfg = os.path.join(config_dir, "prepare_config.txt")

    if not os.path.exists(matcher_cfg):
        subprocess.run([binaries["wass_match"], "--genconfig"], cwd=config_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not os.path.exists(stereo_cfg):
        subprocess.run([binaries["wass_stereo"], "--genconfig"], cwd=config_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not os.path.exists(prepare_cfg):
        subprocess.run([binaries["wass_prepare"], "--genconfig"], cwd=config_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def extract_frames_from_videos(video0_path, video1_path, video_sbs_path, work_dir, step=1, max_frames=None):
    """Extract stereo frames from video input into WASS workdir."""
    if step is None or step < 1:
        raise ValueError(f"step must be a positive integer (>= 1), got {step}")
    if max_frames is not None and max_frames < 1:
        raise ValueError(f"max_frames must be a positive integer (>= 1), got {max_frames}")

    cam0_dir = os.path.join(work_dir, "input", "cam0")
    cam1_dir = os.path.join(work_dir, "input", "cam1")
    os.makedirs(cam0_dir, exist_ok=True)
    os.makedirs(cam1_dir, exist_ok=True)

    frame_count = 0
    saved_count = 0

    if video_sbs_path:
        print(f"[Video Feeder] Reading side-by-side video: {video_sbs_path}")
        cap = cv2.VideoCapture(video_sbs_path)
        if not cap.isOpened():
            raise RuntimeError(f"Failed to open video {video_sbs_path}")

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        print(f"[Video Feeder] Total frames: {total_frames}, FPS: {fps:.1f}")

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_count % step == 0:
                h, w, _ = frame.shape
                half_w = w // 2
                im0 = frame[:, :half_w]
                im1 = frame[:, half_w:]

                ts_ms = int((frame_count / fps) * 1000.0)
                name0 = f"{saved_count:06d}_{ts_ms:013d}_01.png"
                name1 = f"{saved_count:06d}_{ts_ms:013d}_02.png"

                cv2.imwrite(os.path.join(cam0_dir, name0), im0)
                cv2.imwrite(os.path.join(cam1_dir, name1), im1)
                saved_count += 1

                if max_frames and saved_count >= max_frames:
                    break
            frame_count += 1
        cap.release()
        img_w, img_h = half_w, h

    elif video0_path and video1_path:
        print(f"[Video Feeder] Reading dual camera videos: {video0_path} & {video1_path}")
        cap0 = cv2.VideoCapture(video0_path)
        cap1 = cv2.VideoCapture(video1_path)

        if not cap0.isOpened() or not cap1.isOpened():
            raise RuntimeError("Failed to open one or both video streams")

        fps = cap0.get(cv2.CAP_PROP_FPS) or 25.0

        while True:
            ret0, frame0 = cap0.read()
            ret1, frame1 = cap1.read()
            if not ret0 or not ret1:
                break
            if frame_count % step == 0:
                h, w, _ = frame0.shape
                ts_ms = int((frame_count / fps) * 1000.0)
                name0 = f"{saved_count:06d}_{ts_ms:013d}_01.png"
                name1 = f"{saved_count:06d}_{ts_ms:013d}_02.png"

                cv2.imwrite(os.path.join(cam0_dir, name0), frame0)
                cv2.imwrite(os.path.join(cam1_dir, name1), frame1)
                saved_count += 1

                if max_frames and saved_count >= max_frames:
                    break
            frame_count += 1
        cap0.release()
        cap1.release()
        img_w, img_h = w, h
    else:
        raise ValueError("Must provide either --video-sbs OR both --video0 and --video1")

    print(f"[Video Feeder] Extracted {saved_count} stereo pairs ({img_w}x{img_h}) into {work_dir}/input/")
    return saved_count, img_w, img_h


def run_wass_pipeline(work_dir, binaries, num_frames):
    """Execute WASS 4-stage processing pipeline."""
    config_dir = os.path.join(work_dir, "config")
    input_c0 = os.path.join(work_dir, "input", "cam0")
    input_c1 = os.path.join(work_dir, "input", "cam1")
    output_dir = os.path.join(work_dir, "output")

    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    c0_files = sorted(glob.glob(os.path.join(input_c0, "*.*")))
    c1_files = sorted(glob.glob(os.path.join(input_c1, "*.*")))

    frames_to_proc = min(len(c0_files), len(c1_files), num_frames)
    print(f"\n=======================================================")
    print(f" Starting WASS Pipeline on {frames_to_proc} Stereo Frames")
    print(f"=======================================================\n")

    # 1. wass_prepare
    print("[1/4] Running wass_prepare...")
    workspaces = []
    for i in range(frames_to_proc):
        wd = os.path.join(output_dir, f"{i:06d}_wd")
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
            print(f"Error in wass_prepare for frame {i}:\n{res.stderr}\n{res.stdout}")
            return False
    print(f"  -> wass_prepare complete ({len(workspaces)} workspaces created).")

    # 2. wass_match
    print("\n[2/4] Running wass_match...")
    matcher_cfg = os.path.join(config_dir, "matcher_config.txt")
    for i, wd in enumerate(workspaces):
        cmd = [binaries["wass_match"], matcher_cfg, wd]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Error in wass_match for workspace {wd}:\n{res.stderr}\n{res.stdout}")
            return False
        # Extract epipolar error from output if present
        for line in res.stdout.splitlines():
            if "Epipolar error" in line or "matches have passed" in line:
                print(f"  Frame {i:02d}: {line.strip()}")
    print("  -> wass_match complete.")

    # 3. wass_autocalibrate
    print("\n[3/4] Running wass_autocalibrate (SBA optimization)...")
    ws_file = os.path.join(output_dir, "workspaces.txt")
    with open(ws_file, "w") as f:
        for wd in workspaces:
            # WASS expects forward slashes or escaped backslashes
            f.write(wd.replace("\\", "/") + "\n")

    cmd = [binaries["wass_autocalibrate"], ws_file]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error in wass_autocalibrate:\n{res.stderr}\n{res.stdout}")
        return False
    for line in res.stdout.splitlines():
        if "SBA-optimized" in line or "Final SBA-optimized" in line:
            print(f"  {line.strip()}")
    print("  -> wass_autocalibrate complete.")

    # 4. wass_stereo
    print("\n[4/4] Running wass_stereo (Dense 3D Reconstruction)...")
    stereo_cfg = os.path.join(config_dir, "stereo_config.txt")
    for i, wd in enumerate(workspaces):
        cmd = [binaries["wass_stereo"], stereo_cfg, wd]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Error in wass_stereo for workspace {wd}:\n{res.stderr}\n{res.stdout}")
            return False
        
        # Check generated outputs
        ply_file = os.path.join(wd, "mesh.ply")
        xyz_file = os.path.join(wd, "mesh_cam.xyzC")
        disp_file = os.path.join(wd, "disparity_final_scaled.png")
        plane_file = os.path.join(wd, "plane.txt")
        
        ply_exists = os.path.exists(ply_file)
        xyz_exists = os.path.exists(xyz_file)
        disp_exists = os.path.exists(disp_file)
        
        print(f"  Frame {i:02d} reconstructed: mesh.ply={ply_exists}, mesh_cam.xyzC={xyz_exists}, disparity={disp_exists}")

    print("\n=======================================================")
    print(" WASS Pipeline Reconstructed Successfully!")
    print(f" Outputs saved to: {output_dir}")
    print("=======================================================\n")
    return True


def main():
    parser = argparse.ArgumentParser(description="WASS Video Bypass & 3D Reconstruction")
    parser.add_argument("--video0", type=str, help="Path to Cam0 video file")
    parser.add_argument("--video1", type=str, help="Path to Cam1 video file")
    parser.add_argument("--video-sbs", type=str, help="Path to Side-by-Side stereo video file")
    parser.add_argument("--calib-dir", type=str, help="Path to calibration config directory")
    parser.add_argument("--work-dir", type=str, default=r"C:\Users\tanay\.gemini\antigravity\scratch\wass_video_workspace", help="Working directory")
    parser.add_argument("--step", type=int, default=1, help="Frame step/skip factor")
    parser.add_argument("--max-frames", type=int, default=10, help="Maximum number of frames to process")

    args = parser.parse_args()

    if args.max_frames is not None and args.max_frames < 1:
        parser.error(f"--max-frames must be a positive integer (>= 1), got {args.max_frames}")
    if args.step is not None and args.step < 1:
        parser.error(f"--step must be a positive integer (>= 1), got {args.step}")
    if not args.video_sbs and not (args.video0 and args.video1):
        parser.error("Must provide either --video-sbs OR both --video0 and --video1")

    binaries = get_wass_binaries()
    os.makedirs(args.work_dir, exist_ok=True)

    # 1. Extract frames from video
    n_frames, w, h = extract_frames_from_videos(
        video0_path=args.video0,
        video1_path=args.video1,
        video_sbs_path=args.video_sbs,
        work_dir=args.work_dir,
        step=args.step,
        max_frames=args.max_frames
    )

    # 2. Setup configs and calibration
    config_dir = os.path.join(args.work_dir, "config")
    copy_or_create_configs(binaries, config_dir, calib_src_dir=args.calib_dir, width=w, height=h)

    # Enable SAVE_AS_PLY in stereo_config.txt if not already set
    stereo_cfg = os.path.join(config_dir, "stereo_config.txt")
    if os.path.exists(stereo_cfg):
        with open(stereo_cfg, "r") as f:
            content = f.read()
        if "SAVE_AS_PLY" not in content or "SAVE_AS_PLY=false" in content:
            content = content.replace("SAVE_AS_PLY=false", "SAVE_AS_PLY=true")
            if "SAVE_AS_PLY" not in content:
                content += "\nSAVE_AS_PLY=true\n"
            with open(stereo_cfg, "w") as f:
                f.write(content)

    # 3. Execute WASS Pipeline
    success = run_wass_pipeline(args.work_dir, binaries, n_frames)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
