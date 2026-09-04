"""
Model architecture for the pre/post-disaster building damage classifier.

This MUST match the architecture the checkpoint was trained with:
  - Shared ResNet-18 backbone (ImageNet-pretrained, fc removed) applied
    independently to a PRE-disaster and POST-disaster image of the same
    building.
  - The two 512-dim feature vectors are concatenated -> 1024-dim.
  - Classifier head: Linear(1024, 512) -> ReLU -> Linear(512, num_classes)

Verified against resnet18_prepost_plaince_xbd_128_seed17.pt with
strict=True (zero missing/unexpected keys).
"""

import torch
import torch.nn as nn
import torchvision


class PrePostResNet(nn.Module):
    def __init__(self, num_classes: int = 4):
        super().__init__()
        base = torchvision.models.resnet18(weights=None)
        base.fc = nn.Identity()  # strip classifier, keep 512-dim pooled features
        self.backbone = base
        self.classifier = nn.Sequential(
            nn.Linear(1024, 512),
            nn.ReLU(inplace=True),
            nn.Linear(512, num_classes),
        )

    def forward(self, pre: torch.Tensor, post: torch.Tensor) -> torch.Tensor:
        f_pre = self.backbone(pre)
        f_post = self.backbone(post)
        feat = torch.cat([f_pre, f_post], dim=1)
        return self.classifier(feat)


def load_model(checkpoint_path: str, device: torch.device):
    """Load checkpoint and return (model, class_names, val_metrics)."""
    ckpt = torch.load(checkpoint_path, map_location=device, weights_only=False)

    class_names = ckpt["class_names"]
    model = PrePostResNet(num_classes=len(class_names))

    state_dict = ckpt["model_state_dict"]
    # Defensive: strip DataParallel/DDP "module." prefix if present
    state_dict = {k.replace("module.", "", 1) if k.startswith("module.") else k: v
                  for k, v in state_dict.items()}

    missing, unexpected = model.load_state_dict(state_dict, strict=True)
    if missing or unexpected:
        raise RuntimeError(f"State dict mismatch. Missing={missing} Unexpected={unexpected}")

    model.to(device)
    model.eval()

    return model, class_names, ckpt.get("val_metrics", {})
