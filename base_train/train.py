"""
train.py — Building damage classification training pipeline.

Trains a ResNet-34-based classifier on post-disaster satellite image
crops to predict building damage severity (no-damage, minor, major,
destroyed). Supports class-imbalance handling via weighted sampling
and/or weighted loss, early stopping, and per-epoch macro F1 tracking.
"""

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"  # must be set before torch import

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
import torchvision.models as models
import torchvision.transforms as transforms
from PIL import Image
from sklearn.metrics import classification_report, f1_score
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ============================================================
# CONSTANTS
# ============================================================

IMAGE_SIZE = (128, 128)
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]
NUM_CLASSES = 4
CLASS_NAMES = ["no-damage", "minor-damage", "major-damage", "destroyed"]


# ============================================================
# CONFIG 
# ============================================================

@dataclass
class TrainingConfig:
    train_labels_csv: Path
    train_image_dir: Path
    test_labels_csv: Path
    test_image_dir: Path
    checkpoint_dir: Path = Path("../checkpoints")
    num_epochs: int = 20
    batch_size: int = 32
    learning_rate: float = 1e-4
    weight_decay: float = 1e-4
    freeze_backbone: bool = True
    use_weighted_sampler: bool = True
    early_stopping_patience: int = 5
    num_workers: int = 4
    dropout: float = 0.5
    device: Optional[torch.device] = None

    def __post_init__(self) -> None:
        self.train_labels_csv = Path(self.train_labels_csv)
        self.train_image_dir = Path(self.train_image_dir)
        self.test_labels_csv = Path(self.test_labels_csv)
        self.test_image_dir = Path(self.test_image_dir)
        self.checkpoint_dir = Path(self.checkpoint_dir)
        if self.device is None:
            self.device = (
                torch.device("mps") if torch.backends.mps.is_available()
                else torch.device("cuda") if torch.cuda.is_available()
                else torch.device("cpu")
            )


# ============================================================
# MODEL
# ============================================================

class SingleImageResNet34(nn.Module):
    """ResNet-34 classifier for single-image damage severity prediction."""

    def __init__(self, num_classes: int = NUM_CLASSES, pretrained: bool = True,
                 freeze_backbone: bool = False, dropout: float = 0.5) -> None:
        super().__init__()
        weights = "IMAGENET1K_V1" if pretrained else None
        self.resnet = models.resnet34(weights=weights)

        if freeze_backbone:
            for param in self.resnet.parameters():
                param.requires_grad = False

        in_features = self.resnet.fc.in_features
        self.resnet.fc = nn.Sequential(
            nn.Linear(in_features, 128),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(128, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.resnet(x)

    def set_backbone_trainable(self, trainable: bool) -> None:
        """Toggle backbone freezing without rebuilding the model (for Phase 2 fine-tuning)."""
        for param in self.resnet.parameters():
            param.requires_grad = trainable
        # classifier head always stays trainable
        for param in self.resnet.fc.parameters():
            param.requires_grad = True


# ============================================================
# DATASET
# ============================================================

def get_train_transform() -> transforms.Compose:
    """Augmented transform — used for training data only."""
    return transforms.Compose([
        transforms.Resize(IMAGE_SIZE),
        transforms.RandomHorizontalFlip(),
        transforms.RandomVerticalFlip(),
        transforms.RandomRotation(15),
        transforms.ColorJitter(brightness=0.1, contrast=0.1),
        transforms.ToTensor(),
        transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
    ])


def get_eval_transform() -> transforms.Compose:
    """Clean transform, no augmentation — used for test/inference."""
    return transforms.Compose([
        transforms.Resize(IMAGE_SIZE),
        transforms.ToTensor(),
        transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
    ])


class PostImageDamageDataset(Dataset):
    """Loads post-disaster building crops and their numeric damage labels."""

    def __init__(self, labels_csv_path: Path, image_dir: Path,
                 transform: Optional[transforms.Compose] = None) -> None:
        self.labels_df = pd.read_csv(labels_csv_path)
        self.image_dir = Path(image_dir)
        self.transform = transform or get_eval_transform()

        if not self.image_dir.is_dir():
            raise FileNotFoundError(f"Image directory not found: {self.image_dir}")

    def __len__(self) -> int:
        return len(self.labels_df)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, int]:
        row = self.labels_df.iloc[idx]
        image_path = self.image_dir / row["image_name"]
        img = Image.open(image_path).convert("RGB")
        img = self.transform(img)
        return img, int(row["damage_level"])


# ============================================================
# CLASS IMBALANCE HANDLING — reads the label CSV once, reused
# for both loss weights and the sampler (avoids double disk read)
# ============================================================

def compute_class_distribution(labels_csv_path: Path) -> pd.Series:
    """Reads label counts once; reused by both weighting strategies below."""
    df = pd.read_csv(labels_csv_path)
    return df["damage_level"].value_counts().sort_index()


def compute_class_weights(class_counts: pd.Series, num_classes: int = NUM_CLASSES) -> torch.Tensor:
    """Inverse-frequency class weights for CrossEntropyLoss."""
    total = class_counts.sum()
    weights = total / (num_classes * class_counts)
    return torch.tensor(weights.values, dtype=torch.float32)


def create_weighted_sampler(labels_csv_path: Path, class_counts: pd.Series) -> WeightedRandomSampler:
    """Builds a sampler that oversamples rare classes per batch."""
    df = pd.read_csv(labels_csv_path)
    inv_freq = 1.0 / class_counts
    sample_weights = df["damage_level"].map(inv_freq).values
    return WeightedRandomSampler(weights=sample_weights, num_samples=len(sample_weights), replacement=True)


# ============================================================
# METRIC TRACKING — replaces manual running-sum bookkeeping,
# shared identically between train and eval to avoid duplication
# ============================================================

class MetricTracker:
    """Accumulates loss/accuracy/predictions across a single epoch."""

    def __init__(self) -> None:
        self.total_loss = 0.0
        self.total_correct = 0
        self.total_samples = 0
        self.all_preds: list[int] = []
        self.all_labels: list[int] = []

    def update(self, loss: torch.Tensor, outputs: torch.Tensor, labels: torch.Tensor) -> None:
        batch_size = labels.size(0)
        self.total_loss += loss.item() * batch_size
        preds = outputs.argmax(dim=1)
        self.total_correct += (preds == labels).sum().item()
        self.total_samples += batch_size
        self.all_preds.extend(preds.cpu().tolist())
        self.all_labels.extend(labels.cpu().tolist())

    @property
    def avg_loss(self) -> float:
        return self.total_loss / max(self.total_samples, 1)

    @property
    def accuracy(self) -> float:
        return self.total_correct / max(self.total_samples, 1)

    @property
    def macro_f1(self) -> float:
        return f1_score(self.all_labels, self.all_preds, average="macro")


# ============================================================
# SHARED EPOCH LOGIC — single implementation used for both
# training and evaluation passes, eliminating duplicated code
# ============================================================

def run_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
    optimizer: Optional[optim.Optimizer] = None,
    desc: str = "",
) -> MetricTracker:
    """
    Runs one pass over `loader`. If `optimizer` is provided, runs in
    training mode with backprop; otherwise runs in eval/inference mode.
    """
    is_train = optimizer is not None
    model.train() if is_train else model.eval()
    tracker = MetricTracker()

    progress_bar = tqdm(loader, desc=desc, leave=False)
    context = torch.enable_grad() if is_train else torch.inference_mode()

    with context:
        for imgs, labels in progress_bar:
            imgs = imgs.to(device, non_blocking=True)
            labels = labels.to(device, non_blocking=True)

            if is_train:
                optimizer.zero_grad()

            outputs = model(imgs)
            loss = criterion(outputs, labels)

            if is_train:
                loss.backward()
                optimizer.step()

            tracker.update(loss, outputs, labels)
            progress_bar.set_postfix({"loss": f"{tracker.avg_loss:.4f}", "acc": f"{tracker.accuracy:.4f}"})

    return tracker


# ============================================================
# CHECKPOINTING
# ============================================================

def save_checkpoint(model: nn.Module, path: Path, epoch: int, metrics: MetricTracker) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "epoch": epoch,
        "model_state_dict": model.state_dict(),
        "test_loss": metrics.avg_loss,
        "test_acc": metrics.accuracy,
        "macro_f1": metrics.macro_f1,
    }, path)


# ============================================================
# MAIN TRAINING ROUTINE
# ============================================================

def train_post_classifier(config: TrainingConfig) -> nn.Module:
    """Trains and returns the damage classification model per `config`."""
    logger.info("Using device: %s", config.device)

    train_class_counts = compute_class_distribution(config.train_labels_csv)
    logger.info("Class counts: %s", train_class_counts.to_dict())

    class_weights = compute_class_weights(train_class_counts).to(config.device)
    logger.info("Class weights: %s", class_weights.tolist())

    train_dataset = PostImageDamageDataset(config.train_labels_csv, config.train_image_dir, get_train_transform())
    test_dataset = PostImageDamageDataset(config.test_labels_csv, config.test_image_dir, get_eval_transform())
    logger.info("Train dataset: %d images | Test dataset: %d images", len(train_dataset), len(test_dataset))

    if config.use_weighted_sampler:
        sampler = create_weighted_sampler(config.train_labels_csv, train_class_counts)
        train_loader = DataLoader(train_dataset, batch_size=config.batch_size, sampler=sampler,
                                   num_workers=config.num_workers)
        logger.info("Using WeightedRandomSampler for class balance.")
    else:
        train_loader = DataLoader(train_dataset, batch_size=config.batch_size, shuffle=True,
                                   num_workers=config.num_workers)

    test_loader = DataLoader(test_dataset, batch_size=config.batch_size, shuffle=False,
                              num_workers=config.num_workers)

    model = SingleImageResNet34(
        num_classes=NUM_CLASSES, pretrained=True,
        freeze_backbone=config.freeze_backbone, dropout=config.dropout,
    ).to(config.device)

    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min", patience=3, factor=0.5)

    best_test_loss = float("inf")
    epochs_without_improvement = 0
    checkpoint_path = config.checkpoint_dir / "best_post_classifier_v3.pt"

    for epoch in range(config.num_epochs):
        epoch_label = f"Epoch {epoch + 1}/{config.num_epochs}"

        train_metrics = run_epoch(model, train_loader, criterion, config.device,
                                   optimizer=optimizer, desc=f"{epoch_label} [Train]")
        test_metrics = run_epoch(model, test_loader, criterion, config.device,
                                  optimizer=None, desc=f"{epoch_label} [Test]")

        scheduler.step(test_metrics.avg_loss)

        logger.info(
            "%s | Train Loss: %.4f, Train Acc: %.4f | Test Loss: %.4f, Test Acc: %.4f, Macro F1: %.4f",
            epoch_label, train_metrics.avg_loss, train_metrics.accuracy,
            test_metrics.avg_loss, test_metrics.accuracy, test_metrics.macro_f1,
        )

        if (epoch + 1) % 5 == 0:
            logger.info("\n%s", classification_report(
                test_metrics.all_labels, test_metrics.all_preds, target_names=CLASS_NAMES,
            ))

        if test_metrics.avg_loss < best_test_loss:
            best_test_loss = test_metrics.avg_loss
            epochs_without_improvement = 0
            save_checkpoint(model, checkpoint_path, epoch, test_metrics)
            logger.info("  -> Saved new best model (test_loss=%.4f)", best_test_loss)
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= config.early_stopping_patience:
                logger.info("No improvement for %d epochs. Stopping early at epoch %d.",
                             config.early_stopping_patience, epoch + 1)
                break

    return model


# ============================================================
# INFERENCE
# ============================================================

def classify_image(model: nn.Module, image_path: Path, device: torch.device,
                    transform: Optional[transforms.Compose] = None) -> tuple[int, np.ndarray]:
    """Runs the model on a single image; returns predicted class and full probability vector."""
    transform = transform or get_eval_transform()
    img = Image.open(image_path).convert("RGB")
    img_tensor = transform(img).unsqueeze(0).to(device)

    model.eval()
    with torch.inference_mode():
        logits = model(img_tensor)
        probs = torch.softmax(logits, dim=1).cpu().numpy()[0]

    return int(np.argmax(probs)), probs


def compute_relative_damage(model: nn.Module, pre_path: Path, post_path: Path, device: torch.device) -> dict:
    """Classifies pre- and post-disaster crops independently and computes the difference."""
    pre_class, pre_probs = classify_image(model, pre_path, device)
    post_class, post_probs = classify_image(model, post_path, device)

    return {
        "pre_predicted_class": pre_class,
        "pre_probs": pre_probs.tolist(),
        "post_predicted_class": post_class,
        "post_probs": post_probs.tolist(),
        "class_diff": post_class - pre_class,
        "prob_diff": (post_probs - pre_probs).tolist(),
    }


# ============================================================
# ENTRY POINT
# ============================================================

def main() -> None:
    config = TrainingConfig(
        train_labels_csv="../data/training_labels.csv",
        train_image_dir="../data/processed/train/post",
        test_labels_csv="../data/testing1_labels.csv",
        test_image_dir="../data/processed/test1/post",
        num_epochs=20,
        batch_size=32,
        learning_rate=1e-4,
        freeze_backbone=True,
        early_stopping_patience=5,
    )
    train_post_classifier(config)


if __name__ == "__main__":
    main()