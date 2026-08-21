"""
evaluate.py
-----------
Run a trained checkpoint over a held-out manifest split and report metrics
(confusion matrix image + classification report), including the xBD-style
damage F1 (macro F1 over the 4 damage classes, and a "harmonic" localization
+ damage combo score if you extend this to include localization).

Example:
    python evaluate.py --checkpoint checkpoints/best_model.pt \
        --manifest manifest_train.csv --data-root /path/to/xbd_root
"""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
from sklearn.metrics import confusion_matrix, classification_report, f1_score
from torch.utils.data import DataLoader

from dataset import XBDDamageDataset, DAMAGE_CLASSES
from model import SiameseDamageNet
from transforms import build_transforms
from utils import load_manifest, group_train_val_split


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--data-root", required=True)
    p.add_argument("--output-dir", default="outputs")
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--num-workers", type=int, default=4)
    p.add_argument("--use-val-split", action="store_true",
                    help="Re-derive the same val split used in training (same seed) instead of using the full manifest")
    p.add_argument("--val-size", type=float, default=0.15)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def plot_confusion_matrix(cm, class_names, out_path):
    cm_norm = cm.astype(np.float64) / cm.sum(axis=1, keepdims=True).clip(min=1)
    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(cm_norm, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(class_names)))
    ax.set_yticks(range(len(class_names)))
    ax.set_xticklabels(class_names, rotation=45, ha="right")
    ax.set_yticklabels(class_names)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title("Damage Classification Confusion Matrix (row-normalized)")
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, f"{cm[i, j]}\n({cm_norm[i, j]*100:.0f}%)",
                     ha="center", va="center",
                     color="white" if cm_norm[i, j] > 0.5 else "black", fontsize=8)
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main():
    args = parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ckpt = torch.load(args.checkpoint, map_location=device)
    train_args = ckpt["args"]
    num_classes = len(DAMAGE_CLASSES) + (1 if train_args.get("include_unclassified") else 0)

    model = SiameseDamageNet(
        num_classes=num_classes,
        backbone=train_args.get("backbone", "simple"),
    ).to(device)
    model.load_state_dict(ckpt["model_state"])
    model.eval()

    df = load_manifest(args.manifest, include_unclassified=train_args.get("include_unclassified", False))
    if args.use_val_split:
        _, df = group_train_val_split(df, val_size=args.val_size, seed=args.seed)

    tfms = build_transforms(train_args.get("image_size", 128))
    ds = XBDDamageDataset(df, args.data_root, transform=tfms["val"])
    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers)

    all_preds, all_labels = [], []
    with torch.no_grad():
        for pre, post, labels in loader:
            pre, post = pre.to(device), post.to(device)
            logits = model(pre, post)
            all_preds.append(logits.argmax(1).cpu().numpy())
            all_labels.append(labels.numpy())
    all_preds = np.concatenate(all_preds)
    all_labels = np.concatenate(all_labels)

    class_names = DAMAGE_CLASSES[:num_classes]
    report = classification_report(all_labels, all_preds, target_names=class_names, zero_division=0)
    macro_f1 = f1_score(all_labels, all_preds, average="macro", zero_division=0)
    print(report)
    print(f"Macro F1: {macro_f1:.4f}")

    (out_dir / "classification_report.txt").write_text(report + f"\nMacro F1: {macro_f1:.4f}\n")

    cm = confusion_matrix(all_labels, all_preds, labels=list(range(num_classes)))
    plot_confusion_matrix(cm, class_names, out_dir / "confusion_matrix.png")
    print(f"Saved report + confusion matrix to {out_dir}/")


if __name__ == "__main__":
    main()
