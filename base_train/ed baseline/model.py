"""
model.py
--------
Dual-encoder ("Siamese") CNN for building damage classification.

Why dual-encoder: damage assessment is inherently a *change detection*
problem - the label depends on how the post-disaster crop differs from the
pre-disaster crop, not on either image alone. A shared-weight CNN encodes
both crops into feature vectors; we then fuse them with
[pre, post, |pre - post|, pre * post] before the classifier head, which
gives the network an explicit "difference" signal on top of raw appearance.

Two backbone options:
  - "simple": a lightweight from-scratch CNN (no external weights needed,
    good default in offline/sandboxed environments).
  - "resnet18": torchvision ResNet-18, optionally ImageNet-pretrained
    (requires internet access to download weights the first time).
"""

import torch
import torch.nn as nn
import torchvision


class SimpleCNNBackbone(nn.Module):
    """Lightweight conv backbone, no pretrained weights required."""

    def __init__(self, in_channels=3, out_dim=256):
        super().__init__()

        def block(c_in, c_out, pool=True):
            layers = [
                nn.Conv2d(c_in, c_out, 3, padding=1, bias=False),
                nn.BatchNorm2d(c_out),
                nn.ReLU(inplace=True),
                nn.Conv2d(c_out, c_out, 3, padding=1, bias=False),
                nn.BatchNorm2d(c_out),
                nn.ReLU(inplace=True),
            ]
            if pool:
                layers.append(nn.MaxPool2d(2))
            return nn.Sequential(*layers)

        self.features = nn.Sequential(
            block(in_channels, 32),   # 128 -> 64
            block(32, 64),            # 64 -> 32
            block(64, 128),           # 32 -> 16
            block(128, 256),          # 16 -> 8
        )
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.out_dim = out_dim
        self.proj = nn.Linear(256, out_dim)

    def forward(self, x):
        x = self.features(x)
        x = self.pool(x).flatten(1)
        return self.proj(x)


class ResNet18Backbone(nn.Module):
    """torchvision ResNet-18 with the FC head replaced by a projection."""

    def __init__(self, out_dim=256, pretrained=False):
        super().__init__()
        weights = torchvision.models.ResNet18_Weights.IMAGENET1K_V1 if pretrained else None
        net = torchvision.models.resnet18(weights=weights)
        self.body = nn.Sequential(*list(net.children())[:-1])  # drop fc
        self.out_dim = out_dim
        self.proj = nn.Linear(net.fc.in_features, out_dim)

    def forward(self, x):
        x = self.body(x).flatten(1)
        return self.proj(x)


def build_backbone(name: str, out_dim: int, pretrained: bool = False):
    if name == "simple":
        return SimpleCNNBackbone(out_dim=out_dim)
    if name == "resnet18":
        return ResNet18Backbone(out_dim=out_dim, pretrained=pretrained)
    raise ValueError(f"Unknown backbone: {name}")


class SiameseDamageNet(nn.Module):
    """Shared-weight dual encoder + fusion classifier head."""

    def __init__(
        self,
        num_classes: int = 4,
        backbone: str = "simple",
        feat_dim: int = 256,
        pretrained: bool = False,
        dropout: float = 0.3,
    ):
        super().__init__()
        self.encoder = build_backbone(backbone, feat_dim, pretrained)

        # fusion: [pre, post, |pre-post|, pre*post] -> 4 * feat_dim
        fusion_dim = feat_dim * 4
        self.classifier = nn.Sequential(
            nn.Linear(fusion_dim, 512),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
            nn.Linear(512, 128),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
            nn.Linear(128, num_classes),
        )

    def forward(self, pre_img, post_img):
        pre_feat = self.encoder(pre_img)
        post_feat = self.encoder(post_img)  # shared weights (Siamese)

        diff = torch.abs(pre_feat - post_feat)
        prod = pre_feat * post_feat
        fused = torch.cat([pre_feat, post_feat, diff, prod], dim=1)

        return self.classifier(fused)


if __name__ == "__main__":
    # quick shape sanity check
    model = SiameseDamageNet(num_classes=4, backbone="simple")
    pre = torch.randn(2, 3, 128, 128)
    post = torch.randn(2, 3, 128, 128)
    out = model(pre, post)
    print("output shape:", out.shape)  # expect (2, 4)
