"""
train.py
--------
Train the Siamese damage-classification CNN on the xBD manifest.

Example:
    python train.py \
        --manifest /path/to/manifest_train.csv \
        --data-root /path/to/xbd_root \
        --backbone simple --epochs 20 --batch-size 64

`--data-root` must be the directory such that
`data_root / row.pre_crop_path` resolves to an actual PNG on disk.
"""

import argparse
import json
import time
from pathlib import Path

import torch
from sklearn.metrics import f1_score, classification_report
from torch.utils.data import DataLoader

from dataset import XBDDamageDataset, DAMAGE_CLASSES
from model import SiameseDamageNet
from transforms import build_transforms
from utils import (
    load_manifest,
    group_train_val_split,
    compute_class_weights,
    print_class_distribution,
)


def parse_args():
    p = argparse.ArgumentParser(description="Train xBD damage classification CNN")
    p.add_argument("--manifest", required=True, help="Path to manifest CSV")
    p.add_argument("--data-root", required=True, help="Root dir for crop_path columns")
    p.add_argument("--output-dir", default="checkpoints")
    p.add_argument("--backbone", default="simple", choices=["simple", "resnet18"])
    p.add_argument("--pretrained", action="store_true", help="Use ImageNet weights (resnet18 only, needs internet)")
    p.add_argument("--image-size", type=int, default=128)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--weight-decay", type=float, default=1e-4)
    p.add_argument("--val-size", type=float, default=0.15)
    p.add_argument("--num-workers", type=int, default=4)
    p.add_argument("--patience", type=int, default=5, help="Early stopping patience (epochs w/o val F1 improvement)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--include-unclassified", action="store_true")
    p.add_argument("--limit-rows", type=int, default=None, help="Debug: subsample manifest rows")
    return p.parse_args()


def run_epoch(model, loader, criterion, optimizer, device, train=True):
    model.train(mode=train)
    total_loss, all_preds, all_labels = 0.0, [], []

    torch.set_grad_enabled(train)
    for pre, post, labels in loader:
        pre, post, labels = pre.to(device), post.to(device), labels.to(device)

        if train:
            optimizer.zero_grad()

        logits = model(pre, post)
        loss = criterion(logits, labels)

        if train:
            loss.backward()
            optimizer.step()

        total_loss += loss.item() * labels.size(0)
        all_preds.append(logits.argmax(1).detach().cpu())
        all_labels.append(labels.detach().cpu())
    torch.set_grad_enabled(True)

    all_preds = torch.cat(all_preds).numpy()
    all_labels = torch.cat(all_labels).numpy()
    avg_loss = total_loss / len(all_labels)
    macro_f1 = f1_score(all_labels, all_preds, average="macro", zero_division=0)
    return avg_loss, macro_f1, all_preds, all_labels


def main():
    args = parse_args()
    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- data ----
    df = load_manifest(args.manifest, include_unclassified=args.include_unclassified)
    if args.limit_rows:
        df = df.sample(n=min(args.limit_rows, len(df)), random_state=args.seed).reset_index(drop=True)

    train_df, val_df = group_train_val_split(df, val_size=args.val_size, seed=args.seed)
    print_class_distribution(train_df, "Train")
    print_class_distribution(val_df, "Val")

    tfms = build_transforms(args.image_size)
    train_ds = XBDDamageDataset(train_df, args.data_root, transform=tfms["train"])
    val_ds = XBDDamageDataset(val_df, args.data_root, transform=tfms["val"])

    train_loader = DataLoader(
        train_ds, batch_size=args.batch_size, shuffle=True,
        num_workers=args.num_workers, pin_memory=True, drop_last=True,
    )
    val_loader = DataLoader(
        val_ds, batch_size=args.batch_size, shuffle=False,
        num_workers=args.num_workers, pin_memory=True,
    )

    num_classes = len(DAMAGE_CLASSES) + (1 if args.include_unclassified else 0)
    class_weights = compute_class_weights(train_ds.labels, num_classes=num_classes).to(device)
    print(f"Class weights: {dict(zip(DAMAGE_CLASSES, class_weights.tolist()))}")

    # ---- model ----
    model = SiameseDamageNet(
        num_classes=num_classes, backbone=args.backbone, pretrained=args.pretrained
    ).to(device)
    criterion = torch.nn.CrossEntropyLoss(weight=class_weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="max", factor=0.5, patience=2)

    best_f1, epochs_no_improve = -1.0, 0
    history = []

    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        train_loss, train_f1, _, _ = run_epoch(model, train_loader, criterion, optimizer, device, train=True)
        val_loss, val_f1, val_preds, val_labels = run_epoch(model, val_loader, criterion, optimizer, device, train=False)
        scheduler.step(val_f1)

        dt = time.time() - t0
        print(
            f"Epoch {epoch:3d}/{args.epochs} | "
            f"train loss {train_loss:.4f} f1 {train_f1:.4f} | "
            f"val loss {val_loss:.4f} f1 {val_f1:.4f} | {dt:.1f}s"
        )
        history.append(dict(epoch=epoch, train_loss=train_loss, train_f1=train_f1,
                             val_loss=val_loss, val_f1=val_f1))

        if val_f1 > best_f1:
            best_f1 = val_f1
            epochs_no_improve = 0
            torch.save(
                {"model_state": model.state_dict(), "args": vars(args), "val_f1": val_f1, "epoch": epoch},
                out_dir / "best_model.pt",
            )
            report = classification_report(
                val_labels, val_preds, target_names=DAMAGE_CLASSES[:num_classes],
                zero_division=0,
            )
            (out_dir / "best_classification_report.txt").write_text(report)
            print(f"  -> new best (macro F1={best_f1:.4f}), checkpoint saved")
        else:
            epochs_no_improve += 1
            if epochs_no_improve >= args.patience:
                print(f"Early stopping: no val F1 improvement in {args.patience} epochs")
                break

    (out_dir / "history.json").write_text(json.dumps(history, indent=2))
    print(f"\nBest val macro F1: {best_f1:.4f}")
    print(f"Checkpoint: {out_dir / 'best_model.pt'}")


if __name__ == "__main__":
    main()
