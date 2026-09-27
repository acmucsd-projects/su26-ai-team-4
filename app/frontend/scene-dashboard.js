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

  function setSceneStatus(message = "", isError = false) {
    sceneStatusMessage.textContent = message;
    sceneStatusMessage.classList.toggle("error", isError);
  }

  function displayName(value) {
    return String(value).replace(/[-_]/g, " ");
  }

  function loadImage(url) {
    return new Promise((resolve, reject) => {
      scenePostImage.onload = () => resolve();
      scenePostImage.onerror = () => reject(new Error("The POST scene image could not be loaded."));
      scenePostImage.src = url;
      if (scenePostImage.complete) {
        if (scenePostImage.naturalWidth > 0) resolve();
        else reject(new Error("The POST scene image could not be loaded."));
      }
    });
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

  function renderBuildings(buildings) {
    if (!Array.isArray(buildings) || buildings.length === 0) throw new Error("The scene contains no packaged buildings.");
    sceneOverlay.replaceChildren();
    buildings.forEach((building) => {
      const predictedClass = building?.prediction?.predicted_class;
      if (!DAMAGE_CLASSES.includes(predictedClass)) throw new Error("A building prediction is invalid.");
      const polygon = document.createElementNS(SVG_NAMESPACE, "polygon");
      polygon.setAttribute("points", polygonPoints(building.pixel_polygon));
      polygon.setAttribute("class", "scene-building " + predictedClass);
      polygon.setAttribute("tabindex", "0");
      polygon.setAttribute("aria-label", "Building " + building.id + ", predicted " + displayName(predictedClass));
      polygon.dataset.buildingId = building.id;
      polygon.dataset.predictedClass = predictedClass;
      sceneOverlay.append(polygon);
    });
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

      const selectedScene = listBody.scenes[0];
      const sceneResponse = await fetch(DEMO_SCENES_URL + "/" + encodeURIComponent(selectedScene.scene_id));
      const scene = await sceneResponse.json().catch(() => ({}));
      if (!sceneResponse.ok) throw new Error("The selected demo scene could not be loaded.");
      if (!scene?.image?.post_url || !Number.isFinite(Number(scene?.image?.width)) || !Number.isFinite(Number(scene?.image?.height))) {
        throw new Error("The selected demo scene is incomplete.");
      }

      sceneDescription.textContent = displayName(scene.event_name) + " · " + displayName(scene.scene_id);
      sceneBuildingCount.textContent = Array.isArray(scene.buildings) ? scene.buildings.length + " buildings" : "";
      sceneBuildingCount.hidden = false;
      sceneOverlay.setAttribute("viewBox", "0 0 " + Number(scene.image.width) + " " + Number(scene.image.height));
      await loadImage(scene.image.post_url);
      renderBuildings(scene.buildings);
      sceneCanvas.hidden = false;
      setSceneStatus("Showing model predictions for the POST-disaster scene.");
    } catch (error) {
      sceneCanvas.hidden = true;
      sceneBuildingCount.hidden = true;
      sceneDescription.textContent = "Demo scene unavailable.";
      setSceneStatus(error.message || "The demo scene could not be loaded.", true);
    }
  }

  loadSceneDashboard();
})();
