"""Deterministic, reusable evidence derived from one packaged demo scene.

The structure is deliberately independent of any language model. It contains
the scene facts, ranked predictions and reviewed context needed by scene- and
building-level assessment, while keeping candidate references stable for UI
inspection and future scene analysis.
"""

from __future__ import annotations

import math
from datetime import date
from typing import TypedDict

from .building_context import valid_context


SCENE_EVIDENCE_SCHEMA_VERSION = 1
DAMAGE_CLASSES = ("no-damage", "minor-damage", "major-damage", "destroyed")
SEVERE_CLASSES = frozenset(("major-damage", "destroyed"))
LOW_DAMAGE_CLASSES = frozenset(("no-damage", "minor-damage"))
MAX_SCENE_CANDIDATES = 9
MAX_CANDIDATE_CONTEXT_CLAIMS = 4


class SceneEvidence(TypedDict):
    """JSON-compatible deterministic scene evidence source of truth."""

    schema_version: int
    scene_metadata: dict
    damage_distribution: dict
    model_uncertainty: dict
    context_summary: dict
    candidate_order: list[str]
    candidates: dict[str, dict]


# These values are supported by the tracked, reviewed GIS audit notes and
# overlays. Unknown location/date values intentionally remain null.
SCENE_METADATA_BY_ID = {
    "hurricane-harvey_00000177": {
        "event_name": "hurricane-harvey",
        "hazard_type": "hurricane",
        "hazard_type_basis": "allowlisted mapping from packaged event_name",
        "location": "Harris County, Texas",
        "location_basis": "reviewed HCAD / City of Houston GIS coverage",
        "location_source": "app/backend/gis_context/HARVEY_FEASIBILITY.md",
        "pre_acquisition_date": None,
        "post_acquisition_date": "2017-08-31T17:38:50.685Z",
        "acquisition_date_basis": "POST xBD metadata.capture_date recorded in the reviewed audit",
        "acquisition_date_source": "app/backend/gis_context/HARVEY_FEASIBILITY.md",
    },
    "hurricane-michael_00000247": {
        "event_name": "hurricane-michael",
        "hazard_type": "hurricane",
        "hazard_type_basis": "allowlisted mapping from packaged event_name",
        "location": "Bay County, Florida",
        "location_basis": "reviewed Bay County Property Appraiser overlay",
        "location_source": "app/demo_gis_context/hurricane-michael_00000247.json",
        "pre_acquisition_date": None,
        "post_acquisition_date": "2018-10-13T16:48:15.000Z",
        "acquisition_date_basis": "POST xBD capture time recorded in the reviewed audit",
        "acquisition_date_source": "app/backend/gis_context/MILESTONE_2_FEASIBILITY.md",
    },
    "hurricane-matthew_00000060": {
        "event_name": "hurricane-matthew",
        "hazard_type": "hurricane",
        "hazard_type_basis": "allowlisted mapping from packaged event_name",
        "location": None,
        "location_basis": None,
        "location_source": None,
        "pre_acquisition_date": None,
        "post_acquisition_date": None,
        "acquisition_date_basis": None,
        "acquisition_date_source": None,
    },
    "hurricane-florence_00000459": {
        "event_name": "hurricane-florence",
        "hazard_type": "hurricane",
        "hazard_type_basis": "allowlisted mapping from packaged event_name",
        "location": "Duplin County, North Carolina",
        "location_basis": "reviewed audit of the Duplin County parcel source",
        "location_source": "app/backend/gis_context/README.md",
        "pre_acquisition_date": None,
        "post_acquisition_date": None,
        "acquisition_date_basis": None,
        "acquisition_date_source": None,
    },
    "palu-tsunami_00000065": {
        "event_name": "palu-tsunami",
        "hazard_type": "tsunami",
        "hazard_type_basis": "allowlisted mapping from packaged event_name",
        "location": None,
        "location_basis": None,
        "location_source": None,
        "pre_acquisition_date": None,
        "post_acquisition_date": None,
        "acquisition_date_basis": None,
        "acquisition_date_source": None,
    },
    "santa-rosa-wildfire_00000014": {
        "event_name": "santa-rosa-wildfire",
        "hazard_type": "wildfire",
        "hazard_type_basis": "allowlisted mapping from packaged event_name",
        "location": "Sonoma County, California",
        "location_basis": "reviewed Sonoma County GIS overlay and audit",
        "location_source": "app/backend/gis_context/MILESTONE_2_FEASIBILITY.md",
        "pre_acquisition_date": None,
        "post_acquisition_date": "2017-10-11T19:19:41.000Z",
        "acquisition_date_basis": "POST xBD capture time recorded in the reviewed audit",
        "acquisition_date_source": "app/backend/gis_context/MILESTONE_2_FEASIBILITY.md",
    },
    "socal-fire_00000663": {
        "event_name": "socal-fire",
        "hazard_type": "wildfire",
        "hazard_type_basis": "allowlisted mapping from packaged event_name",
        "location": None,
        "location_basis": None,
        "location_source": None,
        "pre_acquisition_date": None,
        "post_acquisition_date": None,
        "acquisition_date_basis": None,
        "acquisition_date_source": None,
    },
}

HAZARD_TYPE_BY_EVENT_NAME = {
    row["event_name"]: row["hazard_type"] for row in SCENE_METADATA_BY_ID.values()
}


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _probability(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and 0 <= number <= 1 else None


def _iso_date(value: object) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        parsed_date = date.fromisoformat(text)
    except ValueError:
        return None
    return text if parsed_date.isoformat() == text else None


def _percentage(count: int, denominator: int) -> float | None:
    return round(100 * count / denominator, 2) if denominator else None


def build_scene_metadata(scene: dict) -> dict:
    """Return curated metadata only when the scene ID and event name agree."""

    scene_id = _optional_text(scene.get("scene_id"))
    event_name = _optional_text(scene.get("event_name"))
    curated = SCENE_METADATA_BY_ID.get(scene_id or "")
    if curated and event_name == curated["event_name"]:
        return {
            "scene_id": scene_id,
            "event_name": curated["event_name"],
            "hazard_type": curated["hazard_type"],
            "hazard_type_basis": curated["hazard_type_basis"],
            "location": curated["location"],
            "location_basis": curated["location_basis"],
            "location_source": curated["location_source"],
            "pre_acquisition_date": curated["pre_acquisition_date"],
            "post_acquisition_date": curated["post_acquisition_date"],
            "acquisition_date_basis": curated["acquisition_date_basis"],
            "acquisition_date_source": curated["acquisition_date_source"],
        }

    # Unknown scenes may still provide explicit metadata. Never infer a
    # location or acquisition date from an event name or provider coverage.
    result = {
        "scene_id": scene_id,
        "event_name": event_name,
        "hazard_type": HAZARD_TYPE_BY_EVENT_NAME.get(event_name or ""),
        "hazard_type_basis": (
            "allowlisted mapping from packaged event_name"
            if event_name in HAZARD_TYPE_BY_EVENT_NAME else None
        ),
        "location": _optional_text(scene.get("location")),
        "location_basis": "explicit scene manifest field" if _optional_text(scene.get("location")) else None,
        "location_source": "scene manifest" if _optional_text(scene.get("location")) else None,
        "pre_acquisition_date": _iso_date(scene.get("pre_acquisition_date")),
        "post_acquisition_date": _iso_date(scene.get("post_acquisition_date")),
        "acquisition_date_basis": "explicit scene manifest field" if any(
            _iso_date(scene.get(field)) for field in ("pre_acquisition_date", "post_acquisition_date")
        ) else None,
        "acquisition_date_source": "scene manifest" if any(
            _iso_date(scene.get(field)) for field in ("pre_acquisition_date", "post_acquisition_date")
        ) else None,
    }
    return result


def _prediction_record(building: object) -> dict | None:
    if not isinstance(building, dict):
        return None
    building_id = _optional_text(building.get("id"))
    prediction = building.get("prediction")
    if not building_id or not isinstance(prediction, dict):
        return None
    predicted_class = prediction.get("predicted_class")
    if predicted_class not in DAMAGE_CLASSES:
        return None
    raw_probabilities = prediction.get("probabilities")
    raw_probabilities = raw_probabilities if isinstance(raw_probabilities, dict) else {}
    probabilities = {name: _probability(raw_probabilities.get(name)) for name in DAMAGE_CLASSES}
    if any(value is None for value in probabilities.values()):
        return {
            "building_id": building_id,
            "uid": _optional_text(building.get("uid")),
            "predicted_class": predicted_class,
            "probabilities": probabilities,
            "probability_ranking": None,
        }
    ranked_classes = sorted(DAMAGE_CLASSES, key=lambda name: (-probabilities[name], DAMAGE_CLASSES.index(name)))
    first, second = ranked_classes[:2]
    return {
        "building_id": building_id,
        "uid": _optional_text(building.get("uid")),
        "predicted_class": predicted_class,
        "probabilities": probabilities,
        "probability_ranking": {
            "most_likely_class": first,
            "top_probability": probabilities[first],
            "second_most_likely_class": second,
            "second_probability": probabilities[second],
            "top_two_gap": probabilities[first] - probabilities[second],
        },
    }


def _reviewed_context_by_building(scene: dict, contexts_by_uid: object) -> dict[str, dict]:
    if not isinstance(contexts_by_uid, dict):
        return {}
    result = {}
    buildings = scene.get("buildings")
    for building in buildings if isinstance(buildings, list) else []:
        if not isinstance(building, dict):
            continue
        building_id = _optional_text(building.get("id"))
        uid = _optional_text(building.get("uid"))
        context = contexts_by_uid.get(uid) if uid else None
        if building_id and valid_context(context) and context["claims"]:
            result[building_id] = context
    return result


def _context_facts(context: dict | None) -> dict:
    if not isinstance(context, dict):
        return {
            "available": False,
            "primary_category": None,
            "claim_count": 0,
            "source_count": 0,
            "scopes": [],
            "claims": [],
            "conflicts": [],
            "area_only": False,
        }
    claims = [claim for claim in context["claims"] if claim["displayable"] is True]
    normalized_claims = [
        {
            "kind": claim["kind"],
            "scope": claim["scope"],
            "title": claim["title"],
            "value": claim["value"],
            "category": claim["category_hint"],
            "source": claim["source"],
            "temporal_relation": claim["temporal_relation"],
            "timing": claim["timing"],
            "modeled": claim["modeled"],
            "multi_structure": claim["multi_structure"],
            "qualifier": claim["qualifier"] or None,
            "qualifications": list(claim["qualifications"]),
        }
        for claim in claims[:MAX_CANDIDATE_CONTEXT_CLAIMS]
    ]
    return {
        "available": bool(claims),
        "primary_category": context["primary_category"],
        "claim_count": len(claims),
        "source_count": len({claim["source_key"] for claim in claims}),
        "scopes": sorted({claim["scope"] for claim in claims}),
        "claims": normalized_claims,
        "conflicts": [
            {"reason": conflict["reason"], "resolution": conflict["resolution"]}
            for conflict in context["conflicts"]
        ],
        "area_only": context["area_only"],
    }


def _context_summary(buildings: list, contexts: dict[str, dict]) -> dict:
    primary_categories: dict[str, int] = {}
    buildings_with_building_or_place = 0
    buildings_with_modeled_use = 0
    buildings_with_parcel = 0
    buildings_with_site = 0
    buildings_with_area = 0
    buildings_area_only = 0
    buildings_with_conflicts = 0

    for building in buildings:
        if not isinstance(building, dict):
            continue
        building_id = _optional_text(building.get("id"))
        context = contexts.get(building_id or "")
        if not context:
            continue
        category = context["primary_category"]
        primary_categories[category] = primary_categories.get(category, 0) + 1
        claims = context["claims"]
        scopes = {claim["scope"] for claim in claims if claim["displayable"] is True}
        kinds = {claim["kind"] for claim in claims if claim["displayable"] is True}
        normalized_scopes = {item["scope"] for item in context["contexts"]}
        buildings_with_building_or_place += bool(scopes & {"building", "place"})
        buildings_with_modeled_use += "modeled_occupancy" in kinds
        buildings_with_parcel += "parcel" in scopes
        buildings_with_site += "site" in scopes or bool(normalized_scopes & {"site", "area"})
        buildings_with_area += "area_use" in kinds or "area" in normalized_scopes
        buildings_area_only += context["area_only"] is True
        buildings_with_conflicts += bool(context["conflicts"])

    total = len(buildings)
    with_context = len(contexts)
    return {
        "building_count": total,
        "buildings_with_reviewed_context": with_context,
        "buildings_without_reviewed_context": max(0, total - with_context),
        "coverage_percentage": _percentage(with_context, total),
        "buildings_with_building_or_place_evidence": buildings_with_building_or_place,
        "buildings_with_modeled_use_evidence": buildings_with_modeled_use,
        "buildings_with_parcel_evidence": buildings_with_parcel,
        "buildings_with_site_evidence": buildings_with_site,
        "buildings_with_area_evidence": buildings_with_area,
        "buildings_with_area_only_context": buildings_area_only,
        "buildings_with_context_conflicts": buildings_with_conflicts,
        "primary_category_counts": dict(sorted(primary_categories.items())),
    }


def _candidate_context(context: dict | None) -> dict:
    facts = _context_facts(context)
    # Scene prompts need compact semantic evidence, with scope and timing
    # qualifications intact. The building prompt gets selected-building GIS
    # claims from the separate, already normalized building evidence packet.
    return {
        key: facts[key]
        for key in ("available", "primary_category", "claim_count", "source_count", "scopes", "claims", "conflicts", "area_only")
    }


def _candidate(record: dict, reason: dict, context: dict | None) -> dict:
    return {
        "building_id": record["building_id"],
        "reason": reason,
        "damage_prediction": {
            "predicted_class": record["predicted_class"],
            "probabilities": record["probabilities"],
            "probability_ranking": record["probability_ranking"],
        },
        "reviewed_context": _candidate_context(context),
    }


def build_scene_evidence(scene: dict, contexts_by_uid: object = None) -> SceneEvidence:
    """Build deterministic scene facts and a bounded set of inspectable candidates."""

    raw_buildings = scene.get("buildings")
    buildings = raw_buildings if isinstance(raw_buildings, list) else []
    metadata = build_scene_metadata(scene)
    prediction_records = [record for item in buildings if (record := _prediction_record(item))]
    counts = {name: 0 for name in DAMAGE_CLASSES}
    for record in prediction_records:
        counts[record["predicted_class"]] += 1
    total = len(buildings)
    classified_count = len(prediction_records)
    severe_count = sum(counts[name] for name in SEVERE_CLASSES)
    distribution = {
        "total_buildings": total,
        "classified_buildings": classified_count,
        "unclassified_buildings": max(0, total - classified_count),
        "class_counts": counts,
        "class_percentages": {name: _percentage(counts[name], total) for name in DAMAGE_CLASSES},
        "severe_count": severe_count,
        "severe_percentage": _percentage(severe_count, total),
        "percentage_denominator": "all packaged buildings",
    }

    uncertainty_ranked = [
        record for record in prediction_records if record["probability_ranking"] is not None
    ]
    uncertainty_ranked.sort(key=lambda row: (row["probability_ranking"]["top_two_gap"], row["building_id"]))
    decisiveness_ranked = sorted(
        uncertainty_ranked,
        key=lambda row: (-row["probability_ranking"]["top_probability"], row["building_id"]),
    )
    uncertainty_ranks = {
        record["building_id"]: index + 1 for index, record in enumerate(uncertainty_ranked)
    }
    decisiveness_ranks = {
        record["building_id"]: index + 1 for index, record in enumerate(decisiveness_ranked)
    }
    uncertainty_rows = [
        {
            "building_id": record["building_id"],
            "rank": index + 1,
            "most_likely_class": record["probability_ranking"]["most_likely_class"],
            "top_probability": record["probability_ranking"]["top_probability"],
            "second_most_likely_class": record["probability_ranking"]["second_most_likely_class"],
            "second_probability": record["probability_ranking"]["second_probability"],
            "top_two_gap": record["probability_ranking"]["top_two_gap"],
        }
        for index, record in enumerate(uncertainty_ranked)
    ]
    decisiveness_rows = [
        {
            "building_id": record["building_id"],
            "rank": index + 1,
            "most_likely_class": record["probability_ranking"]["most_likely_class"],
            "top_probability": record["probability_ranking"]["top_probability"],
        }
        for index, record in enumerate(decisiveness_ranked)
    ]
    gap_values = [row["top_two_gap"] for row in uncertainty_rows]
    top_probability_values = [row["top_probability"] for row in decisiveness_rows]
    model_uncertainty = {
        "ranked_building_count": len(uncertainty_ranked),
        "uncertainty_ranking": uncertainty_rows,
        "decisiveness_ranking": decisiveness_rows,
        "top_two_gap_range": {
            "smallest": min(gap_values) if gap_values else None,
            "largest": max(gap_values) if gap_values else None,
        },
        "top_probability_range": {
            "smallest": min(top_probability_values) if top_probability_values else None,
            "largest": max(top_probability_values) if top_probability_values else None,
        },
    }

    contexts = _reviewed_context_by_building(scene, contexts_by_uid)
    context_summary = _context_summary(buildings, contexts)
    records_by_id = {record["building_id"]: record for record in prediction_records}
    candidate_order: list[str] = []
    candidates: dict[str, dict] = {}

    def add(key: str, record: dict | None, reason: dict, context: dict | None = None) -> None:
        if len(candidates) >= MAX_SCENE_CANDIDATES or record is None:
            return
        candidates[key] = _candidate(record, reason, context)
        candidate_order.append(key)

    for index, record in enumerate(uncertainty_ranked[:2], 1):
        ranking = record["probability_ranking"]
        add(
            f"most_ambiguous_{index}", record,
            {"type": "smallest_top_two_gap", "rank": index, "top_two_gap": ranking["top_two_gap"]},
            contexts.get(record["building_id"]),
        )
    for index, record in enumerate(decisiveness_ranked[:2], 1):
        ranking = record["probability_ranking"]
        add(
            f"most_decisive_{index}", record,
            {"type": "largest_top_class_probability", "rank": index, "top_probability": ranking["top_probability"]},
            contexts.get(record["building_id"]),
        )
    severe_candidates = [row for row in decisiveness_ranked if row["predicted_class"] in SEVERE_CLASSES]
    low_damage_candidates = [row for row in decisiveness_ranked if row["predicted_class"] in LOW_DAMAGE_CLASSES]
    if severe_candidates:
        record = severe_candidates[0]
        add(
            "representative_severe", record,
            {"type": "representative_severe_prediction", "rank": decisiveness_ranks[record["building_id"]]},
            contexts.get(record["building_id"]),
        )
    if low_damage_candidates:
        record = low_damage_candidates[0]
        add(
            "representative_low_damage", record,
            {"type": "representative_low_damage_prediction", "rank": decisiveness_ranks[record["building_id"]]},
            contexts.get(record["building_id"]),
        )

    context_ranked = []
    qualified_ranked = []
    for building_id, context in contexts.items():
        facts = _context_facts(context)
        record = records_by_id.get(building_id)
        if record is None:
            continue
        context_ranked.append((
            (-facts["claim_count"], -facts["source_count"], -len(facts["scopes"]), building_id),
            record,
            context,
            facts,
        ))
        qualified_count = sum(bool(claim["qualifier"] or claim["qualifications"]) for claim in context["claims"])
        conflict_count = len(context["conflicts"])
        if qualified_count or conflict_count:
            qualified_ranked.append((
                (-conflict_count, -qualified_count, building_id), record, context,
                {"qualified_claim_count": qualified_count, "conflict_count": conflict_count},
            ))
    context_ranked.sort(key=lambda item: item[0])
    qualified_ranked.sort(key=lambda item: item[0])
    for index, (_, record, context, facts) in enumerate(context_ranked[:2], 1):
        add(
            f"context_rich_{index}", record,
            {"type": "rich_reviewed_context", "claim_count": facts["claim_count"],
             "source_count": facts["source_count"], "scopes": facts["scopes"]},
            context,
        )
    if qualified_ranked:
        _, record, context, facts = qualified_ranked[0]
        add("qualified_context_1", record, {"type": "qualified_or_conflicting_context", **facts}, context)

    return {
        "schema_version": SCENE_EVIDENCE_SCHEMA_VERSION,
        "scene_metadata": metadata,
        "damage_distribution": distribution,
        "model_uncertainty": model_uncertainty,
        "context_summary": context_summary,
        "candidate_order": candidate_order,
        "candidates": candidates,
    }


def building_scene_context(scene_evidence: SceneEvidence, building_id: str | None) -> dict:
    """Return the shared scene facts most relevant to one building assessment."""

    distribution = scene_evidence["damage_distribution"]
    uncertainty = scene_evidence["model_uncertainty"]
    candidate_keys = [
        candidate_key for candidate_key in scene_evidence["candidate_order"]
        if scene_evidence["candidates"][candidate_key]["building_id"] == building_id
    ]
    selected_uncertainty = next(
        (row for row in uncertainty["uncertainty_ranking"] if row["building_id"] == building_id),
        None,
    )
    selected_decisiveness = next(
        (row for row in uncertainty["decisiveness_ranking"] if row["building_id"] == building_id),
        None,
    )
    return {
        "damage_distribution": distribution,
        "uncertainty_summary": {
            "ranked_building_count": uncertainty["ranked_building_count"],
            "top_two_gap_range": uncertainty["top_two_gap_range"],
            "selected_building": {
                "uncertainty_rank": selected_uncertainty["rank"] if selected_uncertainty else None,
                "decisiveness_rank": selected_decisiveness["rank"] if selected_decisiveness else None,
                "candidate_keys": candidate_keys,
            },
        },
        "context_summary": scene_evidence["context_summary"],
    }


def scene_evidence_for_prompt(scene_evidence: SceneEvidence) -> dict:
    """Minimize the shared source into scene-level facts and bounded candidates."""

    uncertainty = scene_evidence["model_uncertainty"]
    candidate_keys = scene_evidence["candidate_order"]
    candidate_key_set = set(candidate_keys)
    return {
        "schema_version": scene_evidence["schema_version"],
        "scene_metadata": scene_evidence["scene_metadata"],
        "damage_distribution": scene_evidence["damage_distribution"],
        "model_uncertainty": {
            "ranked_building_count": uncertainty["ranked_building_count"],
            "most_ambiguous": [
                {"candidate_key": key, **scene_evidence["candidates"][key]}
                for key in candidate_keys if key.startswith("most_ambiguous_")
            ],
            "most_decisive": [
                {"candidate_key": key, **scene_evidence["candidates"][key]}
                for key in candidate_keys if key.startswith("most_decisive_")
            ],
        },
        "context_summary": scene_evidence["context_summary"],
        "candidates": {
            key: scene_evidence["candidates"][key]
            for key in candidate_keys if key in candidate_key_set
        },
    }
