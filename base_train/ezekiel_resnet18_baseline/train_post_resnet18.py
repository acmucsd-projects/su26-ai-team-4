#!/usr/bin/env python3
"""POST-only ResNet-18 with inverse-frequency weighted cross entropy."""

from pathlib import Path
import random

from PIL import Image
import torch
from torch import nn
from torch.utils.data import Dataset
from torchvision import transforms
from torchvision.models import ResNet18_Weights, resnet18
from torchvision.transforms import functional as TF

from train_common import (ExperimentSpec, IMAGENET_MEAN, IMAGENET_STD, add_training_arguments,
                          compute_class_weights, move_image_tensor, move_targets, run_experiment)


BASELINE_DIR = Path(__file__).resolve().parent


class PostDataset(Dataset):
    """Cached POST crops with the original independent geometric augmentation."""
    def __init__(self, df, training: bool):
        self.paths = df["post_path"].tolist()
        self.targets = df["target"].astype(int).to_numpy()
        self.building_ids = df["building_id"].astype(str).tolist()
        self.training = training

    def __len__(self):
        return len(self.targets)

    def __getitem__(self, index):
        with Image.open(self.paths[index]) as image:
            image = image.convert("RGB").copy()
        if self.training:
            if random.random() < 0.5:
                image = TF.hflip(image)
            if random.random() < 0.5:
                image = TF.vflip(image)
            image = TF.rotate(image, random.uniform(-10.0, 10.0),
                              interpolation=transforms.InterpolationMode.BILINEAR, fill=0)
        tensor = TF.to_tensor(image)
        return (tensor - IMAGENET_MEAN) / IMAGENET_STD, int(self.targets[index]), self.building_ids[index]


class PostResNet18(nn.Module):
    """ImageNet-pretrained ResNet-18: 512 features -> 512-unit head -> 4 classes."""
    def __init__(self):
        super().__init__()
        backbone = resnet18(weights=ResNet18_Weights.DEFAULT)
        feature_dim = backbone.fc.in_features
        backbone.fc = nn.Identity()
        self.backbone = backbone
        self.classifier = nn.Sequential(nn.Linear(feature_dim, 512), nn.ReLU(inplace=True), nn.Linear(512, 4))

    def forward(self, images):
        return self.classifier(self.backbone(images))


def build_criterion(train_df, device):
    class_weights = compute_class_weights(train_df, device)
    return nn.CrossEntropyLoss(weight=class_weights), class_weights


def forward_batch(model, batch, device):
    images, targets, ids = batch
    return model(move_image_tensor(images, device)), move_targets(targets, device), ids


def main():
    args = add_training_arguments("Train the POST-only xBD ResNet-18 baseline.",
                                 BASELINE_DIR / "cache" / "cache_manifest.csv", BASELINE_DIR / "results")
    run_experiment(args, ExperimentSpec(
        model_name="post_resnet18", title="xBD POST-ONLY RESNET-18 BASELINE", input_mode="post_only",
        loss_name="inverse_frequency_weighted_cross_entropy", class_weighting=True,
        loss_display="inverse-frequency weighted cross entropy", architecture="ResNet-18 (512-feature POST head)",
        pretrained_weights="ImageNet ResNet18_Weights.DEFAULT", paired_input=False, dataset_class=PostDataset,
        build_model=PostResNet18, build_criterion=build_criterion, forward_batch=forward_batch,
    ))


if __name__ == "__main__":
    main()
