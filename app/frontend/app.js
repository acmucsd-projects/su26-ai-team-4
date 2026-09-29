const API_BASE_URL = "";
const PREDICT_URL = API_BASE_URL + "/predict";
const CLASS_ORDER = ["no-damage", "minor-damage", "major-damage", "destroyed"];

const EXAMPLES = {
  "no-damage": { label: "No damage", pre: "examples/no_damage/pre.png", post: "examples/no_damage/post.png" },
  "minor-damage": { label: "Minor damage", pre: "examples/minor_damage/pre.png", post: "examples/minor_damage/post.png" },
  "major-damage": { label: "Major damage", pre: "examples/major_damage/pre.png", post: "examples/major_damage/post.png" },
  destroyed: { label: "Destroyed", pre: "examples/destroyed/pre.png", post: "examples/destroyed/post.png" },
};

const state = { pre: null, post: null, previewUrls: { pre: null, post: null }, source: null, scenePrediction: null };
const assessmentCache = new Map();
const assessmentRequests = new Map();
let selectedAssessmentIdentity = null;
const preInput = document.querySelector("#pre-image");
const postInput = document.querySelector("#post-image");
const prePreview = document.querySelector("#pre-preview");
const postPreview = document.querySelector("#post-preview");
const prePlaceholder = document.querySelector("#pre-placeholder");
const postPlaceholder = document.querySelector("#post-placeholder");
const selectionLabel = document.querySelector("#selection-label");
const statusMessage = document.querySelector("#status-message");
const predictButton = document.querySelector("#predict-button");
const resultCard = document.querySelector("#result-card");
const resultClass = document.querySelector("#result-class");
const resultConfidence = document.querySelector("#result-confidence");
const resultBadge = document.querySelector("#result-badge");
const probabilityBars = document.querySelector("#probability-bars");
const buildingContext = document.querySelector("#building-context");
const contextClaims = document.querySelector("#context-claims");
const contextMore = document.querySelector("#context-more");
const contextSecondaryClaims = document.querySelector("#context-secondary-claims");
const contextAttribution = document.querySelector("#context-attribution");
const contextCategory = document.querySelector("#context-category");
const contextEvidence = document.querySelector("#context-evidence");
const contextNotes = document.querySelector("#context-notes");
const buildingAssessment = document.querySelector("#building-assessment");
const assessmentGenerateButton = document.querySelector("#assessment-generate-button");
const assessmentStatus = document.querySelector("#assessment-status");
const assessmentResult = document.querySelector("#assessment-result");
const assessmentModel = document.querySelector("#assessment-model");
const assessmentEvidenceUsed = document.querySelector("#assessment-evidence-used");
const assessmentSections = {
  assessment: { block: document.querySelector("#assessment-assessment-section"), content: document.querySelector("#assessment-assessment-text") },
  what_stands_out: { block: document.querySelector("#assessment-stands-out-section"), content: document.querySelector("#assessment-stands-out-text") },
  uncertainty: { block: document.querySelector("#assessment-uncertainty-section"), content: document.querySelector("#assessment-uncertainty-text") },
  context_interpretation: { block: document.querySelector("#assessment-context-section"), content: document.querySelector("#assessment-context-text") },
  suggested_review: { block: document.querySelector("#assessment-review-section"), content: document.querySelector("#assessment-review-text") },
  evidence_gaps: { block: document.querySelector("#assessment-gaps-section"), content: document.querySelector("#assessment-gaps-text") },
};
const assessmentLimitationsBlock = document.querySelector("#assessment-limitations-block");
const assessmentLimitations = document.querySelector("#assessment-limitations");
const ASSESSMENT_EVIDENCE_LABELS = {
  damage_prediction: "Damage prediction",
  class_probabilities: "4-class probabilities",
  reviewed_context: "Reviewed building context",
};

function clearAssessmentResult() {
  assessmentModel.textContent = "";
  assessmentModel.hidden = true;
  assessmentEvidenceUsed.textContent = "";
  assessmentEvidenceUsed.hidden = true;
  Object.values(assessmentSections).forEach(({ block, content }) => {
    block.hidden = true;
    content.textContent = "";
  });
  assessmentLimitations.replaceChildren();
  assessmentLimitationsBlock.hidden = true;
}

function assessmentModelLabel(generatedBy) {
  if (typeof generatedBy !== "string" || generatedBy.length > 120) return "";
  const modelId = generatedBy.split("/").pop();
  if (!modelId || !/^[A-Za-z0-9._-]+$/.test(modelId)) return "";
  const words = modelId.split(/[-_]+/).filter(Boolean).map((word) =>
    word.toLowerCase() === "gpt" ? "GPT" : word.charAt(0).toUpperCase() + word.slice(1)
  );
  if (words[0] === "GPT" && /^\d/.test(words[1] || "")) words[1] = "-" + words[1];
  return words.join(" ").replace("GPT -", "GPT-");
}

function renderAssessmentResult(result) {
  clearAssessmentResult();
  Object.entries(assessmentSections).forEach(([field, elements]) => {
    const value = typeof result[field] === "string" ? result[field].trim() : "";
    if (!value) return;
    elements.content.textContent = value;
    elements.block.hidden = false;
  });
  result.limitations.forEach((limitation) => {
    const item = document.createElement("li");
    item.textContent = limitation;
    assessmentLimitations.append(item);
  });
  assessmentLimitationsBlock.hidden = result.limitations.length === 0;
  const modelLabel = assessmentModelLabel(result.generated_by);
  if (modelLabel) {
    assessmentModel.textContent = modelLabel + " · Evidence-grounded assessment";
    assessmentModel.hidden = false;
  }
  const evidenceLabels = result.evidence_used
    .filter((item) => Object.prototype.hasOwnProperty.call(ASSESSMENT_EVIDENCE_LABELS, item))
    .map((item) => ASSESSMENT_EVIDENCE_LABELS[item]);
  if (evidenceLabels.length) {
    assessmentEvidenceUsed.textContent = "Evidence used: " + evidenceLabels.join(" · ");
    assessmentEvidenceUsed.hidden = false;
  }
}

function normalizedAssessmentResult(body) {
  return {
    assessment: typeof body.assessment === "string" ? body.assessment.trim() : "",
    what_stands_out: body.what_stands_out,
    uncertainty: body.uncertainty,
    context_interpretation: body.context_interpretation,
    suggested_review: body.suggested_review,
    evidence_gaps: body.evidence_gaps,
    limitations: Array.isArray(body.limitations)
      ? body.limitations.filter((item) => typeof item === "string" && item.trim()).map((item) => item.trim())
      : [],
    generated_by: typeof body.generated_by === "string" ? body.generated_by.trim() : "",
    evidence_used: Array.isArray(body.evidence_used) ? body.evidence_used : [],
  };
}

function assessmentIdentity(sceneId, buildingId) {
  return JSON.stringify([sceneId, buildingId]);
}

function resetAssessmentView() {
  selectedAssessmentIdentity = null;
  buildingAssessment.hidden = true;
  assessmentGenerateButton.disabled = false;
  assessmentGenerateButton.hidden = false;
  assessmentStatus.textContent = "";
  assessmentStatus.classList.remove("error");
  assessmentResult.hidden = true;
  clearAssessmentResult();
}

function renderAssessment(identity) {
  const cached = assessmentCache.get(identity);
  const pending = assessmentRequests.has(identity);
  buildingAssessment.hidden = false;
  assessmentStatus.classList.remove("error");
  assessmentStatus.textContent = "";
  assessmentResult.hidden = true;
  clearAssessmentResult();
  if (cached) {
    assessmentGenerateButton.hidden = true;
    assessmentGenerateButton.disabled = false;
    assessmentResult.hidden = false;
    renderAssessmentResult(cached);
    return;
  }
  assessmentGenerateButton.hidden = false;
  assessmentGenerateButton.disabled = pending;
  if (pending) assessmentStatus.textContent = "Generating assessment…";
}

function sceneIdForBuilding(building, sceneId) {
  if (typeof sceneId === "string" && sceneId.trim()) return sceneId;
  const match = typeof building?.id === "string" ? building.id.match(/^(.*)_b\d+$/) : null;
  return match?.[1] || "";
}

async function generateAssessment() {
  const identity = selectedAssessmentIdentity;
  if (!identity || assessmentCache.has(identity) || assessmentRequests.has(identity)) return;
  const [sceneId, buildingId] = JSON.parse(identity);
  assessmentRequests.set(identity, true);
  renderAssessment(identity);
  let failureMessage = "";
  try {
    const url = "/demo-scenes/" + encodeURIComponent(sceneId) + "/buildings/" + encodeURIComponent(buildingId) + "/assessment";
    const response = await fetch(url, { method: "POST" });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      failureMessage = body?.detail?.code === "assessment_provider_unavailable"
        ? "AI assessment is currently unavailable."
        : "Assessment could not be generated. Try again.";
    } else if (typeof body?.assessment !== "string" || !body.assessment.trim()) {
      failureMessage = "Assessment could not be generated. Try again.";
    } else {
      assessmentCache.set(identity, normalizedAssessmentResult(body));
    }
  } catch (_error) {
    failureMessage = "Assessment could not be generated. Try again.";
  } finally {
    assessmentRequests.delete(identity);
    if (selectedAssessmentIdentity === identity) {
      renderAssessment(identity);
      if (failureMessage) {
        assessmentStatus.textContent = failureMessage;
        assessmentStatus.classList.add("error");
      }
    }
  }
}

function clearBuildingContext() {
  buildingContext.hidden = true;
  contextClaims.replaceChildren();
  contextSecondaryClaims.replaceChildren();
  contextEvidence.replaceChildren();
  contextCategory.textContent = "";
  contextNotes.textContent = "";
  contextNotes.hidden = true;
  buildingContext.classList.remove("area-only");
  contextMore.hidden = true;
  contextMore.open = false;
  contextAttribution.hidden = true;
}

function showBuildingContext(context) {
  clearBuildingContext();
  if (context?.version !== 2) return;
  const claims = Array.isArray(context.claims) ? context.claims.filter((claim) =>
    claim?.displayable === true && ["id", "title", "original_value", "source", "timing"].every((key) =>
      typeof claim[key] === "string" && claim[key].trim())) : [];
  if (!claims.length) return;
  const claimIds = new Set(claims.map((claim) => claim.id));
  const statements = Array.isArray(context.statements) ? context.statements.filter((statement) =>
    ["id", "label", "text", "temporal_label"].every((key) => typeof statement?.[key] === "string") &&
    Array.isArray(statement.supporting_claims) && statement.supporting_claims.length &&
    statement.supporting_claims.every((id) => claimIds.has(id)) &&
    Array.isArray(statement.corroborating_claims) && statement.corroborating_claims.every((id) => claimIds.has(id))) : [];
  const primaryIds = new Set(context.primary_statement_ids || []);
  if (!statements.some((statement) => primaryIds.has(statement.id))) return;
  contextCategory.textContent = context.primary_label;
  buildingContext.classList.toggle("area-only", context.area_only === true);
  statements.forEach((statement) => {
    const row = document.createElement("li");
    const description = document.createElement("p");
    const label = document.createElement("span");
    label.className = "context-label";
    label.textContent = statement.label + ": ";
    const value = document.createElement("span");
    value.className = "context-value";
    value.textContent = statement.text;
    description.append(label, value);
    const timing = document.createElement("p");
    timing.className = "context-timing";
    timing.textContent = statement.temporal_label;
    row.append(description, timing);
    if (statement.has_multiple_sources) {
      const support = document.createElement("p");
      support.className = "context-support";
      support.textContent = statement.support_label || "Supporting evidence from multiple sources";
      row.append(support);
    }
    (primaryIds.has(statement.id) ? contextClaims : contextSecondaryClaims).append(row);
  });
  // Group repetitive source rows for reading; each claim remains in the API.
  const evidenceGroups = new Map();
  claims.forEach((claim) => {
    const key = [claim.source_key, claim.title, claim.timing, claim.qualifier].join("|");
    if (!evidenceGroups.has(key)) evidenceGroups.set(key, { ...claim, originals: [] });
    const originals = evidenceGroups.get(key).originals;
    if (!originals.includes(claim.original_value)) originals.push(claim.original_value);
  });
  evidenceGroups.forEach((claim) => {
    const row = document.createElement("li");
    const source = document.createElement("p");
    source.className = "context-source";
    source.textContent = claim.source + " · " + claim.title;
    const timing = document.createElement("p");
    timing.textContent = claim.timing;
    const original = document.createElement("p");
    original.textContent = "Source wording: “" + claim.originals.join("”; “") + "”";
    row.append(source, timing, original);
    if (claim.qualifier) {
      const qualifier = document.createElement("p");
      qualifier.textContent = claim.qualifier;
      row.append(qualifier);
    }
    contextEvidence.append(row);
  });
  contextNotes.textContent = Array.isArray(context.notes) ? context.notes.join(" ") : "";
  contextNotes.hidden = !contextNotes.textContent;
  contextMore.hidden = false;
  contextAttribution.hidden = !claims.some((claim) => claim.osm === true);
  buildingContext.hidden = false;
}

function setStatus(message = "", isError = false) {
  statusMessage.textContent = message;
  statusMessage.classList.toggle("error", isError);
}

function clearPreview(slot) {
  const preview = slot === "pre" ? prePreview : postPreview;
  const placeholder = slot === "pre" ? prePlaceholder : postPlaceholder;
  if (state.previewUrls[slot]) {
    URL.revokeObjectURL(state.previewUrls[slot]);
    state.previewUrls[slot] = null;
  }
  preview.removeAttribute("src");
  preview.hidden = true;
  placeholder.hidden = false;
}

function showPreview(slot, source, isObjectUrl = false) {
  const preview = slot === "pre" ? prePreview : postPreview;
  const placeholder = slot === "pre" ? prePlaceholder : postPlaceholder;
  clearPreview(slot);
  if (isObjectUrl) state.previewUrls[slot] = source;
  preview.src = source;
  preview.hidden = false;
  placeholder.hidden = true;
}

function clearSceneBuildingSelection() {
  document.dispatchEvent(new Event("scene-building-clear"));
}

function leaveSceneSelectionForManualInput() {
  if (state.source !== "scene") return;
  state.pre = null;
  state.post = null;
  clearPreview("pre");
  clearPreview("post");
  resultCard.hidden = true;
  clearSceneBuildingSelection();
}

function setManualFile(slot, file) {
  if (!file) return;
  resetAssessmentView();
  clearBuildingContext();
  leaveSceneSelectionForManualInput();
  state[slot] = { file, name: file.name };
  state.source = "custom";
  state.scenePrediction = null;
  showPreview(slot, URL.createObjectURL(file), true);
  document.querySelectorAll(".example-button").forEach((button) => button.classList.remove("selected"));
  selectionLabel.textContent = "Custom upload";
  resultCard.hidden = true;
  setStatus("");
}

function selectExample(name) {
  const example = EXAMPLES[name];
  resetAssessmentView();
  clearBuildingContext();
  clearSceneBuildingSelection();
  state.pre = { assetUrl: example.pre, name: name + "-pre.png" };
  state.post = { assetUrl: example.post, name: name + "-post.png" };
  state.source = "example";
  state.scenePrediction = null;
  preInput.value = "";
  postInput.value = "";
  showPreview("pre", example.pre);
  showPreview("post", example.post);
  document.querySelectorAll(".example-button").forEach((button) => {
    button.classList.toggle("selected", button.dataset.example === name);
  });
  selectionLabel.textContent = example.label;
  resultCard.hidden = true;
  setStatus("");
}

async function uploadFor(input) {
  if (input.file) return input.file;
  const response = await fetch(input.assetUrl);
  if (!response.ok) throw new Error("Could not load built-in example (" + response.status + ").");
  const blob = await response.blob();
  return new File([blob], input.name, { type: blob.type || "image/png" });
}

function showResult(prediction, sourceLabel = "Prediction") {
  resultClass.textContent = prediction.predicted_class.replace("-", " ");
  resultConfidence.textContent = (prediction.confidence * 100).toFixed(1) + "% confidence";
  resultBadge.textContent = sourceLabel;
  probabilityBars.replaceChildren();
  CLASS_ORDER.forEach((className) => {
    const probability = Number(prediction.probabilities[className] || 0);
    const row = document.createElement("div");
    row.className = "probability-row";
    const label = document.createElement("span");
    label.textContent = className.replace("-", " ");
    const track = document.createElement("div");
    track.className = "probability-track";
    const fill = document.createElement("div");
    fill.className = "probability-fill";
    fill.style.width = (Math.max(0, Math.min(1, probability)) * 100) + "%";
    track.append(fill);
    const value = document.createElement("span");
    value.className = "probability-value";
    value.textContent = (probability * 100).toFixed(1) + "%";
    row.append(label, track, value);
    probabilityBars.append(row);
  });
  resultCard.hidden = false;
}

function inspectSceneBuilding(building, sceneId) {
  const preUrl = building?.crops?.pre_url;
  const postUrl = building?.crops?.post_url;
  const prediction = building?.prediction;
  if (!preUrl || !postUrl || !prediction?.predicted_class || !prediction?.probabilities) return false;

  state.pre = { assetUrl: preUrl, name: building.id + "-pre.png" };
  state.post = { assetUrl: postUrl, name: building.id + "-post.png" };
  state.source = "scene";
  state.scenePrediction = prediction;
  preInput.value = "";
  postInput.value = "";
  showPreview("pre", preUrl);
  showPreview("post", postUrl);
  document.querySelectorAll(".example-button").forEach((button) => button.classList.remove("selected"));
  selectionLabel.textContent = "Scene selection";
  showResult(prediction, "Scene selection");
  showBuildingContext(building.building_context);
  const selectedSceneId = sceneIdForBuilding(building, sceneId);
  selectedAssessmentIdentity = selectedSceneId ? assessmentIdentity(selectedSceneId, building.id) : null;
  if (selectedAssessmentIdentity) renderAssessment(selectedAssessmentIdentity);
  else resetAssessmentView();
  setStatus("Viewing precomputed scene result for " + building.id + ".");
  return true;
}

async function predictDamage() {
  if (!state.pre || !state.post) {
    setStatus("Choose a built-in example or upload both PRE and POST images.", true);
    return;
  }
  if (state.source === "scene" && state.scenePrediction) {
    showResult(state.scenePrediction, "Scene selection");
    setStatus("Showing the precomputed prediction for the selected scene building.");
    return;
  }
  predictButton.disabled = true;
  predictButton.querySelector("span").textContent = "Analyzing pair…";
  setStatus("Sending the paired crops to the classifier…");
  resultCard.hidden = true;
  try {
    const files = await Promise.all([uploadFor(state.pre), uploadFor(state.post)]);
    const formData = new FormData();
    formData.append("pre_image", files[0]);
    formData.append("post_image", files[1]);
    const response = await fetch(PREDICT_URL, { method: "POST", body: formData });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || "The classifier returned HTTP " + response.status + ".");
    showResult(body);
    setStatus("Prediction complete.");
  } catch (error) {
    setStatus("Could not run prediction: " + error.message, true);
  } finally {
    predictButton.disabled = false;
    predictButton.querySelector("span").textContent = "Predict damage";
  }
}

function clearSelection() {
  resetAssessmentView();
  clearBuildingContext();
  clearSceneBuildingSelection();
  state.pre = null;
  state.post = null;
  state.source = null;
  state.scenePrediction = null;
  preInput.value = "";
  postInput.value = "";
  clearPreview("pre");
  clearPreview("post");
  document.querySelectorAll(".example-button").forEach((button) => button.classList.remove("selected"));
  selectionLabel.textContent = "No pair selected";
  resultCard.hidden = true;
  setStatus("");
}

document.addEventListener("scene-building-selected", (event) => {
  const selection = event.detail;
  if (!selection || typeof selection !== "object") return;
  selection.handled = true;
  if (!inspectSceneBuilding(selection.building, selection.scene_id)) event.preventDefault();
});

document.addEventListener("scene-changed", () => {
  if (state.source === "scene") clearSelection();
});

document.addEventListener("scene-building-filtered-out", () => {
  if (state.source === "scene") clearSelection();
});

preInput.addEventListener("change", () => setManualFile("pre", preInput.files[0]));
postInput.addEventListener("change", () => setManualFile("post", postInput.files[0]));
document.querySelectorAll(".example-button").forEach((button) => {
  button.addEventListener("click", () => selectExample(button.dataset.example));
});
document.querySelector("#clear-selection").addEventListener("click", clearSelection);
predictButton.addEventListener("click", predictDamage);
assessmentGenerateButton.addEventListener("click", generateAssessment);
