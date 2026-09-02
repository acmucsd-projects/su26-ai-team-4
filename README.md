# Post-Disaster Building Damage Triage Assistant

A tool for using pre- and post-disaster satellite imagery to help assess building damage after a disaster.

Current work focuses on building and validating the ML models behind the system. The longer-term goal is an application that uses those model predictions to support emergency-response triage and guidance.

## Setup

**Workflow:** Environment → xBD setup and preprocessing → smoke test → training → checkpoint inference.

1. Clone the repo.

2. Create the environment:

   ```bash
   conda env create -f environment.yml
   ```

3. Activate it:

   ```bash
   conda activate disaster-triage
   ```

4. Set up the xBD dataset.

   Follow [`data/README.md`](data/README.md) for the expected data layout and preprocessing steps.

CUDA is the primary tested training environment. See the [ResNet-18 baseline README](base_train/ezekiel_resnet18_baseline/README.md) for MPS and CPU notes.

## ML Training

The current ResNet-18 baseline is documented here:

[`base_train/ezekiel_resnet18_baseline/README.md`](base_train/ezekiel_resnet18_baseline/README.md)

Follow that README to prepare the training cache, run the smoke test, train the baseline models, and see the available experiments and recommended settings.

For a first run, use the recommended 128×128 configuration.

## Checkpoints

Released model checkpoints are documented in [`checkpoints/README.md`](checkpoints/README.md), including downloads, loading and inference, and checkpoint verification.

Checkpoint binaries are distributed through GitHub Releases rather than stored directly in Git.

## Documentation

Use the README closest to the part of the project you are working on:

- [`data/README.md`](data/README.md) — dataset setup and preprocessing
- [`base_train/ezekiel_resnet18_baseline/README.md`](base_train/ezekiel_resnet18_baseline/README.md) — ResNet-18 training and experiments
- [`checkpoints/README.md`](checkpoints/README.md) — released models and inference
- [`docs/`](docs/) — research notes and project decisions

## Team

[names/roles]