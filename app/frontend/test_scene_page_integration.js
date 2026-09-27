const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class FakeElement {
  constructor() {
    this.attributes = new Map();
    this.children = [];
    this.dataset = {};
    this.listeners = new Map();
    this.hidden = false;
    this.style = {};
    this.value = "";
    this.files = [];
    this.textContent = "";
    this.complete = false;
    this.naturalWidth = 0;
    this._classes = new Set();
    this.classList = {
      add: (...classes) => classes.forEach((className) => this._classes.add(className)),
      remove: (...classes) => classes.forEach((className) => this._classes.delete(className)),
      toggle: (className, force) => {
        if (force === true || (force === undefined && !this._classes.has(className))) this._classes.add(className);
        else this._classes.delete(className);
      },
      contains: (className) => this._classes.has(className),
    };
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === "class") this._classes = new Set(String(value).split(/\s+/).filter(Boolean));
  }
  getAttribute(name) { return this.attributes.get(name); }
  removeAttribute(name) { this.attributes.delete(name); if (name === "src") this._src = undefined; }
  replaceChildren() { this.children = []; }
  append(...children) { this.children.push(...children); }
  addEventListener(type, listener) { this.listeners.set(type, listener); }
  trigger(type, event = {}) { return this.listeners.get(type)?.({ preventDefault() {}, ...event }); }
  querySelector(selector) {
    if (selector === "span") return this.buttonLabel || (this.buttonLabel = new FakeElement());
    return undefined;
  }
  set src(value) {
    this._src = value;
    this.complete = true;
    this.naturalWidth = 1024;
    this.onload?.();
  }
  get src() { return this._src; }
}

function createDocument() {
  const ids = [
    "#scene-description", "#scene-building-count", "#scene-status-message", "#scene-canvas", "#scene-post-image", "#scene-overlay",
    "#pre-image", "#post-image", "#pre-preview", "#post-preview", "#pre-placeholder", "#post-placeholder", "#selection-label",
    "#status-message", "#predict-button", "#result-card", "#result-class", "#result-confidence", "#result-badge", "#probability-bars", "#clear-selection",
  ];
  const elements = new Map(ids.map((id) => [id, new FakeElement()]));
  const examples = ["no-damage", "minor-damage", "major-damage", "destroyed"].map((name) => {
    const button = new FakeElement();
    button.dataset.example = name;
    return button;
  });
  const listeners = new Map();
  return {
    elements,
    querySelector(selector) { return elements.get(selector); },
    querySelectorAll(selector) { return selector === ".example-button" ? examples : []; },
    createElement() { return new FakeElement(); },
    createElementNS() { return new FakeElement(); },
    addEventListener(type, listener) {
      listeners.set(type, [...(listeners.get(type) || []), listener]);
    },
    dispatchEvent(event) {
      for (const listener of listeners.get(event.type) || []) listener(event);
      return !event.defaultPrevented;
    },
  };
}

class PageEvent {
  constructor(type, options = {}) {
    this.type = type;
    this.detail = options.detail;
    this.cancelable = options.cancelable;
    this.defaultPrevented = false;
  }
  preventDefault() { if (this.cancelable) this.defaultPrevented = true; }
}

async function main() {
  const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
  assert.ok(html.indexOf('src="scene-dashboard.js?v=scene-inspection-1"') < html.indexOf('src="app.js?v=scene-inspection-1"'));

  const document = createDocument();
  const building = {
    id: "hurricane-michael_00000247_b0000",
    pixel_polygon: [[0, 0], [10, 0], [10, 10]],
    crops: { pre_url: "/demo-scenes/hurricane-michael_00000247/crops/0051675_pre.png", post_url: "/demo-scenes/hurricane-michael_00000247/crops/0051675_post.png" },
    prediction: { predicted_class: "major-damage", confidence: 0.8, probabilities: { "no-damage": 0.05, "minor-damage": 0.1, "major-damage": 0.8, destroyed: 0.05 } },
  };
  const scene = { scene_id: "hurricane-michael_00000247", event_name: "hurricane-michael", image: { width: 1024, height: 1024, post_url: "/demo-scenes/hurricane-michael_00000247/post.png" }, buildings: [building] };
  let predictRequests = 0;
  const fetch = async (url) => {
    if (url === "/demo-scenes") return { ok: true, json: async () => ({ scenes: [{ scene_id: scene.scene_id }] }) };
    if (url === "/demo-scenes/hurricane-michael_00000247") return { ok: true, json: async () => scene };
    predictRequests += 1;
    throw new Error("Unexpected request: " + url);
  };
  const context = {
    Array, CustomEvent: PageEvent, Error, Event: PageEvent, FormData: class {}, Math, Number, Promise,
    URL: { createObjectURL() { return "blob:manual"; }, revokeObjectURL() {} }, document, fetch,
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "scene-dashboard.js"), "utf8"), context);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "app.js"), "utf8"), context);
  await new Promise((resolve) => setTimeout(resolve, 0));

  const polygon = document.elements.get("#scene-overlay").children[0];
  polygon.trigger("click");
  assert.equal(polygon.classList.contains("selected"), true);
  assert.equal(document.elements.get("#pre-preview").src, building.crops.pre_url);
  assert.equal(document.elements.get("#post-preview").src, building.crops.post_url);
  assert.equal(document.elements.get("#selection-label").textContent, "Scene selection");
  assert.equal(document.elements.get("#result-card").hidden, false);
  assert.equal(document.elements.get("#result-class").textContent, "major damage");
  assert.equal(document.elements.get("#result-confidence").textContent, "80.0% confidence");
  assert.equal(document.elements.get("#probability-bars").children.length, 4);
  assert.equal(predictRequests, 0);
  console.log("scene_page_integration=passed");
}

main();
