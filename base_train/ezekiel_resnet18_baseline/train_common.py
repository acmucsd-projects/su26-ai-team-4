"""Shared infrastructure for the xBD ResNet-18 experiments.

The experiment entry points intentionally keep their dataset, model, loss, and
batch-forwarding adapters local.  This module owns the reproducibility,
splitting, training, evaluation, and output mechanics they share.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import GroupShuffleSplit
from torch import nn
from torch.utils.data import DataLoader, Dataset


CLASS_NAMES = ["no-damage", "minor-damage", "major-damage", "destroyed"]
SHORT_CLASS_NAMES = ["no", "minor", "major", "destroyed"]
IMAGENET_MEAN = torch.tensor([0.485, 0.456, 0.406], dtype=torch.float32).view(3, 1, 1)
IMAGENET_STD = torch.tensor([0.229, 0.224, 0.225], dtype=torch.float32).view(3, 1, 1)


@dataclass(frozen=True)
class ExperimentSpec:
    """The concise, experiment-specific interface used by ``run_experiment``."""

    model_name: str
    title: str
    input_mode: str
    loss_name: str
    class_weighting: bool
    loss_display: str
    architecture: str
    pretrained_weights: str
    paired_input: bool
    dataset_class: type[Dataset]
    build_model: Callable[[], nn.Module]
    build_criterion: Callable[[pd.DataFrame, torch.device], tuple[nn.Module, torch.Tensor | None]]
    forward_batch: Callable[[nn.Module, Any, torch.device], tuple[torch.Tensor, torch.Tensor, list[str] | tuple[str, ...]]]


def add_training_arguments(
    description: str,
    default_cache_manifest: Path,
    default_results_dir: Path,
) -> argparse.Namespace:
    """Parse the common CLI while retaining one simple CLI per experiment."""
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--cache-manifest", type=Path, default=default_cache_manifest,
                        help="Cache manifest created by prepare_xbd_cache.py.")
    parser.add_argument("--results-dir", type=Path, default=default_results_dir,
                        help="Directory for checkpoints, metrics, and predictions.")
    parser.add_argument("--epochs", type=int, default=8, help="Number of training epochs.")
    parser.add_argument("--batch-size", type=int, default=128,
                        help="Training and validation batch size.")
    parser.add_argument("--image-size", type=int, default=224,
                        help="Square input size; 224 is the canonical baseline.")
    parser.add_argument("--learning-rate", type=float, default=1e-4,
                        help="AdamW learning rate.")
    parser.add_argument("--weight-decay", type=float, default=1e-4,
                        help="AdamW weight decay.")
    parser.add_argument("--seed", type=int, default=42, help="Training random seed.")
    parser.add_argument("--split-seed", type=int, default=42,
                        help="Scene-level train/validation split seed.")
    parser.add_argument("--val-fraction", type=float, default=0.20,
                        help="Fraction of scenes assigned to validation.")
    parser.add_argument("--max-val-buildings", type=int, default=15000,
                        help="Maximum number of validation buildings.")
    parser.add_argument("--num-workers", type=int, default=None,
                        help="DataLoader workers. A conservative default is chosen when omitted.")
    args = parser.parse_args()
    if args.epochs < 1:
        parser.error("--epochs must be at least 1.")
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1.")
    if args.image_size < 1:
        parser.error("--image-size must be at least 1.")
    if args.learning_rate <= 0:
        parser.error("--learning-rate must be greater than 0.")
    if args.weight_decay < 0:
        parser.error("--weight-decay must be at least 0.")
    if not 0 < args.val_fraction < 1:
        parser.error("--val-fraction must be greater than 0 and less than 1.")
    if args.max_val_buildings < 1:
        parser.error("--max-val-buildings must be at least 1.")
    if args.num_workers is not None and args.num_workers < 0:
        parser.error("--num-workers must be at least 0.")
    return args


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def worker_init_fn(worker_id: int) -> None:
    del worker_id
    worker_seed = torch.initial_seed() % (2**32)
    random.seed(worker_seed)
    np.random.seed(worker_seed)


def default_num_workers() -> int:
    cpu_count = os.cpu_count() or 1
    return min(4, cpu_count)


def format_seconds(seconds: float) -> str:
    seconds = int(max(0, round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes:02d}m {seconds:02d}s" if hours else f"{minutes}m {seconds:02d}s"


def select_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def configure_device(device: torch.device) -> str:
    """Configure CUDA-only optimizations and return a human-readable device name."""
    if device.type == "cuda":
        torch.backends.cudnn.benchmark = True
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.set_float32_matmul_precision("high")
        return torch.cuda.get_device_name(0)
    if device.type == "mps":
        return "Apple MPS"
    print("WARNING: CPU selected; ResNet-18 training may be very slow.")
    return "CPU"


def load_cache_manifest(path: Path, paired_input: bool) -> pd.DataFrame:
    path = path.expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"Cache manifest was not found:\n    {path}\n\nRun prepare_xbd_cache.py before training.")
    df = pd.read_csv(path, dtype={"cache_id": str})
    required = {"cache_id", "building_id", "scene_id", "damage_label", "target", "post_png"}
    if paired_input:
        required.add("pre_png")
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"cache_manifest.csv is missing required columns:\n    {sorted(missing)}")
    if df.empty:
        raise SystemExit(
            "cache_manifest.csv contains zero usable four-class examples.\n\n"
            "Regenerate the cache with prepare_xbd_cache.py --rebuild after checking the manifest."
        )

    cache_root = path.parent
    image_columns = ["post"] + (["pre"] if paired_input else [])
    missing_files: list[Path] = []
    for image_type in image_columns:
        path_column = f"{image_type}_path"
        df[path_column] = df[f"{image_type}_png"].map(
            lambda relative_path: str((cache_root / str(relative_path)).resolve())
        )
        missing_files.extend(Path(image_path) for image_path in df[path_column] if not Path(image_path).exists())
    if missing_files:
        mode = "PRE/POST" if paired_input else "POST"
        raise SystemExit(
            f"{mode} cache is incomplete. Missing files: {len(missing_files):,}\n"
            f"Example:\n    {missing_files[0]}\n\nRe-run prepare_xbd_cache.py to restore the cache."
        )
    return df


def make_scene_split(
    df: pd.DataFrame,
    results_dir: Path,
    split_seed: int,
    val_fraction: float,
    max_val_buildings: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create a scene-disjoint split, then cap validation buildings as before."""
    if df["scene_id"].nunique() < 2:
        raise SystemExit(
            "At least two distinct scenes are required for a scene-disjoint "
            "train/validation split."
        )
    splitter = GroupShuffleSplit(n_splits=1, test_size=val_fraction, random_state=split_seed)
    train_indices, val_indices = next(splitter.split(df, groups=df["scene_id"]))
    train_df = df.iloc[train_indices].copy().reset_index(drop=True)
    val_df = df.iloc[val_indices].copy().reset_index(drop=True)
    if len(val_df) > max_val_buildings:
        val_df = val_df.sample(n=max_val_buildings, random_state=split_seed).reset_index(drop=True)
    overlap = set(train_df["scene_id"]) & set(val_df["scene_id"])
    if overlap:
        raise RuntimeError(f"Scene leakage detected: {len(overlap)} overlapping scenes.")

    audit_columns = ["cache_id", "building_id", "scene_id", "damage_label", "target"]
    pd.concat(
        [train_df[audit_columns].assign(experiment_split="train"),
         val_df[audit_columns].assign(experiment_split="validation")],
        ignore_index=True,
    ).to_csv(results_dir / "split_manifest.csv", index=False)
    summary = []
    for name, part in (("train", train_df), ("validation", val_df)):
        counts = part["target"].value_counts().reindex([0, 1, 2, 3], fill_value=0)
        summary.append({"split": name, "buildings": len(part), "scenes": part["scene_id"].nunique(),
                        "no_damage": int(counts[0]), "minor_damage": int(counts[1]),
                        "major_damage": int(counts[2]), "destroyed": int(counts[3])})
    pd.DataFrame(summary).to_csv(results_dir / "split_summary.csv", index=False)
    return train_df, val_df


def compute_class_weights(train_df: pd.DataFrame, device: torch.device) -> torch.Tensor:
    counts = train_df["target"].value_counts().reindex([0, 1, 2, 3], fill_value=0).to_numpy(dtype=np.float64)
    weights = counts.sum() / (4.0 * np.maximum(counts, 1.0))
    return torch.tensor(weights, dtype=torch.float32, device=device)


def move_image_tensor(images: torch.Tensor, device: torch.device) -> torch.Tensor:
    kwargs: dict[str, Any] = {"non_blocking": device.type == "cuda"}
    if device.type == "cuda":
        kwargs["memory_format"] = torch.channels_last
    return images.to(device, **kwargs)


def move_targets(targets: torch.Tensor, device: torch.device) -> torch.Tensor:
    return targets.to(device, non_blocking=device.type == "cuda")


def _autocast_context(device: torch.device):
    if device.type == "cuda":
        return torch.autocast(device_type="cuda", dtype=torch.float16)
    return contextlib.nullcontext()


def calculate_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float | int]:
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=[0, 1, 2, 3], zero_division=0
    )
    metrics: dict[str, float | int] = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(np.mean(f1)),
    }
    for index, name in enumerate(SHORT_CLASS_NAMES):
        metrics[f"precision_{name}"] = float(precision[index])
        metrics[f"recall_{name}"] = float(recall[index])
        metrics[f"f1_{name}"] = float(f1[index])
        metrics[f"support_{name}"] = int(support[index])
    return metrics


def train_one_epoch(model: nn.Module, loader: DataLoader, optimizer: torch.optim.Optimizer,
                    scaler: torch.amp.GradScaler | None, criterion: nn.Module, device: torch.device,
                    forward_batch: Callable) -> dict[str, float]:
    model.train()
    seen = correct = 0
    total_loss = 0.0
    if device.type == "cuda":
        torch.cuda.synchronize()
    start = time.perf_counter()
    for batch in loader:
        optimizer.zero_grad(set_to_none=True)
        with _autocast_context(device):
            logits, targets, _ = forward_batch(model, batch, device)
            loss = criterion(logits, targets)
        if scaler is None:
            loss.backward()
            optimizer.step()
        else:
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
        batch_size = targets.size(0)
        seen += batch_size
        total_loss += float(loss.detach()) * batch_size
        correct += int((logits.argmax(dim=1) == targets).sum().item())
    if device.type == "cuda":
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - start
    return {"loss": total_loss / seen, "accuracy": correct / seen,
            "samples_per_sec": seen / elapsed, "elapsed_sec": elapsed}


@torch.inference_mode()
def evaluate(model: nn.Module, loader: DataLoader, criterion: nn.Module, device: torch.device,
             forward_batch: Callable, save_predictions: bool = False) -> tuple[dict[str, float | int], pd.DataFrame | None, np.ndarray, np.ndarray]:
    model.eval()
    seen = 0
    total_loss = 0.0
    y_true: list[int] = []
    y_pred: list[int] = []
    building_ids: list[str] = []
    probability_batches: list[np.ndarray] = []
    if device.type == "cuda":
        torch.cuda.synchronize()
    start = time.perf_counter()
    for batch in loader:
        with _autocast_context(device):
            logits, targets, ids = forward_batch(model, batch, device)
            loss = criterion(logits, targets)
        probabilities = torch.softmax(logits.float(), dim=1)
        predictions = probabilities.argmax(dim=1)
        batch_size = targets.size(0)
        seen += batch_size
        total_loss += float(loss.detach()) * batch_size
        y_true.extend(targets.cpu().tolist())
        y_pred.extend(predictions.cpu().tolist())
        if save_predictions:
            building_ids.extend(list(ids))
            probability_batches.append(probabilities.cpu().numpy())
    if device.type == "cuda":
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - start
    y_true_array = np.asarray(y_true, dtype=np.int64)
    y_pred_array = np.asarray(y_pred, dtype=np.int64)
    metrics = calculate_metrics(y_true_array, y_pred_array)
    metrics["loss"] = total_loss / seen
    metrics["samples_per_sec"] = seen / elapsed
    prediction_df = None
    if save_predictions:
        probabilities = np.concatenate(probability_batches, axis=0)
        prediction_df = pd.DataFrame({"building_id": building_ids, "target": y_true_array,
                                      "prediction": y_pred_array, "p_no_damage": probabilities[:, 0],
                                      "p_minor_damage": probabilities[:, 1], "p_major_damage": probabilities[:, 2],
                                      "p_destroyed": probabilities[:, 3]})
    return metrics, prediction_df, y_true_array, y_pred_array


def _history_row(epoch: int, train: dict[str, float], val: dict[str, float | int], epoch_elapsed: float,
                 loss_name: str) -> dict[str, float | int | str]:
    row: dict[str, float | int | str] = {
        "epoch": epoch, "train_loss": train["loss"], "train_accuracy": train["accuracy"],
        "train_samples_per_sec": train["samples_per_sec"], "train_elapsed_sec": train["elapsed_sec"],
        "val_loss": val["loss"], "val_loss_objective": loss_name, "val_accuracy": val["accuracy"],
        "val_macro_f1": val["macro_f1"], "val_samples_per_sec": val["samples_per_sec"],
        "epoch_elapsed_sec": epoch_elapsed,
    }
    for name in SHORT_CLASS_NAMES:
        for metric in ("precision", "recall", "f1"):
            row[f"val_{metric}_{name}"] = val[f"{metric}_{name}"]
    return row


def _checkpoint_payload(spec: ExperimentSpec, model: nn.Module, epoch: int, val_metrics: dict,
                        class_weights: torch.Tensor | None, args: argparse.Namespace, device: torch.device) -> dict:
    metadata = {"model": spec.model_name, "input_mode": spec.input_mode, "loss": spec.loss_name,
                "class_weighting": spec.class_weighting, "architecture": spec.architecture,
                "pretrained_weights": spec.pretrained_weights, "seed": args.seed,
                "split_seed": args.split_seed, "device": str(device)}
    config = {**metadata, "epochs": args.epochs, "batch_size": args.batch_size,
              "learning_rate": args.learning_rate, "weight_decay": args.weight_decay,
              "val_fraction": args.val_fraction, "max_val_buildings": args.max_val_buildings}
    payload = {"model_name": spec.model_name, "epoch": epoch, "model_state_dict": model.state_dict(),
               "class_names": CLASS_NAMES, "val_metrics": val_metrics, "config": config, "metadata": metadata}
    if class_weights is not None:
        payload["class_weights"] = class_weights.detach().cpu()
    return payload


def _write_final_outputs(spec: ExperimentSpec, args: argparse.Namespace, results_dir: Path, model: nn.Module,
                         val_loader: DataLoader, criterion: nn.Module, device: torch.device, forward_batch: Callable,
                         history: list[dict], best_epoch: int, train_df: pd.DataFrame, val_df: pd.DataFrame,
                         device_name: str, run_start: float) -> None:
    checkpoint = torch.load(results_dir / "best.pt", map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model_state_dict"])
    final_metrics, predictions, y_true, y_pred = evaluate(
        model, val_loader, criterion, device, forward_batch, save_predictions=True
    )
    assert predictions is not None
    predictions.to_csv(results_dir / "val_predictions.csv", index=False)
    matrix = confusion_matrix(y_true, y_pred, labels=[0, 1, 2, 3])
    pd.DataFrame(matrix, index=CLASS_NAMES, columns=CLASS_NAMES).to_csv(results_dir / "confusion_matrix.csv")
    runtime = time.perf_counter() - run_start
    peak_vram_gb = torch.cuda.max_memory_allocated() / (1024**3) if device.type == "cuda" else None
    best_history = history[best_epoch - 1]
    result = {
        "model": spec.model_name, "input_mode": spec.input_mode, "loss": spec.loss_name,
        "class_weighting": spec.class_weighting, "architecture": spec.architecture,
        "pretrained_weights": spec.pretrained_weights, "device": str(device), "device_name": device_name,
        "best_epoch": best_epoch, "train_buildings": len(train_df), "validation_buildings": len(val_df),
        "train_scenes": train_df["scene_id"].nunique(), "validation_scenes": val_df["scene_id"].nunique(),
        "train_loss_at_best": best_history["train_loss"], "train_accuracy_at_best": best_history["train_accuracy"],
        "val_loss": final_metrics["loss"], "val_loss_objective": spec.loss_name,
        "val_accuracy": final_metrics["accuracy"], "macro_f1": final_metrics["macro_f1"],
        "runtime_minutes": runtime / 60.0, "train_samples_per_sec_at_best": best_history["train_samples_per_sec"],
        "peak_vram_gb": peak_vram_gb, "gpu": device_name, "pytorch_version": torch.__version__,
        "seed": args.seed, "split_seed": args.split_seed, "epochs": args.epochs, "batch_size": args.batch_size,
        "learning_rate": args.learning_rate, "weight_decay": args.weight_decay,
    }
    for name in SHORT_CLASS_NAMES:
        for metric in ("precision", "recall", "f1"):
            result[f"{metric}_{name}"] = final_metrics[f"{metric}_{name}"]
    (results_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    summary_lines = [spec.title, "=" * 80, "", f"Device: {device_name} ({device})",
                     f"Training buildings: {len(train_df):,}", f"Validation buildings: {len(val_df):,}",
                     f"Training scenes: {train_df['scene_id'].nunique():,}",
                     f"Validation scenes: {val_df['scene_id'].nunique():,}",
                     f"Best epoch: {best_epoch}/{args.epochs}", f"Loss: {spec.loss_display}", "",
                     "PERFORMANCE", "-" * 80,
                     f"Train loss at best epoch:     {best_history['train_loss']:.4f}",
                     f"Train accuracy at best epoch: {best_history['train_accuracy']:.4f}",
                     f"Validation loss ({spec.loss_name}): {final_metrics['loss']:.4f}",
                     f"Validation accuracy:           {final_metrics['accuracy']:.4f}",
                     f"Macro F1:                      {final_metrics['macro_f1']:.4f}", "",
                     "PER-CLASS METRICS", "-" * 80]
    for display, name in zip(("No damage", "Minor", "Major", "Destroyed"), SHORT_CLASS_NAMES):
        summary_lines.append(f"{display:<11} | P={final_metrics[f'precision_{name}']:.4f} "
                             f"R={final_metrics[f'recall_{name}']:.4f} F1={final_metrics[f'f1_{name}']:.4f}")
    summary_lines.extend(["", "RUNTIME", "-" * 80, f"Total training/evaluation time: {format_seconds(runtime)}",
                          f"Training throughput at best epoch: {best_history['train_samples_per_sec']:.1f} samples/s"])
    summary_lines.append(f"Peak allocated CUDA VRAM: {peak_vram_gb:.2f} GB" if peak_vram_gb is not None else "Peak CUDA VRAM: not applicable")
    summary = "\n".join(summary_lines)
    (results_dir / "summary.txt").write_text(summary, encoding="utf-8")
    print("\n" + "=" * 80 + "\nTRAINING COMPLETE\n" + "=" * 80 + "\n\n" + summary + f"\n\nOutput:\n  {results_dir}")


def print_run_configuration(
    spec: ExperimentSpec,
    args: argparse.Namespace,
    device: torch.device,
    device_name: str,
    cache_manifest_path: Path,
    results_dir: Path,
    num_workers: int,
) -> None:
    """Print the run details before loading the cache manifest."""
    print("=" * 80 + f"\n{spec.title}\n" + "=" * 80)
    print(
        f"Device:          {device_name} ({device})\n"
        f"PyTorch:         {torch.__version__}\n"
        f"Cache manifest:  {cache_manifest_path}\n"
        f"Results:         {results_dir}\n"
        f"Epochs:          {args.epochs}\n"
        f"Batch size:      {args.batch_size}\n"
        f"Workers:         {num_workers}\n"
        f"Seed:            {args.seed}\n"
        f"Split seed:      {args.split_seed}"
    )


def print_split_summary(train_df: pd.DataFrame, val_df: pd.DataFrame) -> None:
    """Print the existing scene-disjoint split summary."""
    print(f"Training:        {len(train_df):,} buildings / {train_df['scene_id'].nunique():,} scenes\n"
          f"Validation:      {len(val_df):,} buildings / {val_df['scene_id'].nunique():,} scenes")


def build_data_loaders(
    spec: ExperimentSpec,
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    args: argparse.Namespace,
    device: torch.device,
    num_workers: int,
) -> tuple[DataLoader, DataLoader]:
    """Build the train and validation loaders with the established settings."""
    generator = torch.Generator().manual_seed(args.seed)
    loader_kwargs: dict[str, Any] = {
        "batch_size": args.batch_size,
        "num_workers": num_workers,
        "pin_memory": device.type == "cuda",
        "persistent_workers": num_workers > 0,
        "worker_init_fn": worker_init_fn,
    }
    if num_workers > 0:
        loader_kwargs["prefetch_factor"] = 1
    train_loader = DataLoader(
        spec.dataset_class(train_df, training=True, image_size=args.image_size),
        shuffle=True,
        generator=generator,
        **loader_kwargs,
    )
    val_loader = DataLoader(
        spec.dataset_class(val_df, training=False, image_size=args.image_size),
        shuffle=False,
        **loader_kwargs,
    )
    return train_loader, val_loader


def build_training_components(
    spec: ExperimentSpec,
    train_df: pd.DataFrame,
    args: argparse.Namespace,
    device: torch.device,
) -> tuple[
    nn.Module,
    nn.Module,
    torch.Tensor | None,
    torch.optim.Optimizer,
    torch.amp.GradScaler | None,
]:
    """Create the model, loss, optimizer, and CUDA scaler for one experiment."""
    print("\nLoading ImageNet-pretrained ResNet-18...")
    model = spec.build_model().to(device)
    if device.type == "cuda":
        model = model.to(memory_format=torch.channels_last)
    criterion, class_weights = spec.build_criterion(train_df, device)
    if class_weights is None:
        print(f"Loss:            {spec.loss_display}")
    else:
        print("Class weights:   " + ", ".join(f"{name}={weight:.4f}" for name, weight in zip(CLASS_NAMES, class_weights.detach().cpu().tolist())))
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    scaler = torch.amp.GradScaler("cuda") if device.type == "cuda" else None
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
    return model, criterion, class_weights, optimizer, scaler


def run_training_loop(
    spec: ExperimentSpec,
    args: argparse.Namespace,
    results_dir: Path,
    model: nn.Module,
    train_loader: DataLoader,
    val_loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    scaler: torch.amp.GradScaler | None,
    criterion: nn.Module,
    class_weights: torch.Tensor | None,
    device: torch.device,
) -> tuple[list[dict], int, float]:
    """Run epochs, retain the best Macro F1 checkpoint, and write history."""
    history: list[dict] = []
    best_macro_f1, best_epoch = -1.0, -1
    run_start = time.perf_counter()
    print("\n" + "=" * 80 + "\nTRAINING\n" + "=" * 80)
    for epoch in range(1, args.epochs + 1):
        epoch_start = time.perf_counter()
        train_metrics = train_one_epoch(model, train_loader, optimizer, scaler, criterion, device, spec.forward_batch)
        val_metrics, _, _, _ = evaluate(model, val_loader, criterion, device, spec.forward_batch)
        row = _history_row(epoch, train_metrics, val_metrics, time.perf_counter() - epoch_start, spec.loss_name)
        history.append(row)
        if val_metrics["macro_f1"] > best_macro_f1:
            best_macro_f1, best_epoch = float(val_metrics["macro_f1"]), epoch
            torch.save(_checkpoint_payload(spec, model, epoch, val_metrics, class_weights, args, device), results_dir / "best.pt")
        pd.DataFrame(history).to_csv(results_dir / "history.csv", index=False)
        eta = (args.epochs - epoch) * float(np.mean([entry["epoch_elapsed_sec"] for entry in history]))
        marker = " <-- BEST" if epoch == best_epoch else ""
        print(f"\nEpoch {epoch}/{args.epochs}{marker}\n  train | loss={train_metrics['loss']:.4f} | acc={train_metrics['accuracy']:.4f} | "
              f"{train_metrics['samples_per_sec']:.1f} samples/s\n  val   | loss ({spec.loss_name})={val_metrics['loss']:.4f} | "
              f"acc={val_metrics['accuracy']:.4f} | MacroF1={val_metrics['macro_f1']:.4f}\n  timing | "
              f"epoch={format_seconds(row['epoch_elapsed_sec'])} | ETA={format_seconds(eta)}")
    return history, best_epoch, run_start


def run_experiment(args: argparse.Namespace, spec: ExperimentSpec) -> None:
    """Run one seed/split experiment and write the standard artifacts."""
    seed_everything(args.seed)
    device = select_device()
    device_name = configure_device(device)
    cache_manifest_path = args.cache_manifest.expanduser().resolve()
    results_dir = args.results_dir.expanduser().resolve()
    results_dir.mkdir(parents=True, exist_ok=True)
    num_workers = args.num_workers if args.num_workers is not None else default_num_workers()
    print_run_configuration(
        spec,
        args,
        device,
        device_name,
        cache_manifest_path,
        results_dir,
        num_workers,
    )

    df = load_cache_manifest(cache_manifest_path, spec.paired_input)
    train_df, val_df = make_scene_split(
        df,
        results_dir,
        args.split_seed,
        args.val_fraction,
        args.max_val_buildings,
    )
    print_split_summary(train_df, val_df)
    train_loader, val_loader = build_data_loaders(
        spec,
        train_df,
        val_df,
        args,
        device,
        num_workers,
    )
    model, criterion, class_weights, optimizer, scaler = build_training_components(
        spec,
        train_df,
        args,
        device,
    )
    history, best_epoch, run_start = run_training_loop(
        spec,
        args,
        results_dir,
        model,
        train_loader,
        val_loader,
        optimizer,
        scaler,
        criterion,
        class_weights,
        device,
    )
    _write_final_outputs(spec, args, results_dir, model, val_loader, criterion, device, spec.forward_batch,
                         history, best_epoch, train_df, val_df, device_name, run_start)
