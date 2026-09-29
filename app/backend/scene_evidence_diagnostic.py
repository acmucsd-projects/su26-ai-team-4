"""Print a deterministic evidence inventory for every packaged demo scene.

Run from the repository root with ``python -m app.backend.scene_evidence_diagnostic``.
This is an offline validation report; it makes no provider or network requests.
"""

from __future__ import annotations

import json
from pathlib import Path

from .building_context import load_context_overlay
from .scene_evidence import build_scene_evidence


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def build_demo_scene_diagnostics(repository_root: Path = REPOSITORY_ROOT) -> dict:
    scenes_root = repository_root / "app" / "demo_scenes"
    overlays_root = repository_root / "app" / "demo_gis_context"
    scenes = []
    for manifest_path in sorted(scenes_root.glob("*/scene.json")):
        scene = json.loads(manifest_path.read_text(encoding="utf-8"))
        contexts = load_context_overlay(overlays_root, scene["scene_id"], manifest_path, scene)
        evidence = build_scene_evidence(scene, contexts)
        model, uncertainty, spatial, gis = (
            evidence["model_summary"], evidence["uncertainty_summary"],
            evidence["spatial_summary"], evidence["gis_summary"],
        )
        method = spatial["severe_group_method"] or {}
        missing = []
        if spatial["coordinate_space"] != "geographic_lon_lat":
            missing.append("geographic coordinates / scene geotransform")
        if not evidence["event"]["location"]:
            missing.append("verified location")
        if not evidence["event"]["pre_acquisition_date"]:
            missing.append("PRE acquisition date")
        if not evidence["event"]["post_acquisition_date"]:
            missing.append("POST acquisition date")
        if not gis["buildings_with_reviewed_context"]:
            missing.append("reviewed GIS context")
        missing.append("validated image-change indicators (deferred)")
        scenes.append({
            "scene_id": scene["scene_id"],
            "building_count": model["total_buildings"],
            "class_counts": model["class_counts"],
            "severe_percentage": model["severe_percentage"],
            "spatial_geometry": {
                "PRE_valid": spatial["pre_geometry_buildings"],
                "POST_valid": spatial["post_geometry_buildings"],
                "coordinate_space": spatial["coordinate_space"],
                "distance_unit": spatial["distance_unit"],
                "nearest_neighbor_scale": method.get("scene_median_nearest_neighbor_distance"),
                "group_method": method.get("name"),
            },
            "uncertainty": {
                "top_two_gap": uncertainty["top_two_gap"],
                "common_competing_class_pairs": uncertainty["top_competing_class_pairs"],
            },
            "spatial_summary": {
                "severe_group_count": spatial["severe_group_count"],
                "largest_severe_group_size": spatial["largest_severe_group_size"],
                "severe_buildings_in_groups": spatial["severe_buildings_in_groups"],
                "isolated_severe_predictions": spatial["isolated_severe_predictions"],
                "local_class_disagreements": spatial["local_disagreement_count"],
                "local_severity_contrasts": spatial["local_severity_contrast_count"],
            },
            "gis_coverage": {
                "reviewed_buildings": gis["buildings_with_reviewed_context"],
                "direct_building_or_place": gis["buildings_with_direct_building_or_place_evidence"],
                "parcel_or_property": gis["buildings_with_parcel_or_property_evidence"],
                "named_site": gis["buildings_with_named_site_evidence"],
                "modeled_use": gis["buildings_with_modeled_use_evidence"],
                "area": gis["buildings_with_area_evidence"],
                "severe_with_context": gis["severe_predictions_with_reviewed_context"],
                "conflicts": gis["buildings_with_context_conflicts"],
            },
            "site_groups": [{"name": site["name"], "scope": site["scope"],
                             "building_count": site["building_count"],
                             "prediction_counts": site["prediction_counts"]}
                            for site in evidence["site_groups"]],
            "candidate_finding_types": sorted({candidate["type"] for candidate in evidence["candidate_findings"].values()}),
            "missing_or_deferred_layers": missing,
        })
    return {"schema_version": 1, "mode": "offline_deterministic_diagnostic", "scenes": scenes}


def main() -> None:
    print(json.dumps(build_demo_scene_diagnostics(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
