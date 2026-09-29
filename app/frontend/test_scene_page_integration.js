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
  replaceChildren(...children) { this.children = [...children]; }
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
    "#scene-description", "#scene-dashboard-title", "#scene-event-context", "#scene-building-count", "#scene-status-message", "#scene-canvas", "#scene-post-image", "#scene-overlay",
    "#scene-loading", "#scene-tooltip", ".scene-legend", "#scene-uncertainty-legend",
    "#scene-selector", "#scene-previous", "#scene-current", "#scene-next", "#scene-filters",
    "#scene-analysis-content", "#scene-analysis-locked", "#scene-reveal", "#scene-reveal-button", "#scene-reveal-status", ".workspace-hint",
    "#scene-assessment", "#scene-assessment-generate-button", "#scene-assessment-status", "#scene-assessment-result",
    "#scene-assessment-model", "#scene-assessment-overview", "#scene-assessment-findings-block", "#scene-assessment-findings",
    "#scene-assessment-review-block", "#scene-assessment-review", "#scene-assessment-details", "#scene-assessment-evidence-used",
    "#scene-assessment-limitations-block", "#scene-assessment-limitations",
    "#scene-summary", "#scene-summary-total", "#scene-summary-no-damage", "#scene-summary-minor-damage", "#scene-summary-major-damage", "#scene-summary-destroyed", "#scene-summary-severe", "#scene-summary-severe-detail",
    "#scene-group-inspection", "#scene-group-inspection-status", "#scene-group-previous", "#scene-group-next", "#scene-group-clear",
    "#pre-image", "#post-image", "#pre-preview", "#post-preview", "#pre-placeholder", "#post-placeholder", "#selection-label",
    "#inspector-empty", "#inspector-content", "#inspector-context-pill", "#comparison", "#comparison-range",
    "#status-message", "#predict-button", "#result-card", "#result-class", "#result-confidence", "#result-badge", "#probability-bars", "#clear-selection",
    "#building-context", "#context-claims", "#context-more", "#context-more-label", "#context-secondary-claims", "#context-attribution", "#context-category", "#context-evidence", "#context-notes",
    "#building-assessment", "#assessment-generate-button", "#assessment-status", "#assessment-result",
    "#assessment-model", "#assessment-text", "#assessment-review-block", "#assessment-review-text",
    "#assessment-evidence-details", "#assessment-evidence-used", "#assessment-supporting-block",
    "#assessment-supporting-details", "#assessment-limitations-block", "#assessment-limitations",
  ];
  const elements = new Map(ids.map((id) => [id, new FakeElement()]));
  elements.get("#inspector-content").hidden = true;
  elements.get("#assessment-generate-button").textContent = "Generate assessment";
  elements.get("#scene-assessment-generate-button").textContent = "Generate analysis";
  const examples = ["no-damage", "minor-damage", "major-damage", "destroyed"].map((name) => {
    const button = new FakeElement();
    button.dataset.example = name;
    return button;
  });
  const imageryButtons = ["pre", "post", "post-predictions", "uncertainty"].map((mode) => {
    const button = new FakeElement();
    button.dataset.imageryMode = mode;
    return button;
  });
  const filterButtons = ["all", "severe", "no-damage", "minor-damage", "major-damage", "destroyed"].map((filter) => {
    const button = new FakeElement();
    button.dataset.sceneFilter = filter;
    return button;
  });
  const listeners = new Map();
  return {
    elements,
    querySelector(selector) { return elements.get(selector); },
    querySelectorAll(selector) {
      if (selector === ".example-button") return examples;
      if (selector === "[data-imagery-mode]") return imageryButtons;
      if (selector === "[data-scene-filter]") return filterButtons;
      return [];
    },
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
  const styles = fs.readFileSync(path.join(__dirname, "styles.css"), "utf8");
  assert.match(html, /href="styles\.css\?v=geo-workspace-4"/);
  assert.ok(html.indexOf('src="scene-dashboard.js?v=geo-workspace-4"') < html.indexOf('src="app.js?v=geo-workspace-4"'));
  assert.match(styles, /button:focus-visible, input:focus-visible, summary:focus-visible/);
  assert.match(styles, /prefers-reduced-motion: reduce/);
  assert.match(styles, /@media \(max-width: 920px\)/);
  assert.match(styles, /@media \(max-width: 650px\)/);
  assert.match(styles, /\.inspector-panel \{ position: sticky/);
  assert.match(html, /openstreetmap.org\/copyright/);
  assert.match(html, /ODbL/);
  assert.match(html, /<details id="context-more"/);
  assert.match(html, /Sources, scope &amp; limitations/);
  assert.match(styles, /\.scene-canvas img, \.scene-overlay \{ position: absolute/);
  assert.match(styles, /\.scene-building\.neutral/);
  assert.match(styles, /\.scene-imagery-mode/);
  assert.match(styles, /\.scene-summary/);
  assert.match(styles, /\.scene-severe-summary/);
  assert.match(styles, /\.scene-filters/);
  assert.equal((html.match(/class="scene-summary-metric /g) || []).length, 4);
  assert.doesNotMatch(html, /scene-summary-metric severe/);
  assert.match(html, /Severe predictions/);
  assert.match(html, /AI-Assisted Assessment/);
  assert.match(html, /AI Scene Analysis/);
  assert.match(html, /Generate analysis/);
  assert.match(html, /Reveal damage assessment/);
  assert.match(styles, /@media \(min-width: 1600px\)/);
  assert.match(styles, /contain: size; overflow-y: auto/);
  assert.match(styles, /align-items: stretch/);
  assert.match(html, /Assessment not revealed/);
  assert.doesNotMatch(html, /Quick Explore|Read full analysis|scene-assessment-overview-excerpt/);
  assert.match(html, /Test your own PRE \/ POST pair/);
  assert.match(html, /id="scene-assessment-overview"/);
  assert.ok(html.indexOf('id="scene-assessment-overview"') < html.indexOf('id="scene-assessment-review-block"'));
  assert.ok(html.indexOf('id="scene-assessment-review-block"') < html.indexOf('id="scene-assessment-findings-block"'));
  assert.doesNotMatch(html, /Curated PRE and POST satellite imagery/);
  assert.doesNotMatch(html, /GPT-6 Sol/);
  assert.ok(html.indexOf('id="scene-analysis"') < html.indexOf('class="scene-workspace"'));
  assert.ok(html.indexOf('class="scene-workspace"') < html.indexOf('id="building-inspector"'));
  assert.ok(html.indexOf('id="scene-assessment-details"') < html.indexOf('id="scene-assessment-model"'));
  assert.ok(html.indexOf('id="assessment-evidence-details"') < html.indexOf('id="assessment-model"'));
  assert.match(html, /id="comparison-range"/);
  assert.doesNotMatch(html, /id="scene-highlights"/);
  assert.match(html, /data-imagery-mode="uncertainty"/);
  assert.match(html, /Key findings/);
  assert.match(html, /scene-assessment-details/);
  assert.match(html, /<h4 id="assessment-review-title">Recommended review<\/h4>/);
  assert.match(html, /<details id="assessment-evidence-details"/);
  assert.match(html, /Evidence &amp; limitations/);
  assert.doesNotMatch(html, /What stands out|Context interpretation|Evidence gaps/);
  assert.doesNotMatch(html, /priority|emergency|likely needs help/i);

  const document = createDocument();
  const building = {
    id: "hurricane-michael_00000247_b0000",
    pre_pixel_polygon: [[100, 100], [110, 100], [110, 110]],
    post_pixel_polygon: [[0, 0], [10, 0], [10, 10]],
    crops: { pre_url: "/demo-scenes/hurricane-michael_00000247/crops/0051675_pre.png", post_url: "/demo-scenes/hurricane-michael_00000247/crops/0051675_post.png" },
    prediction: { predicted_class: "major-damage", confidence: 0.8, probabilities: { "no-damage": 0.05, "minor-damage": 0.1, "major-damage": 0.8, destroyed: 0.05 } },
    building_context: { version: 2, primary_label: "Residential", primary_statement_ids: ["property"], notes: [],
      claims: [{ id: "claim-0", title: "Property context", original_value: "SINGLE FAMILY", source: "Bay County", source_key: "bay", timing: "2017 pre-event property record", displayable: true }],
      statements: [{ id: "property", label: "Property use", text: "Single-family residential", temporal_label: "2017 pre-event",
        supporting_claims: ["claim-0"], corroborating_claims: [] }] },
  };
  const groupBuilding = {
    id: "hurricane-michael_00000247_b0001", pre_pixel_polygon: [[30, 30], [40, 30], [40, 40]],
    post_pixel_polygon: [[30, 30], [40, 30], [40, 40]],
    crops: { pre_url: "/demo-scenes/hurricane-michael_00000247/crops/group-pre.png", post_url: "/demo-scenes/hurricane-michael_00000247/crops/group-post.png" },
    prediction: { predicted_class: "destroyed", confidence: 0.9, probabilities: { "no-damage": 0.03, "minor-damage": 0.03, "major-damage": 0.04, destroyed: 0.9 } },
  };
  const lowBuilding = {
    id: "hurricane-michael_00000247_b0002", pre_pixel_polygon: [[50, 50], [60, 50], [60, 60]],
    post_pixel_polygon: [[50, 50], [60, 50], [60, 60]],
    crops: { pre_url: "/demo-scenes/hurricane-michael_00000247/crops/low-pre.png", post_url: "/demo-scenes/hurricane-michael_00000247/crops/low-post.png" },
    prediction: { predicted_class: "no-damage", confidence: 0.9, probabilities: { "no-damage": 0.9, "minor-damage": 0.04, "major-damage": 0.03, destroyed: 0.03 } },
  };
  const scene = { scene_id: "hurricane-michael_00000247", event_name: "hurricane-michael", scene_evidence_context: { event_name: "hurricane-michael", location: "Bay County, Florida", post_acquisition_date: "2018-10-13T16:48:15.000Z" }, image: { width: 1024, height: 1024, pre_url: "/demo-scenes/hurricane-michael_00000247/pre.png", post_url: "/demo-scenes/hurricane-michael_00000247/post.png" }, buildings: [building, groupBuilding, lowBuilding] };
  const nextBuilding = {
    id: "hurricane-harvey_00000177_b0000",
    pre_pixel_polygon: [[120, 120], [130, 120], [130, 130]],
    post_pixel_polygon: [[20, 20], [30, 20], [30, 30]],
    crops: { pre_url: "/demo-scenes/hurricane-harvey_00000177/crops/0001234_pre.png", post_url: "/demo-scenes/hurricane-harvey_00000177/crops/0001234_post.png" },
    prediction: { predicted_class: "no-damage", confidence: 0.9, probabilities: { "no-damage": 0.9, "minor-damage": 0.05, "major-damage": 0.03, destroyed: 0.02 } },
  };
  const nextScene = { scene_id: "hurricane-harvey_00000177", event_name: "hurricane-harvey", scene_evidence_context: { event_name: "hurricane-harvey", location: "Harris County, Texas", post_acquisition_date: "2017-08-31T17:38:50.685Z" }, image: { width: 1024, height: 1024, pre_url: "/demo-scenes/hurricane-harvey_00000177/pre.png", post_url: "/demo-scenes/hurricane-harvey_00000177/post.png" }, buildings: [nextBuilding] };
  let predictRequests = 0;
  const assessmentRequests = [];
  const assessmentResponses = [];
  const fetch = async (url, options = {}) => {
    if (url === "/demo-scenes") return { ok: true, json: async () => ({ scenes: [{ scene_id: scene.scene_id, event_name: scene.event_name }, { scene_id: nextScene.scene_id, event_name: nextScene.event_name }] }) };
    if (url === "/demo-scenes/hurricane-michael_00000247") return { ok: true, json: async () => scene };
    if (url === "/demo-scenes/hurricane-harvey_00000177") return { ok: true, json: async () => nextScene };
    if (options.method === "POST") {
      assessmentRequests.push({ url, options });
      const next = assessmentResponses.shift();
      if (!next) throw new Error("Unexpected assessment request: " + url);
      return typeof next === "function" ? next() : next;
    }
    predictRequests += 1;
    throw new Error("Unexpected request: " + url);
  };
  const context = {
    Array, CustomEvent: PageEvent, Error, Event: PageEvent, FormData: class {}, Math, Number, Promise,
    URL: { createObjectURL() { return "blob:manual"; }, revokeObjectURL() {} }, document, fetch,
    setTimeout: (callback) => callback(), matchMedia: () => ({ matches: true }),
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "scene-dashboard.js"), "utf8"), context);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "app.js"), "utf8"), context);
  await new Promise((resolve) => setTimeout(resolve, 0));

  const overlay = document.elements.get("#scene-overlay");
  const image = document.elements.get("#scene-post-image");
  const imageryButtons = document.querySelectorAll("[data-imagery-mode]");
  const filterButtons = document.querySelectorAll("[data-scene-filter]");
  const filterButton = (filter) => filterButtons.find((button) => button.dataset.sceneFilter === filter);
  assert.equal(overlay.hidden, true);
  assert.equal(overlay.children.length, 0);
  assert.equal(document.elements.get("#scene-summary").hidden, true);
  assert.equal(document.elements.get("#scene-analysis-content").hidden, true);
  assert.equal(document.elements.get("#scene-analysis-locked").hidden, false);
  assert.equal(document.elements.get("#inspector-empty").hidden, false);
  assert.equal(document.elements.get("#inspector-content").hidden, true);
  assert.equal(document.elements.get("#scene-reveal").hidden, false);
  assert.equal(assessmentRequests.length, 0);
  await document.elements.get("#scene-reveal-button").trigger("click");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(overlay.children[0].getAttribute("class"), "scene-building major-damage");
  assert.equal(document.elements.get("#scene-analysis-locked").hidden, true);
  assert.equal(document.elements.get("#inspector-empty").hidden, false);
  assert.equal(document.elements.get("#scene-event-context").textContent, "Bay County, Florida · POST Oct 2018");
  assert.equal(filterButton("all").getAttribute("aria-pressed"), "true");
  assert.equal(document.elements.get("#scene-summary-total").textContent, "3 buildings analyzed");
  assert.equal(document.elements.get("#scene-summary-major-damage").textContent, "1");
  assert.equal(document.elements.get("#scene-summary-destroyed").textContent, "1");
  assert.equal(document.elements.get("#scene-summary-severe").textContent, "2");
  assert.equal(document.elements.get("#scene-summary-severe-detail").textContent, "1 Major + 1 Destroyed");
  const sceneAssessment = document.elements.get("#scene-assessment");
  const sceneGenerate = document.elements.get("#scene-assessment-generate-button");
  assert.equal(sceneAssessment.hidden, false);
  assert.equal(sceneGenerate.textContent, "Generate analysis");
  assert.equal(document.elements.get("#scene-assessment-result").hidden, true);
  assert.equal(assessmentRequests.length, 0);

  // The overview is explicit, deduplicated, grounded in returned candidate keys, and interactive.
  let resolveOverview;
  assessmentResponses.push(() => new Promise((resolve) => { resolveOverview = resolve; }));
  const generating = sceneGenerate.trigger("click");
  sceneGenerate.trigger("click");
  assert.equal(assessmentRequests.length, 1);
  assert.equal(assessmentRequests[0].url, "/demo-scenes/hurricane-michael_00000247/assessment");
  assert.equal(assessmentRequests[0].options.method, "POST");
  assert.equal(sceneGenerate.disabled, true);
  assert.equal(document.elements.get("#scene-assessment-status").textContent, "Generating scene brief…");
  resolveOverview({
    ok: true,
    json: async () => ({
      overview: "The packaged scene predictions are mostly severe.",
      findings: [
        { title: "Inspect a representative prediction", explanation: "The candidate group has multiple supplied members.", candidate_keys: ["representative", "same_building_alias"] },
        { title: "Inspect one building", explanation: "This selected prediction is available for individual review.", candidate_keys: ["single_building"] },
        { title: "Untrusted invented ID", explanation: "Inspect hurricane-michael_00000247_b9999.", candidate_keys: [] },
        { title: "Unknown reference", explanation: "This key is not in the candidate map.", candidate_keys: ["unknown"] },
        { title: "Out-of-scene reference", explanation: "The candidate map points outside this scene.", candidate_keys: ["invalid_scene_id"] },
      ],
      recommended_review: "Can the imagery distinguish the leading model classes?",
      limitations: ["Model output is not verified damage."],
      candidate_buildings: { representative: [building.id, groupBuilding.id], same_building_alias: [building.id], single_building: [lowBuilding.id], invalid_scene_id: ["hurricane-harvey_00000177_b0000"] },
      candidate_types: { representative: "SEVERE_PROXIMITY_GROUP", same_building_alias: "REPRESENTATIVE_SEVERE", single_building: "REPRESENTATIVE_SEVERE", invalid_scene_id: "REPRESENTATIVE_SEVERE" },
      generated_by: "openai/gpt-6-sol",
      evidence_used: ["model", "spatial", "event", "reviewed_gis", "image", "unknown"],
    }),
  });
  await generating;
  assert.equal(document.elements.get("#scene-assessment-result").hidden, false);
  assert.equal(document.elements.get("#scene-assessment-overview").textContent, "The packaged scene predictions are mostly severe.");
  assert.equal(document.elements.get("#scene-assessment-model").textContent, "Generated by GPT-6 Sol");
  assert.equal(document.elements.get("#scene-assessment-findings").children.length, 2);
  assert.equal(document.elements.get("#scene-assessment-findings").children[0].children[0].textContent, "Severe proximity group · 2 buildings");
  assert.equal(document.elements.get("#scene-assessment-findings").children[0].children[3].textContent, "Show group →");
  assert.equal(document.elements.get("#scene-assessment-findings").children[0].children.length, 4);
  assert.equal(document.elements.get("#scene-assessment-findings").children[1].children[3].textContent, "Inspect building →");
  assert.equal(document.elements.get("#scene-assessment-review").textContent, "Can the imagery distinguish the leading model classes?");
  assert.equal(document.elements.get("#scene-assessment-review-block").hidden, false);
  assert.equal(document.elements.get("#scene-assessment-details").open, false);
  assert.deepEqual(document.elements.get("#scene-assessment-evidence-used").children.map((badge) => badge.textContent), ["MODEL", "SPATIAL", "EVENT", "GIS"]);
  const inspectButton = document.elements.get("#scene-assessment-findings").children[0].children[3];
  assert.equal(document.elements.get("#scene-assessment-findings").children[0].children[2].children[0].textContent, "Read explanation");
  assert.equal(document.elements.get("#scene-assessment-findings").children[0].children[2].children[1].textContent, "The candidate group has multiple supplied members.");
  inspectButton.trigger("click");
  assert.equal(document.elements.get("#scene-group-inspection").hidden, false);
  assert.match(document.elements.get("#scene-group-inspection-status").textContent, /^Severe proximity group · 2 buildings · building 1 of 2$/);
  assert.equal(overlay.children.filter((item) => item.classList.contains("group-highlight")).length, 2);
  assert.equal(overlay.children.find((item) => item.dataset.buildingId === lowBuilding.id).classList.contains("group-muted"), true);
  assert.equal(overlay.children[0].classList.contains("selected"), true);
  document.elements.get("#scene-group-next").trigger("click");
  assert.equal(overlay.children.find((item) => item.dataset.buildingId === groupBuilding.id).classList.contains("selected"), true);
  document.elements.get("#scene-group-clear").trigger("click");
  assert.equal(document.elements.get("#scene-group-inspection").hidden, true);
  assert.equal(overlay.children.some((item) => item.classList.contains("group-highlight")), false);
  assert.equal(overlay.children.some((item) => item.classList.contains("group-muted")), false);
  overlay.children.find((item) => item.dataset.buildingId === building.id).trigger("click");
  assert.equal(document.elements.get("#selection-label").textContent, "Building b0000");
  assert.equal(document.elements.get("#pre-preview").src, building.crops.pre_url);
  assert.equal(document.elements.get("#inspector-empty").hidden, true);
  assert.equal(document.elements.get("#inspector-content").hidden, false);
  await imageryButtons[0].trigger("click");
  assert.equal(image.src, scene.image.pre_url);
  assert.equal(overlay.children[0].getAttribute("points"), "100,100 110,100 110,110");
  assert.equal(overlay.children[0].getAttribute("class"), "scene-building neutral");
  await imageryButtons[1].trigger("click");
  assert.equal(image.src, scene.image.post_url);
  assert.equal(overlay.children[0].getAttribute("points"), "0,0 10,0 10,10");
  assert.equal(overlay.children[0].getAttribute("class"), "scene-building neutral");
  await imageryButtons[2].trigger("click");
  assert.equal(image.src, scene.image.post_url);
  assert.equal(overlay.children[0].getAttribute("class"), "scene-building major-damage");

  const polygon = overlay.children[0];
  polygon.trigger("click");
  assert.equal(polygon.classList.contains("selected"), true);
  assert.equal(document.elements.get("#pre-preview").src, building.crops.pre_url);
  assert.equal(document.elements.get("#post-preview").src, building.crops.post_url);
  assert.equal(document.elements.get("#selection-label").textContent, "Building b0000");
  assert.equal(document.elements.get("#result-card").hidden, false);
  assert.equal(document.elements.get("#result-class").textContent, "major damage");
  assert.equal(document.elements.get("#result-confidence").textContent, "80.0% top-class score");
  assert.equal(document.elements.get("#probability-bars").children.length, 4);
  assert.equal(document.elements.get("#building-context").hidden, false);
  await filterButton("severe").trigger("click");
  assert.equal(overlay.children.length, 2);
  assert.equal(overlay.children[0].classList.contains("selected"), true);
  await imageryButtons[0].trigger("click");
  assert.equal(overlay.children[0].classList.contains("selected"), true);
  assert.equal(overlay.children[0].classList.contains("neutral"), true);
  await imageryButtons[1].trigger("click");
  assert.equal(overlay.children[0].classList.contains("neutral"), true);
  await imageryButtons[2].trigger("click");
  assert.equal(overlay.children[0].classList.contains("selected"), true);
  await filterButton("no-damage").trigger("click");
  assert.equal(document.elements.get("#building-context").hidden, true);
  assert.equal(overlay.children.length, 1);
  assert.equal(document.elements.get("#pre-preview").src, undefined);
  assert.equal(document.elements.get("#post-preview").src, undefined);
  assert.equal(document.elements.get("#selection-label").textContent, "No building selected");
  assert.equal(document.elements.get("#result-card").hidden, true);
  await filterButton("all").trigger("click");
  assert.equal(overlay.children.length, 3);
  overlay.children[0].trigger("click");
  assert.equal(document.elements.get("#building-context").hidden, false);
  await document.elements.get("#scene-next").trigger("click");
  assert.equal(overlay.hidden, true);
  assert.equal(document.elements.get("#scene-analysis-content").hidden, true);
  assert.equal(document.elements.get("#scene-analysis-locked").hidden, false);
  assert.equal(document.elements.get("#inspector-empty").hidden, false);
  await document.elements.get("#scene-reveal-button").trigger("click");
  assert.equal(sceneAssessment.hidden, false);
  assert.equal(document.elements.get("#scene-event-context").textContent, "Harris County, Texas · POST Aug 2017");
  assert.equal(document.elements.get("#scene-assessment-result").hidden, true);
  assert.equal(sceneGenerate.hidden, false);
  assert.equal(document.elements.get("#building-context").hidden, true);
  assert.equal(document.elements.get("#scene-summary-total").textContent, "1 building analyzed");
  assert.equal(document.elements.get("#scene-summary-no-damage").textContent, "1");
  assert.equal(document.elements.get("#scene-summary-major-damage").textContent, "0");
  assert.equal(document.elements.get("#scene-summary-severe").textContent, "0");
  assert.equal(document.elements.get("#scene-summary-severe-detail").textContent, "0 Major + 0 Destroyed");
  assert.equal(document.elements.get("#pre-preview").src, undefined);
  assert.equal(document.elements.get("#post-preview").src, undefined);
  assert.equal(document.elements.get("#selection-label").textContent, "No building selected");
  assert.equal(document.elements.get("#result-card").hidden, true);
  const nextPolygon = document.elements.get("#scene-overlay").children[0];
  nextPolygon.trigger("click");
  assert.equal(document.elements.get("#pre-preview").src, nextBuilding.crops.pre_url);
  assert.equal(document.elements.get("#post-preview").src, nextBuilding.crops.post_url);
  assert.equal(document.elements.get("#result-class").textContent, "no damage");
  assert.equal(document.elements.get("#building-context").hidden, true);
  assert.equal(document.elements.get("#scene-assessment-overview").textContent, "");
  assessmentResponses.push({ ok: false, status: 503, json: async () => ({ detail: { code: "assessment_provider_unavailable" } }) });
  await sceneGenerate.trigger("click");
  assert.equal(document.elements.get("#scene-assessment-status").textContent, "AI scene brief is currently unavailable.");
  assert.equal(sceneGenerate.disabled, false);
  const longHarveyOverview = "The packaged scene predictions and local context provide several review paths. "
    + "Nearby severe predictions should be compared with the paired imagery, while property claims retain their source and timing. "
    + "This summary does not establish observed damage.";
  assessmentResponses.push({ ok: true, json: async () => ({
    overview: longHarveyOverview, findings: [], recommended_review: null, limitations: [],
    generated_by: "openai/alternate-model-v2", evidence_used: ["model", "event", "image", "unknown", "model"], candidate_buildings: {},
  }) });
  await sceneGenerate.trigger("click");
  assert.equal(assessmentRequests.length, 3);
  assert.equal(assessmentRequests[2].url, "/demo-scenes/hurricane-harvey_00000177/assessment");
  assert.equal(document.elements.get("#scene-assessment-overview").textContent, longHarveyOverview);
  assert.equal((html.match(/id="scene-assessment-overview"/g) || []).length, 1);
  assert.equal(document.elements.get("#scene-assessment-model").textContent, "Generated by Alternate Model V2");
  assert.equal(document.elements.get("#scene-assessment-findings-block").hidden, true);
  assert.equal(document.elements.get("#scene-assessment-review-block").hidden, true);
  assert.equal(document.elements.get("#scene-assessment-limitations-block").hidden, true);
  assert.deepEqual(document.elements.get("#scene-assessment-evidence-used").children.map((badge) => badge.textContent), ["MODEL", "EVENT"]);
  await document.elements.get("#scene-previous").trigger("click");
  assert.equal(overlay.hidden, true);
  await document.elements.get("#scene-reveal-button").trigger("click");
  assert.equal(document.elements.get("#scene-assessment-overview").textContent, "The packaged scene predictions are mostly severe.");
  assert.equal(assessmentRequests.length, 3);
  assert.equal(predictRequests, 0);
  console.log("scene_page_integration=passed");
}

main();
