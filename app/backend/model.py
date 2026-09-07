"""Model architecture compatible with released PRE+POST plain-CE checkpoints."""

from __future__ import annotations

import torch
from torch import nn
from torchvision.models import resnet18


class PrePostResNet18(nn.Module):
    """Apply one shared ResNet-18 backbone to PRE and POST building crops."""

    def __init__(self, num_classes: int = 4) -> None:
        super().__init__()
        backbone = resnet18(weights=None)
        feature_dim = backbone.fc.in_features
        backbone.fc = nn.Identity()
        self.backbone = backbone
        self.classifier = nn.Sequential(
            nn.Linear(feature_dim * 2, 512),
            nn.ReLU(inplace=True),
            nn.Linear(512, num_classes),
        )

    def forward(self, pre_images: torch.Tensor, post_images: torch.Tensor) -> torch.Tensor:
        pre_features = self.backbone(pre_images)
        post_features = self.backbone(post_images)
        return self.classifier(torch.cat([pre_features, post_features], dim=1))
