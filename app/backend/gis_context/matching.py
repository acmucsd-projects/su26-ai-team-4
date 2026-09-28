"""Conservative, independent matchers. All inputs use one local metric CRS."""

from collections import defaultdict

from shapely.geometry.base import BaseGeometry

from .geometry import overlap
from .models import Feature, Match


def footprint_matches(buildings: dict[str, BaseGeometry], features: list[Feature]) -> dict[str, list[Match]]:
    results = {uid: [] for uid in buildings}
    owners = defaultdict(list)
    for uid, building in buildings.items():
        candidates = []
        for feature in features:
            if building.distance(feature.geometry) > 15:
                continue
            evidence = overlap(building, feature.geometry)
            coverage, iou, distance = (evidence[k] for k in ("xbd_coverage", "iou", "centroid_distance_m"))
            confidence = "strong" if coverage >= .65 and iou >= .40 and distance <= 8 else (
                "moderate" if coverage >= .45 and iou >= .25 and distance <= 12 else "rejected")
            evidence["candidate_score"] = (coverage + iou) / 2
            candidates.append(Match(feature.record_id, "footprint", False, confidence,
                                    "below_threshold", evidence))
        candidates.sort(key=lambda m: (-m.evidence["candidate_score"], m.record_id))
        if candidates:
            best = candidates[0]
            gap = best.evidence["candidate_score"] - candidates[1].evidence["candidate_score"] if len(candidates) > 1 else 1
            best.evidence["winner_margin"] = gap
            if best.spatial_confidence != "rejected":
                if gap < .10:
                    best.reason, best.ambiguous = "close_competing_footprints", True
                else:
                    best.accepted, best.reason = True, "unique_geometric_winner"
                    owners[best.record_id].append(best)
            for other in candidates[1:]:
                other.reason = "not_unique_winner"
            results[uid] = candidates
    for matches in owners.values():
        if len(matches) > 1:
            for match in matches:
                match.accepted, match.ambiguous, match.reason = False, True, "external_footprint_shared_by_xbd_buildings"
    return results


def point_relationships(point: BaseGeometry, buildings: dict[str, BaseGeometry], record_id: str,
                        relationship: str, allow_near: bool) -> dict[str, Match]:
    distances = sorted((g.distance(point), uid) for uid, g in buildings.items())
    containing = [uid for uid, g in buildings.items() if g.contains(point)]
    touching = [uid for uid, g in buildings.items() if g.covers(point)]
    results = {}
    for distance, uid in distances:
        if distance > 15:
            continue
        evidence = {"distance_m": distance, "containing_uids": containing, "covering_uids": touching}
        results[uid] = Match(record_id, relationship, False, "rejected", "outside_direct_association", evidence)
    if len(touching) > 1:
        for uid in touching:
            results[uid].ambiguous, results[uid].reason = True, "point_shared_by_multiple_buildings"
    elif len(containing) == 1 and len(touching) == 1:
        result = results[containing[0]]
        result.accepted, result.spatial_confidence, result.reason = True, "strong", "unique_point_containment"
    elif distances and distances[0][0] <= 5:
        distance, uid = distances[0]
        gap = distances[1][0] - distance if len(distances) > 1 else None
        result = results[uid]
        result.evidence["nearest_margin_m"] = gap
        if gap is not None and gap < 2:
            result.ambiguous, result.reason = True, "near_point_has_competing_building"
        elif allow_near:
            result.accepted, result.spatial_confidence, result.reason = True, "moderate", "unique_near_boundary"
        else:
            result.reason = "near_nsi_requires_independent_corroboration"
    return results


def poi_matches(buildings: dict[str, BaseGeometry], features: list[Feature]) -> dict[str, list[Match]]:
    results = {uid: [] for uid in buildings}
    for feature in features:
        for uid, match in point_relationships(feature.geometry, buildings, feature.record_id, "place", True).items():
            results[uid].append(match)
    return results


def nsi_matches(buildings: dict[str, BaseGeometry], features: list[Feature]) -> dict[str, list[Match]]:
    results = {uid: [] for uid in buildings}
    lookup = {f.record_id: f for f in features}
    for feature in features:
        # Near points remain rejected until an independent footprint link exists.
        for uid, match in point_relationships(feature.geometry, buildings, feature.record_id, "nsi_structure", False).items():
            results[uid].append(match)
    for matches in results.values():
        accepted = [m for m in matches if m.accepted]
        if len(accepted) <= 1:
            continue
        keys = {(lookup[m.record_id].properties.get("ftprntsrc"), lookup[m.record_id].properties.get("ftprntid")) for m in accepted}
        points = [lookup[m.record_id].geometry for m in accepted]
        same_location = all(p.distance(points[0]) <= .25 for p in points)
        shared_id = len(keys) == 1 and all(str(value or "").strip() not in {"", "0", "-1"} for value in next(iter(keys)))
        for match in accepted:
            if shared_id or same_location:
                match.evidence["stacked_record_ids"] = [m.record_id for m in accepted]
                match.evidence["stacked_basis"] = "shared_footprint_id" if shared_id else "coincident_points"
            else:
                match.accepted, match.ambiguous, match.reason = False, True, "multiple_unlinked_nsi_structures"
    footprint_owners = defaultdict(list)
    for uid, matches in results.items():
        for match in matches:
            record = lookup[match.record_id].properties
            key = (record.get("ftprntsrc"), record.get("ftprntid"))
            if match.accepted and all(str(value or "").strip() not in {"", "0", "-1"} for value in key):
                footprint_owners[key].append((uid, match))
    for owners in footprint_owners.values():
        if len({uid for uid, _ in owners}) > 1:
            for _, match in owners:
                match.accepted, match.ambiguous, match.reason = False, True, "nsi_footprint_shared_by_xbd_buildings"
    return results


def parcel_matches(buildings: dict[str, BaseGeometry], features: list[Feature]) -> dict[str, list[Match]]:
    results = {uid: [] for uid in buildings}
    parcel_members = defaultdict(list)
    for uid, building in buildings.items():
        plausible = []
        for feature in features:
            if not building.intersects(feature.geometry):
                continue
            evidence = overlap(building, feature.geometry)
            centroid_inside = feature.geometry.contains(building.centroid)
            evidence["centroid_inside"] = centroid_inside
            accepted = evidence["xbd_coverage"] >= .8 or (centroid_inside and evidence["xbd_coverage"] >= .5)
            match = Match(feature.record_id, "parcel", accepted, "strong" if accepted else "rejected",
                          "parcel_membership" if accepted else "insufficient_parcel_overlap", evidence)
            results[uid].append(match)
            # Count meaningful competitors even when membership itself is uncertain.
            if evidence["xbd_coverage"] >= .2:
                parcel_members[feature.record_id].append(uid)
            if accepted:
                plausible.append(match)
        if len(plausible) > 1:
            for match in plausible:
                match.accepted, match.ambiguous, match.reason = False, True, "multiple_plausible_parcels"
    lookup = {f.record_id: f for f in features}
    for matches in results.values():
        for match in matches:
            count = lookup[match.record_id].properties.get("BUILDCOUNT")
            try:
                provider_count = int(count) if float(count).is_integer() else None
            except (TypeError, ValueError):
                provider_count = None
            members = parcel_members[match.record_id]
            # One visible roof is insufficient if the parcel continues off-scene.
            status = "single_structure_supported" if len(members) == 1 and provider_count == 1 else (
                "multi_structure" if len(members) > 1 or (provider_count or 0) > 1 else "structure_count_unknown")
            match.evidence.update(parcel_xbd_uids=members, provider_buildcount=provider_count,
                                  structure_association=status,
                                  building_promotion_allowed=match.accepted and status == "single_structure_supported")
    return results


def site_matches(buildings: dict[str, BaseGeometry], features: list[Feature]) -> dict[str, list[Match]]:
    results = {uid: [] for uid in buildings}
    for uid, building in buildings.items():
        for feature in features:
            if not building.intersects(feature.geometry):
                continue
            evidence = overlap(building, feature.geometry)
            accepted = evidence["xbd_coverage"] >= .8 and feature.geometry.contains(building.centroid)
            results[uid].append(Match(feature.record_id, "site", accepted,
                                     "strong" if accepted else "rejected",
                                     "within_site" if accepted else "partial_site_overlap", evidence))
    return results
