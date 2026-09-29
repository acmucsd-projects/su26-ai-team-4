"""Deterministic, reusable evidence derived from one packaged demo scene.

The structure is deliberately independent of any language model. It contains
the scene facts, ranked predictions and reviewed context needed by scene- and
building-level assessment, while keeping candidate references stable for UI
inspection and future scene analysis.
"""

from __future__ import annotations

import math
import hashlib
from datetime import date
from collections import Counter, defaultdict
from typing import TypedDict

from .building_context import valid_context


SCENE_EVIDENCE_SCHEMA_VERSION = 2
DAMAGE_CLASSES = ("no-damage", "minor-damage", "major-damage", "destroyed")
SEVERE_CLASSES = frozenset(("major-damage", "destroyed"))
LOW_DAMAGE_CLASSES = frozenset(("no-damage", "minor-damage"))
CLASS_SEVERITY = {name: index for index, name in enumerate(DAMAGE_CLASSES)}
NEIGHBOR_COUNT = 5
SEVERE_PROXIMITY_SCALE_FACTOR = 1.5
MAX_SCENE_CANDIDATES = 20
MAX_CANDIDATE_CONTEXT_CLAIMS = 4


class SceneEvidence(TypedDict):
    """JSON-compatible deterministic scene evidence source of truth."""

    schema_version: int
    event: dict
    model_summary: dict
    uncertainty_summary: dict
    spatial_summary: dict
    gis_summary: dict
    site_groups: list[dict]
    candidate_order: list[str]
    candidate_findings: dict[str, dict]
    provenance: dict


# Locations come from reviewed GIS records; POST dates come from the matching
# local xBD POST labels (metadata.capture_date). Raw labels are not versioned.
# Unknown locations intentionally remain null.
SCENE_METADATA_BY_ID = {
    "hurricane-harvey_00000177": {
        "event_name": "hurricane-harvey",
        "hazard_type": "hurricane",
        "hazard_type_basis": "allowlisted mapping from packaged event_name",
        "location": "Harris County, Texas",
        "location_scope": "scene",
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
        "location_scope": "scene",
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
        "location_scope": None,
        "location_basis": None,
        "location_source": None,
        "pre_acquisition_date": None,
        "post_acquisition_date": "2016-10-09T15:32:03.000Z",
        "acquisition_date_basis": "POST xBD metadata.capture_date",
        "acquisition_date_source": "data/tier1/labels/hurricane-matthew_00000060_post_disaster.json",
    },
    "hurricane-florence_00000459": {
        "event_name": "hurricane-florence",
        "hazard_type": "hurricane",
        "hazard_type_basis": "allowlisted mapping from packaged event_name",
        "location": "Duplin County, North Carolina",
        "location_scope": "scene",
        "location_basis": "reviewed audit of the Duplin County parcel source",
        "location_source": "app/backend/gis_context/README.md",
        "pre_acquisition_date": None,
        "post_acquisition_date": "2018-09-20T16:04:41.000Z",
        "acquisition_date_basis": "POST xBD metadata.capture_date",
        "acquisition_date_source": "data/tier1/labels/hurricane-florence_00000459_post_disaster.json",
    },
    "palu-tsunami_00000065": {
        "event_name": "palu-tsunami",
        "hazard_type": "tsunami",
        "hazard_type_basis": "allowlisted mapping from packaged event_name",
        "location": None,
        "location_scope": None,
        "location_basis": None,
        "location_source": None,
        "pre_acquisition_date": None,
        "post_acquisition_date": "2018-10-01T02:26:02.000Z",
        "acquisition_date_basis": "POST xBD metadata.capture_date",
        "acquisition_date_source": "data/tier1/labels/palu-tsunami_00000065_post_disaster.json",
    },
    "santa-rosa-wildfire_00000014": {
        "event_name": "santa-rosa-wildfire",
        "hazard_type": "wildfire",
        "hazard_type_basis": "allowlisted mapping from packaged event_name",
        "location": "Sonoma County, California",
        "location_scope": "scene",
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
        "location": "Los Angeles County, California",
        "location_scope": "scene",
        "location_basis": "reviewed SoCal jurisdiction and Los Angeles County GIS audit",
        "location_source": "app/backend/README.md",
        "pre_acquisition_date": None,
        "post_acquisition_date": "2018-11-14T18:42:58.000Z",
        "acquisition_date_basis": "POST xBD metadata.capture_date",
        "acquisition_date_source": "data/tier1/labels/socal-fire_00000663_post_disaster.json",
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
            "location_scope": curated["location_scope"],
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
        "location_scope": (
            scene.get("location_scope") if scene.get("location_scope") in ("scene", "event")
            else "scene"
        ) if _optional_text(scene.get("location")) else None,
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
        "confidence": _probability(prediction.get("confidence")),
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
    for building in scene.get("buildings", []) if isinstance(scene.get("buildings"), list) else []:
        if not isinstance(building, dict):
            continue
        building_id, uid = _optional_text(building.get("id")), _optional_text(building.get("uid"))
        context = contexts_by_uid.get(uid) if uid else None
        if building_id and valid_context(context) and context["claims"]:
            result[building_id] = context
    return result


def _context_facts(context: dict | None) -> dict:
    if not isinstance(context, dict):
        return {"available": False, "primary_category": None, "claim_count": 0, "source_count": 0,
                "scopes": [], "claims": [], "conflicts": [], "area_only": False}
    claims = [claim for claim in context["claims"] if claim["displayable"] is True]
    return {
        "available": bool(claims),
        "primary_category": context["primary_category"],
        "claim_count": len(claims),
        "source_count": len({claim["source_key"] for claim in claims}),
        "scopes": sorted({claim["scope"] for claim in claims}),
        "claims": [{
            "kind": c["kind"], "scope": c["scope"], "title": c["title"], "value": c["value"],
            "name": c["name"], "category": c["category_hint"], "source": c["source"],
            "source_dataset": c["source_dataset"], "source_release": c["source_release"] or None,
            "source_snapshot": c["source_snapshot"] or None, "temporal_relation": c["temporal_relation"],
            "timing": c["timing"], "modeled": c["modeled"], "multi_structure": c["multi_structure"],
            "qualifier": c["qualifier"] or None, "qualifications": list(c["qualifications"]),
        } for c in claims[:MAX_CANDIDATE_CONTEXT_CLAIMS]],
        "conflicts": [{"reason": x["reason"], "resolution": x["resolution"]} for x in context["conflicts"]],
        "area_only": context["area_only"],
    }


def _geometry(points: object) -> dict | None:
    """Return polygon metrics for finite [x,y] rings using the shoelace formula."""
    if not isinstance(points, list) or len(points) < 3:
        return None
    ring = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return None
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            return None
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        ring.append((x, y))
    if ring[0] == ring[-1]:
        ring.pop()
    if len(ring) < 3:
        return None
    def orient(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    for i in range(len(ring)):
        a, b = ring[i], ring[(i + 1) % len(ring)]
        for j in range(i + 1, len(ring)):
            if j == (i + 1) % len(ring) or (j + 1) % len(ring) == i:
                continue
            c, d = ring[j], ring[(j + 1) % len(ring)]
            if orient(a, b, c) * orient(a, b, d) < 0 and orient(c, d, a) * orient(c, d, b) < 0:
                return None
    cross = [ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1]
             for i in range(len(ring))]
    twice_area = sum(cross)
    if abs(twice_area) < 1e-10:
        return None
    cx = sum((ring[i][0] + ring[(i + 1) % len(ring)][0]) * cross[i] for i in range(len(ring))) / (3 * twice_area)
    cy = sum((ring[i][1] + ring[(i + 1) % len(ring)][1]) * cross[i] for i in range(len(ring))) / (3 * twice_area)
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return {"centroid": [cx, cy], "area": abs(twice_area) / 2,
            "bounds": [min(xs), min(ys), max(xs), max(ys)], "ring": ring}


def _geometry_for_building(building: dict) -> tuple[dict | None, str | None]:
    """Prefer explicit geographic geometry; otherwise retain pixel coordinates."""
    geometry = _geometry(building.get("geographic_polygon")) or _geometry(building.get("geo_polygon"))
    if geometry and all(-180 <= x <= 180 and -90 <= y <= 90 for x, y in geometry["ring"]):
        return geometry, "geographic_lon_lat"
    return _geometry(building.get("post_pixel_polygon")), "scene_pixel"


def _distance(left: list[float], right: list[float], coordinate_space: str) -> float:
    if coordinate_space != "geographic_lon_lat":
        return math.dist(left, right)
    radius_m = 6_371_008.8
    lat1, lat2 = math.radians(left[1]), math.radians(right[1])
    delta_lat = lat2 - lat1
    delta_lon = math.radians((right[0] - left[0] + 180) % 360 - 180)
    hav = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return radius_m * 2 * math.asin(min(1, math.sqrt(hav)))


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    result = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(result, 6)


def _distribution(values: list[float]) -> dict:
    return {"count": len(values), "min": _quantile(values, 0), "p25": _quantile(values, .25),
            "median": _quantile(values, .5), "p75": _quantile(values, .75), "max": _quantile(values, 1),
            "quantile_method": "linear interpolation of sorted values"}


def _stable_id(prefix: str, scene_id: str, building_ids: list[str]) -> str:
    payload = scene_id + "\0" + "\0".join(sorted(building_ids))
    return prefix + "_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _context_summary(buildings: list, contexts: dict[str, dict], records_by_id: dict[str, dict]) -> dict:
    category_counts: Counter = Counter()
    scope_counts: Counter = Counter()
    kind_counts: Counter = Counter()
    temporal_counts: Counter = Counter()
    buildings_with_direct = buildings_with_modeled = buildings_with_parcel = 0
    buildings_with_site = buildings_with_area = buildings_with_conflicts = 0
    severe_with_context = 0
    for building in buildings:
        if not isinstance(building, dict):
            continue
        building_id = _optional_text(building.get("id"))
        context = contexts.get(building_id or "")
        if not context:
            continue
        facts = _context_facts(context)
        category_counts[facts["primary_category"] or "unknown"] += 1
        claims = [c for c in context["claims"] if c["displayable"] is True]
        scopes = {c["scope"] for c in claims}
        kinds = {c["kind"] for c in claims}
        scope_counts.update(scopes)
        kind_counts.update(c["kind"] for c in claims)
        temporal_counts.update(c["temporal_relation"] for c in claims)
        buildings_with_direct += bool(scopes & {"building", "place"})
        buildings_with_modeled += "modeled_occupancy" in kinds
        buildings_with_parcel += bool(scopes & {"parcel", "property"})
        buildings_with_site += "site" in scopes and any(c["kind"] in {"school_site", "site_use"} and c["name"] for c in claims)
        buildings_with_area += "area_use" in kinds or "area" in scopes
        buildings_with_conflicts += bool(context["conflicts"])
        severe_with_context += bool(building_id in records_by_id and records_by_id[building_id]["predicted_class"] in SEVERE_CLASSES)
    total, with_context = len(buildings), len(contexts)
    return {
        "building_count": total, "buildings_with_reviewed_context": with_context,
        "buildings_without_reviewed_context": max(0, total - with_context),
        "coverage_percentage": _percentage(with_context, total),
        "buildings_with_direct_building_or_place_evidence": buildings_with_direct,
        "buildings_with_modeled_use_evidence": buildings_with_modeled,
        "buildings_with_parcel_or_property_evidence": buildings_with_parcel,
        "buildings_with_named_site_evidence": buildings_with_site,
        "buildings_with_area_evidence": buildings_with_area,
        "buildings_with_context_conflicts": buildings_with_conflicts,
        "severe_predictions_with_reviewed_context": severe_with_context,
        "primary_category_counts": dict(sorted(category_counts.items())),
        "claim_scope_counts": dict(sorted(scope_counts.items())),
        "claim_kind_counts": dict(sorted(kind_counts.items())),
        "temporal_relation_counts": dict(sorted(temporal_counts.items())),
    }


def _site_groups(scene_id: str, buildings: list, contexts: dict[str, dict], records_by_id: dict[str, dict]) -> list[dict]:
    memberships: dict[tuple, dict] = {}
    for building in buildings:
        if not isinstance(building, dict):
            continue
        building_id = _optional_text(building.get("id"))
        context = contexts.get(building_id or "")
        record = records_by_id.get(building_id or "")
        if not context or not record:
            continue
        for claim in context["claims"]:
            name = _optional_text(claim.get("name"))
            if claim.get("displayable") is not True or claim.get("scope") != "site" or claim.get("kind") not in {"school_site", "site_use"} or not name:
                continue
            signature = (name.casefold(), claim["source_key"], claim["kind"], claim.get("temporal_relation"), claim.get("source_release"))
            entry = memberships.setdefault(signature, {"name": name, "building_ids": set(), "claims": {}})
            entry["building_ids"].add(building_id)
            entry["claims"][signature] = {"source": claim["source"], "dataset": claim["source_dataset"],
                                          "kind": claim["kind"], "temporal_relation": claim["temporal_relation"],
                                          "timing": claim["timing"], "qualifications": list(claim["qualifications"])}
    # Merge separate reviewed records only when both their name and exact
    # analyzed-building membership agree. Broader/different site associations
    # with the same label stay distinct.
    by_membership: dict[tuple[str, tuple[str, ...]], dict] = {}
    for entry in memberships.values():
        ids = tuple(sorted(entry["building_ids"]))
        key = (entry["name"].casefold(), ids)
        merged = by_membership.setdefault(key, {"name": entry["name"], "building_ids": set(ids), "claims": {}})
        merged["claims"].update(entry["claims"])
    result = []
    for entry in by_membership.values():
        ids = sorted(entry["building_ids"])
        if len(ids) < 2:
            continue
        counts = Counter(records_by_id[i]["predicted_class"] for i in ids if i in records_by_id)
        severe = counts["major-damage"] + counts["destroyed"]
        claim_list = sorted(entry["claims"].values(), key=lambda c: (c["source"], c["dataset"], c["kind"]))
        result.append({"site_group_id": _stable_id("site", scene_id, ids + [entry["name"]]),
                       "name": entry["name"], "scope": "site", "building_ids": ids, "building_count": len(ids),
                       "prediction_counts": {name: counts[name] for name in DAMAGE_CLASSES},
                       "severe_prediction_count": severe, "claims": claim_list,
                       "provenance": ["REVIEWED_GIS", "MODEL_DERIVED"]})
    return sorted(result, key=lambda g: (g["name"].casefold(), g["building_ids"]))


def _spatial_analysis(scene: dict, buildings: list, records_by_id: dict[str, dict], contexts: dict[str, dict]) -> tuple[dict, dict[str, dict]]:
    geographic_rows, pixel_rows = {}, {}
    pre_geometry_building_count = sum(
        _geometry(building.get("pre_pixel_polygon")) is not None
        for building in buildings if isinstance(building, dict)
    )
    for building in buildings:
        if not isinstance(building, dict):
            continue
        building_id = _optional_text(building.get("id"))
        if not building_id:
            continue
        geometry, space = _geometry_for_building(building)
        if building_id in records_by_id:
            if geometry and space == "geographic_lon_lat":
                geographic_rows[building_id] = geometry
            pixel_geometry = _geometry(building.get("post_pixel_polygon"))
            if pixel_geometry:
                pixel_rows[building_id] = pixel_geometry
    # Never compare geographic coordinates and image pixels. Use geographic
    # geometry only when it is complete for all classifiable buildings.
    if records_by_id and len(geographic_rows) == len(records_by_id):
        geometry_rows, coordinate_space = geographic_rows, "geographic_lon_lat"
    else:
        geometry_rows, coordinate_space = pixel_rows, "scene_pixel"
    ids = sorted(geometry_rows)
    if not ids:
        return ({"usable_geometry_buildings": 0, "pre_geometry_buildings": pre_geometry_building_count,
                 "post_geometry_buildings": 0, "coordinate_space": None, "distance_unit": None,
                 "scene_bounds": None, "scene_bounds_basis": None, "relative_position_basis": None,
                 "footprint_area_unit": None, "neighborhood_method": {"name": "unavailable", "reason": "No usable classified building geometry"},
                 "severe_group_method": {"name": "unavailable", "reason": "No usable classified building geometry"},
                 "severe_proximity_groups": [], "severe_group_count": 0, "severe_buildings_in_groups": 0,
                 "largest_severe_group_size": 0, "isolated_severe_predictions": 0, "local_disagreement_count": 0,
                 "local_severity_contrast_count": 0, "local_disagreement_building_ids": [],
                 "local_severity_contrast_building_ids": [], "per_building": {}}, {})
    bounds = [min(g["bounds"][0] for g in geometry_rows.values()), min(g["bounds"][1] for g in geometry_rows.values()),
              max(g["bounds"][2] for g in geometry_rows.values()), max(g["bounds"][3] for g in geometry_rows.values())]
    width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
    areas = sorted(g["area"] for g in geometry_rows.values())
    spatial = {}
    nearest_distances = []
    for building_id in ids:
        point = geometry_rows[building_id]["centroid"]
        distances = sorted(((_distance(point, geometry_rows[other]["centroid"], coordinate_space), other) for other in ids if other != building_id), key=lambda x: (x[0], x[1]))
        nearest_distances.append(distances[0][0] if distances else 0.0)
        neighbors = distances[:min(NEIGHBOR_COUNT, len(distances))]
        neighbor_records = [records_by_id[nid] for _, nid in neighbors]
        class_counts = Counter(row["predicted_class"] for row in neighbor_records)
        record = records_by_id[building_id]
        total_confidences = [row["confidence"] for row in neighbor_records if row.get("confidence") is not None]
        gaps = [row["probability_ranking"]["top_two_gap"] for row in neighbor_records if row.get("probability_ranking")]
        area_rank = 1 + sum(value < geometry_rows[building_id]["area"] for value in areas)
        local_n = len(neighbors)
        top_class = sorted(class_counts, key=lambda c: (-class_counts[c], DAMAGE_CLASSES.index(c)))[0] if class_counts else None
        severe_n = sum(class_counts[c] for c in SEVERE_CLASSES)
        low_n = sum(class_counts[c] for c in LOW_DAMAGE_CLASSES)
        neighbor_selected_share = class_counts[record["predicted_class"]] / local_n if local_n else None
        geometry = geometry_rows[building_id]
        local = {
            "coordinate_space": coordinate_space, "centroid": [round(x, 4) for x in geometry["centroid"]],
            "centroid_unit": "degrees_lon_lat" if coordinate_space == "geographic_lon_lat" else "scene_pixels",
            "distance_unit": "meters" if coordinate_space == "geographic_lon_lat" else "scene_pixels",
            "footprint_area": round(geometry["area"], 4),
            "footprint_area_unit": "degrees_squared" if coordinate_space == "geographic_lon_lat" else "pixel_squared",
            "footprint_area_rank": area_rank, "footprint_area_percentile": _percentage(area_rank - 1, max(1, len(areas) - 1)),
            "relative_position": [round((geometry["centroid"][0] - bounds[0]) / width, 4) if width else 0.5,
                                  round((geometry["centroid"][1] - bounds[1]) / height, 4) if height else 0.5],
            "nearest_neighbor_distance": round(distances[0][0], 4) if distances else None,
            "neighbors": [{"building_id": nid, "distance": round(distance, 4)} for distance, nid in neighbors],
            "neighborhood_count": local_n, "neighbor_class_counts": {c: class_counts[c] for c in DAMAGE_CLASSES},
            "neighbor_severe_share": round(severe_n / local_n, 4) if local_n else None,
            "neighbor_mean_confidence": round(sum(total_confidences) / len(total_confidences), 4) if total_confidences else None,
            "neighbor_max_confidence": round(max(total_confidences), 4) if total_confidences else None,
            "neighbor_median_top_two_gap": _quantile(gaps, .5), "selected_class_neighbor_share": neighbor_selected_share,
            "neighbor_plurality_class": top_class,
        }
        if local_n:
            local["local_class_disagreement"] = top_class != record["predicted_class"]
            local["opposing_severity_majority"] = (
                "low_damage_majority" if record["predicted_class"] in SEVERE_CLASSES and low_n > local_n / 2
                else "severe_majority" if record["predicted_class"] in LOW_DAMAGE_CLASSES and severe_n > local_n / 2
                else None
            )
            local["local_agreement_count"] = class_counts[record["predicted_class"]]
        else:
            local["local_class_disagreement"], local["opposing_severity_majority"], local["local_agreement_count"] = False, None, 0
        spatial[building_id] = local
    scale = _quantile(nearest_distances, .5) or 0
    radius = scale * SEVERE_PROXIMITY_SCALE_FACTOR
    severe_ids = [i for i in ids if records_by_id[i]["predicted_class"] in SEVERE_CLASSES]
    adjacency = {i: set() for i in severe_ids}
    for index, left in enumerate(severe_ids):
        for right in severe_ids[index + 1:]:
            if _distance(geometry_rows[left]["centroid"], geometry_rows[right]["centroid"], coordinate_space) <= radius:
                adjacency[left].add(right)
                adjacency[right].add(left)
    components, seen = [], set()
    for building_id in severe_ids:
        if building_id in seen:
            continue
        stack, component = [building_id], []
        seen.add(building_id)
        while stack:
            item = stack.pop()
            component.append(item)
            for neighbor in sorted(adjacency[item], reverse=True):
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        if len(component) > 1:
            components.append(sorted(component))
    group_rows = []
    for component in sorted(components, key=lambda x: (x[0], len(x))):
        component_bounds = [min(geometry_rows[i]["bounds"][0] for i in component), min(geometry_rows[i]["bounds"][1] for i in component),
                            max(geometry_rows[i]["bounds"][2] for i in component), max(geometry_rows[i]["bounds"][3] for i in component)]
        counts = Counter(records_by_id[i]["predicted_class"] for i in component)
        group_probabilities = [records_by_id[i]["probability_ranking"]["top_probability"] for i in component
                               if records_by_id[i].get("probability_ranking")]
        mean_probability = sum(group_probabilities) / len(group_probabilities) if group_probabilities else None
        context_counts = Counter(contexts[i]["primary_category"] for i in component if i in contexts)
        group_rows.append({"group_id": _stable_id("severe", scene.get("scene_id", "unknown"), component),
                           "building_ids": component, "size": len(component), "major_count": counts["major-damage"],
                           "destroyed_count": counts["destroyed"], "mean_top_class_probability": round(mean_probability, 4) if mean_probability is not None else None,
                           "centroid": [round(sum(geometry_rows[i]["centroid"][axis] for i in component) / len(component), 4) for axis in (0, 1)],
                           "bounds": [round(v, 4) for v in component_bounds], "context_building_count": sum(i in contexts for i in component),
                           "context_category_counts": dict(sorted(context_counts.items())), "provenance": ["MODEL_DERIVED", "SPATIAL_DERIVED"]})
    grouped = {i for group in group_rows for i in group["building_ids"]}
    disagreements = sum(row["local_class_disagreement"] for row in spatial.values())
    contrasts = sum(bool(row["opposing_severity_majority"]) for row in spatial.values())
    disagreement_ids = sorted(i for i, row in spatial.items() if row["local_class_disagreement"])
    contrast_ids = sorted(i for i, row in spatial.items() if row["opposing_severity_majority"])
    summary = {"usable_geometry_buildings": len(ids), "pre_geometry_buildings": pre_geometry_building_count,
               "post_geometry_buildings": len(ids), "coordinate_space": coordinate_space,
               "distance_unit": "meters" if coordinate_space == "geographic_lon_lat" else "scene_pixels",
               "scene_bounds_basis": "minimum bounding rectangle of usable building footprints",
               "relative_position_basis": "normalized within analyzed-footprint bounds; not a geographic direction",
               "scene_bounds": [round(v, 4) for v in bounds], "footprint_area_unit": "degrees_squared" if coordinate_space == "geographic_lon_lat" else "pixel_squared",
               "neighborhood_method": {"name": "k_nearest_centroids", "k": NEIGHBOR_COUNT, "actual_neighbors": "up to k, excluding selected building", "distance_metric": "haversine on lon/lat centroids" if coordinate_space == "geographic_lon_lat" else "Euclidean in scene pixels"},
               "severe_group_method": {"name": "connected components of severe predictions", "edge_rule": "centroid distance <= 1.5 x scene median nearest-neighbor centroid distance",
                                       "scale_factor": SEVERE_PROXIMITY_SCALE_FACTOR, "scene_median_nearest_neighbor_distance": round(scale, 4),
                                       "edge_radius": round(radius, 4), "distance_unit": "meters" if coordinate_space == "geographic_lon_lat" else "scene_pixels",
                                       "interpretation": "descriptive proximity groups, not statistical clusters"},
               "severe_proximity_groups": group_rows, "severe_group_count": len(group_rows),
               "largest_severe_group_size": max((group["size"] for group in group_rows), default=0),
               "severe_buildings_in_groups": len(grouped), "isolated_severe_predictions": len(severe_ids) - len(grouped),
               "local_disagreement_count": disagreements, "local_severity_contrast_count": contrasts,
               "local_disagreement_building_ids": disagreement_ids, "local_severity_contrast_building_ids": contrast_ids,
               "per_building": spatial}
    return summary, spatial


def _candidate(record: dict, kind: str, reason: dict, building_ids: list[str], *, spatial: dict | None = None,
               group_id: str | None = None, site_group_id: str | None = None, context: dict | None = None) -> dict:
    return {"type": kind, "reason": reason, "supporting_numbers": {"predicted_class": record["predicted_class"],
            "probabilities": record["probabilities"], "top_two": record["probability_ranking"]},
            "building_ids": sorted(building_ids), "group_id": group_id, "site_group_id": site_group_id,
            "reviewed_context": _context_facts(context), "spatial_context": spatial,
            "evidence_provenance": ["MODEL_DERIVED"] + (["SPATIAL_DERIVED"] if spatial else []) + (["REVIEWED_GIS"] if context else [])}


def build_scene_evidence(scene: dict, contexts_by_uid: object = None) -> SceneEvidence:
    """Build the shared deterministic model, spatial, event and reviewed GIS facts."""
    buildings = scene.get("buildings") if isinstance(scene.get("buildings"), list) else []
    metadata = build_scene_metadata(scene)
    records = [record for item in buildings if (record := _prediction_record(item))]
    records_by_id = {row["building_id"]: row for row in records}
    total = len(buildings)
    counts = Counter(row["predicted_class"] for row in records)
    severe_count = sum(counts[c] for c in SEVERE_CLASSES)
    model_summary = {"total_buildings": total, "classified_buildings": len(records), "unclassified_buildings": max(0, total - len(records)),
                     "class_counts": {c: counts[c] for c in DAMAGE_CLASSES},
                     "class_percentages": {c: _percentage(counts[c], total) for c in DAMAGE_CLASSES},
                     "severe_count": severe_count, "severe_percentage": _percentage(severe_count, total),
                     "percentage_denominator": "all packaged buildings"}
    ranked = [r for r in records if r["probability_ranking"]]
    gaps = [r["probability_ranking"]["top_two_gap"] for r in ranked]
    top_probs = [r["probability_ranking"]["top_probability"] for r in ranked]
    pair_counts = Counter((r["probability_ranking"]["most_likely_class"], r["probability_ranking"]["second_most_likely_class"]) for r in ranked)
    by_predicted_class = {}
    for class_name in DAMAGE_CLASSES:
        class_rows = [r for r in ranked if r["predicted_class"] == class_name]
        by_predicted_class[class_name] = {"building_count": len(class_rows), "top_two_gap": _distribution([r["probability_ranking"]["top_two_gap"] for r in class_rows]),
                                          "top_probability": _distribution([r["probability_ranking"]["top_probability"] for r in class_rows]),
                                          "model_confidence": _distribution([r["confidence"] for r in class_rows if r["confidence"] is not None])}
    uncertainty_ranked = sorted(ranked, key=lambda r: (r["probability_ranking"]["top_two_gap"], r["building_id"]))
    decisive_ranked = sorted(ranked, key=lambda r: (-r["probability_ranking"]["top_probability"], r["building_id"]))
    decisive_ranks = {r["building_id"]: i + 1 for i, r in enumerate(decisive_ranked)}
    uncertainty_summary = {"ranked_building_count": len(ranked), "top_two_gap": _distribution(gaps),
                           "top_class_probability": _distribution(top_probs),
                           "model_confidence": _distribution([r["confidence"] for r in ranked if r["confidence"] is not None]),
                           "per_class_probability": {c: _distribution([r["probabilities"][c] for r in ranked]) for c in DAMAGE_CLASSES},
                           "by_predicted_class": by_predicted_class,
                           "building_rankings": {r["building_id"]: {"uncertainty_rank": i + 1, "decisiveness_rank": decisive_ranks[r["building_id"]],
                                "predicted_class": r["predicted_class"], "confidence": r["confidence"], "probabilities": r["probabilities"],
                                **r["probability_ranking"]} for i, r in enumerate(uncertainty_ranked)},
                           "top_competing_class_pairs": [{"first_class": a, "second_class": b, "count": n}
                                                          for (a, b), n in sorted(pair_counts.items(), key=lambda x: (-x[1], x[0]) )[:8]],
                           "smallest_gap_buildings": [{"building_id": r["building_id"], **r["probability_ranking"]} for r in uncertainty_ranked[:5]],
                           "largest_top_probability_buildings": [{"building_id": r["building_id"], **r["probability_ranking"]} for r in decisive_ranked[:5]],
                           "ranking_rule": "ordinal only; no universal uncertainty threshold"}
    contexts = _reviewed_context_by_building(scene, contexts_by_uid)
    sites = _site_groups(metadata["scene_id"] or "unknown", buildings, contexts, records_by_id)
    gis_summary = _context_summary(buildings, contexts, records_by_id)
    spatial_summary, spatial_by_id = _spatial_analysis(scene, buildings, records_by_id, contexts)
    candidate_findings: dict[str, dict] = {}
    candidate_order: list[str] = []

    def add(key: str, record: dict, kind: str, reason: dict, ids: list[str] | None = None,
            spatial: dict | None = None, group_id: str | None = None, site_group_id: str | None = None) -> None:
        if key in candidate_findings or len(candidate_findings) >= MAX_SCENE_CANDIDATES:
            return
        building_id = record["building_id"]
        candidate_findings[key] = _candidate(record, kind, reason, ids or [building_id], spatial=spatial,
                                                group_id=group_id, site_group_id=site_group_id, context=contexts.get(building_id))
        candidate_order.append(key)

    for index, record in enumerate(uncertainty_ranked[:2], 1):
        pair = record["probability_ranking"]
        add(f"ambiguous_{index}", record, "AMBIGUOUS_CLASS_PAIR", {"rank": index, "top_two_gap": pair["top_two_gap"], "competing_classes": [pair["most_likely_class"], pair["second_most_likely_class"]]})
    severe = [r for r in decisive_ranked if r["predicted_class"] in SEVERE_CLASSES]
    low = [r for r in decisive_ranked if r["predicted_class"] in LOW_DAMAGE_CLASSES]
    if severe:
        add("representative_severe", severe[0], "REPRESENTATIVE_SEVERE", {"decisiveness_rank": decisive_ranks[severe[0]["building_id"]]})
        add("high_confidence_severe", severe[0], "HIGH_CONFIDENCE_SEVERE", {"top_probability": severe[0]["probability_ranking"]["top_probability"]})
    if low:
        add("representative_low_damage", low[0], "REPRESENTATIVE_LOW_DAMAGE", {"decisiveness_rank": decisive_ranks[low[0]["building_id"]]})
    outlier_rows = []
    for building_id, local in spatial_by_id.items():
        reason = local["opposing_severity_majority"]
        if reason:
            outlier_rows.append((-(local["neighbor_severe_share"] if reason == "severe_majority" else 1-local["neighbor_severe_share"]), building_id, reason, local))
    for index, (_, building_id, reason, local) in enumerate(sorted(outlier_rows)[:4], 1):
        record = records_by_id[building_id]
        kind = "LOCAL_SEVERITY_OUTLIER" if record["predicted_class"] in SEVERE_CLASSES else "LOCAL_LOW_DAMAGE_OUTLIER"
        add(f"local_contrast_{index}", record, kind, {"rule": "strict majority of k-nearest predictions has opposing severity family", "neighbor_count": local["neighborhood_count"],
            "neighbor_classes": local["neighbor_class_counts"], "local_agreement_count": local["local_agreement_count"], "opposing_family": reason}, spatial=local)
    disagreement_candidates = sorted(
        ((local["selected_class_neighbor_share"], building_id, local)
         for building_id, local in spatial_by_id.items() if local["local_class_disagreement"]),
        key=lambda row: (row[0], row[1]),
    )
    if disagreement_candidates:
        share, building_id, local = disagreement_candidates[0]
        record = records_by_id[building_id]
        add("local_class_disagreement", record, "LOCAL_CLASS_DISAGREEMENT", {
            "rule": "selected class differs from deterministic plurality among k nearest neighbors",
            "selected_class": record["predicted_class"], "neighbor_plurality_class": local["neighbor_plurality_class"],
            "neighbor_count": local["neighborhood_count"], "neighbor_classes": local["neighbor_class_counts"],
            "selected_class_neighbor_share": share, "local_agreement_count": local["local_agreement_count"]}, spatial=local)
    for group in spatial_summary["severe_proximity_groups"][:2]:
        record = records_by_id[group["building_ids"][0]]
        add("severe_group_" + group["group_id"].split("_")[-1], record, "SEVERE_PROXIMITY_GROUP", {"size": group["size"], "major_count": group["major_count"], "destroyed_count": group["destroyed_count"], "method": spatial_summary["severe_group_method"]},
            group["building_ids"], group_id=group["group_id"])
    rich = sorted((( -(len(_context_facts(c)["claims"])), -(len(_context_facts(c)["scopes"])), bid) for bid,c in contexts.items() if bid in records_by_id and records_by_id[bid]["predicted_class"] in SEVERE_CLASSES))
    for index, (_, _, building_id) in enumerate(rich[:2], 1):
        add(f"context_rich_severe_{index}", records_by_id[building_id], "CONTEXT_RICH_SEVERE", {"reviewed_context_claim_count": _context_facts(contexts[building_id])["claim_count"], "scopes": _context_facts(contexts[building_id])["scopes"]}, spatial=spatial_by_id.get(building_id))
    conflict_ids = sorted(bid for bid, ctx in contexts.items() if bid in records_by_id and ctx["conflicts"])
    if conflict_ids:
        bid = conflict_ids[0]
        add("gis_scope_conflict", records_by_id[bid], "GIS_SCOPE_CONFLICT", {"conflict_count": len(contexts[bid]["conflicts"]), "conflicts": _context_facts(contexts[bid])["conflicts"]}, spatial=spatial_by_id.get(bid))
    for index, site in enumerate(sites[:3], 1):
        record = records_by_id[site["building_ids"][0]]
        add(f"multi_building_site_{index}", record, "MULTI_BUILDING_SITE", {"name": site["name"], "building_count": site["building_count"], "prediction_counts": site["prediction_counts"], "scope": "site"},
            site["building_ids"], site_group_id=site["site_group_id"])
    provenance = {"MODEL_DERIVED": {"source": "scene.json buildings[].prediction", "ground_truth_excluded": True},
                  "SPATIAL_DERIVED": {"source": "scene.json buildings[].post_pixel_polygon or explicit geographic_polygon", "coordinate_space": spatial_summary["coordinate_space"], "distance_unit": spatial_summary["distance_unit"]},
                  "SOURCE_METADATA": {"source": "scene manifest and curated local scene metadata", "scene_metadata_fields": ["event_name", "hazard_type", "location", "pre_acquisition_date", "post_acquisition_date"]},
                  "REVIEWED_GIS": {"source": "validated packaged demo overlays", "ground_truth_excluded": True},
                  "DEMO_REFERENCE_ONLY": {"source": "scene.json buildings[].demo_metadata.ground_truth", "included_in_ai_evidence": False},
                  "IMAGE_DERIVED": {"source": "packaged PRE/POST images and paired crops", "status": "deferred",
                                     "included_in_ai_evidence": False,
                                     "reason": "paired images lack validated registration and illumination controls"}}
    return {"schema_version": SCENE_EVIDENCE_SCHEMA_VERSION, "event": metadata, "model_summary": model_summary,
            "uncertainty_summary": uncertainty_summary, "spatial_summary": spatial_summary, "gis_summary": gis_summary,
            "site_groups": sites, "candidate_order": candidate_order, "candidate_findings": candidate_findings,
            "provenance": provenance}


def building_scene_context(scene_evidence: SceneEvidence, building_id: str | None) -> dict:
    """Return only shared scene context relevant to one selected building."""
    uncertainty = scene_evidence["uncertainty_summary"]
    record = uncertainty["building_rankings"].get(building_id or "")
    spatial = scene_evidence["spatial_summary"]["per_building"].get(building_id or "")
    groups = [group for group in scene_evidence["spatial_summary"]["severe_proximity_groups"] if building_id in group["building_ids"]]
    sites = [site for site in scene_evidence["site_groups"] if building_id in site["building_ids"]]
    return {"event": scene_evidence["event"], "model_summary": scene_evidence["model_summary"],
            "uncertainty_summary": {"scene_top_two_gap": uncertainty["top_two_gap"], "common_competing_class_pairs": uncertainty["top_competing_class_pairs"][:4],
                                    "selected_building_rankings": record},
            "spatial_context": spatial, "severe_proximity_groups": groups, "site_groups": sites,
            "gis_summary": scene_evidence["gis_summary"],
            "evidence_provenance": ["MODEL_DERIVED", "SOURCE_METADATA"] + (["SPATIAL_DERIVED"] if spatial else []) + (["REVIEWED_GIS"] if sites or scene_evidence["gis_summary"]["buildings_with_reviewed_context"] else [])}


def scene_evidence_for_prompt(scene_evidence: SceneEvidence) -> dict:
    """Create a compact LLM packet; full per-building facts remain preview-only."""
    spatial = {key: value for key, value in scene_evidence["spatial_summary"].items() if key != "per_building"}
    uncertainty = {key: value for key, value in scene_evidence["uncertainty_summary"].items() if key != "building_rankings"}
    return {"schema_version": scene_evidence["schema_version"], "event": scene_evidence["event"],
            "model_summary": scene_evidence["model_summary"], "uncertainty_summary": uncertainty,
            "spatial_summary": spatial, "gis_summary": scene_evidence["gis_summary"],
            "site_groups": scene_evidence["site_groups"], "candidate_findings": scene_evidence["candidate_findings"],
            "provenance": scene_evidence["provenance"]}
