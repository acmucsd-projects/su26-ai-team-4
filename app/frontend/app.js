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
const sceneAssessmentCache = new Map();
const sceneAssessmentRequests = new Map();
const sceneAssessmentBuildingIds = new Map();
let selectedAssessmentIdentity = null;
let activeSceneOverviewId = null;
let activeSceneBuildingIds = new Set();
const preInput = document.querySelector("#pre-image");
const postInput = document.querySelector("#post-image");
const prePreview = document.querySelector("#pre-preview");
const postPreview = document.querySelector("#post-preview");
const prePlaceholder = document.querySelector("#pre-placeholder");
const postPlaceholder = document.querySelector("#post-placeholder");
const selectionLabel = document.querySelector("#selection-label");
const inspectorEmpty = document.querySelector("#inspector-empty");
const inspectorContent = document.querySelector("#inspector-content");
const inspectorContextPill = document.querySelector("#inspector-context-pill");
const comparison = document.querySelector("#comparison");
const comparisonRange = document.querySelector("#comparison-range");
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
const assessmentText = document.querySelector("#assessment-text");
const assessmentReviewBlock = document.querySelector("#assessment-review-block");
const assessmentReviewText = document.querySelector("#assessment-review-text");
const assessmentEvidenceDetails = document.querySelector("#assessment-evidence-details");
const assessmentEvidenceUsed = document.querySelector("#assessment-evidence-used");
const assessmentSupportingBlock = document.querySelector("#assessment-supporting-block");
const assessmentSupportingDetails = document.querySelector("#assessment-supporting-details");
const assessmentLimitationsBlock = document.querySelector("#assessment-limitations-block");
const assessmentLimitations = document.querySelector("#assessment-limitations");
const sceneAssessment = document.querySelector("#scene-assessment");
const sceneAssessmentGenerateButton = document.querySelector("#scene-assessment-generate-button");
const sceneAssessmentStatus = document.querySelector("#scene-assessment-status");
const sceneAssessmentResult = document.querySelector("#scene-assessment-result");
const sceneAssessmentModel = document.querySelector("#scene-assessment-model");
const sceneAssessmentOverview = document.querySelector("#scene-assessment-overview");
const sceneAssessmentFindingsBlock = document.querySelector("#scene-assessment-findings-block");
const sceneAssessmentFindings = document.querySelector("#scene-assessment-findings");
const sceneAssessmentReviewBlock = document.querySelector("#scene-assessment-review-block");
const sceneAssessmentReview = document.querySelector("#scene-assessment-review");
const sceneAssessmentDetails = document.querySelector("#scene-assessment-details");
const sceneAssessmentEvidenceUsed = document.querySelector("#scene-assessment-evidence-used");
const sceneAssessmentLimitationsBlock = document.querySelector("#scene-assessment-limitations-block");
const sceneAssessmentLimitations = document.querySelector("#scene-assessment-limitations");
const ASSESSMENT_EVIDENCE_LABELS = {
  model: "MODEL",
  spatial: "SPATIAL",
  event: "EVENT",
  reviewed_gis: "GIS",
};
const SCENE_ASSESSMENT_EVIDENCE_LABELS = {
  model: "MODEL",
  spatial: "SPATIAL",
  event: "EVENT",
  reviewed_gis: "GIS",
};
const BUILDING_ID_PATTERN = /\b[A-Za-z0-9][A-Za-z0-9_-]*_b\d+\b/;

function renderEvidenceBadges(target, evidence, labels) {
  const valid = [...new Set(evidence.filter((item) => Object.prototype.hasOwnProperty.call(labels, item)))];
  target.replaceChildren();
  valid.forEach((item) => {
    const badge = document.createElement("span");
    badge.className = "evidence-badge " + (item === "reviewed_gis" ? "gis" : item);
    badge.textContent = labels[item];
    if (item === "reviewed_gis") badge.title = "Reviewed GIS context";
    target.append(badge);
  });
  target.hidden = valid.length === 0;
  if (valid.length) target.setAttribute("aria-label", "Evidence synthesized: " + valid.map((item) => labels[item]).join(", "));
  else target.removeAttribute("aria-label");
  return valid.length;
}

function clearSceneAssessmentResult() {
  sceneAssessmentModel.textContent = "";
  sceneAssessmentModel.hidden = true;
  sceneAssessmentOverview.textContent = "";
  sceneAssessmentFindings.replaceChildren();
  sceneAssessmentFindingsBlock.hidden = true;
  sceneAssessmentReview.textContent = "";
  sceneAssessmentReviewBlock.hidden = true;
  sceneAssessmentDetails.open = false;
  sceneAssessmentDetails.hidden = true;
  sceneAssessmentEvidenceUsed.replaceChildren();
  sceneAssessmentEvidenceUsed.hidden = true;
  sceneAssessmentLimitations.replaceChildren();
  sceneAssessmentLimitationsBlock.hidden = true;
}

function resetSceneAssessmentView() {
  sceneAssessmentGenerateButton.disabled = false;
  sceneAssessmentGenerateButton.hidden = false;
  sceneAssessmentStatus.textContent = "";
  sceneAssessmentStatus.classList.remove("error");
  sceneAssessmentResult.hidden = true;
  clearSceneAssessmentResult();
}

function normalizeSceneAssessmentResult(body, buildingIds) {
  const overview = typeof body?.overview === "string" ? body.overview.trim() : "";
  const recommendedReview = typeof body?.recommended_review === "string" ? body.recommended_review.trim() : "";
  const generatedBy = typeof body?.generated_by === "string" ? body.generated_by.trim() : "";
  if (!overview || overview.length > 1200 || !generatedBy || generatedBy.length > 120 || BUILDING_ID_PATTERN.test(overview)) return null;
  if (recommendedReview.length > 500 || BUILDING_ID_PATTERN.test(recommendedReview)) return null;

  const candidateBuildings = body?.candidate_buildings;
  const validCandidateBuildings = new Map();
  if (candidateBuildings && typeof candidateBuildings === "object" && !Array.isArray(candidateBuildings)) {
    Object.entries(candidateBuildings).forEach(([key, rawBuildingIds]) => {
      const ids = Array.isArray(rawBuildingIds) ? [...new Set(rawBuildingIds)] : [];
      if (/^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/.test(key) && ids.length > 0 && ids.every((id) => typeof id === "string" && buildingIds.has(id))) {
        validCandidateBuildings.set(key, ids);
      }
    });
  }
  const findings = [];
  if (Array.isArray(body?.findings)) {
    body.findings.slice(0, 4).forEach((finding) => {
      const title = typeof finding?.title === "string" ? finding.title.trim() : "";
      const explanation = typeof finding?.explanation === "string" ? finding.explanation.trim() : "";
      const candidateKeys = Array.isArray(finding?.candidate_keys) ? finding.candidate_keys : [];
      if (!title || title.length > 100 || !explanation || explanation.length > 500 ||
          BUILDING_ID_PATTERN.test(title) || BUILDING_ID_PATTERN.test(explanation) ||
          candidateKeys.length > 3 || candidateKeys.some((key) => !validCandidateBuildings.has(key))) return;
      findings.push({ title, explanation, candidate_keys: [...new Set(candidateKeys)] });
    });
  }
  const limitations = Array.isArray(body?.limitations)
    ? body.limitations.filter((item) => typeof item === "string" && item.trim() && item.length <= 300 && !BUILDING_ID_PATTERN.test(item)).slice(0, 4).map((item) => item.trim())
    : [];
  const evidenceUsed = Array.isArray(body?.evidence_used) ? body.evidence_used : [];
  const candidateTypes = body?.candidate_types && typeof body.candidate_types === "object" && !Array.isArray(body.candidate_types)
    ? Object.fromEntries(Object.entries(body.candidate_types).filter(([key, type]) => validCandidateBuildings.has(key) && typeof type === "string"))
    : {};
  return { overview, findings, recommended_review: recommendedReview, limitations, generated_by: generatedBy, evidence_used: evidenceUsed, candidate_buildings: Object.fromEntries(validCandidateBuildings), candidate_types: candidateTypes };
}

function sceneFindingTypeLabel(type, buildingCount) {
  const labels = {
    AMBIGUOUS_CLASS_PAIR: "Ambiguous prediction",
    HIGH_CONFIDENCE_SEVERE: "High-confidence severe prediction",
    LOCAL_SEVERITY_OUTLIER: "Local contrast",
    LOCAL_LOW_DAMAGE_OUTLIER: "Local contrast",
    LOCAL_CLASS_DISAGREEMENT: "Local contrast",
    SEVERE_PROXIMITY_GROUP: "Severe proximity group",
    MULTI_BUILDING_SITE: "Reviewed multi-building site",
    CONTEXT_RICH_SEVERE: "Context-rich building",
    GIS_SCOPE_CONFLICT: "GIS context qualification",
    REPRESENTATIVE_SEVERE: "Severe prediction",
    REPRESENTATIVE_LOW_DAMAGE: "Lower-damage prediction",
  };
  const label = labels[type] || (typeof type === "string" ? type.replaceAll("_", " ").toLowerCase() : "Scene pattern");
  return buildingCount > 1 ? label + " · " + buildingCount + " buildings" : label;
}

function sceneFindingCategory(type) {
  if (type === "AMBIGUOUS_CLASS_PAIR") return "ambiguity";
  if (["LOCAL_SEVERITY_OUTLIER", "LOCAL_LOW_DAMAGE_OUTLIER", "LOCAL_CLASS_DISAGREEMENT"].includes(type)) return "spatial";
  if (["SEVERE_PROXIMITY_GROUP", "HIGH_CONFIDENCE_SEVERE", "REPRESENTATIVE_SEVERE"].includes(type)) return "severe";
  if (["MULTI_BUILDING_SITE", "CONTEXT_RICH_SEVERE", "GIS_SCOPE_CONFLICT"].includes(type)) return "gis";
  return "event";
}

function sceneFindingGroupLabel(type, fallbackTitle) {
  const labels = {
    AMBIGUOUS_CLASS_PAIR: "Ambiguous prediction",
    SEVERE_PROXIMITY_GROUP: "Severe proximity group",
    MULTI_BUILDING_SITE: "Reviewed multi-building site",
  };
  return labels[type] || (typeof fallbackTitle === "string" ? fallbackTitle.slice(0, 80) : "Finding group");
}

function renderSceneAssessment(result) {
  clearSceneAssessmentResult();
  sceneAssessmentOverview.textContent = result.overview;
  const modelLabel = assessmentModelLabel(result.generated_by);
  if (modelLabel) {
    sceneAssessmentModel.textContent = "Generated by " + modelLabel;
    sceneAssessmentModel.hidden = false;
  }
  result.findings.forEach((finding) => {
    const item = document.createElement("li");
    item.className = "scene-assessment-finding";
    const targetIds = [...new Set(finding.candidate_keys.flatMap((key) => result.candidate_buildings[key] || []))];
    const type = finding.candidate_keys.map((key) => result.candidate_types?.[key]).find((value) => typeof value === "string");
    item.dataset.findingCategory = sceneFindingCategory(type);
    const typeLabel = document.createElement("span");
    typeLabel.className = "scene-assessment-finding-type";
    typeLabel.textContent = sceneFindingTypeLabel(type, targetIds.length);
    const title = document.createElement("h5");
    title.textContent = finding.title;
    const explanation = document.createElement("p");
    explanation.textContent = finding.explanation;
    const explanationDetails = document.createElement("details");
    explanationDetails.className = "scene-finding-explanation";
    const explanationSummary = document.createElement("summary");
    explanationSummary.textContent = "Read explanation";
    explanationDetails.append(explanationSummary, explanation);
    item.append(typeLabel, title, explanationDetails);
    if (targetIds.length) {
      const inspect = document.createElement("button");
      inspect.type = "button";
      inspect.className = "scene-assessment-inspect";
      inspect.textContent = targetIds.length === 1 ? "Inspect building →" : type === "SEVERE_PROXIMITY_GROUP" ? "Show group →" : "Show " + targetIds.length + " buildings →";
      inspect.addEventListener("click", () => {
        const validIds = targetIds.filter((id) => activeSceneBuildingIds.has(id));
        if (validIds.length === 1) {
          document.dispatchEvent(new CustomEvent("scene-building-inspect-request", {
            detail: { scene_id: activeSceneOverviewId, building_id: validIds[0] },
          }));
        } else if (validIds.length > 1) {
          document.dispatchEvent(new CustomEvent("scene-building-group-inspect-request", {
            detail: {
              scene_id: activeSceneOverviewId,
              building_ids: validIds,
              group_id: finding.candidate_keys[0],
              group_label: sceneFindingGroupLabel(type, finding.title),
            },
          }));
        }
      });
      item.append(inspect);
    }
    sceneAssessmentFindings.append(item);
  });
  sceneAssessmentFindingsBlock.hidden = result.findings.length === 0;
  if (result.recommended_review) {
    sceneAssessmentReview.textContent = result.recommended_review;
    sceneAssessmentReviewBlock.hidden = false;
  }
  result.limitations.forEach((limitation) => {
    const item = document.createElement("li");
    item.textContent = limitation;
    sceneAssessmentLimitations.append(item);
  });
  sceneAssessmentLimitationsBlock.hidden = result.limitations.length === 0;
  const evidenceCount = renderEvidenceBadges(sceneAssessmentEvidenceUsed, result.evidence_used, SCENE_ASSESSMENT_EVIDENCE_LABELS);
  sceneAssessmentDetails.hidden = !evidenceCount && !result.limitations.length && !modelLabel;
  sceneAssessmentGenerateButton.hidden = true;
  sceneAssessmentStatus.textContent = "";
  sceneAssessmentStatus.classList.remove("error");
  sceneAssessmentResult.hidden = false;
}

function renderActiveSceneAssessment() {
  if (!activeSceneOverviewId) return;
  const cached = sceneAssessmentCache.get(activeSceneOverviewId);
  const pending = sceneAssessmentRequests.has(activeSceneOverviewId);
  resetSceneAssessmentView();
  sceneAssessmentGenerateButton.disabled = pending;
  if (pending) sceneAssessmentStatus.textContent = "Generating scene brief…";
  if (cached) renderSceneAssessment(cached);
}

async function generateSceneAssessment() {
  const sceneId = activeSceneOverviewId;
  if (!sceneId || sceneAssessmentCache.has(sceneId) || sceneAssessmentRequests.has(sceneId)) return;
  sceneAssessmentRequests.set(sceneId, true);
  if (sceneId === activeSceneOverviewId) {
    sceneAssessmentStatus.classList.remove("error");
    sceneAssessmentStatus.textContent = "Generating scene brief…";
    sceneAssessmentGenerateButton.disabled = true;
  }
  let failureMessage = "";
  try {
    const response = await fetch("/demo-scenes/" + encodeURIComponent(sceneId) + "/assessment", { method: "POST" });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      failureMessage = body?.detail?.code === "assessment_provider_unavailable"
        ? "AI scene brief is currently unavailable."
        : "Scene brief could not be generated. Try again.";
    } else {
      const result = normalizeSceneAssessmentResult(body, activeSceneBuildingIdsFor(sceneId));
      if (!result) failureMessage = "Scene brief could not be generated. Try again.";
      else sceneAssessmentCache.set(sceneId, result);
    }
  } catch (_error) {
    failureMessage = "Scene brief could not be generated. Try again.";
  } finally {
    sceneAssessmentRequests.delete(sceneId);
    if (sceneId === activeSceneOverviewId) {
      if (sceneAssessmentCache.has(sceneId)) renderActiveSceneAssessment();
      else {
        sceneAssessmentGenerateButton.disabled = false;
        sceneAssessmentStatus.textContent = failureMessage;
        sceneAssessmentStatus.classList.toggle("error", Boolean(failureMessage));
      }
    }
  }
}

function activeSceneBuildingIdsFor(sceneId) {
  return sceneAssessmentBuildingIds.get(sceneId) || new Set();
}

function clearAssessmentResult() {
  assessmentModel.textContent = "";
  assessmentModel.hidden = true;
  assessmentText.textContent = "";
  assessmentReviewText.textContent = "";
  assessmentReviewBlock.hidden = true;
  assessmentEvidenceDetails.open = false;
  assessmentEvidenceDetails.hidden = true;
  assessmentEvidenceUsed.replaceChildren();
  assessmentEvidenceUsed.hidden = true;
  assessmentSupportingDetails.replaceChildren();
  assessmentSupportingBlock.hidden = true;
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
  assessmentText.textContent = result.assessment;
  const recommendedReview = typeof result.recommended_review === "string" ? result.recommended_review.trim() : "";
  if (recommendedReview) {
    assessmentReviewText.textContent = recommendedReview;
    assessmentReviewBlock.hidden = false;
  }
  result.supporting_details.forEach((detail) => {
    const item = document.createElement("li");
    item.textContent = detail;
    assessmentSupportingDetails.append(item);
  });
  assessmentSupportingBlock.hidden = result.supporting_details.length === 0;
  result.limitations.forEach((limitation) => {
    const item = document.createElement("li");
    item.textContent = limitation;
    assessmentLimitations.append(item);
  });
  assessmentLimitationsBlock.hidden = result.limitations.length === 0;
  const modelLabel = assessmentModelLabel(result.generated_by);
  if (modelLabel) {
    assessmentModel.textContent = "Generated by " + modelLabel;
    assessmentModel.hidden = false;
  }
  const evidenceCount = renderEvidenceBadges(assessmentEvidenceUsed, result.evidence_used, ASSESSMENT_EVIDENCE_LABELS);
  assessmentEvidenceDetails.hidden = !evidenceCount && !result.supporting_details.length && !result.limitations.length && !modelLabel;
}

function normalizedAssessmentResult(body) {
  return {
    assessment: typeof body.assessment === "string" ? body.assessment.trim() : "",
    recommended_review: body.recommended_review,
    supporting_details: Array.isArray(body.supporting_details)
      ? body.supporting_details.filter((item) => typeof item === "string" && item.trim()).map((item) => item.trim())
      : [],
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
  inspectorContextPill.hidden = true;
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
  inspectorContextPill.hidden = false;
}

function setStatus(message = "", isError = false) {
  statusMessage.textContent = message;
  statusMessage.classList.toggle("error", isError);
}

function updateComparison() {
  const reveal = Math.max(0, Math.min(100, Number(comparisonRange.value) || 0));
  comparison.setAttribute("style", "--reveal: " + reveal + "%");
  comparisonRange.setAttribute("aria-valuetext", reveal + "% PRE visible");
}

function resetComparison() {
  comparisonRange.value = "50";
  updateComparison();
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
  inspectorEmpty.hidden = true;
  inspectorContent.hidden = false;
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
  resetComparison();
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
  resetComparison();
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
  resultConfidence.textContent = (prediction.confidence * 100).toFixed(1) + "% top-class score";
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

  resetComparison();

  state.pre = { assetUrl: preUrl, name: building.id + "-pre.png" };
  state.post = { assetUrl: postUrl, name: building.id + "-post.png" };
  state.source = "scene";
  state.scenePrediction = prediction;
  preInput.value = "";
  postInput.value = "";
  showPreview("pre", preUrl);
  showPreview("post", postUrl);
  document.querySelectorAll(".example-button").forEach((button) => button.classList.remove("selected"));
  selectionLabel.textContent = "Building " + building.id.split("_").pop();
  selectionLabel.title = building.id;
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
  resetComparison();
  inspectorContent.hidden = true;
  inspectorEmpty.hidden = false;
  document.querySelectorAll(".example-button").forEach((button) => button.classList.remove("selected"));
  selectionLabel.textContent = "No building selected";
  selectionLabel.title = "";
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
  activeSceneOverviewId = null;
  activeSceneBuildingIds = new Set();
  sceneAssessment.hidden = true;
  resetSceneAssessmentView();
  if (state.source === "scene") clearSelection();
});

document.addEventListener("scene-loaded", (event) => {
  const sceneId = event.detail?.scene_id;
  const buildings = event.detail?.scene?.buildings;
  if (typeof sceneId !== "string" || !Array.isArray(buildings)) return;
  activeSceneOverviewId = sceneId;
  activeSceneBuildingIds = new Set(buildings.map((building) => building?.id).filter((id) => typeof id === "string"));
  sceneAssessmentBuildingIds.set(sceneId, activeSceneBuildingIds);
  sceneAssessment.hidden = false;
  renderActiveSceneAssessment();
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
comparisonRange.addEventListener("input", updateComparison);
updateComparison();
predictButton.addEventListener("click", predictDamage);
assessmentGenerateButton.addEventListener("click", generateAssessment);
sceneAssessmentGenerateButton.addEventListener("click", generateSceneAssessment);
