# xBD Building Damage Classification CNN

A PyTorch pipeline that classifies building damage severity from paired
pre-/post-disaster satellite image crops, driven by your `manifest_train.csv`.

Based on your manifest (162,787 rows), the label distribution is heavily
imbalanced, which the pipeline handles explicitly (see below):

| damage_label   | count   | % |
|---|---|---|
| no-damage      | 117,426 | 72.1% |
| minor-damage   | 14,980  | 9.2% |
| major-damage   | 14,161  | 8.7% |
| destroyed      | 13,227  | 8.1% |
| un-classified  | 2,993   | 1.8% (dropped by default) |

## Why this architecture

Damage assessment is fundamentally a **change-detection** problem: the label
depends on how a building changed between the pre- and post-disaster image,
not on either image in isolation. So instead of a plain single-image CNN,
this uses a **Siamese (shared-weight) dual-encoder**:

```
pre_image  ──► shared CNN encoder ──► pre_features  ─┐
                                                       ├─► [pre, post, |pre-post|, pre*post] ──► FC classifier ──► damage class
post_image ──► shared CNN encoder ──► post_features ─┘
```

- **Shared weights** mean the network learns one consistent way to describe
  a building, applied to both images — this halves the parameters vs. two
  separate encoders and forces the model to compare like with like.
- **Explicit difference features** (`|pre - post|`, elementwise product) give
  the classifier a direct "how much changed and in what direction" signal on
  top of the raw appearance features, which is what actually distinguishes
  `no-damage` from `destroyed`.
- Two backbone choices: `simple` (a small from-scratch CNN, no downloaded
  weights needed — good default for offline/restricted environments) or
  `resnet18` (torchvision, optional ImageNet pretraining with `--pretrained`).

## Handling class imbalance

`no-damage` outnumbers `destroyed` roughly 9:1. The pipeline addresses this
via **inverse-frequency class weighting** in the loss (`utils.compute_class_weights`),
so misclassifying a rare `destroyed` building costs the model more than
misclassifying a common `no-damage` one. Model selection during training is
also driven by **validation macro-F1** (not accuracy), which weights all four
classes equally — a model that just predicts `no-damage` for everything will
score near 0.

## Preventing data leakage

The manifest's `split` column is entirely `tier1` (no train/val split is
provided). Splitting by row would leak buildings from the same disaster scene
into both train and val, since many crops share a `scene_id`. Instead
`utils.group_train_val_split` uses `GroupShuffleSplit` on `scene_id`, so a
given post-disaster image never has some of its buildings in train and others
in val.

## Project layout

```
xbd_damage_cnn/
├── dataset.py      # XBDDamageDataset: reads manifest rows, loads pre/post crops
├── transforms.py   # Paired augmentation (identical flip/rotate on pre+post)
├── model.py         # SiameseDamageNet + backbones
├── utils.py         # manifest loading, group split, class weights
├── train.py         # training loop, checkpointing, early stopping
├── evaluate.py       # confusion matrix + classification report on a checkpoint
├── predict.py        # single pre/post pair inference
├── requirements.txt
├── checkpoints/       # (empty) trained models land here
└── outputs/            # (empty) evaluation reports/plots land here
```

## Setup

```bash
pip install -r requirements.txt
```

## Data layout

The manifest's `pre_crop_path` / `post_crop_path` columns look like:
```
processed/tier1/pre/guatemala-volcano_00000000_b0000.png
processed/tier1/post/guatemala-volcano_00000000_b0000.png
```
These are **relative paths**. Point `--data-root` at whatever directory
contains that `processed/...` tree (i.e. wherever you unpacked the xBD
processed crops), so `data_root / pre_crop_path` resolves to a real file.

## Train

```bash
python train.py \
    --manifest /path/to/manifest_train.csv \
    --data-root /path/to/xbd_root \
    --backbone simple \
    --image-size 128 \
    --batch-size 64 \
    --epochs 30 \
    --lr 1e-3
```

Key flags:
- `--backbone {simple,resnet18}` — `resnet18 --pretrained` usually gives the
  best accuracy if you have internet access to fetch ImageNet weights and a
  GPU; `simple` is the safe offline default and is much faster per epoch.
- `--include-unclassified` — keep the small `un-classified` bucket as a 5th
  class instead of dropping those rows.
- `--limit-rows N` — subsample the manifest for a fast debug run.
- `--patience N` — early-stop if val macro-F1 doesn't improve for N epochs.

Outputs land in `checkpoints/`: `best_model.pt` (weights + config),
`best_classification_report.txt`, and `history.json` (per-epoch loss/F1).

On the full 162k-row manifest, expect real (non-trivial) image loading and
several minutes/epoch on CPU, much faster on GPU. This was smoke-tested on a
small synthetic sample to confirm the training/eval/inference loop is bug-free;
actual accuracy depends on training against the real xBD crop images.

## Evaluate

```bash
python evaluate.py \
    --checkpoint checkpoints/best_model.pt \
    --manifest /path/to/manifest_train.csv \
    --data-root /path/to/xbd_root \
    --use-val-split
```
`--use-val-split` re-derives the same held-out scenes used during training
(same seed) so you're not evaluating on data the model trained on. Produces
`outputs/classification_report.txt` and `outputs/confusion_matrix.png`.

## Predict on a single pair

```bash
python predict.py \
    --checkpoint checkpoints/best_model.pt \
    --pre path/to/pre_crop.png \
    --post path/to/post_crop.png
```

## Extending this

- **Localization + classification**: xBD's original task also includes
  building *segmentation* (where is the building), typically with a U-Net on
  the pre-image. This repo assumes crops are already localized (as your
  manifest's `original_bbox` columns suggest) and focuses purely on the
  4-way damage classification of each crop.
- **Test-time augmentation** or **ensembling** multiple backbones is a cheap
  way to squeeze out extra macro-F1 once the base pipeline is working.
- **Disaster-type stratification**: `disaster_type` in the manifest (e.g.
  `hurricane-harvey`, `palu-tsunami`) could be added as an auxiliary input or
  used for per-disaster-type evaluation to check the model isn't just
  learning wildfire-specific vs. flood-specific damage cues.
