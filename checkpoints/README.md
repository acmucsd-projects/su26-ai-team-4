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

## Loading a checkpoint

Run this from the repository root. It imports the existing control model rather than recreating its architecture.

```python
import sys
from pathlib import Path

import torch

repo_root = Path.cwd()
baseline_dir = repo_root / "base_train" / "ezekiel_resnet18_baseline"
sys.path.insert(0, str(baseline_dir))

from train_common import select_device
from train_prepost_resnet18_plaince import PrePostResNet18

device = select_device()  # CUDA, then Apple MPS, then CPU.
checkpoint_path = Path("resnet18_prepost_plaince_xbd_128_seed17.pt")

checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
model = PrePostResNet18().to(device)
model.load_state_dict(checkpoint["model_state_dict"])
model.eval()

print("best epoch:", checkpoint["epoch"])
print("classes:", checkpoint["class_names"])
print("validation Macro-F1:", checkpoint["val_metrics"]["macro_f1"])
```

`PrePostResNet18()` follows the training code and constructs an ImageNet-pretrained torchvision ResNet-18 before the released state dictionary replaces its weights. If the torchvision pretrained weights are not already cached, that constructor may require Internet access.

## Running inference

The model requires two aligned building crops: one PRE-disaster image and one POST-disaster image. Reuse the existing `PrePostDataset` with `training=False` so inference uses the training pipeline's exact RGB conversion, optional bilinear resize, tensor conversion, and ImageNet normalization. Set `image_size` to match the selected checkpoint.

```python
import pandas as pd

from train_prepost_resnet18_plaince import PrePostDataset

inputs = pd.DataFrame([{
    "pre_path": "path/to/pre_building_crop.png",
    "post_path": "path/to/post_building_crop.png",
    "target": 0,          # Required by the dataset API; ignored for inference.
    "building_id": "inference-example",
}])
dataset = PrePostDataset(inputs, training=False, image_size=128)
pre_tensor, post_tensor, _, _ = dataset[0]

with torch.no_grad():
    logits = model(
        pre_tensor.unsqueeze(0).to(device),
        post_tensor.unsqueeze(0).to(device),
    )
    predicted_index = logits.argmax(dim=1).item()

predicted_class = checkpoint["class_names"][predicted_index]
print(predicted_class)
```

For the 224x224 checkpoint, change `image_size=128` to `image_size=224`. The repository does not currently expose a separate standalone inference-preprocessing helper; the existing dataset is the supported reusable path.

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
