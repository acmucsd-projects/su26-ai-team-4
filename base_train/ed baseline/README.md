# xBD Building Damage Classification CNN

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

Using `build_manifest.py` on the unprocessed data set, there should be a folder with the layout:
```bash
processed/
└── tier1
    ├── post
    └── pre 
```
Route `--data-root` to where this processed folder sits

## Train

```bash
python train.py \
    --manifest /path/to/manifest_train.csv \
    --data-root /path/to/processed \
    --backbone resnet18 --pretrained \
    --image-size 128 \
    --batch-size 64 \
    --epochs 30 \
    --lr 1e-4
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

## Evaluate

```bash
python evaluate.py \
    --checkpoint checkpoints/best_model.pt \
    --manifest /path/to/manifest_train.csv \
    --data-root /path/to/processed \
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
