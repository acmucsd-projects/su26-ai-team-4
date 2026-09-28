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

  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name); }
  removeAttribute(name) { this.attributes.delete(name); if (name === "src") this._src = undefined; }
  replaceChildren() { this.children = []; }
  append(...children) { this.children.push(...children); }
  addEventListener(type, listener) { this.listeners.set(type, listener); }
  trigger(type) { return this.listeners.get(type)?.(); }
  querySelector(selector) {
    if (selector === "span") return this.buttonLabel || (this.buttonLabel = new FakeElement());
    return undefined;
  }
  set src(value) { this._src = value; }
  get src() { return this._src; }
}

function createDocument() {
  const ids = [
    "#pre-image", "#post-image", "#pre-preview", "#post-preview", "#pre-placeholder", "#post-placeholder",
    "#selection-label", "#status-message", "#predict-button", "#result-card", "#result-class",
    "#result-confidence", "#result-badge", "#probability-bars", "#clear-selection",
    "#building-context", "#context-claims", "#context-more", "#context-more-label", "#context-secondary-claims", "#context-attribution",
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
    examples,
    querySelector(selector) { return elements.get(selector); },
    querySelectorAll(selector) { return selector === ".example-button" ? examples : []; },
    createElement() { return new FakeElement(); },
    addEventListener(type, listener) { listeners.set(type, listener); },
    dispatchEvent(event) {
      listeners.get(event.type)?.(event);
      return !event.defaultPrevented;
    },
  };
}

async function main() {
  const document = createDocument();
  let fetchCalls = 0;
  let clearedSceneSelections = 0;
  document.addEventListener("scene-building-clear", () => { clearedSceneSelections += 1; });
  const source = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
  vm.runInNewContext(source, {
    document,
    Event: class { constructor(type) { this.type = type; } },
    URL: { createObjectURL() { return "blob:manual"; }, revokeObjectURL() {} },
    fetch: async () => { fetchCalls += 1; throw new Error("/predict should not be called for a scene selection"); },
    Array,
    Error,
    FormData: class {},
    Math,
    Number,
    Promise,
  });

  const first = {
    id: "hurricane-michael_00000247_b0001",
    crops: { pre_url: "/demo-scenes/hurricane-michael_00000247/crops/0001_pre.png", post_url: "/demo-scenes/hurricane-michael_00000247/crops/0001_post.png" },
    prediction: { predicted_class: "major-damage", confidence: 0.8, probabilities: { "no-damage": 0.05, "minor-damage": 0.1, "major-damage": 0.8, destroyed: 0.05 } },
    building_context: { claims: [
      { title: "Modeled use", value: "Single-family residential", source: "USACE National Structure Inventory", timing: "Current modeled inventory; not event-aligned", displayable: true },
      { title: "Property context", value: "Residential", source: "Bay County Property Appraiser", timing: "2017 pre-event property record", displayable: true },
      { title: "School site context", value: "Within Example School", source: "Sonoma County", timing: "Advertised July 2017 · vintage unverified", qualifier: "Site membership; individual building use may differ.", displayable: true },
      { title: "Site context", value: "Within Example School", source: "OpenStreetMap", timing: "Mapped near disaster date · 2017-10-11", osm: true, displayable: true },
      { title: "Mapped place", value: "Example Dental", source: "OpenStreetMap", timing: "Current context", osm: true, displayable: true },
      { title: "Mapped place", value: "QA-held identity", source: "OpenStreetMap", timing: "Current context", osm: true, displayable: false },
    ] },
  };
  const second = {
    id: "hurricane-michael_00000247_b0002",
    crops: { pre_url: "/demo-scenes/hurricane-michael_00000247/crops/0002_pre.png", post_url: "/demo-scenes/hurricane-michael_00000247/crops/0002_post.png" },
    prediction: { predicted_class: "no-damage", confidence: 0.9, probabilities: { "no-damage": 0.9, "minor-damage": 0.05, "major-damage": 0.03, destroyed: 0.02 } },
  };

  const selectSceneBuilding = (building) => {
    const event = {
      type: "scene-building-selected",
      detail: { building, handled: false },
      defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; },
    };
    document.dispatchEvent(event);
    return event.detail.handled && !event.defaultPrevented;
  };
  assert.equal(selectSceneBuilding(first), true);
  assert.equal(document.elements.get("#pre-preview").src, first.crops.pre_url);
  assert.equal(document.elements.get("#post-preview").src, first.crops.post_url);
  assert.equal(document.elements.get("#selection-label").textContent, "Scene selection");
  assert.equal(document.elements.get("#result-class").textContent, "major damage");
  assert.equal(document.elements.get("#result-confidence").textContent, "80.0% confidence");
  assert.equal(document.elements.get("#result-badge").textContent, "Scene selection");
  assert.equal(document.elements.get("#probability-bars").children.length, 4);
  assert.equal(document.elements.get("#result-card").hidden, false);
  const gis = document.elements.get("#building-context");
  const primary = document.elements.get("#context-claims");
  const secondary = document.elements.get("#context-secondary-claims");
  const text = (element) => element.textContent + element.children.map(text).join(" ");
  assert.equal(gis.hidden, false);
  assert.equal(primary.children.length, 3);
  assert.equal(secondary.children.length, 2);
  assert.match(text(primary), /Modeled use:.*Single-family residential/);
  assert.match(text(primary), /USACE National Structure Inventory/);
  assert.match(text(primary), /2017 pre-event property record/);
  assert.match(text(primary), /Within Example School/);
  assert.match(text(primary), /vintage unverified/);
  assert.match(text(secondary), /Mapped near disaster date/);
  assert.match(text(secondary), /Current context/);
  assert.doesNotMatch(text(primary) + text(secondary), /QA-held identity/);
  assert.equal(document.elements.get("#context-attribution").hidden, false);
  await document.elements.get("#predict-button").trigger("click");
  assert.equal(fetchCalls, 0);
  assert.equal(gis.hidden, false);

  assert.equal(selectSceneBuilding(second), true);
  assert.equal(document.elements.get("#pre-preview").src, second.crops.pre_url);
  assert.equal(document.elements.get("#result-class").textContent, "no damage");
  assert.equal(document.elements.get("#result-confidence").textContent, "90.0% confidence");
  assert.equal(gis.hidden, true);
  assert.equal(primary.children.length, 0);
  assert.equal(secondary.children.length, 0);
  assert.equal(document.elements.get("#context-attribution").hidden, true);

  selectSceneBuilding(first);
  document.examples[0].trigger("click");
  assert.equal(gis.hidden, true);
  assert.equal(document.elements.get("#pre-preview").src, "examples/no_damage/pre.png");
  assert.equal(document.elements.get("#post-preview").src, "examples/no_damage/post.png");
  assert.equal(document.elements.get("#result-card").hidden, true);
  assert.ok(clearedSceneSelections > 0);

  selectSceneBuilding(first);
  document.elements.get("#pre-image").files = [{ name: "manual-pre.png" }];
  document.elements.get("#pre-image").trigger("change");
  assert.equal(document.elements.get("#pre-preview").src, "blob:manual");
  assert.equal(document.elements.get("#selection-label").textContent, "Custom upload");
  assert.equal(gis.hidden, true);
  selectSceneBuilding(first);
  document.elements.get("#context-more").open = true;
  document.elements.get("#clear-selection").trigger("click");
  assert.equal(gis.hidden, true);
  assert.equal(document.elements.get("#context-more").open, false);
  selectSceneBuilding({ ...second, building_context: { claims: first.building_context.claims.filter((c) => !c.displayable) } });
  assert.equal(gis.hidden, true);
  console.log("scene_inspection=passed");
}

main();
