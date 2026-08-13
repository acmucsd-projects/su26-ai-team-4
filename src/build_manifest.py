#!/usr/bin/env python3
"""
build_manifest.py
===============================

Reproducible xBD building-crop + manifest generator.

INPUT
-----
A raw xBD challenge training folder with this structure:

    data/
    └── train/
        ├── images/
        ├── labels/
        ├── targets/
        └── metadata_stats/

The script only requires:
    train/images/
    train/labels/

OUTPUT
------
Inside the same data/ folder it creates:

    data/
    ├── processed/
    │   └── tier1/
    │       ├── pre/
    │       └── post/
    │
    └── manifest_train.csv

The manifest build schema matches the previous manifest:

    building_id
    scene_id
    split
    disaster_type
    damage_label
    pre_crop_path
    post_crop_path
    original_bbox
    original_crop_width
    original_crop_height

POST CROP RULE
--------------
    left   = int(min_x) - 10
    top    = int(min_y) - 10
    right  = int(max_x) + 10
    bottom = int(max_y) + 10

Then clip the box to the image boundaries.

PRE CROP RULE
-------------
The PRE crop uses the same crop coordinates as POST.

That gives us:
    - POST behavior compatible with the established preprocessing
    - a matching PRE image for future paired PRE+POST experiments

IMPORTANT
---------
This script does NOT resize crops to 224x224.

It reproduces the variable-size building crops first.
For example, a later cache/preprocessing script can resize these once to 224x224 for fast
ResNet training.

NORMAL USE
----------
If this script is somewhere inside a repository containing:

    repo/src/

then simply run:

    python build_manifest.py

The script searches upward for data/train automatically.

Or explicitly specify the data directory:

    python build_xbd_manifest_and_crops.py --data-dir "C:\\path\\to\\repo\\data"

Use --overwrite if you intentionally want to regenerate existing crop PNGs.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import pandas as pd
from PIL import Image


# ---------------------------------------------------------------------------
# DAMAGE LABELS
# ---------------------------------------------------------------------------

VALID_DAMAGE_LABELS = {
    "no-damage",
    "minor-damage",
    "major-damage",
    "destroyed",
    "un-classified",
}


# ---------------------------------------------------------------------------
# ARGUMENTS
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Create schema-compatible xBD POST crops, matching PRE crops, "
            "and manifest_train.csv."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help=(
            "Path to the repo's data/ folder. "
            "If omitted, the script searches upward for data/train."
        ),
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite PRE/POST crop PNGs that already exist.",
    )

    parser.add_argument(
        "--split-name",
        type=str,
        default="tier1",
        help="Value written to the manifest's split column.",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# GENERAL HELPERS
# ---------------------------------------------------------------------------

def format_seconds(seconds: float) -> str:
    seconds = int(max(0, round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"

    if minutes:
        return f"{minutes}m {seconds:02d}s"

    return f"{seconds}s"


def find_data_dir(script_path: Path) -> Path:
    """
    Search upward from this script for:

        data/train/

    This keeps the normal repo command path-free.
    """
    for parent in [script_path.parent, *script_path.parents]:
        candidate = parent / "data"

        if (candidate / "train").exists():
            return candidate.resolve()

    raise SystemExit(
        "Could not automatically find data/train.\n\n"
        "Either place this script somewhere inside the repository or run:\n"
        '    python build_xbd_manifest_and_crops.py '
        '--data-dir "C:\\path\\to\\repo\\data"'
    )


def scene_id_from_filename(path: Path) -> str:
    """
    Convert:

        hurricane-harvey_00000348_post_disaster.json

    into:

        hurricane-harvey_00000348
    """
    suffix = "_post_disaster"

    name = path.stem

    if name.endswith(suffix):
        return name[:-len(suffix)]

    return name


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# xBD LABEL PARSING
# ---------------------------------------------------------------------------

def get_xy_features(label_json: dict) -> list[dict]:
    """
    Return xBD pixel-coordinate features.

    Common xBD JSON structure:

        {
            "features": {
                "xy": [...]
            }
        }

    Features may also be provided directly as a list.
    """
    features = label_json.get("features", [])

    if isinstance(features, dict):
        features = features.get("xy", [])

    if not isinstance(features, list):
        return []

    return features


def parse_wkt_points(wkt: str) -> list[tuple[float, float]]:
    """
    Extract x/y coordinate pairs from a WKT polygon.

    Only the polygon bounding box is required, so a lightweight numeric parser
    is sufficient and avoids adding Shapely as a dependency.
    """
    numbers = re.findall(
        r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?",
        str(wkt),
    )

    values = [float(value) for value in numbers]

    if len(values) < 6:
        return []

    return [
        (values[index], values[index + 1])
        for index in range(0, len(values) - 1, 2)
    ]


def damage_label_from_feature(feature: dict) -> str:
    """
    Read the damage class from the POST-disaster feature.

    Un-classified records are retained in the generated manifest.
    Downstream workflows can include or exclude these records as needed.
    """
    properties = feature.get("properties", {}) or {}

    label = (
        properties.get("subtype")
        or properties.get("damage")
        or properties.get("damage_label")
        or "un-classified"
    )

    label = str(label).strip()

    if label not in VALID_DAMAGE_LABELS:
        label = "un-classified"

    return label


# ---------------------------------------------------------------------------
# BUILDING CROP RULE
# ---------------------------------------------------------------------------

def build_crop_box(
    points: list[tuple[float, float]],
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int]:
    """
    Apply the established building crop rule.

    CROP RULE:

        left   = int(min_x) - 10
        top    = int(min_y) - 10
        right  = int(max_x) + 10
        bottom = int(max_y) + 10

    followed by image-boundary clipping.
    """
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]

    left = int(min(xs)) - 10
    top = int(min(ys)) - 10
    right = int(max(xs)) + 10
    bottom = int(max(ys)) + 10

    # Same boundary clipping behavior confirmed by diagnostic.
    left = max(0, min(image_width, left))
    top = max(0, min(image_height, top))
    right = max(0, min(image_width, right))
    bottom = max(0, min(image_height, bottom))

    # Very defensive guard against malformed geometry.
    if right <= left:
        right = min(image_width, left + 1)

    if bottom <= top:
        bottom = min(image_height, top + 1)

    return left, top, right, bottom


# ---------------------------------------------------------------------------
# IMAGE LOOKUP
# ---------------------------------------------------------------------------

def find_scene_image(
    images_dir: Path,
    scene_id: str,
    phase: str,
) -> Path | None:
    """
    Find PRE or POST image for one scene.

    Standard xBD naming:
        <scene_id>_pre_disaster.png
        <scene_id>_post_disaster.png
    """
    for extension in [
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
    ]:
        candidate = (
            images_dir
            / f"{scene_id}_{phase}_disaster{extension}"
        )

        if candidate.exists():
            return candidate

    return None


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    script_path = Path(__file__).resolve()

    data_dir = (
        args.data_dir.expanduser().resolve()
        if args.data_dir is not None
        else find_data_dir(script_path)
    )

    train_dir = data_dir / "train"
    images_dir = train_dir / "images"
    labels_dir = train_dir / "labels"

    if not images_dir.exists():
        raise SystemExit(
            f"Missing raw image folder:\n{images_dir}"
        )

    if not labels_dir.exists():
        raise SystemExit(
            f"Missing raw label folder:\n{labels_dir}"
        )

    # Keep schema-compatible naming.
    processed_dir = (
        data_dir
        / "processed"
        / args.split_name
    )

    pre_dir = processed_dir / "pre"
    post_dir = processed_dir / "post"

    pre_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    post_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    manifest_path = (
        data_dir
        / "manifest_train.csv"
    )

    # POST labels define the building ordering and damage labels.
    post_label_files = sorted(
        labels_dir.glob(
            "*_post_disaster.json"
        )
    )

    if not post_label_files:
        raise SystemExit(
            "No *_post_disaster.json files were found in:\n"
            f"{labels_dir}"
        )

    print("=" * 80)
    print("xBD MANIFEST + PRE/POST BUILDING CROP GENERATOR")
    print("=" * 80)
    print()
    print(f"Data folder:      {data_dir}")
    print(f"Raw images:       {images_dir}")
    print(f"Raw labels:       {labels_dir}")
    print(f"POST label files: {len(post_label_files):,}")
    print()
    print("Creating:")
    print(f"  {pre_dir}")
    print(f"  {post_dir}")
    print(f"  {manifest_path}")
    print()
    print(
        "POST crop rule: int(polygon bounds) +/- 10 px, clipped to image edges"
    )
    print(
        "PRE crop rule:  same exact coordinates as corresponding POST crop"
    )
    print()

    start_time = time.perf_counter()

    manifest_rows = []

    processed_scenes = 0
    skipped_scenes = 0
    skipped_features = 0

    for scene_number, post_label_path in enumerate(
        post_label_files,
        start=1,
    ):
        scene_id = scene_id_from_filename(
            post_label_path
        )

        pre_image_path = find_scene_image(
            images_dir,
            scene_id,
            "pre",
        )

        post_image_path = find_scene_image(
            images_dir,
            scene_id,
            "post",
        )

        if pre_image_path is None:
            print(
                f"WARNING: missing PRE image for {scene_id}; skipping scene."
            )
            skipped_scenes += 1
            continue

        if post_image_path is None:
            print(
                f"WARNING: missing POST image for {scene_id}; skipping scene."
            )
            skipped_scenes += 1
            continue

        post_label_json = load_json(
            post_label_path
        )

        features = get_xy_features(
            post_label_json
        )

        if not features:
            skipped_scenes += 1
            continue

        # Load each full scene only once.
        with Image.open(pre_image_path) as image:
            pre_image = image.convert("RGB").copy()

        with Image.open(post_image_path) as image:
            post_image = image.convert("RGB").copy()

        # POST coordinates define the crop box. PRE and POST images are
        # expected to share the same spatial dimensions.
        post_width = post_image.width
        post_height = post_image.height

        # If PRE dimensions differ unexpectedly, the same bbox is clipped
        # separately only when applying the PRE crop.
        pre_width = pre_image.width
        pre_height = pre_image.height

        valid_building_index = 0

        for feature in features:
            if not isinstance(feature, dict):
                skipped_features += 1
                continue

            wkt = feature.get("wkt", "")

            points = parse_wkt_points(
                wkt
            )

            if not points:
                skipped_features += 1
                continue

            # Building numbering follows valid POST feature order.
            building_id = (
                f"{scene_id}_b{valid_building_index:04d}"
            )

            valid_building_index += 1

            damage_label = damage_label_from_feature(
                feature
            )

            # Apply the standard building crop rule.
            post_box = build_crop_box(
                points=points,
                image_width=post_width,
                image_height=post_height,
            )

            left, top, right, bottom = post_box

            crop_width = right - left
            crop_height = bottom - top

            post_output = (
                post_dir
                / f"{building_id}.png"
            )

            pre_output = (
                pre_dir
                / f"{building_id}.png"
            )

            # Build and validate both crop boxes before writing either image.
            # This guarantees that every saved POST crop has a valid matching PRE crop.
            pre_box = (
                max(0, min(pre_width, left)),
                max(0, min(pre_height, top)),
                max(0, min(pre_width, right)),
                max(0, min(pre_height, bottom)),
            )

            pl, pt, pr, pb = pre_box

            post_valid = right > left and bottom > top
            pre_valid = pr > pl and pb > pt

            if not post_valid or not pre_valid:
                skipped_features += 1
                continue

            if args.overwrite or not post_output.exists():
                post_crop = post_image.crop(
                    post_box
                )

                post_crop.save(
                    post_output,
                    format="PNG",
                    compress_level=3,
                )

            if args.overwrite or not pre_output.exists():
                pre_crop = pre_image.crop(
                    pre_box
                )

                pre_crop.save(
                    pre_output,
                    format="PNG",
                    compress_level=3,
                )

            # Relative paths are written from data/ because manifest_train.csv
            # itself is stored directly inside data/.
            manifest_rows.append({
                "building_id": building_id,
                "scene_id": scene_id,
                "split": args.split_name,

                "disaster_type": (
                    scene_id.rsplit("_", 1)[0]
                ),

                "damage_label": damage_label,

                "pre_crop_path": (
                    Path("processed")
                    / args.split_name
                    / "pre"
                    / f"{building_id}.png"
                ).as_posix(),

                "post_crop_path": (
                    Path("processed")
                    / args.split_name
                    / "post"
                    / f"{building_id}.png"
                ).as_posix(),

                "original_bbox": str(
                    post_box
                ),

                "original_crop_width": (
                    crop_width
                ),

                "original_crop_height": (
                    crop_height
                ),
            })

        processed_scenes += 1

        # Periodic progress output.
        if (
            scene_number % 50 == 0
            or scene_number == len(post_label_files)
        ):
            elapsed = (
                time.perf_counter()
                - start_time
            )

            scene_rate = (
                scene_number / elapsed
                if elapsed > 0
                else 0.0
            )

            remaining = (
                len(post_label_files)
                - scene_number
            )

            eta = (
                remaining / scene_rate
                if scene_rate > 0
                else 0.0
            )

            print(
                f"Scenes "
                f"{scene_number:,}/{len(post_label_files):,} | "
                f"manifest rows={len(manifest_rows):,} | "
                f"elapsed={format_seconds(elapsed)} | "
                f"ETA={format_seconds(eta)}"
            )

    # -----------------------------------------------------------------------
    # SAVE MANIFEST
    # -----------------------------------------------------------------------

    manifest = pd.DataFrame(
        manifest_rows,
        columns=[
            "building_id",
            "scene_id",
            "split",
            "disaster_type",
            "damage_label",
            "pre_crop_path",
            "post_crop_path",
            "original_bbox",
            "original_crop_width",
            "original_crop_height",
        ],
    )

    manifest.to_csv(
        manifest_path,
        index=False,
    )

    elapsed = (
        time.perf_counter()
        - start_time
    )

    print()
    print("=" * 80)
    print("MANIFEST / CROP CREATION COMPLETE")
    print("=" * 80)
    print()
    print(f"Scenes processed: {processed_scenes:,}")
    print(f"Scenes skipped:   {skipped_scenes:,}")
    print(f"Features skipped: {skipped_features:,}")
    print(f"Manifest rows:    {len(manifest):,}")
    print(f"Total time:       {format_seconds(elapsed)}")
    print()
    print("Output:")
    print(f"  {manifest_path}")
    print(f"  {pre_dir}")
    print(f"  {post_dir}")
    print()


if __name__ == "__main__":
    main()
