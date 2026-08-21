"""
utils.py
--------
Manifest loading, leakage-safe train/val splitting, and class-imbalance
weighting helpers.
"""

import numpy as np
import pandas as pd
import torch
from sklearn.model_selection import GroupShuffleSplit

from dataset import CLASS_TO_IDX, DAMAGE_CLASSES


def load_manifest(csv_path, include_unclassified=False):
    """Read the manifest CSV and drop rows with unusable labels.

    `un-classified` is dropped by default: it's a small (<2%), ambiguous
    bucket in xBD that doesn't correspond to a real damage level and hurts
    a 4-way classifier if included as noise.
    """
    df = pd.read_csv(csv_path)
    df = df[df["damage_label"].notna()]
    if not include_unclassified:
        df = df[df["damage_label"] != "un-classified"].copy()
    else:
        df = df[df["damage_label"].isin(list(CLASS_TO_IDX) + ["un-classified"])].copy()
    return df.reset_index(drop=True)


def group_train_val_split(df, val_size=0.15, seed=42, group_col="scene_id"):
    """Split by `scene_id` (not by row) so crops from the same disaster
    scene never appear in both train and val - this prevents the model
    from memorizing scene-specific background/context as a shortcut.
    """
    splitter = GroupShuffleSplit(n_splits=1, test_size=val_size, random_state=seed)
    train_idx, val_idx = next(splitter.split(df, groups=df[group_col]))
    train_df = df.iloc[train_idx].reset_index(drop=True)
    val_df = df.iloc[val_idx].reset_index(drop=True)
    return train_df, val_df


def compute_class_weights(labels, num_classes=None):
    """Inverse-frequency class weights for CrossEntropyLoss, to counter
    the heavy 'no-damage' majority class in xBD.
    """
    num_classes = num_classes or len(DAMAGE_CLASSES)
    counts = np.bincount(labels, minlength=num_classes).astype(np.float64)
    counts = np.clip(counts, 1, None)  # avoid div-by-zero for absent classes
    weights = counts.sum() / (num_classes * counts)
    return torch.tensor(weights, dtype=torch.float32)


def print_class_distribution(df, name=""):
    counts = df["damage_label"].value_counts().reindex(DAMAGE_CLASSES, fill_value=0)
    total = counts.sum()
    print(f"\n{name} class distribution (n={total}):")
    for cls, n in counts.items():
        pct = 100 * n / total if total else 0
        print(f"  {cls:<15} {n:>7}  ({pct:5.1f}%)")
