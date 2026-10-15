import os
import re
import time
import urllib.request
import pytest
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

BASE_URL = "http://127.0.0.1:8080"
SCREENSHOT_DIR = r"C:\Users\tanay\.gemini\antigravity\brain\50bedeba-f832-4060-b1f8-e67903048f49"


@pytest.fixture(scope="module")
def driver():
    """Initializes headless Edge WebDriver with 1920x1080 viewport."""
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")

    driver = webdriver.Edge(options=opts)
    driver.set_window_size(1920, 1080)
    driver.get(BASE_URL)
    time.sleep(2.0)  # Wait for initial WebGL and sequence metadata load
    yield driver
    driver.quit()


def test_01_navigation_and_tab_switching(driver):
    """Verify page title and clean switching between all 4 cockpit tabs."""
    assert driver.title == "WASS - 3D Ocean Wave Stereophotogrammetry Studio"

    tab_buttons = [
        ("tabStudioBtn", "tabStudio"),
        ("tabProcessorBtn", "tabProcessor"),
        ("tabTelemetryBtn", "tabTelemetry"),
        ("tabVideoBtn", "tabVideo"),
    ]

    for btn_id, pane_id in tab_buttons:
        btn = driver.find_element(By.ID, btn_id)
        assert btn.is_displayed(), f"Button #{btn_id} is not displayed"
        btn.click()
        time.sleep(0.4)

        pane = driver.find_element(By.ID, pane_id)
        assert "active" in pane.get_attribute("class"), f"Pane #{pane_id} is not active after clicking #{btn_id}"
        assert "active" in btn.get_attribute("class"), f"Button #{btn_id} is not marked active"

    # Switch back to Tab 1 (Studio)
    driver.find_element(By.ID, "tabStudioBtn").click()
    time.sleep(0.4)
    studio_pane = driver.find_element(By.ID, "tabStudio")
    assert "active" in studio_pane.get_attribute("class")


def test_02_tab1_3d_wave_studio(driver):
    """Verify 3D Ocean Wave Studio viewport, playback, camera presets, shading, arcs & vessel mask."""
    driver.find_element(By.ID, "tabStudioBtn").click()
    time.sleep(0.5)

    # 1. Canvas #waveCanvas exists and is visible
    canvas = driver.find_element(By.ID, "waveCanvas")
    assert canvas.is_displayed(), "#waveCanvas is not visible"
    size = canvas.size
    assert size["width"] > 400 and size["height"] > 300, f"Canvas dimensions too small: {size}"

    # 2. Play button #playBtn toggles playback
    play_btn = driver.find_element(By.ID, "playBtn")
    assert "Play" in play_btn.text
    play_btn.click()
    time.sleep(0.3)
    assert "Pause" in play_btn.text
    play_btn.click()
    time.sleep(0.3)
    assert "Play" in play_btn.text

    # 3. Frame slider #frameSlider scrubs 60 frames (0 to 59) and #currentFrameLabel updates
    frame_slider = driver.find_element(By.ID, "frameSlider")
    assert int(frame_slider.get_attribute("min")) == 0
    assert int(frame_slider.get_attribute("max")) >= 59

    # Scrub to Frame 25
    driver.execute_script("document.getElementById('frameSlider').value = 25; onScrub(25);")
    time.sleep(0.6)
    frame_label = driver.find_element(By.ID, "currentFrameLabel")
    assert "25" in frame_label.text, f"Expected Frame 25, got '{frame_label.text}'"

    # Scrub back to Frame 0
    driver.execute_script("document.getElementById('frameSlider').value = 0; onScrub(0);")
    time.sleep(0.6)
    assert "00" in frame_label.text or "0" in frame_label.text

    # 4. #playbackSpeed has 0.5x, 1x, 2x, 5x
    speed_select = Select(driver.find_element(By.ID, "playbackSpeed"))
    speed_options = [opt.text.strip() for opt in speed_select.options]
    for expected_speed in ["0.5x", "1x", "2x", "5x"]:
        assert expected_speed in speed_options, f"Missing speed option {expected_speed}"
    speed_select.select_by_value("2x")
    time.sleep(0.2)
    assert speed_select.first_selected_option.text.strip() == "2x"

    # 5. Camera preset buttons (Isometric, Top-Down, Sea-Level, Close-Up) update camera position
    presets = [
        ("presetTopDown", "topdown"),
        ("presetSeaLevel", "sealevel"),
        ("presetCloseUp", "closeup"),
        ("presetIsometric", "isometric"),
    ]
    prev_pos = None
    for btn_id, preset_name in presets:
        btn = driver.find_element(By.ID, btn_id)
        btn.click()
        time.sleep(0.2)
        pos = driver.execute_script(
            "return window.camera ? [window.camera.position.x, window.camera.position.y, window.camera.position.z] : null;"
        )
        assert pos is not None, "window.camera is not defined"
        if prev_pos is not None:
            assert pos != prev_pos, f"Camera preset {preset_name} did not alter camera position"
        prev_pos = pos

    # 6. #wireframeToggle toggles wireframe
    wireframe_toggle = driver.find_element(By.ID, "wireframeToggle")
    initial_checked = wireframe_toggle.is_selected()
    driver.execute_script("arguments[0].click();", wireframe_toggle)
    time.sleep(0.2)
    assert wireframe_toggle.is_selected() != initial_checked
    driver.execute_script("arguments[0].click();", wireframe_toggle)
    time.sleep(0.2)
    assert wireframe_toggle.is_selected() == initial_checked

    # 7. #paletteSelect switches palettes (viridis, plasma, ocean, coolwarm, jet)
    palette_select = Select(driver.find_element(By.ID, "paletteSelect"))
    palette_options = [opt.get_attribute("value") for opt in palette_select.options]
    for pal in ["viridis", "plasma", "ocean", "coolwarm", "jet"]:
        assert pal in palette_options, f"Palette option {pal} missing"
    palette_select.select_by_value("plasma")
    time.sleep(0.2)
    assert palette_select.first_selected_option.get_attribute("value") == "plasma"
    palette_select.select_by_value("ocean")

    # 8. #pointSizeSlider changes point size
    pt_slider = driver.find_element(By.ID, "pointSizeSlider")
    driver.execute_script("arguments[0].value = 4.5; arguments[0].dispatchEvent(new Event('input'));", pt_slider)
    time.sleep(0.2)
    assert float(pt_slider.get_attribute("value")) == 4.5

    # 9. #arcSelector has 10 range bands (0-5m to 45-50m) and highlights arcs
    arc_select = Select(driver.find_element(By.ID, "arcSelector"))
    arc_options = [opt.get_attribute("value") for opt in arc_select.options]
    expected_bands = [
        "0-5m", "5-10m", "10-15m", "15-20m", "20-25m",
        "25-30m", "30-35m", "35-40m", "40-45m", "45-50m"
    ]
    for b in expected_bands:
        assert b in arc_options, f"Range band {b} not in #arcSelector"
    arc_select.select_by_value("25-30m")
    time.sleep(0.2)
    assert arc_select.first_selected_option.get_attribute("value") == "25-30m"
    arc_select.select_by_value("all")

    # 10. #vesselMaskToggle toggles vessel bow exclusion zone
    vessel_toggle = driver.find_element(By.ID, "vesselMaskToggle")
    init_vessel = vessel_toggle.is_selected()
    driver.execute_script("arguments[0].click();", vessel_toggle)
    time.sleep(0.2)
    assert vessel_toggle.is_selected() != init_vessel
    vessel_visible = driver.execute_script(
        "return window.vesselBowObject ? window.vesselBowObject.visible : null;"
    )
    if vessel_visible is not None:
        assert vessel_visible == vessel_toggle.is_selected()
    driver.execute_script("arguments[0].click();", vessel_toggle)
    time.sleep(0.2)
    assert vessel_toggle.is_selected() == init_vessel


def test_03_tab2_pipeline_processor(driver):
    """Verify source dropdown with required options, inputs max_frames and step, progress bar & logs."""
    driver.find_element(By.ID, "tabProcessorBtn").click()
    time.sleep(0.5)

    # 1. Source dropdown with pair1, pair2, dual, sbs, sample
    source_select = Select(driver.find_element(By.ID, "videoSource"))
    source_values = [opt.get_attribute("value") for opt in source_select.options]
    for exp_val in ["pair1", "pair2", "dual", "sbs", "sample"]:
        assert exp_val in source_values, f"Source dropdown missing value '{exp_val}'"

    # 2. Input fields max_frames and step
    max_frames_input = driver.find_element(By.ID, "max_frames")
    assert max_frames_input.is_displayed()
    assert int(max_frames_input.get_attribute("value")) > 0

    step_input = driver.find_element(By.ID, "step")
    assert step_input.is_displayed()
    assert int(step_input.get_attribute("value")) >= 1

    # 3. Progress bar #progressBar
    prog_bar = driver.find_element(By.ID, "progressBar")
    assert prog_bar.is_displayed()

    # 4. Pipeline logs #pipelineLogs
    logs = driver.find_element(By.ID, "pipelineLogs")
    assert logs.is_displayed()
    assert len(logs.text.strip()) > 0


def test_04_tab3_data_export_and_telemetry(driver):
    """Verify 6 wave statistics cards, 10-row circular arcs table, and HTTP 200 export links."""
    driver.find_element(By.ID, "tabTelemetryBtn").click()
    time.sleep(0.6)

    # 1. 6 wave statistics cards
    stat_cards = {
        "cardValHs": "Significant Wave Height (Hs)",
        "cardValMean": "Mean Elevation",
        "cardValCrest": "Peak Crest",
        "cardValTrough": "Deepest Trough",
        "cardValAmp": "Amplitude",
        "cardValVar": "Variance",
    }
    num_pattern = re.compile(r"[-+]?\d+\.\d+")

    for elem_id, name in stat_cards.items():
        card_elem = driver.find_element(By.ID, elem_id)
        assert card_elem.is_displayed(), f"Card '{name}' (#{elem_id}) not visible"
        text = card_elem.text.strip()
        assert text, f"Card '{name}' (#{elem_id}) is empty"
        assert num_pattern.search(text), f"Card '{name}' (#{elem_id}) text '{text}' does not contain numeric float"

    # 2. Circular arcs table with 10 arc rows with valid numbers
    table = driver.find_element(By.ID, "tableDistanceProfile")
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", table)
    time.sleep(0.3)
    assert table.is_displayed(), "#tableDistanceProfile is not displayed"
    rows = driver.find_elements(By.CSS_SELECTOR, "#tbodyDistanceProfile tr")
    assert len(rows) == 10, f"Expected 10 circular arc rows, found {len(rows)}"

    for idx, row in enumerate(rows):
        cells = row.find_elements(By.TAG_NAME, "td")
        assert len(cells) >= 8, f"Row {idx} has fewer than 8 columns: {len(cells)}"
        radius_txt = cells[0].text.strip()
        band_txt = cells[1].text.strip()
        vertices_txt = cells[2].text.strip()
        mean_txt = cells[3].text.strip()
        crest_txt = cells[4].text.strip()
        trough_txt = cells[5].text.strip()
        amp_txt = cells[6].text.strip()
        hs_txt = cells[7].text.strip()

        assert "m" in radius_txt, f"Row {idx} radius invalid: {radius_txt}"
        assert "-" in band_txt, f"Row {idx} band invalid: {band_txt}"
        assert vertices_txt.replace(",", "").isdigit(), f"Row {idx} vertex count invalid: {vertices_txt}"
        assert num_pattern.search(mean_txt), f"Row {idx} mean elevation invalid: {mean_txt}"
        assert num_pattern.search(crest_txt), f"Row {idx} peak crest invalid: {crest_txt}"
        assert num_pattern.search(trough_txt), f"Row {idx} deepest trough invalid: {trough_txt}"
        assert num_pattern.search(amp_txt), f"Row {idx} wave amplitude invalid: {amp_txt}"
        assert num_pattern.search(hs_txt), f"Row {idx} Hs invalid: {hs_txt}"

    # 3. CSV export button and Annotated XYZ export button links return HTTP 200
    btn_csv = driver.find_element(By.ID, "btnCsvExport")
    csv_url = btn_csv.get_attribute("href")
    assert csv_url, "Missing href on #btnCsvExport"
    req_csv = urllib.request.Request(csv_url, headers={"User-Agent": "WASS-E2E-Verifier"})
    with urllib.request.urlopen(req_csv) as resp_csv:
        assert resp_csv.status == 200, f"CSV export link {csv_url} returned {resp_csv.status}"
        content_type = resp_csv.headers.get("Content-Type", "")
        assert "csv" in content_type.lower() or "text" in content_type.lower()

    btn_xyz = driver.find_element(By.ID, "btnXyzExport")
    xyz_url = btn_xyz.get_attribute("href")
    assert xyz_url, "Missing href on #btnXyzExport"
    req_xyz = urllib.request.Request(xyz_url, headers={"User-Agent": "WASS-E2E-Verifier"})
    with urllib.request.urlopen(req_xyz) as resp_xyz:
        assert resp_xyz.status == 200, f"XYZ export link {xyz_url} returned {resp_xyz.status}"


def test_05_tab4_video_and_disparity_playback(driver):
    """Verify dual video stream container and disparity map view."""
    driver.find_element(By.ID, "tabVideoBtn").click()
    time.sleep(0.5)

    # 1. Dual stream container exists and is visible
    dual_cont = driver.find_element(By.ID, "dualStreamContainer")
    assert dual_cont.is_displayed(), "#dualStreamContainer is not displayed"

    # Left and Right video players exist
    left_player = driver.find_element(By.ID, "liveVideoPlayerLeft")
    right_player = driver.find_element(By.ID, "liveVideoPlayerRight")
    assert left_player.is_displayed()
    assert right_player.is_displayed()

    # 2. Disparity map view #liveDispPlayer exists and is displayed
    disp_player = driver.find_element(By.ID, "liveDispPlayer")
    assert disp_player.is_displayed(), "#liveDispPlayer is not displayed"
    assert "disparity" in disp_player.get_attribute("src").lower()


def test_06_console_errors(driver):
    """Verify driver reports zero unhandled JavaScript errors."""
    logs = driver.get_log("browser")
    severe_errors = [entry for entry in logs if entry.get("level") == "SEVERE"]
    assert len(severe_errors) == 0, f"Found unhandled console errors: {severe_errors}"


def test_07_capture_tab_screenshots(driver):
    """Capture full screenshots of all 4 tabs and save into the caller artifacts directory."""
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    tabs_to_capture = [
        ("tabStudioBtn", "tab1_wave_studio.png"),
        ("tabProcessorBtn", "tab2_pipeline_processor.png"),
        ("tabTelemetryBtn", "tab3_data_export_telemetry.png"),
        ("tabVideoBtn", "tab4_video_disparity.png"),
    ]

    for btn_id, filename in tabs_to_capture:
        driver.find_element(By.ID, btn_id).click()
        time.sleep(0.6)  # Give time for layouts, WebGL and images to settle
        out_path = os.path.join(SCREENSHOT_DIR, filename)
        saved = driver.save_screenshot(out_path)
        assert saved, f"Failed to save screenshot {filename}"
        assert os.path.exists(out_path), f"Screenshot file not found: {out_path}"
        assert os.path.getsize(out_path) > 10000, f"Screenshot file too small: {os.path.getsize(out_path)} bytes"

    # Also switch back to Tab 1
    driver.find_element(By.ID, "tabStudioBtn").click()
