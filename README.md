# WASS - 3D Ocean Wave Stereophotogrammetry Studio

[![CI Validation](https://github.com/tanay1904/wass-ocean-wave-stereo/actions/workflows/ci.yml/badge.svg)](https://github.com/tanay1904/wass-ocean-wave-stereo/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Codespaces Ready](https://img.shields.io/badge/Codespaces-Ready-brightgreen.svg)](https://github.com/features/codespaces)

A real-time, interactive 3D Ocean Wave Stereophotogrammetry Web Studio and processing pipeline based on the **WASS (Waves Acquisition Stereo System)** methodology. The system ingests calibrated binocular video streams, computes dense disparity and 3D slant range ocean surface elevation, drapes concentric nautical radar range arcs, and visualizes dynamic wave kinematics at up to 10 FPS.

---

## Key Features

* **3D Marine Reconstruction:** Generates continuous $100 \times 70$ regularized elevation grids ($7,000$ vertices, $13,662$ triangles per frame) across lateral and range coordinates $X \in [-25, 15]\,\text{m}, Y \in [2.5, 50]\,\text{m}$.
* **10 Concentric 5m Circular Radar Arcs:** Dynamically drapes nautical range ribbons ($5\,\text{m} \to 50\,\text{m}$) directly onto the sea wave surface with staggered distance labels.
* **Physically Scaled Vessel Bow:** Realistic 3D Kerala orange wooden boat hull ($Y \in [-1.2, 4.0]\,\text{m}$) with bilateral water channels ($24.45\,\text{m}$ port, $14.45\,\text{m}$ starboard) and $1.000\,\text{m}$ bow clearance to the 5m radar arc.
* **Rigorous Physical Scaling:** Formulates metric elevation via 3D slant range $R_{\text{grid}} = \sqrt{X_{\text{grid}}^2 + Y_{\text{grid}}^2 + H_{\text{cam}}^2}$ and metric scale factor $\text{scale\_geom} = \frac{R_{\text{grid}} \cdot H_{\text{cam}}}{f_{\text{scaled}} \cdot B}$ with zero heuristic clipping.
* **Dual Synchronized Video Playback:** Synchronized dual-camera video streams, dense disparity viewer, elevation probability histogram, and 10-bin distance telemetry tables.
* **100% Offline Asset Vendoring:** Vendored Three.js r128, OrbitControls, and Bootstrap 5 for instant load times and immunity to browser tracking prevention.

---

## System Architecture

```
.
├── .devcontainer/
│   └── devcontainer.json               # GitHub Codespaces container specification
├── .github/
│   └── workflows/
│       └── ci.yml                      # Automated CI verification suite
├── docs/
│   └── DATA_SPECIFICATION.md           # Oceanographic coordinates & mathematical specification
├── tests/
│   ├── test_wave_math.py               # Unit tests for physical stereo math & 5m arcs
│   └── test_api_endpoints.py           # Integration tests for FastAPI endpoints & RFC 4180 CSV
├── wass_webapp/
│   ├── app.py                          # High-performance FastAPI application
│   ├── static/
│   │   ├── vendor/                     # 100% offline Three.js, OrbitControls, Bootstrap
│   │   └── webfonts/                   # Vendored FontAwesome webfonts
│   ├── templates/
│   │   └── index.html                  # Responsive 3D WebGL cockpit
│   └── workspace/
│       └── sequence/                   # Benchmark 60-frame calibrated stereo dataset
├── analyze_wave_xyz.py                 # Core oceanographic wave field analyzer & circular arcs
├── wass_video_pipeline.py              # Stereo ingestion & calibration pipeline
├── regenerate_5m_arcs.py               # Batch sequence telemetry regeneration tool
└── requirements.txt                    # Project Python dependencies
```

---

## Quickstart

### Option 1: GitHub Codespaces (1-Click Cloud Launch)
1. Open this repository in **GitHub Codespaces**.
2. Codespaces automatically builds the Python 3.10 container and installs dependencies.
3. Start the application:
   ```bash
   python -m uvicorn wass_webapp.app:app --host 0.0.0.0 --port 8080
   ```
4. Click the forwarded port **8080** in the Ports tab to open the 3D Wave Studio.

### Option 2: Local Installation (Windows / Linux / macOS)
1. **Clone the repository:**
   ```bash
   git clone https://github.com/tanay1904/wass-ocean-wave-stereo.git
   cd wass-ocean-wave-stereo
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Launch the Web Studio:**
   ```bash
   python -m uvicorn wass_webapp.app:app --host 0.0.0.0 --port 8080
   ```
   Open your browser at `http://127.0.0.1:8080/`.

---

## REST API Endpoints

| Method | Endpoint | Description |
| :---: | :--- | :--- |
| `GET` | `/` | Web Studio 3D cockpit interface |
| `GET` | `/favicon.ico` | Instant zero-latency SVG wave icon |
| `GET` | `/api/status` | Current pipeline and playback state |
| `GET` | `/api/sequence/meta` | Sequence metadata (frame count, FPS, grid dimensions) |
| `GET` | `/api/sequence/frame/{index}` | 7,000 regularized $[X, Y, Z]$ vertices for frame index |
| `GET` | `/api/sequence/all_points` | Pre-cached binary sequence point cloud buffer |
| `GET` | `/api/wave_analysis/{frame_id}` | Oceanographic wave telemetry and 10 concentric 5m radar arcs |
| `GET` | `/api/wave_analysis/export_arcs/{frame_id}` | RFC 4180 compliant CSV export of the 10 circular range arcs |

---

## Running the Automated Test Suite

Run the full automated test suite covering unit math, geometry verification, and FastAPI endpoints:

```bash
python -m pytest tests/ -v
```

All 12 test modules evaluate metric scale formulas, bow clearances, 5m range rings, and API error boundaries.

---

## Scientific Background & References

* **WASS (Waves Acquisition Stereo System):** Developed by F. Bergamasco, A. Cavallaro, and A. Benetazzo.
* **Stereo Formulation:**
  * Benetazzo, A. (2006). *Measurements of short water waves using stereo photography.* Coastal Engineering, 53(12), 1013-1027.
  * Bergamasco, F., Torsello, A., Sclavo, M., Barbariol, F., & Benetazzo, A. (2017). *WASS: An open-source pipeline for 3D stereo reconstruction of ocean waves.* Computers & Geosciences, 107, 28-38.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
