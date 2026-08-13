#!/usr/bin/env python3
"""
train_post_resnet18.py
======================

POST-only ResNet-18 baseline for xBD building-damage classification.

This script is intentionally limited to one task:

    train and evaluate a ResNet-18 using POST-disaster building crops.

It assumes prepare_xbd_cache.py has already created the local 224 x 224 cache.

EXPECTED DIRECTORY LAYOUT
-------------------------

repo/
├── data/
│   ├── manifest_train.csv
│   └── processed/
│
└── base_train/
    └── ezekiel_post_resnet18_baseline/
        ├── prepare_xbd_cache.py
        ├── train_post_resnet18.py      <-- THIS FILE
        │
        ├── cache/
        │   ├── cache_manifest.csv
        │   ├── pre/
        │   └── post/
        │
        └── results/                    <-- CREATED BY THIS SCRIPT

NORMAL USE
----------

From this baseline directory:

    python train_post_resnet18.py

No path arguments are required in the standard layout.

INPUT
-----

    ./cache/cache_manifest.csv
    ./cache/post/*.png

The cache manifest is expected to contain:

    cache_id
    building_id
    scene_id
    damage_label
    target
    pre_png
    post_png

Only post_png is used by this model.

CLASSES
-------

    0 = no-damage
    1 = minor-damage
    2 = major-damage
    3 = destroyed

MODEL
-----

    224 x 224 POST-disaster RGB crop
        -> ImageNet-pretrained ResNet-18
        -> 512-dimensional feature vector
        -> 512-unit ReLU classification layer
        -> four damage classes

TRAIN / VALIDATION SPLIT
------------------------

The split is grouped by scene_id rather than by individual building.

This prevents buildings from the same satellite scene from appearing in both
training and validation, which would make validation less independent.

Default split:
    80% of scenes -> training
    20% of scenes -> validation

Validation is capped at 15,000 buildings to keep evaluation time consistent.

CLASS IMBALANCE
---------------

xBD contains substantially more no-damage buildings than the other classes.

The baseline therefore uses inverse-frequency class weights with cross-entropy
loss so minority classes have greater influence during optimization.

TRAINING DEFAULTS
-----------------

    architecture:     ResNet-18
    initialization:   ImageNet pretrained weights
    epochs:           8
    batch size:       128
    optimizer:        AdamW
    learning rate:    1e-4
    weight decay:     1e-4
    loss:             weighted cross entropy
    seed:             42
    split seed:       42
    augmentation:     horizontal flip, vertical flip, +/-10 degree rotation
    precision:        CUDA automatic mixed precision

The checkpoint with the highest validation Macro F1 is retained.

PRIMARY METRIC
--------------

Macro F1 is the primary comparison metric because it gives each damage class
equal weight despite class imbalance.

Accuracy, loss, per-class precision, recall, F1, and a confusion matrix are
also recorded.

OUTPUT
------

The script creates:

    ./results/
        ├── best.pt
        ├── history.csv
        ├── result.json
        ├── summary.txt
        ├── confusion_matrix.csv
        ├── val_predictions.csv
        ├── split_manifest.csv
        └── split_summary.csv

OPTIONAL OVERRIDES
------------------

Examples:

    python train_post_resnet18.py --epochs 12

    python train_post_resnet18.py --batch-size 64

    python train_post_resnet18.py --cache-manifest "D:\\cache\\cache_manifest.csv"

    python train_post_resnet18.py --results-dir "D:\\results"

The standard baseline values should be left unchanged when reproducing the
reference experiment.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import time
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from torchvision.models import ResNet18_Weights, resnet18
from torchvision.transforms import functional as TF

from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
)
from sklearn.model_selection import GroupShuffleSplit


# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------

BASELINE_DIR = Path(__file__).resolve().parent
DEFAULT_CACHE_MANIFEST = BASELINE_DIR / "cache" / "cache_manifest.csv"
DEFAULT_RESULTS_DIR = BASELINE_DIR / "results"


# ---------------------------------------------------------------------------
# CLASS DEFINITIONS
# ---------------------------------------------------------------------------

CLASS_NAMES = [
    "no-damage",
    "minor-damage",
    "major-damage",
    "destroyed",
]

SHORT_CLASS_NAMES = [
    "no",
    "minor",
    "major",
    "destroyed",
]


# ---------------------------------------------------------------------------
# IMAGENET NORMALIZATION
# ---------------------------------------------------------------------------

# The model starts from ImageNet-pretrained weights, so inputs use the
# normalization statistics expected by those weights.

IMAGENET_MEAN = torch.tensor(
    [0.485, 0.456, 0.406],
    dtype=torch.float32,
).view(3, 1, 1)

IMAGENET_STD = torch.tensor(
    [0.229, 0.224, 0.225],
    dtype=torch.float32,
).view(3, 1, 1)


# ---------------------------------------------------------------------------
# ARGUMENTS
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Train the POST-only xBD ResNet-18 baseline.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--cache-manifest",
        type=Path,
        default=DEFAULT_CACHE_MANIFEST,
        help="Cache manifest created by prepare_xbd_cache.py.",
    )

    parser.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help="Directory for checkpoints, metrics, and predictions.",
    )

    parser.add_argument(
        "--epochs",
        type=int,
        default=8,
        help="Number of training epochs.",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=128,
        help="Training and validation batch size.",
    )

    parser.add_argument(
        "--learning-rate",
        type=float,
        default=1e-4,
        help="AdamW learning rate.",
    )

    parser.add_argument(
        "--weight-decay",
        type=float,
        default=1e-4,
        help="AdamW weight decay.",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Training random seed.",
    )

    parser.add_argument(
        "--split-seed",
        type=int,
        default=42,
        help="Scene-level train/validation split seed.",
    )

    parser.add_argument(
        "--val-fraction",
        type=float,
        default=0.20,
        help="Fraction of scenes assigned to validation.",
    )

    parser.add_argument(
        "--max-val-buildings",
        type=int,
        default=15000,
        help="Maximum number of validation buildings.",
    )

    parser.add_argument(
        "--num-workers",
        type=int,
        default=None,
        help="DataLoader workers. A conservative default is chosen when omitted.",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# REPRODUCIBILITY / TIMING HELPERS
# ---------------------------------------------------------------------------

def seed_everything(seed: int) -> None:
    """Seed Python, NumPy, and PyTorch random number generators."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def worker_init_fn(worker_id: int) -> None:
    """Give each DataLoader worker deterministic Python and NumPy seeds."""
    worker_seed = torch.initial_seed() % (2 ** 32)
    random.seed(worker_seed)
    np.random.seed(worker_seed)


def default_num_workers() -> int:
    """
    Choose a conservative DataLoader worker count.

    Windows multiprocessing can use substantial RAM, so the default is kept
    lower there. Users may override this with --num-workers.
    """
    cpu_count = os.cpu_count() or 1

    if platform.system() == "Windows":
        return min(2, cpu_count)

    return min(4, cpu_count)


def format_seconds(seconds: float) -> str:
    """Convert elapsed seconds to a compact readable duration."""
    seconds = int(max(0, round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"

    return f"{minutes}m {seconds:02d}s"


# ---------------------------------------------------------------------------
# CACHE MANIFEST
# ---------------------------------------------------------------------------

def load_cache_manifest(path: Path) -> pd.DataFrame:
    """
    Load the prepared cache and resolve POST image paths.

    post_png is stored relative to cache_manifest.csv, so the cache directory
    remains portable between machines.
    """
    path = path.expanduser().resolve()

    if not path.exists():
        raise SystemExit(
            "Cache manifest was not found.\n\n"
            f"Expected:\n    {path}\n\n"
            "Run prepare_xbd_cache.py before training."
        )

    df = pd.read_csv(
        path,
        dtype={"cache_id": str},
    )

    required = {
        "cache_id",
        "building_id",
        "scene_id",
        "damage_label",
        "target",
        "post_png",
    }

    missing = required - set(df.columns)

    if missing:
        raise SystemExit(
            "cache_manifest.csv is missing required columns:\n"
            f"    {sorted(missing)}"
        )

    cache_root = path.parent

    df["post_path"] = df["post_png"].map(
        lambda relative_path: str(
            (
                cache_root
                / str(relative_path)
            ).resolve()
        )
    )

    # Fail early if the cache is incomplete.
    missing_files = [
        path
        for path in df["post_path"]
        if not Path(path).exists()
    ]

    if missing_files:
        example = missing_files[0]

        raise SystemExit(
            "POST cache is incomplete.\n\n"
            f"Missing files: {len(missing_files):,}\n"
            f"Example:\n    {example}\n\n"
            "Re-run prepare_xbd_cache.py to restore the cache."
        )

    return df


# ---------------------------------------------------------------------------
# SCENE-DISJOINT SPLIT
# ---------------------------------------------------------------------------

def make_scene_split(
    df: pd.DataFrame,
    results_dir: Path,
    split_seed: int,
    val_fraction: float,
    max_val_buildings: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split the dataset by scene_id.

    Buildings from one satellite scene may share visual context. Grouping by
    scene prevents the same scene from leaking into both training and
    validation.
    """
    splitter = GroupShuffleSplit(
        n_splits=1,
        test_size=val_fraction,
        random_state=split_seed,
    )

    train_indices, val_indices = next(
        splitter.split(
            df,
            groups=df["scene_id"],
        )
    )

    train_df = (
        df.iloc[train_indices]
        .copy()
        .reset_index(drop=True)
    )

    val_df = (
        df.iloc[val_indices]
        .copy()
        .reset_index(drop=True)
    )

    if len(val_df) > max_val_buildings:
        val_df = (
            val_df.sample(
                n=max_val_buildings,
                random_state=split_seed,
            )
            .reset_index(drop=True)
        )

    overlap = (
        set(train_df["scene_id"])
        & set(val_df["scene_id"])
    )

    if overlap:
        raise RuntimeError(
            f"Scene leakage detected: {len(overlap)} overlapping scenes."
        )

    # Save the exact split so results can be reproduced and audited.
    split_manifest = pd.concat(
        [
            train_df[
                [
                    "cache_id",
                    "building_id",
                    "scene_id",
                    "damage_label",
                    "target",
                ]
            ].assign(experiment_split="train"),

            val_df[
                [
                    "cache_id",
                    "building_id",
                    "scene_id",
                    "damage_label",
                    "target",
                ]
            ].assign(experiment_split="validation"),
        ],
        ignore_index=True,
    )

    split_manifest.to_csv(
        results_dir / "split_manifest.csv",
        index=False,
    )

    summary_rows = []

    for split_name, part in [
        ("train", train_df),
        ("validation", val_df),
    ]:
        counts = (
            part["target"]
            .value_counts()
            .reindex(
                [0, 1, 2, 3],
                fill_value=0,
            )
        )

        summary_rows.append({
            "split": split_name,
            "buildings": len(part),
            "scenes": part["scene_id"].nunique(),
            "no_damage": int(counts[0]),
            "minor_damage": int(counts[1]),
            "major_damage": int(counts[2]),
            "destroyed": int(counts[3]),
        })

    pd.DataFrame(
        summary_rows
    ).to_csv(
        results_dir / "split_summary.csv",
        index=False,
    )

    return train_df, val_df


# ---------------------------------------------------------------------------
# DATASET
# ---------------------------------------------------------------------------

class PostDataset(Dataset):
    """Dataset for cached POST-disaster building crops."""

    def __init__(
        self,
        df: pd.DataFrame,
        training: bool,
    ):
        self.paths = df["post_path"].tolist()
        self.targets = df["target"].astype(int).to_numpy()
        self.building_ids = df["building_id"].astype(str).tolist()
        self.training = training

    def __len__(self) -> int:
        return len(self.targets)

    def __getitem__(self, index: int):
        with Image.open(
            self.paths[index]
        ) as image:
            image = image.convert("RGB").copy()

        # Orientation augmentation is applied only during training.
        if self.training:
            if random.random() < 0.5:
                image = TF.hflip(image)

            if random.random() < 0.5:
                image = TF.vflip(image)

            image = TF.rotate(
                image,
                random.uniform(-10.0, 10.0),
                interpolation=transforms.InterpolationMode.BILINEAR,
                fill=0,
            )

        tensor = TF.to_tensor(image)

        tensor = (
            tensor - IMAGENET_MEAN
        ) / IMAGENET_STD

        return (
            tensor,
            int(self.targets[index]),
            self.building_ids[index],
        )


# ---------------------------------------------------------------------------
# MODEL
# ---------------------------------------------------------------------------

class PostResNet18(nn.Module):
    """
    ImageNet-pretrained ResNet-18 with a four-class damage head.

    The original 1000-class ImageNet output layer is removed. ResNet-18 then
    produces a 512-dimensional feature vector that is passed through a small
    task-specific classifier.
    """

    def __init__(self):
        super().__init__()

        backbone = resnet18(
            weights=ResNet18_Weights.DEFAULT
        )

        feature_dim = backbone.fc.in_features

        backbone.fc = nn.Identity()

        self.backbone = backbone

        self.classifier = nn.Sequential(
            nn.Linear(
                feature_dim,
                512,
            ),
            nn.ReLU(
                inplace=True
            ),
            nn.Linear(
                512,
                4,
            ),
        )

    def forward(self, images):
        features = self.backbone(images)
        return self.classifier(features)


# ---------------------------------------------------------------------------
# CLASS-WEIGHTED LOSS
# ---------------------------------------------------------------------------

def compute_class_weights(
    train_df: pd.DataFrame,
    device: torch.device,
) -> torch.Tensor:
    """
    Compute inverse-frequency class weights from the training split.

    Each class therefore contributes approximately equal total weight to the
    cross-entropy objective despite unequal class frequencies.
    """
    counts = (
        train_df["target"]
        .value_counts()
        .reindex(
            [0, 1, 2, 3],
            fill_value=0,
        )
        .to_numpy(dtype=np.float64)
    )

    weights = (
        counts.sum()
        / (
            4.0
            * np.maximum(
                counts,
                1.0,
            )
        )
    )

    return torch.tensor(
        weights,
        dtype=torch.float32,
        device=device,
    )


# ---------------------------------------------------------------------------
# METRICS
# ---------------------------------------------------------------------------

def calculate_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
) -> dict:
    """Calculate accuracy, Macro F1, and per-class precision/recall/F1."""
    precision, recall, f1, support = (
        precision_recall_fscore_support(
            y_true,
            y_pred,
            labels=[0, 1, 2, 3],
            zero_division=0,
        )
    )

    metrics = {
        "accuracy": float(
            accuracy_score(
                y_true,
                y_pred,
            )
        ),
        "macro_f1": float(
            np.mean(f1)
        ),
    }

    for index, name in enumerate(
        SHORT_CLASS_NAMES
    ):
        metrics[f"precision_{name}"] = float(precision[index])
        metrics[f"recall_{name}"] = float(recall[index])
        metrics[f"f1_{name}"] = float(f1[index])
        metrics[f"support_{name}"] = int(support[index])

    return metrics


# ---------------------------------------------------------------------------
# TRAINING
# ---------------------------------------------------------------------------

def train_one_epoch(
    model,
    loader,
    optimizer,
    scaler,
    criterion,
    device,
):
    """Run one training epoch."""
    model.train()

    seen = 0
    correct = 0
    total_loss = 0.0

    torch.cuda.synchronize()
    start = time.perf_counter()

    for images, targets, _ in loader:
        images = images.to(
            device,
            non_blocking=True,
            memory_format=torch.channels_last,
        )

        targets = targets.to(
            device,
            non_blocking=True,
        )

        optimizer.zero_grad(
            set_to_none=True
        )

        with torch.autocast(
            device_type="cuda",
            dtype=torch.float16,
        ):
            logits = model(images)
            loss = criterion(logits, targets)

        scaler.scale(loss).backward()
        scaler.step(optimizer)
        scaler.update()

        batch_size = targets.size(0)

        seen += batch_size
        total_loss += float(loss.detach()) * batch_size

        correct += int(
            (
                logits.argmax(dim=1)
                == targets
            )
            .sum()
            .item()
        )

    torch.cuda.synchronize()

    elapsed = (
        time.perf_counter()
        - start
    )

    return {
        "loss": total_loss / seen,
        "accuracy": correct / seen,
        "samples_per_sec": seen / elapsed,
        "elapsed_sec": elapsed,
    }


@torch.inference_mode()
def evaluate(
    model,
    loader,
    criterion,
    device,
    save_predictions=False,
):
    """Evaluate the model without gradient computation."""
    model.eval()

    seen = 0
    total_loss = 0.0

    y_true = []
    y_pred = []

    building_ids = []
    probability_batches = []

    torch.cuda.synchronize()
    start = time.perf_counter()

    for images, targets, ids in loader:
        images = images.to(
            device,
            non_blocking=True,
            memory_format=torch.channels_last,
        )

        targets = targets.to(
            device,
            non_blocking=True,
        )

        with torch.autocast(
            device_type="cuda",
            dtype=torch.float16,
        ):
            logits = model(images)
            loss = criterion(logits, targets)

        probabilities = torch.softmax(
            logits.float(),
            dim=1,
        )

        predictions = probabilities.argmax(
            dim=1
        )

        batch_size = targets.size(0)

        seen += batch_size
        total_loss += float(loss.detach()) * batch_size

        y_true.extend(
            targets.cpu().tolist()
        )

        y_pred.extend(
            predictions.cpu().tolist()
        )

        if save_predictions:
            building_ids.extend(
                list(ids)
            )

            probability_batches.append(
                probabilities.cpu().numpy()
            )

    torch.cuda.synchronize()

    elapsed = (
        time.perf_counter()
        - start
    )

    y_true = np.asarray(
        y_true,
        dtype=np.int64,
    )

    y_pred = np.asarray(
        y_pred,
        dtype=np.int64,
    )

    metrics = calculate_metrics(
        y_true,
        y_pred,
    )

    metrics["loss"] = (
        total_loss / seen
    )

    metrics["samples_per_sec"] = (
        seen / elapsed
    )

    prediction_df = None

    if save_predictions:
        probabilities = np.concatenate(
            probability_batches,
            axis=0,
        )

        prediction_df = pd.DataFrame({
            "building_id": building_ids,
            "target": y_true,
            "prediction": y_pred,
            "p_no_damage": probabilities[:, 0],
            "p_minor_damage": probabilities[:, 1],
            "p_major_damage": probabilities[:, 2],
            "p_destroyed": probabilities[:, 3],
        })

    return (
        metrics,
        prediction_df,
        y_true,
        y_pred,
    )


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    if not torch.cuda.is_available():
        raise SystemExit(
            "CUDA is required by this baseline script, but no CUDA device "
            "was detected."
        )

    seed_everything(
        args.seed
    )

    device = torch.device(
        "cuda"
    )

    # Fixed-size inputs allow cuDNN to benchmark efficient convolution kernels.
    torch.backends.cudnn.benchmark = True

    # Modern NVIDIA GPUs can accelerate matrix operations with TF32.
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.set_float32_matmul_precision(
        "high"
    )

    cache_manifest_path = (
        args.cache_manifest
        .expanduser()
        .resolve()
    )

    results_dir = (
        args.results_dir
        .expanduser()
        .resolve()
    )

    results_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    num_workers = (
        args.num_workers
        if args.num_workers is not None
        else default_num_workers()
    )

    print("=" * 80)
    print("xBD POST-ONLY RESNET-18 BASELINE")
    print("=" * 80)
    print()
    print(f"GPU:             {torch.cuda.get_device_name(0)}")
    print(f"PyTorch:         {torch.__version__}")
    print(f"Cache manifest:  {cache_manifest_path}")
    print(f"Results:         {results_dir}")
    print(f"Epochs:          {args.epochs}")
    print(f"Batch size:      {args.batch_size}")
    print(f"Workers:         {num_workers}")
    print(f"Seed:            {args.seed}")
    print(f"Split seed:      {args.split_seed}")
    print()

    # -----------------------------------------------------------------------
    # Load prepared data and create the scene-disjoint split.
    # -----------------------------------------------------------------------

    df = load_cache_manifest(
        cache_manifest_path
    )

    train_df, val_df = make_scene_split(
        df=df,
        results_dir=results_dir,
        split_seed=args.split_seed,
        val_fraction=args.val_fraction,
        max_val_buildings=args.max_val_buildings,
    )

    print(
        f"Training:        "
        f"{len(train_df):,} buildings / "
        f"{train_df['scene_id'].nunique():,} scenes"
    )

    print(
        f"Validation:      "
        f"{len(val_df):,} buildings / "
        f"{val_df['scene_id'].nunique():,} scenes"
    )

    # -----------------------------------------------------------------------
    # DataLoaders.
    # -----------------------------------------------------------------------

    generator = torch.Generator()
    generator.manual_seed(
        args.seed
    )

    loader_kwargs = {
        "batch_size": args.batch_size,
        "num_workers": num_workers,
        "pin_memory": True,
        "persistent_workers": num_workers > 0,
        "worker_init_fn": worker_init_fn,
    }

    if num_workers > 0:
        loader_kwargs[
            "prefetch_factor"
        ] = 1

    train_loader = DataLoader(
        PostDataset(
            train_df,
            training=True,
        ),
        shuffle=True,
        generator=generator,
        **loader_kwargs,
    )

    val_loader = DataLoader(
        PostDataset(
            val_df,
            training=False,
        ),
        shuffle=False,
        **loader_kwargs,
    )

    # -----------------------------------------------------------------------
    # Model, loss, optimizer, and mixed precision.
    # -----------------------------------------------------------------------

    print()
    print("Loading ImageNet-pretrained ResNet-18...")

    model = (
        PostResNet18()
        .to(device)
        .to(memory_format=torch.channels_last)
    )

    class_weights = compute_class_weights(
        train_df,
        device,
    )

    print(
        "Class weights:   "
        + ", ".join(
            f"{name}={weight:.4f}"
            for name, weight in zip(
                CLASS_NAMES,
                class_weights.detach().cpu().tolist(),
            )
        )
    )

    criterion = nn.CrossEntropyLoss(
        weight=class_weights
    )

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=args.learning_rate,
        weight_decay=args.weight_decay,
    )

    scaler = torch.amp.GradScaler(
        "cuda"
    )

    # -----------------------------------------------------------------------
    # Training loop.
    # -----------------------------------------------------------------------

    history = []

    best_macro_f1 = -1.0
    best_epoch = -1

    torch.cuda.reset_peak_memory_stats()

    run_start = time.perf_counter()

    print()
    print("=" * 80)
    print("TRAINING")
    print("=" * 80)

    for epoch in range(
        1,
        args.epochs + 1,
    ):
        epoch_start = (
            time.perf_counter()
        )

        train_metrics = train_one_epoch(
            model=model,
            loader=train_loader,
            optimizer=optimizer,
            scaler=scaler,
            criterion=criterion,
            device=device,
        )

        (
            val_metrics,
            _,
            _,
            _,
        ) = evaluate(
            model=model,
            loader=val_loader,
            criterion=criterion,
            device=device,
            save_predictions=False,
        )

        epoch_elapsed = (
            time.perf_counter()
            - epoch_start
        )

        history_row = {
            "epoch": epoch,

            "train_loss": train_metrics["loss"],
            "train_accuracy": train_metrics["accuracy"],
            "train_samples_per_sec": train_metrics["samples_per_sec"],
            "train_elapsed_sec": train_metrics["elapsed_sec"],

            "val_loss": val_metrics["loss"],
            "val_accuracy": val_metrics["accuracy"],
            "val_macro_f1": val_metrics["macro_f1"],

            "val_precision_no": val_metrics["precision_no"],
            "val_recall_no": val_metrics["recall_no"],
            "val_f1_no": val_metrics["f1_no"],

            "val_precision_minor": val_metrics["precision_minor"],
            "val_recall_minor": val_metrics["recall_minor"],
            "val_f1_minor": val_metrics["f1_minor"],

            "val_precision_major": val_metrics["precision_major"],
            "val_recall_major": val_metrics["recall_major"],
            "val_f1_major": val_metrics["f1_major"],

            "val_precision_destroyed": val_metrics["precision_destroyed"],
            "val_recall_destroyed": val_metrics["recall_destroyed"],
            "val_f1_destroyed": val_metrics["f1_destroyed"],

            "val_samples_per_sec": val_metrics["samples_per_sec"],
            "epoch_elapsed_sec": epoch_elapsed,
        }

        history.append(
            history_row
        )

        # Select the checkpoint by validation Macro F1.
        if (
            val_metrics["macro_f1"]
            > best_macro_f1
        ):
            best_macro_f1 = (
                val_metrics["macro_f1"]
            )

            best_epoch = epoch

            torch.save(
                {
                    "model_name": "post_resnet18",
                    "epoch": epoch,
                    "model_state_dict": model.state_dict(),
                    "class_names": CLASS_NAMES,
                    "class_weights": class_weights.detach().cpu(),
                    "val_metrics": val_metrics,
                    "config": {
                        "epochs": args.epochs,
                        "batch_size": args.batch_size,
                        "learning_rate": args.learning_rate,
                        "weight_decay": args.weight_decay,
                        "seed": args.seed,
                        "split_seed": args.split_seed,
                        "val_fraction": args.val_fraction,
                        "max_val_buildings": args.max_val_buildings,
                    },
                },
                results_dir / "best.pt",
            )

        # Save history after every epoch so useful metrics survive interruption.
        pd.DataFrame(
            history
        ).to_csv(
            results_dir / "history.csv",
            index=False,
        )

        average_epoch_time = np.mean(
            [
                row["epoch_elapsed_sec"]
                for row in history
            ]
        )

        eta = (
            args.epochs - epoch
        ) * average_epoch_time

        marker = (
            " <-- BEST"
            if epoch == best_epoch
            else ""
        )

        print()
        print(
            f"Epoch {epoch}/{args.epochs}{marker}"
        )

        print(
            "  train | "
            f"loss={train_metrics['loss']:.4f} | "
            f"acc={train_metrics['accuracy']:.4f} | "
            f"{train_metrics['samples_per_sec']:.1f} samples/s"
        )

        print(
            "  val   | "
            f"loss={val_metrics['loss']:.4f} | "
            f"acc={val_metrics['accuracy']:.4f} | "
            f"MacroF1={val_metrics['macro_f1']:.4f}"
        )

        print(
            "          "
            f"F1 no={val_metrics['f1_no']:.4f} | "
            f"minor={val_metrics['f1_minor']:.4f} | "
            f"major={val_metrics['f1_major']:.4f} | "
            f"destroyed={val_metrics['f1_destroyed']:.4f}"
        )

        print(
            "          "
            f"minor P/R="
            f"{val_metrics['precision_minor']:.4f}/"
            f"{val_metrics['recall_minor']:.4f}"
        )

        print(
            "  timing | "
            f"epoch={format_seconds(epoch_elapsed)} | "
            f"ETA={format_seconds(eta)}"
        )

    # -----------------------------------------------------------------------
    # Final evaluation using the best checkpoint.
    # -----------------------------------------------------------------------

    checkpoint = torch.load(
        results_dir / "best.pt",
        map_location=device,
        weights_only=False,
    )

    model.load_state_dict(
        checkpoint["model_state_dict"]
    )

    (
        final_metrics,
        predictions,
        y_true,
        y_pred,
    ) = evaluate(
        model=model,
        loader=val_loader,
        criterion=criterion,
        device=device,
        save_predictions=True,
    )

    predictions.to_csv(
        results_dir / "val_predictions.csv",
        index=False,
    )

    matrix = confusion_matrix(
        y_true,
        y_pred,
        labels=[0, 1, 2, 3],
    )

    pd.DataFrame(
        matrix,
        index=CLASS_NAMES,
        columns=CLASS_NAMES,
    ).to_csv(
        results_dir / "confusion_matrix.csv"
    )

    runtime = (
        time.perf_counter()
        - run_start
    )

    peak_vram_gb = (
        torch.cuda.max_memory_allocated()
        / (1024 ** 3)
    )

    best_history = history[
        best_epoch - 1
    ]

    result = {
        "model": "post_resnet18",
        "best_epoch": best_epoch,

        "train_buildings": len(train_df),
        "validation_buildings": len(val_df),
        "train_scenes": train_df["scene_id"].nunique(),
        "validation_scenes": val_df["scene_id"].nunique(),

        "train_loss_at_best": best_history["train_loss"],
        "train_accuracy_at_best": best_history["train_accuracy"],

        "val_loss": final_metrics["loss"],
        "val_accuracy": final_metrics["accuracy"],
        "macro_f1": final_metrics["macro_f1"],

        "precision_no": final_metrics["precision_no"],
        "recall_no": final_metrics["recall_no"],
        "f1_no": final_metrics["f1_no"],

        "precision_minor": final_metrics["precision_minor"],
        "recall_minor": final_metrics["recall_minor"],
        "f1_minor": final_metrics["f1_minor"],

        "precision_major": final_metrics["precision_major"],
        "recall_major": final_metrics["recall_major"],
        "f1_major": final_metrics["f1_major"],

        "precision_destroyed": final_metrics["precision_destroyed"],
        "recall_destroyed": final_metrics["recall_destroyed"],
        "f1_destroyed": final_metrics["f1_destroyed"],

        "runtime_minutes": runtime / 60.0,
        "train_samples_per_sec_at_best": best_history["train_samples_per_sec"],
        "peak_vram_gb": peak_vram_gb,

        "gpu": torch.cuda.get_device_name(0),
        "pytorch_version": torch.__version__,
        "seed": args.seed,
        "split_seed": args.split_seed,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "weight_decay": args.weight_decay,
    }

    (
        results_dir / "result.json"
    ).write_text(
        json.dumps(
            result,
            indent=2,
        ),
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Human-readable summary.
    # -----------------------------------------------------------------------

    summary_lines = [
        "xBD POST-ONLY RESNET-18 BASELINE",
        "=" * 80,
        "",
        f"GPU: {torch.cuda.get_device_name(0)}",
        f"Training buildings: {len(train_df):,}",
        f"Validation buildings: {len(val_df):,}",
        f"Training scenes: {train_df['scene_id'].nunique():,}",
        f"Validation scenes: {val_df['scene_id'].nunique():,}",
        f"Best epoch: {best_epoch}/{args.epochs}",
        "",
        "PERFORMANCE",
        "-" * 80,
        f"Train loss at best epoch:     {best_history['train_loss']:.4f}",
        f"Train accuracy at best epoch: {best_history['train_accuracy']:.4f}",
        f"Validation loss:               {final_metrics['loss']:.4f}",
        f"Validation accuracy:           {final_metrics['accuracy']:.4f}",
        f"Macro F1:                      {final_metrics['macro_f1']:.4f}",
        "",
        "PER-CLASS METRICS",
        "-" * 80,
        (
            "No damage   | "
            f"P={final_metrics['precision_no']:.4f} "
            f"R={final_metrics['recall_no']:.4f} "
            f"F1={final_metrics['f1_no']:.4f}"
        ),
        (
            "Minor       | "
            f"P={final_metrics['precision_minor']:.4f} "
            f"R={final_metrics['recall_minor']:.4f} "
            f"F1={final_metrics['f1_minor']:.4f}"
        ),
        (
            "Major       | "
            f"P={final_metrics['precision_major']:.4f} "
            f"R={final_metrics['recall_major']:.4f} "
            f"F1={final_metrics['f1_major']:.4f}"
        ),
        (
            "Destroyed   | "
            f"P={final_metrics['precision_destroyed']:.4f} "
            f"R={final_metrics['recall_destroyed']:.4f} "
            f"F1={final_metrics['f1_destroyed']:.4f}"
        ),
        "",
        "RUNTIME",
        "-" * 80,
        f"Total training/evaluation time: {format_seconds(runtime)}",
        (
            "Training throughput at best epoch: "
            f"{best_history['train_samples_per_sec']:.1f} samples/s"
        ),
        f"Peak allocated CUDA VRAM: {peak_vram_gb:.2f} GB",
    ]

    summary = "\n".join(
        summary_lines
    )

    (
        results_dir / "summary.txt"
    ).write_text(
        summary,
        encoding="utf-8",
    )

    print()
    print("=" * 80)
    print("TRAINING COMPLETE")
    print("=" * 80)
    print()
    print(summary)
    print()
    print("Output:")
    print(f"  {results_dir}")


if __name__ == "__main__":
    main()
