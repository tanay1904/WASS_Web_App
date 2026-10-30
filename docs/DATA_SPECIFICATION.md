# WASS 3D Ocean Wave Stereophotogrammetry: Data & Coordinate Specification

## 1. Coordinate Frame Conventions

The 3D reconstructed sea surface and vessel telemetry adhere to a right-handed oceanographic coordinate system centered on the stereoscopic optical rig:

$$\begin{aligned}
\mathbf{X} &\in [-25.0, +15.0]\,\text{m} \quad &&\text{(Lateral axis: Port } < 0 < \text{Starboard)} \\
\mathbf{Y} &\in [+2.5, +50.0]\,\text{m} \quad &&\text{(Longitudinal range axis: Vessel Bow } \to \text{Far-field Sea)} \\
\mathbf{Z} &\in [-5.0, +5.0]\,\text{m} \quad &&\text{(Vertical wave elevation relative to Mean Sea Level (MSL) } = 0.000\,\text{m)}
\end{aligned}$$

```
                           +Y (Range: 50m)
                                ▲
                                │
             [50m Arc] ─────────┼───────── [50m Arc]
                                │
             [25m Arc] ─────────┼───────── [25m Arc]
                                │
             [10m Arc] ─────────┼───────── [10m Arc]
              [5m Arc] ─────────┼───────── [5m Arc]  (Y = 5.0m)
                                │  ▲ 1.000m Clearance
                       ┌────────┴────────┐
                       │   Vessel Bow    │   (Prow Stem: Y = 4.0m)
   -X (Port: -25.0m) ◄─┤  Kerala Orange  ├─► +X (Starboard: +15.0m)
    [24.45m Channel]   │      Hull       │   [14.45m Channel]
                       └────────┬────────┘
                                │
                       Rig Origin (0, 0, 0)
                          H_cam = 4.76m
```

---

## 2. Stereophotogrammetric Scale Formulation

Wave elevation $\eta(X, Y)$ is extracted from dense optical disparity residuals using physical camera geometry and 3D slant range without heuristic clamping:

### 2.1 Metric Parameters
* **Stereo Baseline ($B$):** $2.000\,\text{m}$ (rigid binocular crossbar mount).
* **Observer Camera Altitude ($H_{\text{cam}}$):** $4.760\,\text{m}$ above MSL.
* **Focal Length ($f$):** $1867.0\,\text{px}$ at $4\text{K}$ acquisition ($466.75\,\text{px}$ at scaled $960 \times 540$ processing).
* **3D Slant Range:**
  $$R_{\text{grid}}(X, Y) = \sqrt{X^2 + Y^2 + H_{\text{cam}}^2}$$

### 2.2 Physical Scale Factor
$$\text{scale\_geom}(X, Y) = \frac{R_{\text{grid}}(X, Y) \cdot H_{\text{cam}}}{f_{\text{scaled}} \cdot B}$$

$$\eta(X, Y) = -\text{residuals}(X, Y) \cdot \text{scale\_geom}(X, Y)$$

---

## 3. Vessel Bow & Water Channel Geometry

* **Vessel Prow Stem:** Apex at $(X=0.000, Y=4.000, Z=0.950)\,\text{m}$.
* **5m Nautical Arc Apex:** Radially positioned at $R = 5.000\,\text{m}$.
* **Bow Clearance:**
  $$\Delta Y_{\text{clearance}} = Y_{\text{arc\_5m}} - Y_{\text{stem}} = 5.000\,\text{m} - 4.000\,\text{m} = 1.000\,\text{m}$$
* **Bilateral Water Channels:** The water surface begins at $Y = 2.500\,\text{m}$ on both sides of the hull:
  * **Port Channel:** $X \in [-25.000, -0.550]\,\text{m}$ (Total span: $24.450\,\text{m}$).
  * **Starboard Channel:** $X \in [+0.550, +15.000]\,\text{m}$ (Total span: $14.450\,\text{m}$).

---

## 4. 10 Concentric 5m Circular Nautical Radar Arcs

The 10 concentric circular range rings provide distance-stratified wave telemetry radiating from the vessel optical origin $(0, 0, 0)$:

| Arc Radius | Range Band | Nominal Azimuth Span | Typical Vertices | Telemetry Metrics Computed |
| :---: | :---: | :---: | :---: | :--- |
| **5 m** | $[2.5, 7.5]\,\text{m}$ | $[-70^\circ, +60^\circ]$ | $\approx 204$ | $H_s$, Crest, Trough, Amp, $\mu$, $\sigma$, Azimuth |
| **10 m** | $[7.5, 12.5]\,\text{m}$ | $[-75^\circ, +65^\circ]$ | $\approx 488$ | $H_s$, Crest, Trough, Amp, $\mu$, $\sigma$, Azimuth |
| **15 m** | $[12.5, 17.5]\,\text{m}$ | $[-78^\circ, +68^\circ]$ | $\approx 733$ | $H_s$, Crest, Trough, Amp, $\mu$, $\sigma$, Azimuth |
| **20 m** | $[17.5, 22.5]\,\text{m}$ | $[-78^\circ, +68^\circ]$ | $\approx 840$ | $H_s$, Crest, Trough, Amp, $\mu$, $\sigma$, Azimuth |
| **25 m** | $[22.5, 27.5]\,\text{m}$ | $[-75^\circ, +65^\circ]$ | $\approx 922$ | $H_s$, Crest, Trough, Amp, $\mu$, $\sigma$, Azimuth |
| **30 m** | $[27.5, 32.5]\,\text{m}$ | $[-68^\circ, +55^\circ]$ | $\approx 824$ | $H_s$, Crest, Trough, Amp, $\mu$, $\sigma$, Azimuth |
| **35 m** | $[32.5, 37.5]\,\text{m}$ | $[-60^\circ, +45^\circ]$ | $\approx 785$ | $H_s$, Crest, Trough, Amp, $\mu$, $\sigma$, Azimuth |
| **40 m** | $[37.5, 42.5]\,\text{m}$ | $[-52^\circ, +35^\circ]$ | $\approx 777$ | $H_s$, Crest, Trough, Amp, $\mu$, $\sigma$, Azimuth |
| **45 m** | $[42.5, 47.5]\,\text{m}$ | $[-42^\circ, +28^\circ]$ | $\approx 763$ | $H_s$, Crest, Trough, Amp, $\mu$, $\sigma$, Azimuth |
| **50 m** | $[47.5, 52.5]\,\text{m}$ | $[-32^\circ, +20^\circ]$ | $\approx 593$ | $H_s$, Crest, Trough, Amp, $\mu$, $\sigma$, Azimuth |

### 4.1 Wave Field Metrics
* **Significant Wave Height ($H_s$):**
  $$H_s = 4 \cdot \sigma_\eta = 4 \sqrt{\frac{1}{N-1}\sum_{i=1}^N (\eta_i - \bar{\eta})^2}$$
* **Wave Amplitude:**
  $$A_{\text{wave}} = \eta_{\text{crest}} - \eta_{\text{trough}}$$

---

## 5. Export Schemas

### 5.1 RFC 4180 CSV Header (`/api/wave_analysis/export_arcs/{frame}`)
```csv
arc_radius_m,range_band,vertex_count,mean_elevation_m,peak_crest_m,deepest_trough_m,wave_amplitude_m,significant_wave_height_Hs_m,elevation_std_sigma_m,azimuth_min_deg,azimuth_max_deg,azimuth_span_deg
```

### 5.2 JSON Frame Schema (`/api/sequence/frame/{index}`)
```json
{
  "frame_index": 0,
  "total_points": 7000,
  "grid_width": 100,
  "grid_height": 70,
  "points": [
    [-25.0, 2.5, -0.312],
    [-24.596, 2.5, -0.285]
  ]
}
```

### 5.3 Circumference Points CSV Schema (`/api/wave_analysis/export_circumference/{frame}`)
Exact sea wave elevation for all **1,610 points** sampled along the circumferences of all 10 concentric nautical arcs at $1^\circ$ azimuthal increments from $\theta = -80^\circ$ to $+80^\circ$:
```csv
frame_index,arc_radius_m,azimuth_deg,x_m,y_m,wave_height_m,distance_from_vessel_m
0,5.0,-80.00,-4.9240,0.8682,-0.1245,5.0
0,5.0,-79.00,-4.9081,0.9540,-0.1189,5.0
...
0,50.0,+80.00,49.2404,8.6824,0.3412,50.0
```

### 5.4 Single-Click Full-Sequence ZIP Bundle (`/api/wave_analysis/export_all_arcs_zip`)
Packages all analytical wave products across every video frame in the active sequence into a single downloadable ZIP archive:
* `circular_arcs_points_*.csv`: 1,610-point circumference elevations per frame.
* `annotated_points_*.csv`: Classified 3D points with distance from observer and MSL elevation.
* `circular_arcs_*.csv`: RFC 4180 5m radar arc summary statistics per frame.

---

## 6. Dual Storage Modes & Memory Scalability

| Storage Mode | Video Preview Frames (`video_frame_*.jpg`, `disparity_*.png`) | 3D Wave Meshes & Telemetry (`points_*.json`, `wave_analysis_*.json`, CSVs) | Primary Use Case |
| :---: | :---: | :---: | :--- |
| **Default: Save All Frames** | **100% Permanently Retained on Disk** | **100% Permanently Retained on Disk** | Standard scientific surveys; full video scrubbing across all images and meshes. |
| **Optional: Circular Rolling Buffer** | **Rolling 300-Frame FIFO Window** (Frames older than 300 are evicted) | **100% Permanently Retained on Disk** (Zero telemetry loss) | Infinite live video feeds; prevents disk exhaustion while keeping all analytical plots. |

