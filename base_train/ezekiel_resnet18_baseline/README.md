# ResNet-18 Baselines

ResNet-18 experiments for xBD building-damage classification.

For environment and dataset setup, start with the repository [README](../../README.md) and [`data/README.md`](../../data/README.md).

## Quick Start

Run these commands from the repository root.

### 1. Build the manifest

```bash
python src/build_manifest.py
```

### 2. Build the image cache

```bash
python base_train/ezekiel_resnet18_baseline/prepare_xbd_cache.py
```

### 3. Run the smoke test

```bash
python base_train/ezekiel_resnet18_baseline/smoke_test.py
```

The smoke test runs the real training entry points for one epoch on a small temporary subset and checks that the expected outputs are created. It does not overwrite normal experiment results.

### 4. Run the recommended first experiment

```bash
python base_train/ezekiel_resnet18_baseline/train_prepost_resnet18_plaince.py --image-size 128
```

The models start from ImageNet-pretrained ResNet-18 weights. The first run may need Internet access if torchvision has not already cached those weights.

## Experiments

The baselines classify four damage levels: `no-damage`, `minor-damage`, `major-damage`, and `destroyed`. `un-classified` examples are excluded from the training cache.

All three experiments use ImageNet-pretrained ResNet-18, a scene-disjoint train/validation split, and select `best.pt` using validation Macro F1.

Default result directories are relative to `base_train/ezekiel_resnet18_baseline/`.

| Experiment | Input | Loss | Default results |
| --- | --- | --- | --- |
| `train_post_resnet18.py` | POST only | Weighted cross-entropy | `results/` |
| `train_prepost_resnet18.py` | PRE + POST | Weighted cross-entropy | `results_prepost/` |
| `train_prepost_resnet18_plaince.py` | PRE + POST | Plain cross-entropy | `results_prepost_plaince/` |

The PRE+POST models use one shared ResNet-18 backbone. PRE and POST features are concatenated before classification, and geometric augmentation is synchronized across each image pair.

The plain-CE experiment keeps the paired architecture the same while removing class weighting so the effect of the loss can be compared directly.

## Resolution

**128×128 is recommended for normal development and iteration.** It trained substantially faster in baseline testing while producing similar validation Macro F1.

Use **224×224** for canonical baseline reproduction and heavier comparison runs.

Both resolutions reuse the same 224×224 cache through `--image-size`.

## Training Options

Use `--help` to see all available options:

```bash
python base_train/ezekiel_resnet18_baseline/train_prepost_resnet18_plaince.py --help
```

For example, to adjust batch size and DataLoader workers:

```bash
python base_train/ezekiel_resnet18_baseline/train_prepost_resnet18_plaince.py --image-size 128 --batch-size 64 --num-workers 4
```

## Hardware

Training automatically selects the first available device:

1. NVIDIA CUDA
2. Apple MPS
3. CPU

CUDA is the primary tested training environment.

Apple MPS is supported in FP32 but has not been validated on the project's development hardware. CPU is supported as a fallback but may be slow for training.

DataLoader workers default to up to 4 for portability. Increase `--num-workers` if input loading becomes a bottleneck, or reduce it if you run into instability or high RAM usage.

## Outputs

Each experiment writes standard training and evaluation artifacts to its results directory.

**Important:** Training will not write into a non-empty results directory. Pass `--results-dir` to save a new run separately.

Typical outputs include:

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

`best.pt` is selected using validation Macro F1 and is reloaded before the final validation metrics and predictions are written.

`split_manifest.csv` and `split_summary.csv` record the scene-disjoint train/validation split used for the run.
