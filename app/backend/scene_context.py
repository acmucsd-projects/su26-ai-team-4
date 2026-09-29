"""Deterministic event labels and prediction summaries for packaged demo scenes.

Event names, locations, and acquisition dates come only from explicit scene
manifest fields. Hazard categories use a small allowlisted mapping of the
packaged event names; no location or event date is inferred from GIS claims.
"""

from __future__ import annotations

import math
from .scene_evidence import DAMAGE_CLASSES, HAZARD_TYPE_BY_EVENT_NAME, build_scene_metadata


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def build_event_context(scene: dict) -> dict:
    """Compatibility wrapper around the centralized curated metadata layer."""

    return {"schema_version": 1, **build_scene_metadata(scene)}


def build_scene_context(
    scene: dict,
    selected_building: dict,
    probability_ranking: dict | None,
) -> dict:
    """Summarize packaged predictions without doing model or spatial analysis."""

    raw_buildings = scene.get("buildings")
    buildings = raw_buildings if isinstance(raw_buildings, list) else []
    counts = {name: 0 for name in DAMAGE_CLASSES}
    for building in buildings:
        if not isinstance(building, dict):
            continue
        prediction = building.get("prediction")
        predicted_class = prediction.get("predicted_class") if isinstance(prediction, dict) else None
        if isinstance(predicted_class, str) and predicted_class in counts:
            counts[predicted_class] += 1

    classified_count = sum(counts.values())
    selected_prediction = selected_building.get("prediction")
    selected_prediction_class = (
        selected_prediction.get("predicted_class") if isinstance(selected_prediction, dict) else None
    )
    selected_class = (
        selected_prediction_class
        if isinstance(selected_prediction_class, str) and selected_prediction_class in counts else None
    )
    selected = {"predicted_class": selected_class}
    if selected_class:
        selected["same_class_building_count"] = counts[selected_class]
    if isinstance(probability_ranking, dict):
        top_two_gap = probability_ranking.get("top_two_gap")
        if (
            isinstance(top_two_gap, (int, float))
            and not isinstance(top_two_gap, bool)
            and math.isfinite(top_two_gap)
        ):
            selected["top_two_probability_gap"] = top_two_gap

    context = {
        "schema_version": 1,
        "building_count": len(buildings),
        "classified_building_count": classified_count,
        "predicted_class_counts": counts,
        "severe_prediction_count": counts["major-damage"] + counts["destroyed"],
        "selected_building": selected,
    }
    scene_id = _optional_text(scene.get("scene_id"))
    if scene_id:
        context["scene_id"] = scene_id
    return context
