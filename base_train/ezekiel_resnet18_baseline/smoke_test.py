#!/usr/bin/env python3
"""Run a small end-to-end smoke test for the three ResNet-18 experiments."""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

from inference import EXPECTED_CLASS_NAMES, load_model, predict


BASELINE_DIR = Path(__file__).resolve().parent
CACHE_MANIFEST = BASELINE_DIR / "cache" / "cache_manifest.csv"
CLASS_IDS = (0, 1, 2, 3)
SAMPLES_PER_CLASS = 64
SMOKE_SEED = 42
MAX_SAMPLE_ATTEMPTS = 100
EXPECTED_ARTIFACTS = (
    "best.pt",
    "history.csv",
    "result.json",
    "summary.txt",
    "confusion_matrix.csv",
    "val_predictions.csv",
    "split_manifest.csv",
    "split_summary.csv",
)
EXPERIMENTS = {
    "post": "train_post_resnet18.py",
    "prepost": "train_prepost_resnet18.py",
    "prepost_plaince": "train_prepost_resnet18_plaince.py",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run small end-to-end smoke tests for ResNet-18 experiments."
    )
    parser.add_argument(
        "--experiment",
        choices=("all", *EXPERIMENTS),
        default="all",
        help="Experiment to run; defaults to all three.",
    )
    return parser.parse_args()


def load_cache_manifest(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise RuntimeError(
            f"Cache manifest was not found:\n    {path}\n\n"
            "Run prepare_xbd_cache.py before running the smoke test."
        )
    manifest = pd.read_csv(path, dtype={"cache_id": str})
    required = {
        "cache_id",
        "building_id",
        "scene_id",
        "damage_label",
        "target",
        "pre_png",
        "post_png",
    }
    missing = required - set(manifest.columns)
    if missing:
        raise RuntimeError(f"Cache manifest is missing required columns: {sorted(missing)}")
    manifest["target"] = pd.to_numeric(manifest["target"], errors="raise").astype(int)
    return manifest


def resolve_cached_image_paths(manifest: pd.DataFrame, cache_root: Path) -> pd.DataFrame:
    """Use absolute paths because the temporary manifest has a different parent."""
    subset = manifest.copy()
    for column in ("pre_png", "post_png"):
        resolved_paths = [(cache_root / str(value)).resolve() for value in subset[column]]
        missing = [path for path in resolved_paths if not path.exists()]
        if missing:
            raise RuntimeError(
                f"Cache image referenced by {column} was not found:\n    {missing[0]}"
            )
        subset[column] = [str(path) for path in resolved_paths]
    return subset


def has_all_classes(frame: pd.DataFrame) -> bool:
    return set(frame["target"].unique()) == set(CLASS_IDS)


def build_smoke_subset(manifest: pd.DataFrame) -> pd.DataFrame:
    """Deterministically sample a small class-balanced subset suitable for splitting."""
    usable = manifest[manifest["target"].isin(CLASS_IDS)].copy()
    for class_id in CLASS_IDS:
        available = int((usable["target"] == class_id).sum())
        if available < SAMPLES_PER_CLASS:
            raise RuntimeError(
                f"Cache has {available} examples for target {class_id}; smoke testing needs "
                f"at least {SAMPLES_PER_CLASS} examples per class."
            )

    fallback: pd.DataFrame | None = None
    for attempt in range(MAX_SAMPLE_ATTEMPTS):
        samples = [
            usable[usable["target"] == class_id].sample(
                n=SAMPLES_PER_CLASS,
                random_state=SMOKE_SEED + attempt * len(CLASS_IDS) + class_id,
            )
            for class_id in CLASS_IDS
        ]
        candidate = pd.concat(samples, ignore_index=True).sample(
            frac=1,
            random_state=SMOKE_SEED + attempt,
        ).reset_index(drop=True)
        if candidate["scene_id"].nunique() < 2:
            continue

        splitter = GroupShuffleSplit(n_splits=1, test_size=0.20, random_state=SMOKE_SEED)
        train_indices, val_indices = next(splitter.split(candidate, groups=candidate["scene_id"]))
        train_subset = candidate.iloc[train_indices]
        val_subset = candidate.iloc[val_indices]
        if not has_all_classes(train_subset):
            continue
        if has_all_classes(val_subset):
            return candidate
        fallback = candidate

    if fallback is not None:
        return fallback
    raise RuntimeError(
        "Could not construct a deterministic smoke subset with all four classes in "
        "the scene-disjoint training split."
    )


def run_experiment(name: str, manifest_path: Path, results_dir: Path) -> tuple[bool, list[str]]:
    command = [
        sys.executable,
        str(BASELINE_DIR / EXPERIMENTS[name]),
        "--epochs",
        "1",
        "--batch-size",
        "32",
        "--num-workers",
        "0",
        "--cache-manifest",
        str(manifest_path),
        "--results-dir",
        str(results_dir),
    ]
    print(f"\n{'=' * 80}\nSMOKE TEST: {name}\n{'=' * 80}")
    try:
        completed = subprocess.run(command, cwd=BASELINE_DIR, check=False)
    except OSError as exc:
        return False, [f"could not launch training: {exc}"]

    missing = [artifact for artifact in EXPECTED_ARTIFACTS if not (results_dir / artifact).is_file()]
    problems = []
    if completed.returncode != 0:
        problems.append(f"training exited with code {completed.returncode}")
    if missing:
        problems.append(f"missing artifacts: {', '.join(missing)}")
    return not problems, problems


def validate_plaince_inference(results_dir: Path, sample: pd.Series) -> list[str]:
    """Exercise the public inference API with a pair from the smoke-test subset."""
    try:
        loaded_model = load_model(results_dir / "best.pt")
        prediction = predict(loaded_model, sample["pre_png"], sample["post_png"])
    except (FileNotFoundError, KeyError, OSError, RuntimeError, ValueError) as exc:
        return [f"inference validation failed: {exc}"]

    problems = []
    expected_class_names = list(EXPECTED_CLASS_NAMES)
    if loaded_model.class_names != expected_class_names:
        problems.append(f"unexpected checkpoint class names: {loaded_model.class_names!r}")
    if prediction.get("predicted_class") not in expected_class_names:
        problems.append(f"invalid predicted class: {prediction.get('predicted_class')!r}")

    probabilities = prediction.get("probabilities")
    if not isinstance(probabilities, dict) or list(probabilities) != expected_class_names:
        problems.append("inference did not return four probabilities in the expected class order")
    elif not math.isclose(sum(probabilities.values()), 1.0, rel_tol=1e-5, abs_tol=1e-5):
        problems.append("inference probabilities do not sum to 1")
    return problems


def main() -> int:
    args = parse_args()
    selected = tuple(EXPERIMENTS) if args.experiment == "all" else (args.experiment,)
    try:
        subset = build_smoke_subset(load_cache_manifest(CACHE_MANIFEST))
        subset = resolve_cached_image_paths(subset, CACHE_MANIFEST.parent)
    except RuntimeError as exc:
        print(f"SMOKE TEST SETUP FAILED: {exc}", file=sys.stderr)
        return 1

    print(
        f"Smoke subset: {len(subset):,} examples / {subset['scene_id'].nunique():,} scenes "
        f"/ {SAMPLES_PER_CLASS} per class"
    )
    outcomes: dict[str, tuple[bool, list[str]]] = {}
    with tempfile.TemporaryDirectory(prefix="resnet18_smoke_") as temporary_directory:
        temporary_root = Path(temporary_directory)
        manifest_path = temporary_root / "cache_manifest.csv"
        subset.to_csv(manifest_path, index=False)
        for name in selected:
            results_dir = temporary_root / name
            passed, problems = run_experiment(name, manifest_path, results_dir)
            if passed and name == "prepost_plaince":
                problems.extend(validate_plaince_inference(results_dir, subset.iloc[0]))
                passed = not problems
            outcomes[name] = passed, problems

    print(f"\n{'=' * 80}\nSMOKE TEST SUMMARY\n{'=' * 80}")
    for name in selected:
        passed, problems = outcomes[name]
        detail = "" if passed else f" — {'; '.join(problems)}"
        print(f"{'PASS' if passed else 'FAIL'} {name}{detail}")
    overall_passed = all(passed for passed, _ in outcomes.values())
    print(f"{'PASS' if overall_passed else 'FAIL'} overall")
    return 0 if overall_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
