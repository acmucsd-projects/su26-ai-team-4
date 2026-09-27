"""Build a local, precomputed scene pack for the application dashboard demo.

Run from the repository root, for example:

    python -m app.backend.package_demo_scene \
      --checkpoint path/to/resnet18_prepost_plaince_xbd_128_seed17.pt

The utility intentionally writes only a local ignored output pack. It uses the
canonical application inference loader and preprocessing, plus the existing
xBD cache manifest, and does not modify source images or crops.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

from src.build_manifest import parse_wkt_points

from .inference import EXPECTED_CLASS_NAMES, load_classifier, predict_image_pairs


DEFAULT_SCENE_ID = "hurricane-michael_00000247"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_MANIFEST = REPOSITORY_ROOT / "base_train" / "ezekiel_resnet18_baseline" / "cache" / "cache_manifest.csv"
DEFAULT_DATA_DIR = REPOSITORY_ROOT / "data"
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "local_experiments" / "demo_scene_pack"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package one xBD scene and precomputed classifier predictions for the app demo."
    )
    parser.add_argument("--checkpoint", type=Path, required=True, help="Compatible released plain-CE checkpoint.")
    parser.add_argument("--scene-id", default=DEFAULT_SCENE_ID, help="xBD scene identifier to package.")
    parser.add_argument("--cache-manifest", type=Path, default=DEFAULT_CACHE_MANIFEST)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--batch-size", type=int, default=32, help="Pairs evaluated per model call.")
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_verified(source: Path, destination: Path) -> None:
    """Copy one asset and verify that the generated file did not alter its bytes."""

    shutil.copy2(source, destination)
    if file_sha256(source) != file_sha256(destination):
        raise RuntimeError(f"Copied asset does not match source: {source}")


def building_index(building_id: str, scene_id: str) -> int:
    prefix = f"{scene_id}_b"
    if not building_id.startswith(prefix):
        raise ValueError(f"Building ID is not part of {scene_id}: {building_id}")
    return int(building_id.removeprefix(prefix))


def load_scene_cache_rows(cache_manifest: Path, scene_id: str) -> list[dict[str, str]]:
    with cache_manifest.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"cache_id", "building_id", "scene_id", "damage_label", "pre_png", "post_png"}
        if reader.fieldnames is None or required - set(reader.fieldnames):
            raise ValueError(f"Cache manifest is missing required columns: {cache_manifest}")
        rows = [
            row
            for row in reader
            if row["scene_id"] == scene_id and row["damage_label"] in EXPECTED_CLASS_NAMES
        ]

    if not rows:
        raise ValueError(f"No supported cached building pairs found for scene {scene_id}.")
    rows.sort(key=lambda row: building_index(row["building_id"], scene_id))
    if len({row["building_id"] for row in rows}) != len(rows):
        raise ValueError(f"Cache manifest has duplicate building IDs for scene {scene_id}.")
    return rows


def load_geometry_by_uid(label_path: Path, label_name: str) -> dict[str, list[list[float]]]:
    """Read valid xBD pixel polygons keyed by their raw building UID."""

    with label_path.open("r", encoding="utf-8") as handle:
        label_json = json.load(handle)
    features = label_json.get("features", {}).get("xy", [])
    if not isinstance(features, list):
        raise ValueError(f"{label_name} label file has no xBD xy feature list: {label_path}")

    geometry_by_uid: dict[str, list[list[float]]] = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue
        polygon = parse_wkt_points(feature.get("wkt", ""))
        if not polygon:
            continue
        properties = feature.get("properties", {}) or {}
        raw_uid = properties.get("uid")
        if not isinstance(raw_uid, str) or not raw_uid:
            raise ValueError(f"{label_name} feature has no UID: {label_path}")
        if raw_uid in geometry_by_uid:
            raise ValueError(f"{label_name} label file has duplicate UID: {raw_uid}")
        geometry_by_uid[raw_uid] = [[float(x), float(y)] for x, y in polygon]
    return geometry_by_uid


def load_post_geometry_by_building_id(post_label_path: Path, scene_id: str) -> dict[str, dict[str, Any]]:
    """Reproduce the existing crop builder's valid-POST-feature numbering.

    The cache uses this POST ordering for ``building_id``. PRE geometry is
    paired separately by the raw xBD UID, rather than relying on feature order.
    """

    with post_label_path.open("r", encoding="utf-8") as handle:
        label_json = json.load(handle)
    features = label_json.get("features", {}).get("xy", [])
    if not isinstance(features, list):
        raise ValueError(f"POST label file has no xBD xy feature list: {post_label_path}")

    geometry: dict[str, dict[str, Any]] = {}
    valid_feature_index = 0
    for feature in features:
        if not isinstance(feature, dict):
            continue
        polygon = parse_wkt_points(feature.get("wkt", ""))
        if not polygon:
            continue
        building_id = f"{scene_id}_b{valid_feature_index:04d}"
        valid_feature_index += 1
        properties = feature.get("properties", {}) or {}
        raw_uid = properties.get("uid")
        if not isinstance(raw_uid, str) or not raw_uid:
            raise ValueError(f"POST feature has no UID for {building_id}.")
        geometry[building_id] = {
            "uid": raw_uid,
            "post_pixel_polygon": [[float(x), float(y)] for x, y in polygon],
            "raw_ground_truth": str(properties.get("subtype", "un-classified")),
        }
    return geometry


def load_image_copy(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGB").copy()


def validate_scene_pack(payload: dict[str, Any], output_dir: Path, expected_count: int) -> None:
    buildings = payload.get("buildings")
    if not isinstance(buildings, list) or len(buildings) != expected_count:
        raise ValueError(f"Expected {expected_count} packaged buildings, found {len(buildings or [])}.")

    for building in buildings:
        if (
            not building.get("id")
            or not building.get("uid")
            or len(building.get("pre_pixel_polygon", [])) < 3
            or len(building.get("post_pixel_polygon", [])) < 3
        ):
            raise ValueError(f"Incomplete building geometry: {building.get('id')}")
        prediction = building.get("prediction", {})
        probabilities = prediction.get("probabilities", {})
        if set(probabilities) != set(EXPECTED_CLASS_NAMES):
            raise ValueError(f"Prediction classes are incomplete for {building['id']}.")
        if prediction.get("predicted_class") not in EXPECTED_CLASS_NAMES:
            raise ValueError(f"Unsupported prediction for {building['id']}.")
        if not isinstance(prediction.get("confidence"), (float, int)):
            raise ValueError(f"Prediction confidence is missing for {building['id']}.")
        if abs(sum(float(value) for value in probabilities.values()) - 1.0) > 1e-5:
            raise ValueError(f"Probabilities do not sum to one for {building['id']}.")
        crops = building.get("crops", {})
        if set(crops) != {"pre_url", "post_url"}:
            raise ValueError(f"Both crop URLs are required for {building['id']}.")
        for crop_url in crops.values():
            if not isinstance(crop_url, str) or not (output_dir / crop_url).is_file():
                raise ValueError(f"Missing packaged crop for {building['id']}.")

    for image_url in payload.get("image", {}).values():
        if isinstance(image_url, str) and not (output_dir / image_url).is_file():
            raise ValueError(f"Missing packaged scene image: {image_url}")


def build_scene_pack(args: argparse.Namespace) -> dict[str, Any]:
    if args.batch_size < 1:
        raise ValueError("--batch-size must be at least 1.")

    scene_id = str(args.scene_id)
    cache_manifest = args.cache_manifest.resolve()
    data_dir = args.data_dir.resolve()
    output_dir = args.output_root.resolve() / scene_id
    checkpoint_path = args.checkpoint.resolve()
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite existing scene pack: {output_dir}")
    if not cache_manifest.is_file():
        raise FileNotFoundError(f"Cache manifest was not found: {cache_manifest}")

    images_dir = data_dir / "train" / "images"
    labels_dir = data_dir / "train" / "labels"
    pre_scene_path = images_dir / f"{scene_id}_pre_disaster.png"
    post_scene_path = images_dir / f"{scene_id}_post_disaster.png"
    pre_label_path = labels_dir / f"{scene_id}_pre_disaster.json"
    post_label_path = labels_dir / f"{scene_id}_post_disaster.json"
    for source in (pre_scene_path, post_scene_path, pre_label_path, post_label_path):
        if not source.is_file():
            raise FileNotFoundError(f"Required scene source was not found: {source}")

    cache_rows = load_scene_cache_rows(cache_manifest, scene_id)
    geometry_by_id = load_post_geometry_by_building_id(post_label_path, scene_id)
    pre_geometry_by_uid = load_geometry_by_uid(pre_label_path, "PRE")
    missing_geometry = [row["building_id"] for row in cache_rows if row["building_id"] not in geometry_by_id]
    if missing_geometry:
        raise ValueError(f"Cached buildings have no matching POST geometry: {missing_geometry[:3]}")

    cache_root = cache_manifest.parent
    records: list[dict[str, Any]] = []
    for row in cache_rows:
        pre_crop_path = cache_root / row["pre_png"]
        post_crop_path = cache_root / row["post_png"]
        if not pre_crop_path.is_file() or not post_crop_path.is_file():
            raise FileNotFoundError(f"Cached pair is incomplete for {row['building_id']}")
        geometry = geometry_by_id[row["building_id"]]
        if geometry["raw_ground_truth"] != row["damage_label"]:
            raise ValueError(f"Raw label does not match cache label for {row['building_id']}")
        pre_polygon = pre_geometry_by_uid.get(geometry["uid"])
        if pre_polygon is None:
            raise ValueError(f"Cached building has no matching PRE geometry: {row['building_id']}")
        records.append(
            {
                **row,
                **geometry,
                "pre_pixel_polygon": pre_polygon,
                "pre_crop_path": pre_crop_path,
                "post_crop_path": post_crop_path,
            }
        )

    classifier = load_classifier(checkpoint_path)
    predictions_by_id: dict[str, dict[str, Any]] = {}
    for start in range(0, len(records), args.batch_size):
        batch_records = records[start : start + args.batch_size]
        image_pairs = [
            (load_image_copy(record["pre_crop_path"]), load_image_copy(record["post_crop_path"]))
            for record in batch_records
        ]
        for record, prediction in zip(batch_records, predict_image_pairs(classifier, image_pairs), strict=True):
            predictions_by_id[record["building_id"]] = prediction

    output_dir.mkdir(parents=True)
    crops_dir = output_dir / "crops"
    crops_dir.mkdir()
    copy_verified(pre_scene_path, output_dir / "pre.png")
    copy_verified(post_scene_path, output_dir / "post.png")
    with Image.open(post_scene_path) as post_scene:
        scene_width, scene_height = post_scene.size
    with Image.open(pre_scene_path) as pre_scene:
        if pre_scene.size != (scene_width, scene_height):
            raise ValueError("PRE and POST scene dimensions differ.")

    buildings: list[dict[str, Any]] = []
    for record in records:
        cache_id = record["cache_id"]
        pre_crop_url = f"crops/{cache_id}_pre.png"
        post_crop_url = f"crops/{cache_id}_post.png"
        copy_verified(record["pre_crop_path"], output_dir / pre_crop_url)
        copy_verified(record["post_crop_path"], output_dir / post_crop_url)
        buildings.append(
            {
                "id": record["building_id"],
                "uid": record["uid"],
                "pre_pixel_polygon": record["pre_pixel_polygon"],
                "post_pixel_polygon": record["post_pixel_polygon"],
                "prediction": predictions_by_id[record["building_id"]],
                "crops": {"pre_url": pre_crop_url, "post_url": post_crop_url},
                "demo_metadata": {"ground_truth": record["damage_label"]},
            }
        )

    payload: dict[str, Any] = {
        "schema_version": 2,
        "scene_id": scene_id,
        "event_name": scene_id.rsplit("_", 1)[0],
        "image": {
            "width": scene_width,
            "height": scene_height,
            "pre_url": "pre.png",
            "post_url": "post.png",
        },
        "buildings": buildings,
    }
    validate_scene_pack(payload, output_dir, expected_count=len(records))
    with (output_dir / "scene.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")

    return {
        "output_dir": output_dir,
        "building_count": len(buildings),
        "prediction_counts": dict(sorted(Counter(item["prediction"]["predicted_class"] for item in buildings).items())),
    }


def main() -> None:
    result = build_scene_pack(parse_args())
    print(f"Created scene pack: {result['output_dir']}")
    print(f"Buildings: {result['building_count']}")
    print(f"Predicted classes: {result['prediction_counts']}")


if __name__ == "__main__":
    main()
