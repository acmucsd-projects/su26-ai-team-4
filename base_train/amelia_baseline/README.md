# Baseline & Reproduction

## Baseline CNN

See `manifest_analysis.ipynb` for dataset EDA and the scene-based train/val/test split, and `baseline.ipynb` for the from-scratch `ImprovedCNN` baseline.

- Input: post-disaster images only
- Architecture: 4 conv blocks + BatchNorm + Dropout, train-time augmentation
- Loss: class-weighted cross-entropy
- Result: macro F1 0.453 on test (accuracy 0.676, weighted F1 0.712)
- Per-class F1: no-damage 0.81, minor-damage 0.34, major-damage 0.27, destroyed 0.39

## ResNet18 Reproduction (Ezekiel's baseline)

Reproduced Ezekiel's PRE+POST ResNet-18 baseline (`train_prepost_resnet18_plaince.py`) locally on Apple MPS, to test whether his results reproduce across different hardware.

**Setup:** Apple MPS, image size 128x128, batch size 128, 8 epochs, seed 42, split seed 42

**Result:** best epoch 4/8, validation Macro F1 0.7551, validation accuracy 0.8727

**Comparison to Ezekiel's published checkpoint:**

| | Ezekiel (published) | This run |
|---|---|---|
| Device | CUDA | Apple MPS |
| Seed | 17 | 42 |
| Best epoch | 6/8 | 4/8 |
| Macro F1 | 0.7561 | 0.7551 |

Difference of ~0.001 — confirms the baseline reproduces consistently across different hardware and random seeds.

**Per-class F1 (this run):**
- No damage: 0.937
- Minor damage: 0.553
- Major damage: 0.691
- Destroyed: 0.839

Full metrics in `summary.txt` and `result.json`.
