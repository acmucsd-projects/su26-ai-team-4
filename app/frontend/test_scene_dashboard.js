const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const DAMAGE_CLASSES = ["no-damage", "minor-damage", "major-damage", "destroyed"];

class FakeElement {
  constructor() {
    this.attributes = new Map();
    this.children = [];
    this.listeners = new Map();
    this.classList = {
      add: (...classes) => classes.forEach((className) => this._classes.add(className)),
      remove: (...classes) => classes.forEach((className) => this._classes.delete(className)),
      toggle: (className, force) => {
        if (force === true || (force === undefined && !this._classes.has(className))) this._classes.add(className);
        else this._classes.delete(className);
      },
      contains: (className) => this._classes.has(className),
    };
    this._classes = new Set();
    this.dataset = {};
    this.hidden = false;
    this.complete = false;
    this.naturalWidth = 0;
    this.textContent = "";
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === "class") this._classes = new Set(String(value).split(/\s+/).filter(Boolean));
  }

  getAttribute(name) {
    return this.attributes.get(name);
  }

  removeAttribute(name) {
    this.attributes.delete(name);
    if (name === "src") this._src = undefined;
  }

  replaceChildren() {
    this.children = [];
  }

  append(child) {
    this.children.push(child);
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  trigger(type, event = {}) {
    return this.listeners.get(type)?.({ preventDefault() {}, ...event });
  }

  set src(value) {
    this._src = value;
    this.complete = true;
    this.naturalWidth = 1024;
    if (this.onload) this.onload();
  }

  get src() {
    return this._src;
  }
}

function createDocument() {
  const elements = new Map([
    ["#scene-description", new FakeElement()],
    ["#scene-event-context", new FakeElement()],
    ["#scene-building-count", new FakeElement()],
    ["#scene-status-message", new FakeElement()],
    ["#scene-canvas", new FakeElement()],
    ["#scene-post-image", new FakeElement()],
    ["#scene-overlay", new FakeElement()],
    ["#scene-selector", new FakeElement()],
    ["#scene-previous", new FakeElement()],
    ["#scene-current", new FakeElement()],
    ["#scene-next", new FakeElement()],
    ["#scene-summary", new FakeElement()],
    ["#scene-summary-total", new FakeElement()],
    ["#scene-summary-no-damage", new FakeElement()],
    ["#scene-summary-minor-damage", new FakeElement()],
    ["#scene-summary-major-damage", new FakeElement()],
    ["#scene-summary-destroyed", new FakeElement()],
    ["#scene-summary-severe", new FakeElement()],
    ["#scene-summary-severe-detail", new FakeElement()],
    ["#scene-group-inspection", new FakeElement()],
    ["#scene-group-inspection-status", new FakeElement()],
    ["#scene-group-previous", new FakeElement()],
    ["#scene-group-next", new FakeElement()],
    ["#scene-group-clear", new FakeElement()],
  ]);
  const imageryButtons = ["pre", "post", "post-predictions"].map((mode) => {
    const button = new FakeElement();
    button.dataset.imageryMode = mode;
    return button;
  });
  const filterButtons = ["all", "severe", ...DAMAGE_CLASSES].map((filter) => {
    const button = new FakeElement();
    button.dataset.sceneFilter = filter;
    return button;
  });
  const listeners = new Map();
  return {
    elements,
    querySelector(selector) {
      return elements.get(selector);
    },
    createElementNS() {
      return new FakeElement();
    },
    querySelectorAll(selector) {
      if (selector === "[data-imagery-mode]") return imageryButtons;
      if (selector === "[data-scene-filter]") return filterButtons;
      return [];
    },
    addEventListener(type, listener) {
      listeners.set(type, listener);
    },
    dispatchEvent(event) {
      listeners.get(event.type)?.(event);
      return !event.defaultPrevented;
    },
  };
}

async function main() {
  const document = createDocument();
  const selections = [];
  const selectedSceneIds = [];
  let filteredOutSelections = 0;
  document.addEventListener("scene-building-selected", (event) => {
    event.detail.handled = true;
    if (event.detail.building) {
      const building = event.detail.building;
      selections.push(building);
      selectedSceneIds.push(event.detail.scene_id);
    } else event.preventDefault();
  });
  document.addEventListener("scene-building-filtered-out", () => { filteredOutSelections += 1; });
  const sceneSummaries = [
    ["hurricane-michael_00000247", "hurricane-michael", 177],
    ["hurricane-harvey_00000177", "hurricane-harvey", 76],
    ["hurricane-matthew_00000060", "hurricane-matthew", 75],
    ["hurricane-florence_00000459", "hurricane-florence", 56],
    ["palu-tsunami_00000065", "palu-tsunami", 129],
    ["santa-rosa-wildfire_00000014", "santa-rosa-wildfire", 49],
    ["socal-fire_00000663", "socal-fire", 48],
  ].map(([scene_id, event_name, buildingCount]) => ({ scene_id, event_name, building_count: buildingCount }));
  const scenes = new Map(sceneSummaries.map((summary) => {
    const buildings = Array.from({ length: summary.building_count }, (_, index) => ({
      id: `${summary.scene_id}_b${index.toString().padStart(4, "0")}`,
      pre_pixel_polygon: [[index + 100, 10], [index + 101, 10], [index + 101, 11]],
      post_pixel_polygon: [[index, 0], [index + 1, 0], [index + 1, 1]],
      crops: { pre_url: `/demo-scenes/${summary.scene_id}/crops/${index}-pre.png`, post_url: `/demo-scenes/${summary.scene_id}/crops/${index}-post.png` },
      prediction: {
        predicted_class: DAMAGE_CLASSES[index % DAMAGE_CLASSES.length],
        confidence: 0.8,
        probabilities: Object.fromEntries(DAMAGE_CLASSES.map((className) => [className, className === DAMAGE_CLASSES[index % DAMAGE_CLASSES.length] ? 0.8 : 1 / 15])),
      },
    }));
    return [summary.scene_id, { ...summary, image: { width: 1024, height: 1024, pre_url: `/demo-scenes/${summary.scene_id}/pre.png`, post_url: `/demo-scenes/${summary.scene_id}/post.png` }, buildings }];
  }));
  const firstScene = scenes.get(sceneSummaries[0].scene_id);
  const secondScene = scenes.get(sceneSummaries[1].scene_id);
  const fetchCalls = [];
  const fetch = async (url) => {
    fetchCalls.push(url);
    if (url === "/demo-scenes") return { ok: true, json: async () => ({ scenes: sceneSummaries }) };
    const sceneId = url.replace("/demo-scenes/", "");
    if (scenes.has(sceneId)) return { ok: true, json: async () => scenes.get(sceneId) };
    throw new Error(`Unexpected fetch URL: ${url}`);
  };
  const source = fs.readFileSync(path.join(__dirname, "scene-dashboard.js"), "utf8");
  class CustomEvent {
    constructor(type, options = {}) {
      this.type = type;
      this.detail = options.detail;
      this.cancelable = options.cancelable;
      this.defaultPrevented = false;
    }
    preventDefault() { if (this.cancelable) this.defaultPrevented = true; }
  }
  vm.runInNewContext(source, { Array, CustomEvent, Error, Event: class { constructor(type) { this.type = type; } }, Number, Promise, document, fetch });
  await new Promise((resolve) => setTimeout(resolve, 0));

  const canvas = document.elements.get("#scene-canvas");
  const image = document.elements.get("#scene-post-image");
  const overlay = document.elements.get("#scene-overlay");
  assert.deepEqual(fetchCalls, ["/demo-scenes", "/demo-scenes/hurricane-michael_00000247"]);
  assert.equal(canvas.hidden, false);
  assert.equal(image.src, firstScene.image.post_url);
  assert.equal(overlay.getAttribute("viewBox"), "0 0 1024 1024");
  assert.equal(overlay.children.length, 177);
  assert.equal(document.elements.get("#scene-selector").hidden, false);
  assert.equal(document.elements.get("#scene-current").textContent, "Hurricane Michael — Scene 247");
  assert.equal(document.elements.get("#scene-previous").disabled, true);
  assert.equal(document.elements.get("#scene-next").disabled, false);
  assert.equal(document.elements.get("#scene-summary").hidden, false);
  assert.equal(document.elements.get("#scene-summary-total").textContent, "177 buildings analyzed");
  assert.equal(document.elements.get("#scene-summary-no-damage").textContent, "45");
  assert.equal(document.elements.get("#scene-summary-minor-damage").textContent, "44");
  assert.equal(document.elements.get("#scene-summary-major-damage").textContent, "44");
  assert.equal(document.elements.get("#scene-summary-destroyed").textContent, "44");
  assert.equal(document.elements.get("#scene-summary-severe").textContent, "88");
  assert.equal(document.elements.get("#scene-summary-severe-detail").textContent, "44 Major + 44 Destroyed");
  const imageryButtons = document.querySelectorAll("[data-imagery-mode]");
  assert.equal(imageryButtons[2].getAttribute("aria-pressed"), "true");
  assert.equal(overlay.hidden, false);
  assert.deepEqual(new Set(overlay.children.map((polygon) => polygon.getAttribute("class").replace("scene-building ", ""))), new Set(DAMAGE_CLASSES));
  overlay.children.forEach((polygon) => {
    assert.match(polygon.getAttribute("class"), /^scene-building (no-damage|minor-damage|major-damage|destroyed)$/);
    assert.ok(polygon.getAttribute("points"));
  });
  const filterButtons = document.querySelectorAll("[data-scene-filter]");
  const filterButton = (filter) => filterButtons.find((button) => button.dataset.sceneFilter === filter);
  assert.equal(filterButton("all").getAttribute("aria-pressed"), "true");
  overlay.children[0].trigger("click");
  assert.equal(overlay.children[0].classList.contains("selected"), true);
  const fetchCountBeforeFiltering = fetchCalls.length;
  await filterButton("severe").trigger("click");
  assert.equal(overlay.children.length, 88);
  assert.deepEqual(new Set(overlay.children.map((polygon) => polygon.dataset.predictedClass)), new Set(["major-damage", "destroyed"]));
  assert.equal(filteredOutSelections, 1);
  assert.equal(filterButton("severe").getAttribute("aria-pressed"), "true");
  assert.equal(document.elements.get("#scene-summary-total").textContent, "177 buildings analyzed");
  assert.equal(document.elements.get("#scene-summary-severe").textContent, "88");
  assert.equal(fetchCalls.length, fetchCountBeforeFiltering);
  for (const [filter, expectedCount] of [["no-damage", 45], ["minor-damage", 44], ["major-damage", 44], ["destroyed", 44]]) {
    await filterButton(filter).trigger("click");
    assert.equal(overlay.children.length, expectedCount);
    assert.deepEqual(new Set(overlay.children.map((polygon) => polygon.dataset.predictedClass)), new Set([filter]));
  }
  await filterButton("all").trigger("click");
  assert.equal(overlay.children.length, 177);
  const majorPolygon = overlay.children.find((polygon) => polygon.dataset.predictedClass === "major-damage");
  majorPolygon.trigger("click");
  await filterButton("severe").trigger("click");
  assert.equal(overlay.children.length, 88);
  assert.equal(overlay.children.some((polygon) => polygon.classList.contains("selected") && polygon.dataset.buildingId === majorPolygon.dataset.buildingId), true);
  await imageryButtons[0].trigger("click");
  assert.equal(image.src, firstScene.image.pre_url);
  assert.equal(overlay.children.length, 88);
  assert.equal(overlay.children[0].getAttribute("class"), "scene-building neutral");
  await imageryButtons[1].trigger("click");
  assert.equal(image.src, firstScene.image.post_url);
  assert.equal(overlay.children.length, 88);
  assert.equal(overlay.children[0].getAttribute("class"), "scene-building neutral");
  await imageryButtons[2].trigger("click");
  assert.equal(image.src, firstScene.image.post_url);
  assert.equal(overlay.children.length, 88);
  assert.deepEqual(new Set(overlay.children.map((polygon) => polygon.dataset.predictedClass)), new Set(["major-damage", "destroyed"]));
  assert.equal(fetchCalls.length, fetchCountBeforeFiltering);
  await filterButton("all").trigger("click");
  assert.equal(overlay.children.length, 177);
  await imageryButtons[0].trigger("click");
  assert.equal(image.src, firstScene.image.pre_url);
  assert.equal(overlay.hidden, false);
  assert.equal(overlay.children[0].getAttribute("points"), "100,10 101,10 101,11");
  assert.equal(overlay.children[0].getAttribute("class"), "scene-building neutral");
  await document.elements.get("#scene-next").trigger("click");
  assert.equal(image.src, secondScene.image.pre_url);
  assert.equal(overlay.hidden, false);
  assert.equal(overlay.children[0].getAttribute("points"), "100,10 101,10 101,11");
  assert.equal(overlay.children[0].getAttribute("class"), "scene-building neutral");
  assert.equal(document.elements.get("#scene-current").textContent, "Hurricane Harvey — Scene 177");

  assert.equal(document.elements.get("#scene-summary-total").textContent, "76 buildings analyzed");
  assert.equal(document.elements.get("#scene-summary-no-damage").textContent, "19");
  assert.equal(document.elements.get("#scene-summary-minor-damage").textContent, "19");
  assert.equal(document.elements.get("#scene-summary-major-damage").textContent, "19");
  assert.equal(document.elements.get("#scene-summary-destroyed").textContent, "19");
  assert.equal(document.elements.get("#scene-summary-severe").textContent, "38");
  assert.equal(document.elements.get("#scene-summary-severe-detail").textContent, "19 Major + 19 Destroyed");

  await imageryButtons[1].trigger("click");
  assert.equal(image.src, secondScene.image.post_url);
  assert.equal(overlay.hidden, false);
  assert.equal(overlay.children[0].getAttribute("points"), "0,0 1,0 1,1");
  assert.equal(overlay.children[0].getAttribute("class"), "scene-building neutral");
  await imageryButtons[2].trigger("click");
  assert.equal(image.src, secondScene.image.post_url);
  assert.equal(overlay.hidden, false);
  assert.equal(overlay.children[0].getAttribute("points"), "0,0 1,0 1,1");
  assert.equal(overlay.children[0].getAttribute("class"), "scene-building no-damage");
  overlay.children[0].trigger("click");
  assert.equal(selections.length, 3);
  assert.equal(selections[2].id, secondScene.buildings[0].id);
  assert.equal(selectedSceneIds[2], secondScene.scene_id);
  assert.equal(overlay.children[0].classList.contains("selected"), true);

  assert.deepEqual(fetchCalls, ["/demo-scenes", "/demo-scenes/hurricane-michael_00000247", "/demo-scenes/hurricane-harvey_00000177"]);
  assert.equal(overlay.children.length, 76);
  assert.equal(document.elements.get("#scene-building-count").textContent, "76 buildings");
  assert.equal(document.elements.get("#scene-previous").disabled, false);

  for (let index = 2; index < sceneSummaries.length; index += 1) {
    await document.elements.get("#scene-next").trigger("click");
  }
  assert.equal(fetchCalls.length, sceneSummaries.length + 1);
  assert.equal(document.elements.get("#scene-current").textContent, "Socal Fire — Scene 663");
  assert.equal(image.src, "/demo-scenes/socal-fire_00000663/post.png");
  assert.equal(overlay.hidden, false);
  assert.equal(document.elements.get("#scene-next").disabled, true);
  const groupIds = ["socal-fire_00000663_b0001", "socal-fire_00000663_b0002", "socal-fire_00000663_b0003"];
  document.dispatchEvent(new CustomEvent("scene-building-group-inspect-request", { detail: {
    scene_id: "socal-fire_00000663", building_ids: groupIds, group_id: "severe-demo-group",
  } }));
  assert.equal(document.elements.get("#scene-group-inspection").hidden, false);
  assert.equal(document.elements.get("#scene-group-inspection-status").textContent, "Finding group · 3 buildings · building 1 of 3");
  assert.equal(document.elements.get("#scene-current").textContent, "Socal Fire — Scene 663");
  assert.equal(filterButton("all").getAttribute("aria-pressed"), "true");
  assert.deepEqual(overlay.children.filter((polygon) => polygon.classList.contains("group-highlight")).map((polygon) => polygon.dataset.buildingId), groupIds);
  assert.equal(overlay.children.find((polygon) => polygon.dataset.buildingId === groupIds[0]).classList.contains("selected"), true);
  document.elements.get("#scene-group-next").trigger("click");
  assert.equal(document.elements.get("#scene-group-inspection-status").textContent, "Finding group · 3 buildings · building 2 of 3");
  assert.equal(overlay.children.find((polygon) => polygon.dataset.buildingId === groupIds[1]).classList.contains("selected"), true);
  document.elements.get("#scene-group-previous").trigger("click");
  assert.equal(document.elements.get("#scene-group-inspection-status").textContent, "Finding group · 3 buildings · building 1 of 3");
  document.elements.get("#scene-group-clear").trigger("click");
  assert.equal(document.elements.get("#scene-group-inspection").hidden, true);
  assert.equal(overlay.children.some((polygon) => polygon.classList.contains("group-highlight")), false);
  document.dispatchEvent(new CustomEvent("scene-building-group-inspect-request", { detail: {
    scene_id: "socal-fire_00000663", building_ids: groupIds, group_id: "severe-demo-group",
  } }));
  await document.elements.get("#scene-previous").trigger("click");
  assert.equal(document.elements.get("#scene-group-inspection").hidden, true);
  assert.equal(overlay.children.some((polygon) => polygon.classList.contains("group-highlight")), false);
  console.log("scene_dashboard_render=passed");
}

main();
