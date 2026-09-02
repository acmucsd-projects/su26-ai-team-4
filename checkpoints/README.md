# Checkpoints

These `.pt` files contain trained PyTorch model checkpoints. They are distributed through GitHub Releases instead of being committed directly to Git.

## Available checkpoints

| File | Resolution | Training seed | Best epoch | Validation Macro-F1 | Intended use |
| --- | --- | ---: | ---: | ---: | --- |
| `resnet18_prepost_plaince_xbd_128_seed17.pt` | 128x128 | 17 | 6 | 0.756082 | Default/recommended checkpoint from this sweep |
| `resnet18_prepost_plaince_xbd_224_seed17.pt` | 224x224 | 17 | 7 | 0.754094 | Full-resolution reference checkpoint |

Both use split seed 42. Use the 128x128 checkpoint by default; use the 224x224 checkpoint as the full-resolution reference.

Architecture: PRE+POST shared-backbone ResNet-18 for xBD building-damage classification. A single ResNet-18 produces 512-dimensional PRE and POST feature vectors, which are concatenated before a plain cross-entropy classifier.

## Download

Download the assets from the [xBD ResNet-18 Baseline v1 release](https://github.com/acmucsd-projects/su26-ai-team-4/releases/tag/v1.0-resnet18-baseline):

- [128x128 checkpoint](https://github.com/acmucsd-projects/su26-ai-team-4/releases/download/v1.0-resnet18-baseline/resnet18_prepost_plaince_xbd_128_seed17.pt)
- [224x224 checkpoint](https://github.com/acmucsd-projects/su26-ai-team-4/releases/download/v1.0-resnet18-baseline/resnet18_prepost_plaince_xbd_224_seed17.pt)

The release also includes the matching `result.json` files.

## What is inside the checkpoint?

The released plain-CE checkpoints contain these dictionary fields:

- `model_name`: `prepost_resnet18_plaince`
- `epoch`: the best validation epoch
- `model_state_dict`: portable PyTorch parameter tensors
- `class_names`: `['no-damage', 'minor-damage', 'major-damage', 'destroyed']`
- `val_metrics`: validation loss, accuracy, Macro-F1, and per-class metrics
- `config`: model, split, optimizer, image-size, worker, and run settings
- `metadata`: model and runtime/provenance metadata

## Loading and running inference

Use the baseline inference CLI from the repository root; it loads the existing control architecture, reads the checkpoint's class names and image size, selects CUDA then MPS then CPU, and prints the predicted class plus all four probabilities. No labels, targets, training dataset, or `sys.path` changes are required.

```bash
python base_train/ezekiel_resnet18_baseline/inference.py \
  --checkpoint resnet18_prepost_plaince_xbd_128_seed17.pt \
  --pre path/to/pre_building_crop.png \
  --post path/to/post_building_crop.png
```

The model requires two aligned building crops: one PRE-disaster image and one POST-disaster image. Inference applies deterministic validation preprocessing: RGB conversion, bilinear resize to the checkpoint's saved square image size, tensor conversion, and ImageNet normalization; it does not apply training augmentation. The optional `--device` argument accepts `cuda`, `mps`, or `cpu`.

The underlying Python API is `load_model(checkpoint_path, device=None)` and `predict(loaded_model, pre_image, post_image)`. Inference always uses the image size saved in the checkpoint.

Inference constructs the control architecture with `weights=None` before loading the released state dictionary, so it does not need torchvision's pretrained ImageNet weights or an Internet connection.

## Verification

| File | SHA-256 |
| --- | --- |
| `resnet18_prepost_plaince_xbd_128_seed17.pt` | `AA8821C29CF507FD5CABB410083AE291C1EF0B73C75FC99DCC33929C04917A3F` |
| `resnet18_prepost_plaince_xbd_224_seed17.pt` | `C69F34A976F25F240B45426C02585AC02DCF51E10617DC75C9EEF9977C26FD9F` |

On PowerShell, verify a downloaded file with:

```powershell
Get-FileHash -Algorithm SHA256 .\resnet18_prepost_plaince_xbd_128_seed17.pt
```

On macOS or Linux, use:

```sh
shasum -a 256 resnet18_prepost_plaince_xbd_128_seed17.pt
```

Both released checkpoints were successfully deserialized on CPU, had their state dictionaries loaded into the control PRE+POST model, and produced four output logits from dummy PRE/POST forward inference.
