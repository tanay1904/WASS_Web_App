import os
import re
import time
import urllib.request
import pytest

selenium = pytest.importorskip("selenium", reason="selenium is required for end-to-end UI tests")
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
    time.sleep(2.5)  # Wait for initial WebGL and sequence metadata load
    yield driver
    driver.quit()


def test_01_navigation_and_tab_switching(driver):
    """Verify page title and clean switching between the 2 primary cockpit tabs."""
    assert driver.title == "WASS - 3D Ocean Wave Stereophotogrammetry Studio"

    tab_buttons = [
        ("tabPlayerBtn", "tabPlayer"),
        ("tabProcessorBtn", "tabProcessor"),
    ]

    for btn_id, pane_id in tab_buttons:
        btn = driver.find_element(By.ID, btn_id)
        assert btn.is_displayed(), f"Button #{btn_id} is not displayed"
        btn.click()
        time.sleep(0.4)

        pane = driver.find_element(By.ID, pane_id)
        assert "active" in pane.get_attribute("class"), f"Pane #{pane_id} is not active after clicking #{btn_id}"
        assert "active" in btn.get_attribute("class"), f"Button #{btn_id} is not marked active"

    # Switch back to Tab 1 (Real-Time Wave Studio & Continuous Stereo Player)
    driver.find_element(By.ID, "tabPlayerBtn").click()
    time.sleep(0.4)
    player_pane = driver.find_element(By.ID, "tabPlayer")
    assert "active" in player_pane.get_attribute("class")


def test_02_cockpit_column1_video_streams(driver):
    """Verify Column 1 (Left): Synchronized video streams, disparity map, playback controls & dataset selector."""
    driver.find_element(By.ID, "tabPlayerBtn").click()
    time.sleep(0.4)

    # 1. Video stream card exists
    video_card = driver.find_element(By.ID, "videoStreamCard")
    assert video_card.is_displayed()

    # 2. Dual stream container and players
    dual_cont = driver.find_element(By.ID, "dualStreamContainer")
    assert dual_cont.is_displayed()

    left_player = driver.find_element(By.ID, "liveVideoPlayerLeft")
    right_player = driver.find_element(By.ID, "liveVideoPlayerRight")
    assert left_player.is_displayed()
    assert right_player.is_displayed()

    # 3. Disparity preview exists and is displayed
    disp_player = driver.find_element(By.ID, "liveDispPlayer")
    assert disp_player.is_displayed()
    assert "disparity" in disp_player.get_attribute("src").lower()

    # 4. Play button toggles
    play_btn = driver.find_element(By.ID, "playBtn")
    assert "Play" in play_btn.text
    play_btn.click()
    time.sleep(0.3)
    assert "Pause" in play_btn.text
    play_btn.click()
    time.sleep(0.3)
    assert "Play" in play_btn.text

    # 5. Timeline scrubber
    slider = driver.find_element(By.ID, "timelineSlider")
    assert int(slider.get_attribute("min")) == 0
    assert int(slider.get_attribute("max")) >= 59

    # Scrub to frame 20 and back to 0
    driver.execute_script("document.getElementById('timelineSlider').value = 20; onScrub(20);")
    time.sleep(0.5)
    counter_badge = driver.find_element(By.ID, "frameCounterBadge")
    assert "20" in counter_badge.text

    driver.execute_script("document.getElementById('timelineSlider').value = 0; onScrub(0);")
    time.sleep(0.5)
    assert "00" in counter_badge.text or "0" in counter_badge.text

    # 6. Playback FPS select
    fps_select = Select(driver.find_element(By.ID, "fpsSelect"))
    fps_options = [opt.get_attribute("value") for opt in fps_select.options]
    assert "5" in fps_options and "10" in fps_options and "15" in fps_options

    # 7. Dataset selector
    dataset_select = Select(driver.find_element(By.ID, "datasetSelector"))
    ds_values = [opt.get_attribute("value") for opt in dataset_select.options]
    assert "sequence" in ds_values


def test_03_cockpit_column2_3d_wave_canvas(driver):
    """Verify Column 2 (Center): Interactive 3D sea wave surface, Three.js WebGL canvas, shading modes & 5m arcs."""
    # 1. Canvas container exists and holds Three.js WebGL canvas
    container = driver.find_element(By.ID, "canvasContainer")
    assert container.is_displayed()

    canvases = container.find_elements(By.TAG_NAME, "canvas")
    assert len(canvases) >= 1, "No Three.js WebGL canvas found inside #canvasContainer"
    canvas = canvases[0]
    assert canvas.is_displayed()
    size = canvas.size
    assert size["width"] > 300 and size["height"] > 200

    # 2. Shading modes (Surface, Wireframe, Point Cloud)
    btn_surface = driver.find_element(By.ID, "btnModeSurface")
    btn_wireframe = driver.find_element(By.ID, "btnModeWireframe")
    btn_points = driver.find_element(By.ID, "btnModePoints")

    btn_wireframe.click()
    time.sleep(0.2)
    assert "active" in btn_wireframe.get_attribute("class")

    btn_points.click()
    time.sleep(0.2)
    assert "active" in btn_points.get_attribute("class")

    btn_surface.click()
    time.sleep(0.2)
    assert "active" in btn_surface.get_attribute("class")

    # 3. 5m Arcs toggle button
    btn_arcs = driver.find_element(By.ID, "btnToggleRangeArcs")
    btn_arcs.click()
    time.sleep(0.2)
    btn_arcs.click()
    time.sleep(0.2)
    assert "active" in btn_arcs.get_attribute("class")

    # 4. Point count badge
    point_badge = driver.find_element(By.ID, "pointCountBadge")
    assert "Vertices" in point_badge.text


def test_04_cockpit_column3_telemetry_dashboard(driver):
    """Verify Column 3 (Right): Oceanographic wave telemetry cards, elevation histogram & 10-row 5m circular arcs table."""
    # 1. Telemetry card exists
    telem_card = driver.find_element(By.ID, "telemetryCard")
    assert telem_card.is_displayed()

    # 2. Metric tiles
    num_pattern = re.compile(r"[-+]?\d+\.\d+")
    tiles = {
        "statObsHeight": "Observer Altitude",
        "statHs": "Significant Wave Height (Hs)",
        "statDistRange": "Optical Distance",
        "statCrestTrough": "Extrema (Crest / Trough)",
    }
    for elem_id, name in tiles.items():
        elem = driver.find_element(By.ID, elem_id)
        assert elem.is_displayed()
        text = elem.text.strip()
        assert text, f"Tile '{name}' is empty"
        assert num_pattern.search(text), f"Tile '{name}' text '{text}' does not contain numeric value"

    # 3. Elevation distribution histogram canvas
    hist_canvas = driver.find_element(By.ID, "elevationHistCanvas")
    assert hist_canvas.is_displayed()

    # 4. 5m Circular arcs around boat table (10 rows)
    table = driver.find_element(By.ID, "tableDistanceProfile")
    assert table.is_displayed()
    rows = driver.find_elements(By.CSS_SELECTOR, "#tbodyDistanceProfile tr")
    assert len(rows) == 10, f"Expected 10 circular arc rows, found {len(rows)}"

    for idx, row in enumerate(rows):
        cells = row.find_elements(By.TAG_NAME, "td")
        assert len(cells) >= 8, f"Row {idx} has fewer than 8 columns: {len(cells)}"
        radius_txt = cells[0].text.strip()
        band_txt = cells[1].text.strip()
        mean_txt = cells[3].text.strip()
        hs_txt = cells[7].text.strip()

        assert "m" in radius_txt
        assert "-" in band_txt
        assert num_pattern.search(mean_txt)
        assert num_pattern.search(hs_txt)

    # 5. Export buttons exist
    btn_csv = driver.find_element(By.ID, "btnDownloadCsv")
    assert btn_csv.is_displayed()


def test_05_tab2_pipeline_processor(driver):
    """Verify Tab 2 (Pipeline Processor & Frame Batch Renderer): Configuration inputs, progress bar and logs."""
    driver.find_element(By.ID, "tabProcessorBtn").click()
    time.sleep(0.5)

    processor_pane = driver.find_element(By.ID, "tabProcessor")
    assert "active" in processor_pane.get_attribute("class")

    # Inputs exist
    max_frames = driver.find_element(By.ID, "maxFrames")
    assert max_frames.is_displayed()
    assert int(max_frames.get_attribute("value")) > 0

    step_input = driver.find_element(By.ID, "frameStep")
    assert step_input.is_displayed()
    assert int(step_input.get_attribute("value")) >= 1

    # Switch back to Tab 1
    driver.find_element(By.ID, "tabPlayerBtn").click()
    time.sleep(0.3)


def test_06_console_errors(driver):
    """Verify driver reports zero unhandled JavaScript errors in the browser console."""
    logs = driver.get_log("browser")
    severe_errors = [entry for entry in logs if entry.get("level") == "SEVERE"]
    assert len(severe_errors) == 0, f"Found unhandled console errors: {severe_errors}"


def test_07_capture_tab_screenshots(driver):
    """Capture full screenshots of both tabs and save into the caller artifacts directory."""
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    tabs_to_capture = [
        ("tabPlayerBtn", "cockpit_tab1_wave_studio.png"),
        ("tabProcessorBtn", "cockpit_tab2_processor.png"),
    ]

    for btn_id, filename in tabs_to_capture:
        driver.find_element(By.ID, btn_id).click()
        time.sleep(0.6)
        out_path = os.path.join(SCREENSHOT_DIR, filename)
        saved = driver.save_screenshot(out_path)
        assert saved, f"Failed to save screenshot {filename}"
        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) > 10000

    # Ensure left on Tab 1
    driver.find_element(By.ID, "tabPlayerBtn").click()
