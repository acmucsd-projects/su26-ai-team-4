"""Offline scene audit orchestration, with explicit unevaluated results."""

from dataclasses import asdict
from itertools import combinations
import json
from pathlib import Path

from shapely.errors import GEOSException
from shapely.geometry import mapping

from .cache import CachedClient
from .geometry import SCENE_ID, load_scene
from .matching import footprint_matches, nsi_matches, parcel_matches, poi_matches, site_matches
from .normalize import compare_claims, hcad_claims, nsi_claims, osm_claims
from .providers import fetch_hcad, fetch_nsi, fetch_osm, geojson_features, osm_features
from .local_providers import LOCAL, fetch_local, local_features, local_claims
from .scenes import SCENE_COUNTS, SCENE_PROVIDERS, LOCAL_PARCELS


PROVIDERS = ("hcad", "nsi", "osm_historical", "osm_current")
FLAGS = (
    "hcad_parcel_match", "hcad_useful_context", "hcad_single_structure", "hcad_multi_structure",
    "hcad_structure_count_unknown", "nsi_candidate", "nsi_accepted", "nsi_normalized_occupancy",
    "historical_osm_useful_context", "current_osm_useful_context", "mapped_name_place",
    "site_context", "critical_facility", "conflicting_claims", "ambiguous_rejected_candidates",
    "combined_displayable_context", "event_aligned_useful_context", "broad_use_coverage",
    "historical_current_conflicts", "no_context",
    "landuse_area_context", "context_excluding_landuse_areas", "direct_building_place_context",
    "hcad_parcel_ambiguity", "ambiguous_candidates", "site_context_excluding_landuse",
    "direct_mapped_name", "broad_use_excluding_landuse_areas", "event_aligned_direct_context",
    "local_parcel_match", "local_useful_context", "local_single_structure", "local_multi_structure",
    "local_structure_count_unknown", "local_parcel_ambiguity", "local_promoted_structure_context",
    "parcel_only_context", "neighborhood_only_context", "school_site_context", "facility_context",
    "pre_event_aligned_useful_context", "event_or_pre_event_context", "unverified_historical_reference_context",
)


def aggregate(rows: list[dict]) -> dict:
    metrics = {}
    for key in FLAGS:
        if not any(key in row["flags"] for row in rows):
            continue
        values = [row["flags"][key] for row in rows]
        known = [value for value in values if value is not None]
        count = sum(value is True for value in known) if known else None
        percent = round(100 * count / len(rows), 2) if len(known) == len(rows) else None
        metrics[key] = {"count": count, "percent_of_scene": percent,
                        "evaluated_buildings": len(known), "unknown_buildings": len(rows) - len(known),
                        "count_is_lower_bound": len(known) < len(rows) and count is not None}
        if len(rows) == 76:
            metrics[key]["percent_of_76"] = percent  # Legacy Harvey reports.
    return metrics


def empty_report(manifest: dict, reason: str) -> dict:
    rows = [{"building_id": b["id"], "uid": b["uid"], "evaluation_status": "not_evaluated",
             "geometry": None, "claims": [], "candidates": [], "conflicts": [],
             "nsi_occupancies": [], "flags": {key: None for key in FLAGS},
             "displayable_context": None, "qa_reasons": [], "qa_status": "not_evaluated"}
            for b in manifest["buildings"]]
    scene_id = manifest.get("scene_id", SCENE_ID)
    providers = SCENE_PROVIDERS.get(scene_id, PROVIDERS)
    return {"report_schema_version": 2, "scene_id": scene_id, "building_count": len(rows),
            "status": "blocked_missing_raw_input", "blockers": [reason],
            "providers": {p: {"status": "not_queried", "reason": "raw_input_unavailable"} for p in providers},
            "buildings": rows, "metrics": aggregate(rows), "source_contribution": None,
            "qa": {"status": "not_performed", "reason": "No real matches exist to review", "selected_uids": []},
            "decision": "inconclusive; real scene input is required"}


def flag(value: bool, complete: bool):
    return True if value else False if complete else None


def build_row(building: dict, geometry: dict, claims, candidates: list[dict], statuses: dict) -> dict:
    providers = tuple(statuses)
    complete = all(statuses[p]["status"] == "complete" for p in providers)
    event_complete = all(statuses[p]["status"] == "complete" for p in ("hcad", "osm_historical") if p in statuses)
    useful = [claim for claim in claims if claim.displayable]
    conflicts = compare_claims(useful)
    by_provider = {p: [c for c in useful if (c.source.dataset == p if p.startswith("osm_") else c.source.provider == p)] for p in providers}
    matches = {p: [c for c in candidates if c["provider"] == p] for p in providers}
    local_provider = next(p for p in providers if p in LOCAL_PARCELS)
    local_accepted = [c for c in matches[local_provider] if c["accepted"]]
    local_ready = statuses[local_provider]["status"] == "complete"
    hcad_accepted = [c for c in matches.get("hcad", []) if c["accepted"]]
    hc = statuses.get("hcad", {}).get("status") == "complete"
    ns = statuses["nsi"]["status"] == "complete"
    flags = {
        "hcad_parcel_match": flag(bool(hcad_accepted), hc),
        "hcad_useful_context": flag(any(c.category != "unknown" for c in by_provider.get("hcad", [])), hc),
        "hcad_single_structure": flag(any(c["evidence"].get("structure_association") == "single_structure_supported" for c in hcad_accepted), hc),
        "hcad_multi_structure": flag(any(c["evidence"].get("structure_association") == "multi_structure" for c in hcad_accepted), hc),
        "hcad_structure_count_unknown": flag(any(c["evidence"].get("structure_association") == "structure_count_unknown" for c in hcad_accepted), hc),
        "nsi_candidate": flag(bool(matches["nsi"]), ns),
        "nsi_accepted": flag(any(c["accepted"] for c in matches["nsi"]), ns),
        "nsi_normalized_occupancy": flag(bool(by_provider["nsi"]), ns),
        "historical_osm_useful_context": flag(bool(by_provider["osm_historical"]), statuses["osm_historical"]["status"] == "complete"),
        "current_osm_useful_context": flag(bool(by_provider["osm_current"]), statuses["osm_current"]["status"] == "complete"),
        "mapped_name_place": flag(any(c.mapped_name for c in useful), complete),
        "site_context": flag(any(c.scope == "site" for c in useful), complete),
        "critical_facility": flag(any(c.critical_facility for c in useful), complete),
        "conflicting_claims": flag(bool(conflicts), complete),
        "ambiguous_rejected_candidates": flag(any(not c["accepted"] for c in candidates), complete),
        "combined_displayable_context": flag(bool(useful), complete),
        "event_aligned_useful_context": flag(any(c.source.temporal_status in {"event_year", "event_snapshot"} for c in useful), event_complete),
        "broad_use_coverage": flag(any(c.category != "unknown" for c in useful), complete),
        "historical_current_conflicts": flag(any(c["reason"] == "historical_current_difference" for c in conflicts),
                                            all(statuses[p]["status"] == "complete" for p in ("osm_historical", "osm_current"))),
        "no_context": False if useful else True if complete else None,
        "landuse_area_context": flag(any(c.kind == "area_use" for c in useful), complete),
        "context_excluding_landuse_areas": flag(any(c.kind != "area_use" for c in useful), complete),
        "direct_building_place_context": flag(any(c.scope in {"building", "place"} for c in useful), complete),
        "hcad_parcel_ambiguity": flag(any(c["ambiguous"] for c in matches.get("hcad", [])), hc),
        "ambiguous_candidates": flag(any(c["ambiguous"] for c in candidates), complete),
        "site_context_excluding_landuse": flag(any(c.scope == "site" and c.kind != "area_use" for c in useful), complete),
        "direct_mapped_name": flag(any(c.mapped_name and c.scope in {"building", "place"} for c in useful), complete),
        "broad_use_excluding_landuse_areas": flag(any(c.kind != "area_use" and c.category != "unknown" for c in useful), complete),
        "event_aligned_direct_context": flag(any(c.source.temporal_status in {"event_year", "event_snapshot"} and c.scope in {"building", "place"} for c in useful), event_complete),
        "local_parcel_match": flag(bool(local_accepted), local_ready),
        "local_useful_context": flag(any(c.category != "unknown" for c in by_provider[local_provider]), local_ready),
        "local_single_structure": flag(any(c["evidence"].get("structure_association") == "single_structure_supported" for c in local_accepted), local_ready),
        "local_multi_structure": flag(any(c["evidence"].get("structure_association") == "multi_structure" for c in local_accepted), local_ready),
        "local_structure_count_unknown": flag(any(c["evidence"].get("structure_association") == "structure_count_unknown" for c in local_accepted), local_ready),
        "local_parcel_ambiguity": flag(any(c["ambiguous"] for c in matches[local_provider]), local_ready),
        "local_promoted_structure_context": flag(any(c.scope == "building" for c in by_provider[local_provider]), local_ready),
        "parcel_only_context": flag(any(c.scope == "parcel" for c in useful) and all(c.scope == "parcel" or c.kind == "area_use" for c in useful), complete),
        "neighborhood_only_context": flag(bool(useful) and all(c.kind == "area_use" for c in useful), complete),
        "school_site_context": flag(any(c.scope == "site" and c.category == "education" for c in useful), complete),
        "facility_context": flag(any(not c.source.modeled and c.kind != "area_use" and c.category in {"education", "medical", "emergency_services", "government_civic", "religious", "recreation_community"} for c in useful), complete),
        "pre_event_aligned_useful_context": flag(any(c.source.temporal_status == "pre_event_historical" for c in useful), complete),
        "event_or_pre_event_context": flag(any(c.source.temporal_status in {"event_year", "event_snapshot", "pre_event_historical"} for c in useful), complete),
        "unverified_historical_reference_context": flag(any(c.source.temporal_status == "pre_event_reference_vintage_unverified" for c in useful), complete),
    }
    if "hcad" not in providers:
        flags = {k: v for k, v in flags.items() if not k.startswith("hcad_")}
    return {"building_id": building["id"], "uid": building["uid"], "geometry": geometry,
            "evaluation_status": "evaluated" if complete else "partially_evaluated",
            "claims": [c.to_dict() for c in claims], "candidates": candidates, "conflicts": conflicts,
            "nsi_occupancies": sorted({c.raw_value["occtype"] for c in by_provider["nsi"]}),
            "flags": flags, "displayable_context": [c.label for c in useful],
            "qa_reasons": [], "qa_status": "not_selected"}


def select_qa(rows: list[dict]) -> dict:
    mandatory = {"mapped_name_place": "named_place", "critical_facility": "critical_facility", "conflicting_claims": "provider_conflict", "site_context": "site_or_area_context"}
    for row in rows:
        row["qa_reasons"] = [reason for key, reason in mandatory.items() if row["flags"][key]]
    # First cover distinct provider/category/scope/time signatures, then fill.
    representatives, signatures = [], set()
    displayable = [r for r in rows if r["flags"]["combined_displayable_context"]]
    for row in displayable:
        keys = {(c["source"]["provider"], c["category"], c["scope"], c["source"]["temporal_status"]) for c in row["claims"]}
        if keys - signatures and len(representatives) < 20:
            representatives.append(row)
            signatures.update(keys)
    for row in displayable:
        if len(representatives) < 20 and row not in representatives:
            representatives.append(row)
    for row in representatives:
        row["qa_reasons"].append("representative_context")
    for row in [r for r in rows if r["flags"]["ambiguous_rejected_candidates"]][:10]:
        row["qa_reasons"].append("ambiguous_rejected_sample")
    for row in rows:
        if row["qa_reasons"]:
            row["qa_status"] = "pending_review"
    return {"status": "pending_review", "selected_uids": [r["uid"] for r in rows if r["qa_reasons"]],
            "note": "Selection is not a claim that manual review has been completed."}


def source_coverage(rows: list[dict], statuses: dict) -> tuple[dict, dict | None]:
    """Count unique displayable semantics, including after manual claim holds."""
    providers = tuple(statuses)
    sets = {p: set() for p in providers}
    for row in rows:
        for claim in row["claims"]:
            if claim["displayable"]:
                source = claim["source"]
                provider = source["dataset"] if source["provider"] == "osm" else source["provider"]
                sets[provider].add(row["uid"])
    complete = all(statuses[p]["status"] == "complete" for p in providers)
    contributions = {}
    for provider, uids in sets.items():
        others = set().union(*(sets[p] for p in providers if p != provider))
        ready = statuses[provider]["status"] == "complete"
        contributions[provider] = {"displayable_buildings": len(uids) if ready or uids else None,
                                   "percent": round(len(uids) / len(rows) * 100, 2) if ready else None,
                                   "unique_additional_buildings": len(uids - others) if complete else None}
    if not complete:
        return contributions, None
    seen, incremental = set(), {}
    for provider in providers:
        added = len(sets[provider] - seen)
        incremental[provider] = {"count": added, "percent_of_scene": round(100 * added / len(rows), 2)}
        seen.update(sets[provider])
    overlap = {"incremental_order": list(providers), "incremental": incremental,
               "pairwise": {a + "+" + b: {"count": len(sets[a] & sets[b]),
                            "percent_of_scene": round(100 * len(sets[a] & sets[b]) / len(rows), 2)}
                            for a, b in combinations(providers, 2)}}
    return contributions, overlap


def run_audit(manifest_path: Path, label_path: Path, cache_root: Path, snapshot: str, fetch: bool = False) -> dict:
    manifest = json.loads(manifest_path.read_bytes())
    scene_id = manifest.get("scene_id")
    if scene_id not in SCENE_COUNTS or len(manifest.get("buildings", [])) != SCENE_COUNTS[scene_id]:
        raise ValueError("Expected an authorized scene and canonical building count.")
    providers = SCENE_PROVIDERS[scene_id]
    try:
        scene = load_scene(manifest_path, label_path)
    except (OSError, ValueError, KeyError, TypeError, GEOSException) as error:
        report = empty_report(manifest, str(error))
        report["required_input"] = {"path": str(label_path), "fields": ["metadata.capture_date", "features.lng_lat[].properties.uid", "features.lng_lat[].wkt"]}
        return report
    client = CachedClient(cache_root, network=fetch)
    statuses, all_matches, all_features = {}, {}, {}
    for provider in providers:
        try:
            if provider == "hcad":
                payload, source = fetch_hcad(client, scene.query_bbox, snapshot)
            elif provider in LOCAL:
                payload, source = fetch_local(client, provider, scene.query_bbox, snapshot)
            elif provider == "nsi":
                payload, source = fetch_nsi(client, scene.query_bbox, snapshot)
            else:
                historical = provider == "osm_historical"
                payload, source = fetch_osm(client, scene.query_bbox, scene.acquisition_time if historical else snapshot, historical)
            if provider in LOCAL:
                features, issues = local_features(payload, source, scene.projection)
                matches = (site_matches if provider == "sonoma_schools" else parcel_matches)(scene.metric, features)
            elif provider in {"hcad", "nsi"}:
                features, issues = geojson_features(payload, source, scene.projection)
                matches = (parcel_matches if provider == "hcad" else nsi_matches)(scene.metric, features)
            else:
                layers, issues = osm_features(payload, source, scene.projection)
                features = sum(layers.values(), [])
                parts = [matcher(scene.metric, layers[layer]) for layer, matcher in (
                    ("footprint", footprint_matches), ("place", poi_matches), ("site", site_matches))]
                matches = {uid: sum((part[uid] for part in parts), []) for uid in scene.metric}
            statuses[provider] = {"status": "partial" if issues else "complete", "records": len(features),
                                  "parse_issues": issues, "source": asdict(source)}
            all_matches[provider], all_features[provider] = matches, {f.record_id: f for f in features}
        except (OSError, ValueError, KeyError, TypeError, GEOSException) as error:
            statuses[provider] = {"status": "unavailable", "reason": str(error)}
            all_matches[provider], all_features[provider] = {}, {}
    rows = []
    for building in manifest["buildings"]:
        uid, claims, candidates = building["uid"], [], []
        for provider in providers:
            for match in all_matches[provider].get(uid, []):
                feature = all_features[provider][match.record_id]
                candidate = {"provider": provider, **asdict(match), "source": asdict(feature.source),
                             "raw_source_values": feature.properties,
                             "geometry": mapping(scene.projection.unproject(feature.geometry))}
                candidates.append(candidate)
                normalizer = local_claims if provider in LOCAL else hcad_claims if provider == "hcad" else nsi_claims if provider == "nsi" else osm_claims
                claims.extend(normalizer(feature, match))
        rows.append(build_row(building, mapping(scene.geographic[uid]), claims, candidates, statuses))
    complete = all(status["status"] == "complete" for status in statuses.values())
    contributions, provider_overlap = source_coverage(rows, statuses)
    return {"report_schema_version": 2, "scene_id": scene_id, "building_count": len(rows),
            "status": "awaiting_manual_qa" if complete else "partial_provider_data",
            "blockers": [] if complete else [p + ": " + statuses[p]["status"] for p in providers if statuses[p]["status"] != "complete"],
            "post_acquisition_time": scene.acquisition_time, "metric_crs": f"EPSG:{scene.projection.epsg}",
            "query_bbox_wgs84": scene.query_bbox, "query_extent_basis": "all raw POST lng_lat footprint bounds + 50 m; not image georeferencing",
            "input_sha256": {"scene_manifest": scene.manifest_sha256, "raw_post_label": scene.label_sha256},
            "providers": statuses, "cache_entries": client.used, "buildings": rows, "metrics": aggregate(rows),
            "source_contribution": contributions, "provider_overlap": provider_overlap, "qa": select_qa(rows),
            "decision": "pending real-data manual QA; do not infer feasibility from footprint coverage"}
