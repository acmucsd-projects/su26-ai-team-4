#!/usr/bin/env python3
"""Shared-backbone PRE+POST ResNet-18 with ordinary (unweighted) cross entropy."""

# Keep this entry point parallel to train_prepost_resnet18.py: its only scientific
# difference is the explicit unweighted loss below.
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
                          move_image_tensor, move_targets, run_experiment)


BASELINE_DIR = Path(__file__).resolve().parent


class PrePostDataset(Dataset):
    """Cached pairs with synchronized transforms and optional in-memory resizing."""
    def __init__(self, df, training: bool, image_size: int):
        self.pre_paths, self.post_paths = df["pre_path"].tolist(), df["post_path"].tolist()
        self.targets = df["target"].astype(int).to_numpy()
        self.building_ids, self.training = df["building_id"].astype(str).tolist(), training
        self.image_size = image_size

    def __len__(self):
        return len(self.targets)

    def __getitem__(self, index):
        with Image.open(self.pre_paths[index]) as image:
            pre_image = image.convert("RGB").copy()
        with Image.open(self.post_paths[index]) as image:
            post_image = image.convert("RGB").copy()
        if self.image_size != 224:
            size = [self.image_size, self.image_size]
            pre_image = TF.resize(
                pre_image,
                size,
                interpolation=transforms.InterpolationMode.BILINEAR,
                antialias=True,
            )
            post_image = TF.resize(
                post_image,
                size,
                interpolation=transforms.InterpolationMode.BILINEAR,
                antialias=True,
            )
        if self.training:
            use_hflip, use_vflip, angle = random.random() < 0.5, random.random() < 0.5, random.uniform(-10.0, 10.0)
            if use_hflip:
                pre_image, post_image = TF.hflip(pre_image), TF.hflip(post_image)
            if use_vflip:
                pre_image, post_image = TF.vflip(pre_image), TF.vflip(post_image)
            pre_image = TF.rotate(pre_image, angle, interpolation=transforms.InterpolationMode.BILINEAR, fill=0)
            post_image = TF.rotate(post_image, angle, interpolation=transforms.InterpolationMode.BILINEAR, fill=0)
        pre_tensor, post_tensor = TF.to_tensor(pre_image), TF.to_tensor(post_image)
        return ((pre_tensor - IMAGENET_MEAN) / IMAGENET_STD, (post_tensor - IMAGENET_MEAN) / IMAGENET_STD,
                int(self.targets[index]), self.building_ids[index])


class PrePostResNet18(nn.Module):
    """One ImageNet ResNet-18 backbone for both images; 512+512 features are concatenated."""
    def __init__(self):
        super().__init__()
        backbone = resnet18(weights=ResNet18_Weights.DEFAULT)
        feature_dim = backbone.fc.in_features
        backbone.fc = nn.Identity()
        self.backbone = backbone
        self.classifier = nn.Sequential(nn.Linear(feature_dim * 2, 512), nn.ReLU(inplace=True), nn.Linear(512, 4))

    def forward(self, pre_images, post_images):
        return self.classifier(torch.cat([self.backbone(pre_images), self.backbone(post_images)], dim=1))


def build_criterion(train_df, device):
    del train_df, device
    return nn.CrossEntropyLoss(), None


def forward_batch(model, batch, device):
    pre_images, post_images, targets, ids = batch
    return (model(move_image_tensor(pre_images, device), move_image_tensor(post_images, device)),
            move_targets(targets, device), ids)


def main():
    args = add_training_arguments("Train the paired PRE+POST xBD ResNet-18 plain-CE baseline.",
                                 BASELINE_DIR / "cache" / "cache_manifest.csv", BASELINE_DIR / "results_prepost_plaince")
    run_experiment(args, ExperimentSpec(
        model_name="prepost_resnet18_plaince", title="xBD PAIRED PRE+POST RESNET-18 PLAIN-CE BASELINE",
        input_mode="prepost_shared_backbone_concat", loss_name="cross_entropy", class_weighting=False,
        loss_display="plain cross entropy (no class weights)",
        architecture="shared ResNet-18 (512 PRE + 512 POST concatenated)",
        pretrained_weights="ImageNet ResNet18_Weights.DEFAULT", paired_input=True, dataset_class=PrePostDataset,
        build_model=PrePostResNet18, build_criterion=build_criterion, forward_batch=forward_batch,
    ))


if __name__ == "__main__":
    main()
