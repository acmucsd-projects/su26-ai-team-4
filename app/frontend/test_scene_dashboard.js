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
    ["#scene-building-count", new FakeElement()],
    ["#scene-status-message", new FakeElement()],
    ["#scene-canvas", new FakeElement()],
    ["#scene-post-image", new FakeElement()],
    ["#scene-overlay", new FakeElement()],
  ]);
  const listeners = new Map();
  return {
    elements,
    querySelector(selector) {
      return elements.get(selector);
    },
    createElementNS() {
      return new FakeElement();
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
  document.addEventListener("scene-building-selected", (event) => {
    event.detail.handled = true;
    if (event.detail.building) {
      const building = event.detail.building;
      selections.push(building);
    } else event.preventDefault();
  });
  const buildings = Array.from({ length: 177 }, (_, index) => ({
    id: `demo_b${index.toString().padStart(4, "0")}`,
    pixel_polygon: [[index, 0], [index + 1, 0], [index + 1, 1]],
    crops: { pre_url: `/crops/${index}-pre.png`, post_url: `/crops/${index}-post.png` },
    prediction: {
      predicted_class: DAMAGE_CLASSES[index % DAMAGE_CLASSES.length],
      confidence: 0.8,
      probabilities: Object.fromEntries(DAMAGE_CLASSES.map((className) => [className, className === DAMAGE_CLASSES[index % DAMAGE_CLASSES.length] ? 0.8 : 1 / 15])),
    },
  }));
  const scene = {
    scene_id: "hurricane-michael_00000247",
    event_name: "hurricane-michael",
    image: { width: 1024, height: 1024, post_url: "/demo-scenes/hurricane-michael_00000247/post.png" },
    buildings,
  };
  const fetchCalls = [];
  const fetch = async (url) => {
    fetchCalls.push(url);
    if (url === "/demo-scenes") return { ok: true, json: async () => ({ scenes: [{ scene_id: scene.scene_id }] }) };
    if (url === "/demo-scenes/hurricane-michael_00000247") return { ok: true, json: async () => scene };
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
  vm.runInNewContext(source, { Array, CustomEvent, Error, Number, Promise, document, fetch });
  await new Promise((resolve) => setTimeout(resolve, 0));

  const canvas = document.elements.get("#scene-canvas");
  const image = document.elements.get("#scene-post-image");
  const overlay = document.elements.get("#scene-overlay");
  assert.deepEqual(fetchCalls, ["/demo-scenes", "/demo-scenes/hurricane-michael_00000247"]);
  assert.equal(canvas.hidden, false);
  assert.equal(image.src, scene.image.post_url);
  assert.equal(overlay.getAttribute("viewBox"), "0 0 1024 1024");
  assert.equal(overlay.children.length, 177);
  assert.deepEqual(new Set(overlay.children.map((polygon) => polygon.getAttribute("class").replace("scene-building ", ""))), new Set(DAMAGE_CLASSES));
  overlay.children.forEach((polygon) => {
    assert.match(polygon.getAttribute("class"), /^scene-building (no-damage|minor-damage|major-damage|destroyed)$/);
    assert.ok(polygon.getAttribute("points"));
  });
  overlay.children[0].trigger("click");
  assert.equal(selections.length, 1);
  assert.equal(selections[0].id, buildings[0].id);
  assert.equal(overlay.children[0].classList.contains("selected"), true);
  assert.equal(overlay.children[0].getAttribute("aria-pressed"), "true");
  overlay.children[1].trigger("click");
  assert.equal(selections.length, 2);
  assert.equal(selections[1].id, buildings[1].id);
  assert.equal(overlay.children[0].classList.contains("selected"), false);
  assert.equal(overlay.children[1].classList.contains("selected"), true);
  console.log("scene_dashboard_render=passed");
}

main();
