(() => {
  const DEMO_SCENES_URL = "/demo-scenes";
  const DAMAGE_CLASSES = ["no-damage", "minor-damage", "major-damage", "destroyed"];
  const PREDICTION_FILTERS = ["all", "severe", ...DAMAGE_CLASSES];
  const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
  const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  const sceneDescription = document.querySelector("#scene-description");
  const sceneDashboardTitle = document.querySelector("#scene-dashboard-title");
  const sceneEventContext = document.querySelector("#scene-event-context");
  const sceneBuildingCount = document.querySelector("#scene-building-count");
  const sceneStatusMessage = document.querySelector("#scene-status-message");
  const sceneCanvas = document.querySelector("#scene-canvas");
  const sceneLoading = document.querySelector("#scene-loading");
  const sceneTooltip = document.querySelector("#scene-tooltip");
  const sceneLegend = document.querySelector(".scene-legend");
  const uncertaintyLegend = document.querySelector("#scene-uncertainty-legend");
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
  const sceneAnalysisContent = document.querySelector("#scene-analysis-content");
  const sceneAnalysisLocked = document.querySelector("#scene-analysis-locked");
  const sceneReveal = document.querySelector("#scene-reveal");
  const sceneRevealButton = document.querySelector("#scene-reveal-button");
  const sceneRevealStatus = document.querySelector("#scene-reveal-status");
  const sceneFilters = document.querySelector("#scene-filters");
  const workspaceHint = document.querySelector(".workspace-hint");
  const groupInspection = document.querySelector("#scene-group-inspection");
  const groupInspectionStatus = document.querySelector("#scene-group-inspection-status");
  const groupPrevious = document.querySelector("#scene-group-previous");
  const groupNext = document.querySelector("#scene-group-next");
  const groupClear = document.querySelector("#scene-group-clear");
  const predictionFilterButtons = document.querySelectorAll("[data-scene-filter]");
  const imageryModeButtons = document.querySelectorAll("[data-imagery-mode]");
  let selectedPolygon = null;
  let availableScenes = [];
  let currentSceneIndex = -1;
  let currentScene = null;
  let isSceneLoading = false;
  let isImageLoading = false;
  let imageryMode = "post";
  let predictionFilter = "all";
  let activeFindingGroup = null;
  let isRevealed = false;
  let isRevealing = false;
  let revealSequence = 0;

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

  function renderSceneEvidenceContext(scene) {
    const context = scene?.scene_evidence_context;
    if (!context || typeof context !== "object") {
      sceneEventContext.textContent = "";
      sceneEventContext.hidden = true;
      return;
    }
    const location = typeof context.location === "string" && context.location.trim()
      ? context.location.trim() : "";
    const dateMatch = typeof context.post_acquisition_date === "string"
      ? context.post_acquisition_date.match(/^(\d{4})-(\d{2})-\d{2}(?:T|$)/) : null;
    const month = dateMatch ? MONTH_LABELS[Number(dateMatch[2]) - 1] : null;
    const postDate = month ? "POST " + month + " " + dateMatch[1] : "";
    const scopedLocation = location && context.location_scope === "event" ? "Event region: " + location : location;
    const lines = [scopedLocation, postDate].filter(Boolean);
    sceneEventContext.textContent = lines.join(" · ");
    sceneEventContext.hidden = lines.length === 0;
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
      const isPredictionControl = ["post-predictions", "uncertainty"].includes(button.dataset.imageryMode);
      button.disabled = isSceneLoading || isImageLoading || isRevealing || !currentScene || (isPredictionControl && !isRevealed);
    });
    sceneLegend.hidden = !isRevealed || imageryMode !== "post-predictions";
    uncertaintyLegend.hidden = !isRevealed || imageryMode !== "uncertainty";
  }

  function updatePredictionFilterControls() {
    predictionFilterButtons.forEach((button) => {
      const isSelected = button.dataset.sceneFilter === predictionFilter;
      button.setAttribute("aria-pressed", String(isSelected));
      button.disabled = isSceneLoading || isRevealing || !currentScene || !isRevealed;
    });
    sceneFilters.hidden = !isRevealed;
  }

  function isPredictionMode() {
    return imageryMode === "post-predictions";
  }

  function matchesPredictionFilter(predictedClass) {
    return predictionFilter === "all"
      || (predictionFilter === "severe" && (predictedClass === "major-damage" || predictedClass === "destroyed"))
      || predictionFilter === predictedClass;
  }

  function setPredictionFilter(filter) {
    if (!PREDICTION_FILTERS.includes(filter) || !currentScene || isSceneLoading || !isRevealed || filter === predictionFilter) return;
    if (activeFindingGroup) clearFindingGroup(false);
    const selectedPredictedClass = selectedPolygon?.dataset.predictedClass;
    predictionFilter = filter;
    if (selectedPredictedClass && !matchesPredictionFilter(selectedPredictedClass)) {
      document.dispatchEvent(new Event("scene-building-filtered-out"));
    }
    updatePredictionFilterControls();
    renderBuildings(currentScene.buildings);
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
    sceneSummaryTotal.textContent = summary.total + (summary.total === 1 ? " building analyzed" : " buildings analyzed");
    DAMAGE_CLASSES.forEach((className) => {
      sceneSummaryCounts[className].textContent = String(summary.counts[className]);
    });
    sceneSummarySevere.textContent = String(summary.severe);
    sceneSummarySevereDetail.textContent = summary.counts["major-damage"] + " Major + " + summary.counts.destroyed + " Destroyed";
    sceneSummary.hidden = !isRevealed;
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
    // The overlay is withheld until the packaged assessment is revealed.
    // After reveal, neutral footprints remain interactive in PRE and POST.
    sceneOverlay.hidden = !isRevealed;
    scenePostImage.alt = imageryMode === "pre"
      ? "PRE-disaster satellite scene"
      : imageryMode === "uncertainty"
        ? "POST-disaster satellite scene with relative top-two prediction ambiguity overlay"
        : showingPredictions
        ? "POST-disaster satellite scene with model-predicted building damage overlay"
        : "POST-disaster satellite scene";
    await loadImage(imageUrlForCurrentMode());
  }

  async function setImageryMode(mode) {
    if (!["pre", "post", "post-predictions", "uncertainty"].includes(mode) || !currentScene || isSceneLoading || isImageLoading || isRevealing || (!isRevealed && ["post-predictions", "uncertainty"].includes(mode)) || mode === imageryMode) return;
    imageryMode = mode;
    isImageLoading = true;
    updateImageryControls();
    try {
      renderBuildings(currentScene.buildings);
      await showCurrentSceneImage();
      sceneCanvas.hidden = false;
      setSceneStatus(imageryMode === "uncertainty" ? "Showing relative ambiguity from the top-two model probability gap." : isPredictionMode() ? "Showing POST imagery with model predictions." : "Showing " + imageryMode.toUpperCase() + " imagery.");
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
    if (activeFindingGroup && !activeFindingGroup.buildingIds.includes(building.id)) {
      clearFindingGroup(true);
      polygon = Array.from(sceneOverlay.children).find((item) => item.dataset.buildingId === building.id) || polygon;
    }
    setSelectedPolygon(polygon);
    const selection = { scene_id: currentScene.scene_id, building, handled: false };
    const accepted = document.dispatchEvent(new CustomEvent("scene-building-selected", { detail: selection, cancelable: true }));
    if (!selection.handled || !accepted) {
      clearSelectedPolygon();
      setSceneStatus("The selected building could not be opened for inspection.", true);
      return;
    }
    setSceneStatus("Selected " + building.id + ". Its precomputed result is shown in the inspector.");
  }

  function inspectRequestedBuilding(detail) {
    if (!isRevealed || !detail || detail.scene_id !== currentScene?.scene_id || !Array.isArray(currentScene?.buildings)) return;
    const building = currentScene.buildings.find((item) => item?.id === detail.building_id);
    if (!building) return;
    if (!matchesPredictionFilter(building?.prediction?.predicted_class)) {
      predictionFilter = "all";
      updatePredictionFilterControls();
      renderBuildings(currentScene.buildings);
    }
    const polygon = Array.from(sceneOverlay.children).find((item) => item.dataset.buildingId === building.id);
    if (polygon) {
      selectBuilding(building, polygon);
      sceneCanvas.scrollIntoView?.({ block: "nearest" });
    }
  }

  document.addEventListener("scene-building-inspect-request", (event) => inspectRequestedBuilding(event.detail));

  function updateFindingGroupControls() {
    const active = Boolean(activeFindingGroup && currentScene);
    groupInspection.hidden = !active;
    if (!active) return;
    const { buildingIds, index, groupId, groupLabel } = activeFindingGroup;
    const label = groupLabel || (groupId ? "Finding group" : "Finding");
    groupInspectionStatus.textContent = `${label} · ${buildingIds.length} buildings · building ${index + 1} of ${buildingIds.length}`;
    groupPrevious.disabled = index <= 0;
    groupNext.disabled = index >= buildingIds.length - 1;
  }

  function clearFindingGroup(render = true) {
    activeFindingGroup = null;
    updateFindingGroupControls();
    if (render && currentScene) renderBuildings(currentScene.buildings);
  }

  function inspectFindingGroupMember(index) {
    if (!activeFindingGroup || !currentScene) return;
    activeFindingGroup.index = Math.max(0, Math.min(index, activeFindingGroup.buildingIds.length - 1));
    updateFindingGroupControls();
    const buildingId = activeFindingGroup.buildingIds[activeFindingGroup.index];
    const building = currentScene.buildings.find((item) => item?.id === buildingId);
    const polygon = Array.from(sceneOverlay.children).find((item) => item.dataset.buildingId === buildingId);
    if (building && polygon) selectBuilding(building, polygon);
  }

  function inspectRequestedGroup(detail) {
    if (!isRevealed || !detail || detail.scene_id !== currentScene?.scene_id || !Array.isArray(detail.building_ids)) return;
    const validIds = [...new Set(detail.building_ids)].filter((id) => currentScene.buildings.some((item) => item?.id === id));
    if (!validIds.length) return;
    if (validIds.length === 1) return inspectRequestedBuilding({ scene_id: detail.scene_id, building_id: validIds[0] });
    if (activeFindingGroup) clearFindingGroup(false);
    activeFindingGroup = {
      buildingIds: validIds,
      index: 0,
      groupId: typeof detail.group_id === "string" ? detail.group_id : "",
      groupLabel: typeof detail.group_label === "string" ? detail.group_label.slice(0, 80) : "",
    };
    if (validIds.some((id) => {
      const building = currentScene.buildings.find((item) => item?.id === id);
      return !matchesPredictionFilter(building?.prediction?.predicted_class);
    })) {
      predictionFilter = "all";
      updatePredictionFilterControls();
    }
    renderBuildings(currentScene.buildings);
    updateFindingGroupControls();
    inspectFindingGroupMember(0);
    sceneCanvas.scrollIntoView?.({ block: "nearest" });
  }

  document.addEventListener("scene-building-group-inspect-request", (event) => inspectRequestedGroup(event.detail));
  groupPrevious.addEventListener("click", () => inspectFindingGroupMember((activeFindingGroup?.index || 0) - 1));
  groupNext.addEventListener("click", () => inspectFindingGroupMember((activeFindingGroup?.index || 0) + 1));
  groupClear.addEventListener("click", () => clearFindingGroup(true));

  function polygonForCurrentMode(building) {
    return imageryMode === "pre" ? building.pre_pixel_polygon : building.post_pixel_polygon;
  }

  function polygonClassForCurrentMode(predictedClass) {
    return "scene-building " + (imageryMode === "uncertainty" ? "uncertainty" : isPredictionMode() ? predictedClass : "neutral");
  }

  function topTwoGap(prediction) {
    const values = DAMAGE_CLASSES.map((name) => Number(prediction?.probabilities?.[name])).filter(Number.isFinite).sort((a, b) => b - a);
    return values.length < 2 ? 1 : Math.max(0, Math.min(1, values[0] - values[1]));
  }

  function ambiguityFill(gap) {
    const blend = 1 - gap;
    const low = [65, 89, 118], high = [218, 123, 234];
    return "rgb(" + low.map((start, index) => Math.round(start + (high[index] - start) * blend)).join(", ") + ")";
  }

  function hideTooltip() {
    sceneTooltip.hidden = true;
    sceneTooltip.textContent = "";
  }

  function showTooltip(building) {
    if (!isRevealed) return;
    const prediction = building.prediction;
    const shortId = String(building.id).split("_").pop();
    const confidence = Number(prediction.confidence);
    const lines = ["Building " + shortId, titleCase(prediction.predicted_class) + (Number.isFinite(confidence) ? " · " + (confidence * 100).toFixed(1) + "% top-class score" : "")];
    if (imageryMode === "uncertainty") lines.push("Top-two gap: " + (topTwoGap(prediction) * 100).toFixed(1) + " points");
    else if (building.building_context?.claims?.length) lines.push("Reviewed GIS context available");
    sceneTooltip.textContent = lines.join("\n");
    sceneTooltip.hidden = false;
  }

  function renderBuildings(buildings) {
    if (!Array.isArray(buildings) || buildings.length === 0) throw new Error("The scene contains no packaged buildings.");
    const selectedBuildingId = selectedPolygon?.dataset.buildingId;
    clearSelectedPolygon();
    hideTooltip();
    sceneOverlay.replaceChildren();
    if (!isRevealed) return;
    buildings.forEach((building) => {
      const predictedClass = building?.prediction?.predicted_class;
      if (!DAMAGE_CLASSES.includes(predictedClass)) throw new Error("A building prediction is invalid.");
      if (!matchesPredictionFilter(predictedClass)) return;
      const polygon = document.createElementNS(SVG_NAMESPACE, "polygon");
      polygon.setAttribute("points", polygonPoints(polygonForCurrentMode(building)));
      const groupClass = activeFindingGroup
        ? activeFindingGroup.buildingIds.includes(building.id) ? " group-highlight" : " group-muted"
        : "";
      polygon.setAttribute("class", polygonClassForCurrentMode(predictedClass) + groupClass);
      if (imageryMode === "uncertainty") {
        const gap = topTwoGap(building.prediction);
        polygon.setAttribute("style", "--ambiguity-fill: " + ambiguityFill(gap));
        polygon.dataset.topTwoGap = String(gap);
      }
      polygon.setAttribute("tabindex", "0");
      polygon.setAttribute("role", "button");
      polygon.setAttribute("aria-pressed", "false");
      polygon.setAttribute("aria-describedby", "scene-tooltip");
      polygon.setAttribute(
        "aria-label",
        "Building " + building.id + ", model predicts " + displayName(predictedClass) +
          ", " + (Number(building.prediction.confidence) * 100).toFixed(1) + "% top-class score" +
          (imageryMode === "uncertainty" ? ", top-two gap " + (topTwoGap(building.prediction) * 100).toFixed(1) + " points" : ""),
      );
      polygon.dataset.buildingId = building.id;
      polygon.dataset.predictedClass = predictedClass;
      polygon.addEventListener("click", () => selectBuilding(building, polygon));
      polygon.addEventListener("pointerenter", () => showTooltip(building));
      polygon.addEventListener("pointerleave", hideTooltip);
      polygon.addEventListener("focus", () => showTooltip(building));
      polygon.addEventListener("blur", hideTooltip);
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
    revealSequence += 1;
    isRevealing = false;
    isRevealed = false;
    imageryMode = "post";
    predictionFilter = "all";
    clearFindingGroup(false);
    clearSelectedPolygon();
    currentScene = null;
    sceneOverlay.replaceChildren();
    sceneOverlay.hidden = true;
    hideTooltip();
    scenePostImage.removeAttribute("src");
    sceneCanvas.hidden = true;
    sceneCanvas.classList.remove("assessment-revealed");
    sceneReveal.hidden = true;
    sceneRevealButton.disabled = false;
    sceneRevealStatus.textContent = "";
    sceneAnalysisContent.hidden = true;
    sceneAnalysisLocked.hidden = false;
    workspaceHint.textContent = "Reveal the assessment to inspect buildings";
    sceneLoading.hidden = false;
    sceneEventContext.textContent = "";
    sceneEventContext.hidden = true;
    sceneDescription.textContent = "";
    sceneDescription.hidden = true;
    clearSceneSummary();
    document.dispatchEvent(new Event("scene-changed"));
  }

  async function loadSceneAt(index) {
    const selectedScene = availableScenes[index];
    if (!selectedScene || isSceneLoading) return;
    isSceneLoading = true;
    updateSceneControls();
    updateImageryControls();
    updatePredictionFilterControls();
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
      sceneDashboardTitle.textContent = sceneLabel(scene);
      sceneDescription.textContent = "";
      sceneDescription.hidden = true;
      renderSceneEvidenceContext(scene);
      sceneBuildingCount.textContent = Array.isArray(scene.buildings) ? scene.buildings.length + (scene.buildings.length === 1 ? " building" : " buildings") : "";
      sceneBuildingCount.hidden = false;
      sceneOverlay.setAttribute("viewBox", "0 0 " + Number(scene.image.width) + " " + Number(scene.image.height));
      updateSceneSummary(scene.buildings);
      renderBuildings(scene.buildings);
      await showCurrentSceneImage();
      sceneCanvas.hidden = false;
      sceneLoading.hidden = true;
      sceneReveal.hidden = false;
      setSceneStatus("");
      document.dispatchEvent(new CustomEvent("scene-loaded", { detail: { scene_id: scene.scene_id, scene } }));
    } catch (error) {
      sceneCanvas.hidden = true;
      sceneLoading.hidden = true;
      sceneBuildingCount.hidden = true;
      clearSceneSummary();
      sceneDescription.textContent = "Demo scene unavailable.";
      sceneDescription.hidden = false;
      sceneDashboardTitle.textContent = "Explore the scene";
      sceneEventContext.textContent = "";
      sceneEventContext.hidden = true;
      setSceneStatus(error.message || "The demo scene could not be loaded.", true);
    } finally {
      isSceneLoading = false;
      updateSceneControls();
      updateImageryControls();
      updatePredictionFilterControls();
    }
  }

  async function revealDamageAssessment() {
    if (!currentScene || isSceneLoading || isRevealed || isRevealing) return;
    const scene = currentScene;
    const sequence = ++revealSequence;
    const previousMode = imageryMode;
    isRevealing = true;
    sceneRevealButton.disabled = true;
    sceneRevealStatus.textContent = "Preparing precomputed model predictions…";
    updateImageryControls();
    updatePredictionFilterControls();
    const reduceMotion = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    try {
      await new Promise((resolve) => setTimeout(resolve, reduceMotion ? 0 : 650));
      if (sequence !== revealSequence || scene !== currentScene) return;
      imageryMode = "post-predictions";
      await showCurrentSceneImage();
    } catch (error) {
      if (sequence !== revealSequence || scene !== currentScene) return;
      imageryMode = previousMode;
      isRevealing = false;
      sceneRevealButton.disabled = false;
      sceneRevealStatus.textContent = "";
      updateImageryControls();
      updatePredictionFilterControls();
      setSceneStatus(error.message || "The POST scene image could not be loaded.", true);
      return;
    }
    if (sequence !== revealSequence || scene !== currentScene) return;
    isRevealing = false;
    isRevealed = true;
    sceneReveal.hidden = true;
    sceneRevealStatus.textContent = "";
    sceneAnalysisLocked.hidden = true;
    sceneAnalysisContent.hidden = false;
    workspaceHint.textContent = "Select a footprint to inspect";
    sceneSummary.hidden = false;
    sceneCanvas.classList.add("assessment-revealed");
    renderBuildings(scene.buildings);
    sceneOverlay.hidden = false;
    updateImageryControls();
    updatePredictionFilterControls();
    setSceneStatus("Showing packaged model predictions. Select a footprint to inspect its result.");
  }

  async function loadSceneDashboard() {
    try {
      const listResponse = await fetch(DEMO_SCENES_URL);
      const listBody = await listResponse.json().catch(() => ({}));
      if (!listResponse.ok) throw new Error("Available demo scenes could not be loaded.");
      if (!Array.isArray(listBody.scenes) || listBody.scenes.length === 0) {
        sceneDescription.textContent = "No precomputed demo scenes are available locally.";
        sceneDescription.hidden = false;
        sceneDashboardTitle.textContent = "Explore the scene";
        sceneLoading.hidden = true;
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
      sceneLoading.hidden = true;
      sceneBuildingCount.hidden = true;
      clearSceneSummary();
      sceneDescription.textContent = "Demo scene unavailable.";
      sceneDescription.hidden = false;
      sceneDashboardTitle.textContent = "Explore the scene";
      setSceneStatus(error.message || "The demo scene could not be loaded.", true);
    }
  }

  scenePrevious.addEventListener("click", () => loadSceneAt(currentSceneIndex - 1));
  sceneNext.addEventListener("click", () => loadSceneAt(currentSceneIndex + 1));
  sceneRevealButton.addEventListener("click", revealDamageAssessment);
  predictionFilterButtons.forEach((button) => button.addEventListener("click", () => setPredictionFilter(button.dataset.sceneFilter)));
  imageryModeButtons.forEach((button) => button.addEventListener("click", () => setImageryMode(button.dataset.imageryMode)));
  updateImageryControls();
  updatePredictionFilterControls();
  loadSceneDashboard();
})();
