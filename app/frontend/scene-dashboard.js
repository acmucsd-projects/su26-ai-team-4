(() => {
  const DEMO_SCENES_URL = "/demo-scenes";
  const DAMAGE_CLASSES = ["no-damage", "minor-damage", "major-damage", "destroyed"];
  const SVG_NAMESPACE = "http://www.w3.org/2000/svg";

  const sceneDescription = document.querySelector("#scene-description");
  const sceneBuildingCount = document.querySelector("#scene-building-count");
  const sceneStatusMessage = document.querySelector("#scene-status-message");
  const sceneCanvas = document.querySelector("#scene-canvas");
  const scenePostImage = document.querySelector("#scene-post-image");
  const sceneOverlay = document.querySelector("#scene-overlay");
  const sceneSelector = document.querySelector("#scene-selector");
  const scenePrevious = document.querySelector("#scene-previous");
  const sceneCurrent = document.querySelector("#scene-current");
  const sceneNext = document.querySelector("#scene-next");
  const sceneSummary = document.querySelector("#scene-summary");
  const sceneSummaryTotal = document.querySelector("#scene-summary-total");
  const sceneSummaryCounts = Object.fromEntries(DAMAGE_CLASSES.map((className) => [
    className,
    document.querySelector("#scene-summary-" + className),
  ]));
  const sceneSummarySevere = document.querySelector("#scene-summary-severe");
  const sceneSummarySevereDetail = document.querySelector("#scene-summary-severe-detail");
  const imageryModeButtons = document.querySelectorAll("[data-imagery-mode]");
  let selectedPolygon = null;
  let availableScenes = [];
  let currentSceneIndex = -1;
  let currentScene = null;
  let isSceneLoading = false;
  let isImageLoading = false;
  let imageryMode = "post-predictions";

  function setSceneStatus(message = "", isError = false) {
    sceneStatusMessage.textContent = message;
    sceneStatusMessage.classList.toggle("error", isError);
  }

  function displayName(value) {
    return String(value).replace(/[-_]/g, " ");
  }

  function titleCase(value) {
    return displayName(value).split(" ").filter(Boolean).map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
  }

  function sceneLabel(scene) {
    const match = String(scene.scene_id || "").match(/^(.*)_(\d+)$/);
    const eventName = titleCase(scene.event_name || match?.[1] || scene.scene_id);
    return match ? eventName + " — Scene " + Number(match[2]) : eventName;
  }

  function updateSceneControls() {
    if (availableScenes.length === 0) {
      sceneSelector.hidden = true;
      return;
    }
    sceneSelector.hidden = availableScenes.length < 2;
    const scene = availableScenes[currentSceneIndex];
    sceneCurrent.textContent = scene ? sceneLabel(scene) : "Loading scene…";
    scenePrevious.disabled = isSceneLoading || currentSceneIndex <= 0;
    sceneNext.disabled = isSceneLoading || currentSceneIndex >= availableScenes.length - 1;
  }

  function updateImageryControls() {
    imageryModeButtons.forEach((button) => {
      const isSelected = button.dataset.imageryMode === imageryMode;
      button.setAttribute("aria-pressed", String(isSelected));
      button.disabled = isSceneLoading || isImageLoading || !currentScene;
    });
  }

  function isPredictionMode() {
    return imageryMode === "post-predictions";
  }

  function summarizePredictions(buildings) {
    if (!Array.isArray(buildings) || buildings.length === 0) throw new Error("The scene contains no packaged buildings.");
    const counts = Object.fromEntries(DAMAGE_CLASSES.map((className) => [className, 0]));
    buildings.forEach((building) => {
      const predictedClass = building?.prediction?.predicted_class;
      if (!DAMAGE_CLASSES.includes(predictedClass)) throw new Error("A building prediction is invalid.");
      counts[predictedClass] += 1;
    });
    return {
      total: buildings.length,
      counts,
      severe: counts["major-damage"] + counts.destroyed,
    };
  }

  function updateSceneSummary(buildings) {
    const summary = summarizePredictions(buildings);
    sceneSummaryTotal.textContent = summary.total + " buildings analyzed";
    DAMAGE_CLASSES.forEach((className) => {
      sceneSummaryCounts[className].textContent = String(summary.counts[className]);
    });
    sceneSummarySevere.textContent = String(summary.severe);
    sceneSummarySevereDetail.textContent = summary.counts["major-damage"] + " Major + " + summary.counts.destroyed + " Destroyed";
    sceneSummary.hidden = false;
  }

  function clearSceneSummary() {
    sceneSummary.hidden = true;
    sceneSummaryTotal.textContent = "";
    DAMAGE_CLASSES.forEach((className) => {
      sceneSummaryCounts[className].textContent = "";
    });
    sceneSummarySevere.textContent = "";
    sceneSummarySevereDetail.textContent = "";
  }

  function imageUrlForCurrentMode() {
    return imageryMode === "pre" ? currentScene.image.pre_url : currentScene.image.post_url;
  }

  function loadImage(url) {
    return new Promise((resolve, reject) => {
      scenePostImage.onload = () => resolve();
      scenePostImage.onerror = () => reject(new Error("The selected scene image could not be loaded."));
      scenePostImage.src = url;
      if (scenePostImage.complete) {
        if (scenePostImage.naturalWidth > 0) resolve();
        else reject(new Error("The selected scene image could not be loaded."));
      }
    });
  }

  async function showCurrentSceneImage() {
    const showingPredictions = isPredictionMode();
    // Footprints remain available in every imagery mode. Their geometry and
    // styling are selected explicitly in renderBuildings rather than relying
    // on a hidden overlay whose previous damage classes could remain visible.
    sceneOverlay.hidden = false;
    scenePostImage.alt = imageryMode === "pre"
      ? "PRE-disaster satellite scene"
      : showingPredictions
        ? "POST-disaster satellite scene with model-predicted building damage overlay"
        : "POST-disaster satellite scene";
    await loadImage(imageUrlForCurrentMode());
  }

  async function setImageryMode(mode) {
    if (!currentScene || isSceneLoading || isImageLoading || mode === imageryMode) return;
    imageryMode = mode;
    isImageLoading = true;
    updateImageryControls();
    try {
      renderBuildings(currentScene.buildings);
      await showCurrentSceneImage();
      sceneCanvas.hidden = false;
      setSceneStatus(isPredictionMode() ? "Showing POST imagery with model predictions." : "Showing " + imageryMode.toUpperCase() + " imagery.");
    } catch (error) {
      setSceneStatus(error.message || "The selected scene image could not be loaded.", true);
    } finally {
      isImageLoading = false;
      updateImageryControls();
    }
  }

  function polygonPoints(points) {
    if (!Array.isArray(points) || points.length < 3) throw new Error("A building polygon is missing.");
    return points.map((point) => {
      if (!Array.isArray(point) || point.length !== 2 || !Number.isFinite(Number(point[0])) || !Number.isFinite(Number(point[1]))) {
        throw new Error("A building polygon is invalid.");
      }
      return Number(point[0]) + "," + Number(point[1]);
    }).join(" ");
  }

  function setSelectedPolygon(polygon) {
    if (selectedPolygon) {
      selectedPolygon.classList.remove("selected");
      selectedPolygon.setAttribute("aria-pressed", "false");
    }
    selectedPolygon = polygon;
    selectedPolygon.classList.add("selected");
    selectedPolygon.setAttribute("aria-pressed", "true");
  }

  function clearSelectedPolygon() {
    if (!selectedPolygon) return;
    selectedPolygon.classList.remove("selected");
    selectedPolygon.setAttribute("aria-pressed", "false");
    selectedPolygon = null;
  }

  document.addEventListener("scene-building-clear", clearSelectedPolygon);

  function selectBuilding(building, polygon) {
    setSelectedPolygon(polygon);
    const selection = { building, handled: false };
    const accepted = document.dispatchEvent(new CustomEvent("scene-building-selected", { detail: selection, cancelable: true }));
    if (!selection.handled || !accepted) {
      clearSelectedPolygon();
      setSceneStatus("The selected building could not be opened for inspection.", true);
      return;
    }
    setSceneStatus("Selected " + building.id + ". Its precomputed result is shown below.");
  }

  function polygonForCurrentMode(building) {
    return imageryMode === "pre" ? building.pre_pixel_polygon : building.post_pixel_polygon;
  }

  function polygonClassForCurrentMode(predictedClass) {
    return "scene-building " + (isPredictionMode() ? predictedClass : "neutral");
  }

  function renderBuildings(buildings) {
    if (!Array.isArray(buildings) || buildings.length === 0) throw new Error("The scene contains no packaged buildings.");
    const selectedBuildingId = selectedPolygon?.dataset.buildingId;
    clearSelectedPolygon();
    sceneOverlay.replaceChildren();
    buildings.forEach((building) => {
      const predictedClass = building?.prediction?.predicted_class;
      if (!DAMAGE_CLASSES.includes(predictedClass)) throw new Error("A building prediction is invalid.");
      const polygon = document.createElementNS(SVG_NAMESPACE, "polygon");
      polygon.setAttribute("points", polygonPoints(polygonForCurrentMode(building)));
      polygon.setAttribute("class", polygonClassForCurrentMode(predictedClass));
      polygon.setAttribute("tabindex", "0");
      polygon.setAttribute("role", "button");
      polygon.setAttribute("aria-pressed", "false");
      polygon.setAttribute(
        "aria-label",
        isPredictionMode()
          ? "Building " + building.id + ", predicted " + displayName(predictedClass)
          : "Building " + building.id,
      );
      polygon.dataset.buildingId = building.id;
      polygon.dataset.predictedClass = predictedClass;
      polygon.addEventListener("click", () => selectBuilding(building, polygon));
      polygon.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectBuilding(building, polygon);
        }
      });
      sceneOverlay.append(polygon);
      if (building.id === selectedBuildingId) setSelectedPolygon(polygon);
    });
  }

  function clearSceneForLoad() {
    clearSelectedPolygon();
    currentScene = null;
    sceneOverlay.replaceChildren();
    sceneOverlay.hidden = true;
    scenePostImage.removeAttribute("src");
    sceneCanvas.hidden = true;
    clearSceneSummary();
    document.dispatchEvent(new Event("scene-changed"));
  }

  async function loadSceneAt(index) {
    const selectedScene = availableScenes[index];
    if (!selectedScene || isSceneLoading) return;
    isSceneLoading = true;
    updateSceneControls();
    updateImageryControls();
    clearSceneForLoad();
    try {
      const sceneResponse = await fetch(DEMO_SCENES_URL + "/" + encodeURIComponent(selectedScene.scene_id));
      const scene = await sceneResponse.json().catch(() => ({}));
      if (!sceneResponse.ok) throw new Error("The selected demo scene could not be loaded.");
      if (scene?.scene_id !== selectedScene.scene_id || !scene?.image?.pre_url || !scene?.image?.post_url || !Number.isFinite(Number(scene?.image?.width)) || !Number.isFinite(Number(scene?.image?.height))) {
        throw new Error("The selected demo scene is incomplete.");
      }

      currentSceneIndex = index;
      currentScene = scene;
      sceneDescription.textContent = sceneLabel(scene);
      sceneBuildingCount.textContent = Array.isArray(scene.buildings) ? scene.buildings.length + " buildings" : "";
      sceneBuildingCount.hidden = false;
      sceneOverlay.setAttribute("viewBox", "0 0 " + Number(scene.image.width) + " " + Number(scene.image.height));
      updateSceneSummary(scene.buildings);
      renderBuildings(scene.buildings);
      await showCurrentSceneImage();
      sceneCanvas.hidden = false;
      setSceneStatus(isPredictionMode() ? "Showing POST imagery with model predictions." : "Showing " + imageryMode.toUpperCase() + " imagery.");
    } catch (error) {
      sceneCanvas.hidden = true;
      sceneBuildingCount.hidden = true;
      clearSceneSummary();
      sceneDescription.textContent = "Demo scene unavailable.";
      setSceneStatus(error.message || "The demo scene could not be loaded.", true);
    } finally {
      isSceneLoading = false;
      updateSceneControls();
      updateImageryControls();
    }
  }

  async function loadSceneDashboard() {
    try {
      const listResponse = await fetch(DEMO_SCENES_URL);
      const listBody = await listResponse.json().catch(() => ({}));
      if (!listResponse.ok) throw new Error("Available demo scenes could not be loaded.");
      if (!Array.isArray(listBody.scenes) || listBody.scenes.length === 0) {
        sceneDescription.textContent = "No precomputed demo scenes are available locally.";
        setSceneStatus("You can still test a single matched building pair below.");
        return;
      }
      availableScenes = listBody.scenes.filter((scene) => typeof scene?.scene_id === "string" && scene.scene_id);
      if (availableScenes.length === 0) throw new Error("No usable demo scenes are available.");
      currentSceneIndex = 0;
      updateSceneControls();
      await loadSceneAt(currentSceneIndex);
    } catch (error) {
      sceneCanvas.hidden = true;
      sceneBuildingCount.hidden = true;
      clearSceneSummary();
      sceneDescription.textContent = "Demo scene unavailable.";
      setSceneStatus(error.message || "The demo scene could not be loaded.", true);
    }
  }

  scenePrevious.addEventListener("click", () => loadSceneAt(currentSceneIndex - 1));
  sceneNext.addEventListener("click", () => loadSceneAt(currentSceneIndex + 1));
  imageryModeButtons.forEach((button) => button.addEventListener("click", () => setImageryMode(button.dataset.imageryMode)));
  updateImageryControls();
  loadSceneDashboard();
})();
