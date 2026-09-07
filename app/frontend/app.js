const API_BASE_URL = "https://mindpretzel1--building-damage-classifier-128-fastapi-app.modal.run";
const PREDICT_URL = API_BASE_URL + "/predict";
const CLASS_ORDER = ["no-damage", "minor-damage", "major-damage", "destroyed"];

const EXAMPLES = {
  "no-damage": { label: "No damage", pre: "examples/no_damage/pre.png", post: "examples/no_damage/post.png" },
  "minor-damage": { label: "Minor damage", pre: "examples/minor_damage/pre.png", post: "examples/minor_damage/post.png" },
  "major-damage": { label: "Major damage", pre: "examples/major_damage/pre.png", post: "examples/major_damage/post.png" },
  destroyed: { label: "Destroyed", pre: "examples/destroyed/pre.png", post: "examples/destroyed/post.png" },
};

const state = { pre: null, post: null, previewUrls: { pre: null, post: null } };
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
const probabilityBars = document.querySelector("#probability-bars");

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

function setManualFile(slot, file) {
  if (!file) return;
  state[slot] = { file, name: file.name };
  showPreview(slot, URL.createObjectURL(file), true);
  document.querySelectorAll(".example-button").forEach((button) => button.classList.remove("selected"));
  selectionLabel.textContent = "Custom upload";
  resultCard.hidden = true;
  setStatus("");
}

function selectExample(name) {
  const example = EXAMPLES[name];
  state.pre = { assetUrl: example.pre, name: name + "-pre.png" };
  state.post = { assetUrl: example.post, name: name + "-post.png" };
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

function showResult(prediction) {
  resultClass.textContent = prediction.predicted_class.replace("-", " ");
  resultConfidence.textContent = (prediction.confidence * 100).toFixed(1) + "% confidence";
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

async function predictDamage() {
  if (!state.pre || !state.post) {
    setStatus("Choose a built-in example or upload both PRE and POST images.", true);
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
  state.pre = null;
  state.post = null;
  preInput.value = "";
  postInput.value = "";
  clearPreview("pre");
  clearPreview("post");
  document.querySelectorAll(".example-button").forEach((button) => button.classList.remove("selected"));
  selectionLabel.textContent = "No pair selected";
  resultCard.hidden = true;
  setStatus("");
}

preInput.addEventListener("change", () => setManualFile("pre", preInput.files[0]));
postInput.addEventListener("change", () => setManualFile("post", postInput.files[0]));
document.querySelectorAll(".example-button").forEach((button) => {
  button.addEventListener("click", () => selectExample(button.dataset.example));
});
document.querySelector("#clear-selection").addEventListener("click", clearSelection);
predictButton.addEventListener("click", predictDamage);
