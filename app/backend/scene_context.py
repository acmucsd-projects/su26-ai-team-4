"""Deterministic event labels and prediction summaries for packaged demo scenes.

Event names, locations, and acquisition dates come only from explicit scene
manifest fields. Hazard categories use a small allowlisted mapping of the
packaged event names; no location or event date is inferred from GIS claims.
"""

from __future__ import annotations

import math
from datetime import date


DAMAGE_CLASSES = ("no-damage", "minor-damage", "major-damage", "destroyed")
HAZARD_TYPE_BY_EVENT_NAME = {
    "hurricane-florence": "hurricane",
    "hurricane-harvey": "hurricane",
    "hurricane-matthew": "hurricane",
    "hurricane-michael": "hurricane",
    "palu-tsunami": "tsunami",
    "santa-rosa-wildfire": "wildfire",
    "socal-fire": "wildfire",
}


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_iso_date(value: object) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None
    return text if parsed.isoformat() == text else None


def build_event_context(scene: dict) -> dict:
    """Return only explicit manifest event metadata and recognized hazard type."""

    context = {}
    event_name = _optional_text(scene.get("event_name"))
    if event_name:
        context["event_name"] = event_name
        hazard_type = HAZARD_TYPE_BY_EVENT_NAME.get(event_name)
        if hazard_type:
            context["hazard_type"] = hazard_type
            context["hazard_type_basis"] = "explicit mapping from packaged event_name"

    location = _optional_text(scene.get("location"))
    if location:
        context["location"] = location
    for field in ("pre_acquisition_date", "post_acquisition_date"):
        acquisition_date = _optional_iso_date(scene.get(field))
        if acquisition_date:
            context[field] = acquisition_date

    if context:
        return {"schema_version": 1, **context}
    return {}


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
