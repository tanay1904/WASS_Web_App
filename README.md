# WASS - 3D Ocean Wave Stereophotogrammetry Studio

[![CI Validation](https://github.com/tanay1904/wass-ocean-wave-stereo/actions/workflows/ci.yml/badge.svg)](https://github.com/tanay1904/wass-ocean-wave-stereo/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Codespaces Ready](https://img.shields.io/badge/Codespaces-Ready-brightgreen.svg)](https://github.com/features/codespaces)

A real-time, interactive 3D Ocean Wave Stereophotogrammetry Web Studio and processing pipeline based on the **WASS (Waves Acquisition Stereo System)** methodology. The system ingests calibrated binocular video streams, computes dense disparity and 3D slant range ocean surface elevation, drapes concentric nautical radar range arcs, and visualizes dynamic wave kinematics at up to 10 FPS.

---

## 1. Web Studio Cockpit Overview

The primary dashboard provides a unified, zero-latency control room for 3D sea wave visualization, binocular video review, and quantitative oceanographic telemetry.

![WASS 3D Wave Studio Cockpit](docs/images/01_wave_studio_cockpit.png)

### Key Display Elements
* **Dual Synchronized Video Streams (Left):** Real-time synchronized playback of left (`Cam 0`) and right (`Cam 1`) camera views alongside the dense disparity depth field.
* **Interactive 3D Sea Wave Viewport (Center):** 7,000-vertex regularized surface mesh ($100 \times 70$ grid, 13,662 triangles) with the physical Kerala orange boat bow and 10 dynamic nautical radar range arcs.
* **Oceanographic Wave Telemetry & Distribution (Right):** Live Significant Wave Height ($H_s$), extrema crest/trough altitudes, elevation probability density histogram, and distance-stratified 5m arc breakdown table.

---

## 2. 3D Sea Wave Mesh & Nautical Radar Arcs

The 3D WebGL viewport models both the ocean wave field and the physical observing vessel with geometric precision.

![3D Wireframe Surface and Concentric 5m Nautical Arcs](docs/images/04_render_mode_wireframe.png)

### Physical & Spatial Features
* **Kerala Orange Vessel Bow:** Faithfully models a traditional wooden fishing vessel bow ($Y \in [-1.2, 4.0]\,\text{m}$) rendered in marine orange (`#ea580c`) with blue gunwales, forward stem post, and research vessel flag.
* **Bilateral Water Channels:** Water elevation begins at $Y = 2.50\,\text{m}$, allowing sea waves to flow naturally on both sides of the hull with $24.45\,\text{m}$ port and $14.45\,\text{m}$ starboard clearance.
* **10 Concentric 5m Nautical Radar Arcs:** Radiating from the vessel optical origin $(0, 0, 0)$ at radii $5\,\text{m}, 10\,\text{m}, 15\,\text{m}, \dots, 50\,\text{m}$.
* **1.000m Bow Clearance:** The vessel prow apex is situated at $Y = 4.000\,\text{m}$, providing exactly $1.000\,\text{m}$ physical clearance to the 5m radar arc apex at $Y = 5.000\,\text{m}$.
* **Surface-Draped Radar Ribbons:** Each 17cm-wide nautical arc is dynamically draped directly onto the undulating sea mesh surface at $Z_{\text{wave}} + 0.15\,\text{m}$ via bilinear interpolation.
* **Staggered Azimuth Labels:** Arc distance tags are staggered along $-14^\circ$ and $+14^\circ$ azimuths (with the 5m label offset to $-22^\circ$) to eliminate visual occlusion.

### 3D Viewport Controls
* **Render Modes:** Toggle between **Surface** (colored by elevation from Deep Navy to Seafoam Crest), **Wireframe** (topological triangle grid), and **Point Cloud** (individual 3D vertices).
* **5m Arcs Toggle:** Quickly show or hide the 10 circular nautical range rings with the **5m Arcs** toolbar button.
* **Mouse Navigation:**
  * **Left-Click + Drag:** Orbit camera around focus target $(0, 16, 0)$.
  * **Right-Click + Drag:** Pan camera laterally and vertically.
  * **Scroll Wheel:** Zoom into sea troughs or pull back for macro ocean survey.
  * **Reset View Button:** Restores default vantage point $(X=0\,\text{m}, Y=-6.5\,\text{m}, Z=6.0\,\text{m})$.

---

## 3. Synchronized Video Playback & Disparity Field

The left column contains the stereoscopic video stream synchronization and disparity inspection tools.

![Synchronized Video Playback and Dense Disparity Viewer](docs/images/05_video_disparity_playback.png)

### Playback Controls
* **Stream Selector Tabs:**
  * **Dual Streams (SBS):** Side-by-side view showing left and right video streams simultaneously.
  * **Cam 0 (Left):** Primary optical camera view.
  * **Cam 1 (Right):** Secondary stereo camera view.
  * **Dual Stereo (SBS):** Side-by-side composite stream.
* **Playback Controls:** Play / Pause toggle, Previous Frame, Next Frame, and 10 FPS playback rate indicator.
* **Interactive Timeline Slider:** Scrub through all 60 synchronized frames with instantaneous 3D mesh updating.
* **Dense Stereo Disparity Viewer:** Color-mapped disparity map ($u \in [40, 670]$ cone) showing pixel parallax across the stereo overlap region.

---

## 4. Oceanographic Telemetry & Data Export

The right column provides quantitative oceanographic wave telemetry and multiple export options for individual frames and full sequences.

![Oceanographic Wave Telemetry and CSV Export](docs/images/03_data_export_telemetry.png)

### Live Telemetry Metrics
* **Observer Altitude:** Metric camera height $H_{\text{cam}} = 4.76\,\text{m}$ above Mean Sea Level.
* **Significant Wave Height ($H_s$):** Computed oceanographically as $H_s = 4 \cdot \sigma_\eta$.
* **Optical Distance Span:** Minimum and maximum optical range (typically $2.5\,\text{m} \to 55.9\,\text{m}$, mean $\approx 29.7\,\text{m}$).
* **Elevation Extrema:** Peak crest elevation ($+2.08\,\text{m}$) and deepest trough ($-3.85\,\text{m}$) relative to Mean Sea Level ($0.00\,\text{m}$).
* **Elevation Probability Distribution:** 30-bin histogram displaying probability density function of wave heights.
* **5m Circular Arcs Telemetry Table:** Complete breakdown across all 10 range bands listing vertex count, mean elevation, crest height, trough depth, wave amplitude, significant wave height ($H_s$), and azimuth span.

---

### How to Export Data

#### 1. Exporting 5m Circular Arcs CSV (Single Frame)
Click the **Export Arcs CSV** button in the header of the 5m Arcs table (or query `/api/wave_analysis/export_arcs/{frame_id}` directly). This downloads an **RFC 4180** compliant CSV with the following 12 columns:
```csv
arc_radius_m,range_band,vertex_count,mean_elevation_m,peak_crest_m,deepest_trough_m,wave_amplitude_m,significant_wave_height_Hs_m,elevation_std_sigma_m,azimuth_min_deg,azimuth_max_deg,azimuth_span_deg
5.0,2.5 - 7.5m,204,-0.330,0.210,-1.040,1.250,1.520,0.380,-68.5,58.2,126.7
10.0,7.5 - 12.5m,488,-0.290,0.370,-1.440,1.810,2.290,0.570,-74.1,64.8,138.9
...
50.0,47.5 - 52.5m,593,0.110,2.080,-2.260,4.340,3.330,0.830,-31.2,19.8,51.0
```

#### 2. Exporting Annotated 3D Point Cloud (CSV / XYZ)
Click the **Export Annotated CSV / XYZ** button at the top of the telemetry panel. This downloads the complete $[X, Y, Z]$ vertex cloud along with computed distance from observer and elevation relative to Mean Sea Level:
```csv
x_camera_m,y_camera_m,z_camera_m,distance_from_observer_m,height_from_sea_level_m
-25.0000,2.5000,-0.3120,25.5768,-0.3120
-24.5960,2.5000,-0.2850,25.1824,-0.2850
...
```

#### 3. Exporting Full-Sequence Batch Data (All Frames)
To retrieve the entire reconstructed dataset across all 60 frames programmatically:
* **All 3D Points:** `GET /api/sequence/all_points` returns a pre-serialized JSON mapping each frame index to its 7,000 vertices $[X, Y, Z]$.
* **All Wave Telemetry:** `GET /api/sequence/all_analysis` returns the complete 60-frame time series of wave statistics and 10-bin arc telemetry.
* **Command-Line Batch Extraction:** Run the standalone analysis script to regenerate all CSV logs:
  ```bash
  python regenerate_5m_arcs.py
  ```

---

## 5. Pipeline Processor: Importing & Reconstructing Data

Tab 2 provides the batch processing engine for ingesting raw stereo video footage, setting frame quantities and stride, and triggering 3D stereophotogrammetric reconstruction.

![WASS Pipeline Processor & Frame Batch Renderer](docs/images/02_pipeline_processor.png)

### Step-by-Step Reconstruction Guide

1. **Select Tab 2:** Click **2. Pipeline Processor & Frame Batch Renderer** in the top navigation bar.
2. **Choose Input Video Stereo Pair:**
   * **GoPro Pair 1:** Pre-configured calibrated stereo footage (`GX010077` Left $\leftrightarrow$ `GX011273` Right).
   * **GoPro Pair 2:** Alternate calibrated sequence (`GX010078` Left $\leftrightarrow$ `GX011274` Right).
   * **Dual Video Upload:** Upload your own synchronized `Cam 0` and `Cam 1` MP4 video files.
   * **Side-by-Side (SBS) Upload:** Upload a single side-by-side composite stereo MP4 video.
3. **Set the Number of Frames to Reconstruct:**
   * Enter the desired number of frames in the **Frames to Reconstruct** field (e.g. `20`, `60`, `100`, `500`, `1000`).
4. **Set Frame Step / Stride:**
   * Set the extraction stride in the **Frame Step / Stride** field:
     * `1` = Consecutive frames (processes every frame, 30 FPS).
     * `2` = Alternate frames (every 2nd frame).
     * `3` = 10 FPS downsampling (standard for ocean wave temporal analysis).
     * `30` = 1 FPS time-lapse sampling.
5. **Select Reconstruction Mode:**
   * **Full WASS C++ Binaries:** Complete pipeline (`wass_prepare` $\to$ `wass_match` $\to$ `wass_autocalibrate` $\to$ `wass_stereo`).
   * **Regularized Surface Grid:** Fast metric triangulation producing a $100 \times 70$ surface mesh.
6. **Launch Processing:** Click **Start 3D Reconstruction Pipeline**. Real-time logs and stage progress will stream in the **Execution Terminal & Telemetry Logs** panel.

---

## 6. System Architecture & Directory Layout

```
.
├── .devcontainer/
│   └── devcontainer.json               # GitHub Codespaces container specification
├── .github/
│   └── workflows/
│       └── ci.yml                      # Automated CI verification suite
├── docs/
│   ├── DATA_SPECIFICATION.md           # Oceanographic coordinates & mathematical specification
│   └── images/                         # Documentation visual walkthrough assets
├── tests/
│   ├── test_wave_math.py               # Unit tests for physical stereo math & 5m arcs
│   └── test_api_endpoints.py           # Integration tests for FastAPI endpoints & RFC 4180 CSV
├── wass_webapp/
│   ├── app.py                          # High-performance FastAPI backend application
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

## 7. Quickstart

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

## 8. REST API Endpoints

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
| `POST` | `/api/run` | Triggers stereo video batch reconstruction pipeline |

---

## 9. Running the Automated Test Suite

Run the full automated test suite covering unit math, geometry verification, and FastAPI endpoints:

```bash
python -m pytest tests/ -v
```

All 12 test modules evaluate metric scale formulas, bow clearances, 5m range rings, and API error boundaries.

---

## 10. Scientific Background & References

* **WASS (Waves Acquisition Stereo System):** Developed by F. Bergamasco, A. Cavallaro, and A. Benetazzo.
* **Stereo Formulation:**
  * Benetazzo, A. (2006). *Measurements of short water waves using stereo photography.* Coastal Engineering, 53(12), 1013-1027.
  * Bergamasco, F., Torsello, A., Sclavo, M., Barbariol, F., & Benetazzo, A. (2017). *WASS: An open-source pipeline for 3D stereo reconstruction of ocean waves.* Computers & Geosciences, 107, 28-38.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
