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
    this.disabled = false;
    this.style = {};
    this.value = "";
    this.files = [];
    this.textContent = "";
    this._classes = new Set();
    this.classList = {
      add: (...classes) => classes.forEach((name) => this._classes.add(name)),
      remove: (...classes) => classes.forEach((name) => this._classes.delete(name)),
      toggle: (name, force) => {
        if (force === true || (force === undefined && !this._classes.has(name))) this._classes.add(name);
        else this._classes.delete(name);
      },
      contains: (name) => this._classes.has(name),
    };
  }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name); }
  removeAttribute(name) { this.attributes.delete(name); if (name === "src") this._src = undefined; }
  replaceChildren(...children) { this.children = [...children]; }
  append(...children) { this.children.push(...children); }
  addEventListener(type, listener) { this.listeners.set(type, listener); }
  trigger(type) { return this.listeners.get(type)?.({ preventDefault() {} }); }
  querySelector(selector) { return selector === "span" ? (this.buttonLabel || (this.buttonLabel = new FakeElement())) : undefined; }
  set src(value) { this._src = value; }
  get src() { return this._src; }
}

function createDocument() {
  const ids = [
    "#pre-image", "#post-image", "#pre-preview", "#post-preview", "#pre-placeholder", "#post-placeholder",
    "#inspector-empty", "#inspector-content", "#inspector-context-pill", "#comparison", "#comparison-range",
    "#selection-label", "#status-message", "#predict-button", "#result-card", "#result-class",
    "#result-confidence", "#result-badge", "#probability-bars", "#clear-selection",
    "#building-context", "#context-claims", "#context-more", "#context-more-label", "#context-secondary-claims",
    "#context-attribution", "#context-category", "#context-evidence", "#context-notes",
    "#building-assessment", "#assessment-generate-button", "#assessment-status", "#assessment-result",
    "#assessment-model", "#assessment-text", "#assessment-review-block", "#assessment-review-text",
    "#assessment-evidence-details", "#assessment-evidence-used", "#assessment-supporting-block",
    "#assessment-supporting-details", "#assessment-limitations-block", "#assessment-limitations",
    "#scene-assessment", "#scene-assessment-generate-button", "#scene-assessment-status", "#scene-assessment-result",
    "#scene-assessment-model", "#scene-assessment-overview", "#scene-assessment-findings-block", "#scene-assessment-findings",
    "#scene-assessment-review-block", "#scene-assessment-review", "#scene-assessment-details", "#scene-assessment-evidence-used",
    "#scene-assessment-limitations-block", "#scene-assessment-limitations",
  ];
  const elements = new Map(ids.map((id) => [id, new FakeElement()]));
  elements.get("#assessment-generate-button").textContent = "Generate assessment";
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
    addEventListener(type, listener) { listeners.set(type, [...(listeners.get(type) || []), listener]); },
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

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

async function main() {
  const document = createDocument();
  const requests = [];
  const queuedResponses = [];
  const fetch = async (url, options) => {
    requests.push({ url, options });
    const response = queuedResponses.shift();
    if (!response) throw new Error("Unexpected assessment request");
    return typeof response === "function" ? response() : response;
  };
  const response = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
  const context = {
    Array, CustomEvent: PageEvent, Error, Event: PageEvent, FormData: class {}, Math, Number, Promise,
    URL: { createObjectURL() { return "blob:manual"; }, revokeObjectURL() {} }, document, fetch,
  };
  const source = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
  vm.runInNewContext(source, context);
  assert.doesNotMatch(source, /OPENAI_API_KEY|api\.openai\.com|openai-sdk/i);

  const buildingA = {
    id: "hurricane-michael_00000247_b0001",
    crops: { pre_url: "/a-pre.png", post_url: "/a-post.png" },
    prediction: { predicted_class: "major-damage", confidence: 0.8, probabilities: { "no-damage": 0.05, "minor-damage": 0.1, "major-damage": 0.8, destroyed: 0.05 } },
    building_context: { version: 2, primary_label: "Residential", primary_statement_ids: ["s1"], claims: [
      { id: "c1", title: "Use", original_value: "House", source: "Review", source_key: "review", timing: "Reviewed context", displayable: true },
    ], statements: [{ id: "s1", label: "Use", text: "Residential building", temporal_label: "Reviewed", supporting_claims: ["c1"], corroborating_claims: [] }] },
  };
  const buildingB = {
    id: "hurricane-harvey_00000177_b0002",
    crops: { pre_url: "/b-pre.png", post_url: "/b-post.png" },
    prediction: { predicted_class: "no-damage", confidence: 0.9, probabilities: { "no-damage": 0.9, "minor-damage": 0.05, "major-damage": 0.03, destroyed: 0.02 } },
  };

  const select = (building, sceneId) => {
    const event = { type: "scene-building-selected", detail: { scene_id: sceneId, building, handled: false }, defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; } };
    document.dispatchEvent(event);
    assert.equal(event.detail.handled, true);
  };
  const el = (id) => document.elements.get(id);

  // A: Selecting a GIS-context building offers an explicit action and makes no request.
  select(buildingA, "hurricane-michael_00000247");
  assert.equal(el("#building-context").hidden, false);
  assert.equal(el("#building-assessment").hidden, false);
  assert.equal(el("#assessment-generate-button").textContent, "Generate assessment");
  assert.equal(requests.length, 0);

  // B/C: One explicit click posts to the selected scene/building and locks out duplicates.
  const pending = deferred();
  queuedResponses.push(() => pending.promise);
  const firstClick = el("#assessment-generate-button").trigger("click");
  el("#assessment-generate-button").trigger("click");
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "/demo-scenes/hurricane-michael_00000247/buildings/hurricane-michael_00000247_b0001/assessment");
  assert.equal(requests[0].options.method, "POST");
  assert.equal(requests[0].options.body, undefined);
  assert.equal(el("#assessment-generate-button").disabled, true);
  assert.equal(el("#assessment-status").textContent, "Generating assessment…");
  pending.resolve(response(200, {
    assessment: "The classifier favors Major Damage, with Minor Damage as the next interpretation. Current modeled residential occupancy describes context but does not verify event-time building use.",
    recommended_review: "Compare PRE/POST roof and structural changes to distinguish Major from Minor; the assessment model has not viewed the crops.",
    supporting_details: ["The GIS occupancy value is modeled and current."],
    limitations: ["Prediction is not verified ground truth."],
    generated_by: "openai/gpt-6-luna",
    evidence_used: ["model", "spatial", "event", "reviewed_gis", "image"],
  }));
  await firstClick;
  assert.equal(el("#assessment-result").hidden, false);
  assert.match(el("#assessment-text").textContent, /classifier favors Major Damage/);
  assert.equal(el("#assessment-review-block").hidden, false);
  assert.match(el("#assessment-review-text").textContent, /distinguish Major from Minor/);
  assert.equal(el("#assessment-model").textContent, "GPT-6 Luna · Evidence-grounded assessment");
  assert.equal(el("#assessment-evidence-details").hidden, false);
  assert.equal(el("#assessment-evidence-details").open, false);
  assert.deepEqual(el("#assessment-evidence-used").children.map((badge) => badge.textContent), ["MODEL", "SPATIAL", "EVENT", "GIS"]);
  assert.doesNotMatch(el("#assessment-evidence-used").getAttribute("aria-label"), /IMAGE/);
  assert.equal(el("#assessment-supporting-block").hidden, false);
  assert.equal(el("#assessment-supporting-details").children.length, 1);
  assert.equal(el("#assessment-limitations-block").hidden, false);
  assert.equal(el("#assessment-limitations").children.length, 1);
  assert.equal(el("#assessment-generate-button").hidden, true);

  // G: Switching buildings clears the visible previous answer; H: returning restores it from memory.
  select(buildingB, "hurricane-harvey_00000177");
  assert.equal(el("#assessment-result").hidden, true);
  assert.equal(el("#assessment-text").textContent, "");
  assert.equal(el("#assessment-model").hidden, true);
  assert.equal(el("#assessment-review-block").hidden, true);
  assert.equal(el("#assessment-evidence-details").hidden, true);
  assert.equal(el("#assessment-generate-button").hidden, false);
  // I: No-GIS buildings still have an enabled generation action.
  assert.equal(el("#building-context").hidden, true);
  assert.equal(el("#assessment-generate-button").disabled, false);
  select(buildingA, "hurricane-michael_00000247");
  assert.equal(el("#assessment-text").textContent, "The classifier favors Major Damage, with Minor Damage as the next interpretation. Current modeled residential occupancy describes context but does not verify event-time building use.");
  assert.match(el("#assessment-review-text").textContent, /distinguish Major from Minor/);
  assert.equal(el("#assessment-model").textContent, "GPT-6 Luna · Evidence-grounded assessment");
  assert.deepEqual(el("#assessment-evidence-used").children.map((badge) => badge.textContent), ["MODEL", "SPATIAL", "EVENT", "GIS"]);
  assert.equal(requests.length, 1);

  // F: A successful empty limitations array omits that subsection.
  select(buildingB, "hurricane-harvey_00000177");
  queuedResponses.push(response(200, {
    assessment: "The model predicts no damage.", recommended_review: null, supporting_details: [], limitations: [],
    generated_by: "openai/alternate-model-v2",
    evidence_used: ["model", "spatial", "event"],
  }));
  await el("#assessment-generate-button").trigger("click");
  assert.equal(requests.length, 2);
  assert.equal(el("#assessment-text").textContent, "The model predicts no damage.");
  assert.equal(el("#assessment-review-block").hidden, true);
  assert.equal(el("#assessment-model").textContent, "Alternate Model V2 · Evidence-grounded assessment");
  assert.deepEqual(el("#assessment-evidence-used").children.map((badge) => badge.textContent), ["MODEL", "SPATIAL", "EVENT"]);
  assert.equal(el("#assessment-limitations-block").hidden, true);
  assert.equal(el("#assessment-limitations").children.length, 0);
  assert.equal(el("#assessment-evidence-details").open, false);

  // J: Unavailable responses are safely described, retryable, and not cached.
  const buildingC = { ...buildingB, id: "hurricane-harvey_00000177_b0003" };
  select(buildingC, "hurricane-harvey_00000177");
  queuedResponses.push(response(503, { detail: { code: "assessment_provider_unavailable", message: "secret detail" } }));
  await el("#assessment-generate-button").trigger("click");
  assert.equal(el("#assessment-status").textContent, "AI assessment is currently unavailable.");
  assert.equal(el("#assessment-generate-button").disabled, false);
  assert.doesNotMatch(el("#assessment-status").textContent, /secret|provider_unavailable/);
  queuedResponses.push(response(200, { assessment: "A retry succeeded.", limitations: [], evidence_used: ["model", "spatial"] }));
  await el("#assessment-generate-button").trigger("click");
  assert.equal(requests.length, 4);
  assert.equal(el("#assessment-text").textContent, "A retry succeeded.");

  const buildingD = { ...buildingB, id: "hurricane-harvey_00000177_b0004" };
  select(buildingD, "hurricane-harvey_00000177");
  queuedResponses.push(() => Promise.reject(new Error("private provider detail")));
  await el("#assessment-generate-button").trigger("click");
  assert.equal(el("#assessment-status").textContent, "Assessment could not be generated. Try again.");
  assert.doesNotMatch(el("#assessment-status").textContent, /private|provider detail/);
  assert.equal(el("#assessment-generate-button").disabled, false);
  queuedResponses.push(response(200, { assessment: "The retry worked after a temporary failure.", limitations: [], evidence_used: ["model", "spatial"] }));
  await el("#assessment-generate-button").trigger("click");
  assert.equal(requests.length, 6);
  assert.equal(el("#assessment-text").textContent, "The retry worked after a temporary failure.");

  // K: Existing filter-driven clearing also clears assessment UI.
  document.dispatchEvent(new PageEvent("scene-building-filtered-out"));
  assert.equal(el("#building-assessment").hidden, true);
  assert.equal(el("#assessment-text").textContent, "");
  assert.equal(el("#assessment-evidence-used").hidden, true);

  // Switching scenes clears the inspector, while manual examples remain independent.
  select(buildingA, "hurricane-michael_00000247");
  document.dispatchEvent(new PageEvent("scene-changed"));
  assert.equal(el("#building-assessment").hidden, true);
  document.querySelectorAll(".example-button")[0].trigger("click");
  assert.equal(el("#building-assessment").hidden, true);
  assert.equal(requests.length, 6);
  console.log("assessment_ui=passed");
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
