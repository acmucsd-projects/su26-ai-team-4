const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const DAMAGE_CLASSES = ["no-damage", "minor-damage", "major-damage", "destroyed"];

class FakeElement {
  constructor() {
    this.attributes = new Map();
    this.children = [];
    this.classList = { toggle() {} };
    this.dataset = {};
    this.hidden = false;
    this.complete = false;
    this.naturalWidth = 0;
    this.textContent = "";
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
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
  return {
    elements,
    querySelector(selector) {
      return elements.get(selector);
    },
    createElementNS() {
      return new FakeElement();
    },
  };
}

async function main() {
  const document = createDocument();
  const buildings = Array.from({ length: 177 }, (_, index) => ({
    id: `demo_b${index.toString().padStart(4, "0")}`,
    pixel_polygon: [[index, 0], [index + 1, 0], [index + 1, 1]],
    prediction: { predicted_class: DAMAGE_CLASSES[index % DAMAGE_CLASSES.length] },
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
  vm.runInNewContext(source, { Array, Error, Number, Promise, document, fetch });
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
  console.log("scene_dashboard_render=passed");
}

main();
