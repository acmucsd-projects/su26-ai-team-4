# ResNet-18 Baselines

This folder contains ResNet-18 experiments for xBD building-damage classification.

## Quick start

From the repository root:

```bash
python src/build_manifest.py
```

Then prepare the local 224 x 224 cache:

```bash
python base_train/ezekiel_resnet18_baseline/prepare_xbd_cache.py
```

Then run the current POST-only baseline:

```bash
python base_train/ezekiel_resnet18_baseline/train_post_resnet18.py
```

## Expected data layout

```text
data/
└── train/
    ├── images/
    ├── labels/
    ├── targets/
    └── metadata_stats/
```

`build_manifest.py` creates:

```text
data/manifest_train.csv
data/processed/tier1/pre/
data/processed/tier1/post/
```

The cache script creates:

```text
base_train/ezekiel_resnet18_baseline/cache/
```

The training script creates:

```text
base_train/ezekiel_resnet18_baseline/results/
```

## Current experiment

`train_post_resnet18.py`

- POST-disaster crops only
- ImageNet-pretrained ResNet-18
- four damage classes
- scene-disjoint train/validation split
- weighted cross-entropy
- validation Macro F1 checkpoint selection

## Hardware

Training currently requires an NVIDIA CUDA GPU.

The preprocessing and cache scripts are platform-independent.

Training settings and available command-line options are documented in the individual experiment scripts.
```

## Outputs

Typical files in `results/`:

```text
best.pt
history.csv
result.json
summary.txt
confusion_matrix.csv
val_predictions.csv
split_manifest.csv
split_summary.csv
```

## Notes

Generated data, cache files, checkpoints, and results should remain ignored by Git.

Future ResNet-18 variants can be added to this folder, such as PRE-only or paired PRE+POST experiments.
