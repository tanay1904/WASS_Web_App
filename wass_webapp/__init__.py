"""
WASS 3D Ocean Wave Stereophotogrammetry Web Studio & Pipeline Package.
"""

__version__ = "1.0.0"


def ensure_opencv():
    """
    Ensure OpenCV is importable. In headless Linux / Codespaces environments,
    if standard GUI opencv-python was installed without Mesa (libGL.so.1),
    this function automatically repairs the environment by installing OS libraries
    and switching to opencv-python-headless without requiring user intervention.
    """
    try:
        import cv2  # noqa: F401
        return
    except ImportError as err:
        import sys
        import subprocess
        import importlib

        print(f"[WASS Auto-Heal] Notice: OpenCV failed to load ({err}). Automatically repairing headless environment...")
        try:
            if sys.platform.startswith("linux"):
                try:
                    subprocess.run(
                        ["sudo", "apt-get", "update", "-qq"],
                        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15
                    )
                    subprocess.run(
                        ["sudo", "apt-get", "install", "-y", "-qq", "--no-install-recommends", "libgl1", "libglib2.0-0"],
                        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30
                    )
                except Exception:
                    pass

            subprocess.run(
                [sys.executable, "-m", "pip", "uninstall", "-y", "opencv-python", "opencv-contrib-python"],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20
            )
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--no-cache-dir", "opencv-python-headless"],
                check=True, timeout=90
            )
            for mod in list(sys.modules.keys()):
                if mod == "cv2" or mod.startswith("cv2."):
                    sys.modules.pop(mod, None)
            importlib.invalidate_caches()
            import cv2  # noqa: F401
            print("[WASS Auto-Heal] Successfully repaired OpenCV (switched to opencv-python-headless)!")
        except Exception as heal_err:
            raise ImportError(
                f"OpenCV could not be loaded or auto-repaired: {err}. Error during auto-heal: {heal_err}"
            ) from err


ensure_opencv()
