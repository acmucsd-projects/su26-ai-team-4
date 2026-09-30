# Damage Atlas | Geospatial Disaster Analysis

Damage Atlas is a disaster-damage analysis system built around pre- and post-disaster satellite imagery.

The project combines a building-level damage classifier with scene-level spatial analysis, reviewed GIS context, and optional grounded AI synthesis to help users inspect damage predictions across disaster-affected areas.

The system is designed as a **decision-support and human-review tool**, not as an autonomous emergency-response system.

## Project Overview

The core machine-learning task uses the xView2/xBD dataset to classify known buildings into four damage levels:

`no-damage → minor-damage → major-damage → destroyed`

xBD already provides building footprints and damage annotations, so the classifier focuses on **building-level damage classification rather than building detection**.

The main model is a paired PRE/POST ResNet-18:

- PRE building crop → shared ResNet-18 backbone
- POST building crop → same shared backbone
- learned features are concatenated
- final classifier predicts one of four damage classes

The strongest early scene-disjoint validation model achieved approximately:

- **Macro-F1:** 0.756
- **Validation accuracy:** 88.5%

Later research investigated class imbalance, input resolution, additional disaster data, PRE-image dependence, and generalization to unseen disaster events.

## Damage Atlas Application

The final application extends the classifier into a scene-level analysis workflow.

### Scene Explorer

Seven curated xBD disaster scenes are packaged with building footprints and precomputed classifier outputs for interactive exploration.

The scene explorer supports:

- PRE/POST disaster imagery
- building-level prediction overlays
- filtering by damage class
- severe-damage grouping
- building inspection
- full four-class model scores
- relative ambiguity analysis
- PRE/POST crop comparison

Full-scene predictions are precomputed because the trained model is a **building-crop classifier**, not a full-scene detector.

A separate live paired-crop tool runs the deployed model on built-in or user-supplied PRE/POST building crops.

### Spatial Evidence

Damage Atlas computes deterministic scene-level evidence before any generative AI is used.

This includes:

- relative model ambiguity
- nearest-neighbor prediction context
- local prediction contrasts
- severe-damage proximity groups
- scene-level damage summaries
- reviewed GIS/site context

These signals are intended to help identify cases that may deserve closer human review.

### GIS Context

External GIS information is collected and reviewed offline rather than queried live during application use.

The enrichment workflow is approximately:

`xBD footprint → external candidate records → geometry association → semantic review → provenance/conflict review → packaged context`

GIS evidence retains important distinctions such as:

- source/provider
- source date
- individual-building vs site/parcel scope
- modeled vs directly supported information
- ambiguity or conflicting evidence

A geometric match does not automatically become a semantic building claim, and buildings with no reliable contextual match are allowed to have no GIS context.

### Grounded AI Assessment

Optional scene- and building-level AI assessments are generated from structured evidence produced by the application.

The generative model does **not** receive PRE/POST satellite pixels and does **not** receive xBD reference damage labels.

The pipeline is:

`classifier outputs + footprints + scene metadata + reviewed GIS`
→ `deterministic SceneEvidence`
→ `structured evidence`
→ `AI synthesis`
→ `interactive findings`

The AI layer is used to summarize and organize existing evidence rather than discover unsupported visual facts.

## Repository Structure

The main application is under `app/`.

Important components include:

- `app/frontend/` — static HTML/CSS/JavaScript interface
- `app/backend/api.py` — FastAPI backend
- `app/backend/inference.py` — model inference
- `app/backend/model.py` — deployed model architecture
- `app/backend/package_demo_scene.py` — curated scene packaging
- `app/backend/modal_app.py` — Modal deployment

Model training and research code remains under the training directories, while released checkpoints are documented separately.

## Setup

**ML workflow:**

Environment → xBD setup/preprocessing → smoke test → training → checkpoint inference

1. Clone the repository.

2. Create the environment:

   ```bash
   conda env create -f environment.yml
