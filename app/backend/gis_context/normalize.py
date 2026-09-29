"""Normalize source assertions without merging unlike scopes or time periods."""

from itertools import combinations
import re

from .models import Claim, Feature, Match


NSI_TYPES = {
    "RES2": ("residential", "Manufactured housing"),
    "RES4": ("lodging", "Hotel/motel"), "RES5": ("residential", "Dormitory"),
    "RES6": ("medical", "Nursing home"), "COM1": ("commercial_retail", "Retail"),
    "COM2": ("commercial_retail", "Wholesale"), "COM3": ("commercial_retail", "Personal/repair services"),
    "COM4": ("office_professional", "Professional services"), "COM5": ("office_professional", "Bank"),
    "COM6": ("medical", "Hospital"), "COM7": ("medical", "Medical office"),
    "COM8": ("recreation_community", "Entertainment/recreation"), "COM9": ("recreation_community", "Theater"),
    "COM10": ("transportation", "Garage"), "AGR1": ("agricultural", "Agricultural use"),
    "REL1": ("religious", "Religious use"), "GOV1": ("government_civic", "Government services"),
    "GOV2": ("emergency_services", "Emergency response"),
    "EDU1": ("education", "School"), "EDU2": ("education", "College/university"),
}


def nsi_occupancy(value: object) -> tuple[str, str]:
    code = str(value or "").upper().strip()
    if re.fullmatch(r"RES1(?:-(?:[123]S|SL)(?:NB|WB))?", code):
        return "residential", "Single-family residential"
    if re.fullmatch(r"RES3[A-F]?", code):
        return "multifamily", "Multifamily residential"
    if re.fullmatch(r"IND[1-6]", code):
        return "industrial", "Industrial use"
    return NSI_TYPES.get(code, ("unknown", "Unknown occupancy"))


def property_category(value: object) -> str:
    text = str(value or "").lower().replace("_", " ")
    vocabulary = [
        (r"\b(multi[ -]?family|apartments?)\b", "multifamily"),
        (r"\b(hotel|motel|lodging)\b", "lodging"),
        (r"\b(hospital|medical|clinic|nursing home)\b", "medical"),
        (r"\b(school|education|university|college)\b", "education"),
        (r"\b(fire station|police|emergency response)\b", "emergency_services"),
        (r"\b(residential|single[ -]?family|residence)\b", "residential"),
        (r"\b(warehouse|storage)\b", "warehouse"),
        (r"\b(industrial|manufacturing|factory)\b", "industrial"),
        (r"\b(retail|shopping|store|auto service|auto dealer)\b", "commercial_retail"),
        (r"\b(office|professional|bank)\b", "office_professional"),
        (r"\b(church|religious|mosque|temple)\b", "religious"),
        (r"\b(government|municipal|civic)\b", "government_civic"),
        (r"\b(recreation|community center)\b", "recreation_community"),
        (r"\b(agricultural|farm)\b", "agricultural"),
        (r"\b(transportation|airport|railway)\b", "transportation"),
    ]
    categories = {category for pattern, category in vocabulary if re.search(pattern, text)}
    # A compound description is preserved as mixed; no invented primary use.
    if "multifamily" in categories:
        categories.discard("residential")
    return next(iter(categories)) if len(categories) == 1 else "mixed" if categories else "unknown"


def make_claim(feature: Feature, match: Match, kind: str, scope: str, category: str,
               label: str, raw: dict, semantic: str, **kwargs) -> Claim:
    return Claim(kind, scope, category, label, raw, feature.source, feature.record_id,
                 feature.version, feature.record_date, match.spatial_confidence,
                 {"relationship": match.relationship, "reason": match.reason, **match.evidence},
                 semantic, **kwargs)


def hcad_claims(feature: Feature, match: Match) -> list[Claim]:
    if not match.accepted:
        return []
    claims = []
    year = str(feature.properties.get("Tax_Year") or "unknown")
    for key in ("LANDUSE_DS", "ECON_CLASS", "BLDTYPE_DS", "BLDG_STYDS"):
        raw = feature.properties.get(key)
        if not raw or not str(raw).strip():
            continue
        category = property_category(raw)
        if category == "unknown":
            continue  # Raw unrecognized descriptions remain in the review candidates.
        ambiguity = [] if match.evidence.get("building_promotion_allowed") else [
            "property_context_only: " + match.evidence["structure_association"]]
        claims.append(make_claim(feature, match, "property_use", "parcel", category,
                                 f"{year} property context: {raw}", {key: raw},
                                 "assessor_reported_property_attribute", ambiguity=ambiguity))
        if key == "BLDTYPE_DS" and match.evidence.get("building_promotion_allowed"):
            claims.append(make_claim(feature, match, "structure_use", "building", category,
                                     f"{year} parcel-linked structure description: {raw}", {key: raw},
                                     "single_structure_parcel_link; not independently_verified"))
    if feature.properties.get("PROP_NAME"):
        raw = str(feature.properties["PROP_NAME"])
        claims.append(make_claim(feature, match, "property_name", "parcel", "unknown",
                                 f"{year} property name: {raw}", {"PROP_NAME": raw},
                                 "assessor_reported_property_name"))
    return claims


def nsi_claims(feature: Feature, match: Match) -> list[Claim]:
    if not match.accepted:
        return []
    category, label = nsi_occupancy(feature.properties.get("occtype"))
    if category == "unknown":
        return []
    raw = {key: feature.properties.get(key) for key in ("occtype", "ftprntid", "ftprntsrc", "source")}
    # med_yr_blt remains in the raw extract only, never an exact structure-year claim.
    return [make_claim(feature, match, "modeled_occupancy", "building", category,
                       "Modeled use (NSI " + feature.source.release + "): " + label, raw,
                       "modeled_estimate_not_observed", critical_facility=False)]


OSM_VALUES = {
    "school": "education", "college": "education", "university": "education", "kindergarten": "education",
    "hospital": "medical", "clinic": "medical", "doctors": "medical", "dentist": "medical", "nursing_home": "medical",
    "fire_station": "emergency_services", "police": "emergency_services", "ambulance_station": "emergency_services",
    "emergency_ward": "emergency_services", "emergency_shelter": "emergency_services", "disaster_response": "emergency_services",
    "townhall": "government_civic", "courthouse": "government_civic", "public_building": "government_civic",
    "community_centre": "recreation_community", "library": "recreation_community", "sports_centre": "recreation_community",
    "stadium": "recreation_community", "park": "recreation_community", "playground": "recreation_community",
    "place_of_worship": "religious", "church": "religious", "mosque": "religious", "temple": "religious",
    "hotel": "lodging", "motel": "lodging", "hostel": "lodging", "guest_house": "lodging",
    "house": "residential", "detached": "residential", "residential": "residential", "bungalow": "residential",
    "apartments": "multifamily", "dormitory": "residential", "retail": "commercial_retail",
    "restaurant": "commercial_retail", "cafe": "commercial_retail", "fast_food": "commercial_retail",
    "office": "office_professional", "bank": "office_professional", "industrial": "industrial", "warehouse": "warehouse",
    "farm": "agricultural", "farmland": "agricultural", "farm_auxiliary": "agricultural",
    "train_station": "transportation", "transportation": "transportation", "bicycle_rental": "transportation",
}
CRITICAL_TAGS = {
    ("amenity", "hospital"), ("healthcare", "hospital"), ("amenity", "fire_station"),
    ("amenity", "police"), ("emergency", "ambulance_station"), ("emergency", "emergency_ward"),
    ("emergency", "disaster_response"), ("social_facility", "emergency_shelter"),
}


def osm_claims(feature: Feature, match: Match) -> list[Claim]:
    if not match.accepted:
        return []
    tags = feature.properties
    inactive = any(tags.get(key) == "yes" for key in ("disused", "abandoned", "demolished", "proposed"))
    scope = "site" if match.relationship == "site" else "place"
    period = "Disaster-time mapped" if feature.source.temporal_status == "event_snapshot" else "Current mapped"
    name = str(tags.get("name") or "").strip() or None
    claims = []
    for key in ("building:use", "building", "amenity", "healthcare", "emergency", "office", "shop", "tourism", "leisure", "landuse", "social_facility"):
        value = tags.get(key)
        if inactive or not value or value in {"yes", "no", "construction", "proposed", "disused", "abandoned", "vacant", "empty"}:
            continue
        category = OSM_VALUES.get(value, "unknown")
        if key == "shop":
            category = "commercial_retail"
        if key == "office":
            category = "education" if value == "educational_institution" else "office_professional"
        if category == "unknown":
            continue
        building_claim = key in {"building", "building:use"} and match.relationship == "footprint"
        claim_scope = "building" if building_claim else scope
        kind = "structure_type" if key == "building" else "structure_use" if building_claim else "site_use" if scope == "site" else "mapped_place"
        if key == "landuse" and scope == "site":
            kind = "area_use"
        # Structural design tags do not prove the roof's current facility function.
        critical = (key, value) in CRITICAL_TAGS and match.spatial_confidence == "strong"
        label = f"{period} {claim_scope}: {value.replace('_', ' ')}"
        if name and not building_claim:
            label += f" ({name})"
        if scope == "site":
            label = f"Within {period.lower()} site: {name or value.replace('_', ' ')}"
        if kind == "area_use":
            label = f"Within {period.lower()} {value.replace('_', ' ')} area" + (f": {name}" if name else "")
        claims.append(make_claim(feature, match, kind, claim_scope, category, label,
                                 {key: value, **({"name": name} if name else {})},
                                 "explicit_osm_tag_not_independently_verified", mapped_name=name if not building_claim else None,
                                 critical_facility=critical))
    if name and not any(c.mapped_name for c in claims):
        name_scope = "building" if match.relationship == "footprint" else scope
        claims.append(make_claim(feature, match, "mapped_name", name_scope,
                                 "unknown", f"{period} name ({name_scope}): {name}", {"name": name},
                                 "mapped_name_not_verified_building_identity", mapped_name=name))
    unique = {}
    for claim in claims:
        key = (claim.kind, claim.scope, claim.category, claim.label, claim.critical_facility)
        if key in unique:
            unique[key].raw_value.update(claim.raw_value)
        else:
            unique[key] = claim
    return list(unique.values())


def compare_claims(claims: list[Claim]) -> list[dict]:
    """Return only material semantic conflicts; source differences stay qualified."""
    return [difference for difference in classify_claim_differences(claims)
            if difference["classification"] == "semantic_conflict"]


_LABEL_VARIANT_SUFFIXES = {
    "insurance", "company", "co", "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation",
}


def _normalized_name(value: str | None) -> str:
    """Normalize punctuation, case, and common organization suffixes for comparison only."""
    words = re.findall(r"[\w]+", value.casefold()) if value else []
    while words and words[-1] in _LABEL_VARIANT_SUFFIXES:
        words.pop()
    return " ".join(words)


def classify_claim_differences(claims: list[Claim]) -> list[dict]:
    """Classify semantic disagreement separately from source labels and scope/time.

    Claims are never merged or discarded. Returned indices refer to the supplied
    claim list so audit tooling can preserve the original source records.
    """
    differences = []
    compatible = {frozenset(("residential", "multifamily"))}
    for i, j in combinations(range(len(claims)), 2):
        a, b = claims[i], claims[j]
        same_record = a.source.provider == b.source.provider and a.source_record_id == b.source_record_id
        same_snapshot = a.source.snapshot == b.source.snapshot
        names_differ = bool(a.mapped_name and b.mapped_name and a.mapped_name != b.mapped_name)
        same_normalized_name = bool(names_differ and _normalized_name(a.mapped_name) == _normalized_name(b.mapped_name))
        categories = frozenset((a.category, b.category))
        changed_use = len(categories) == 2 and not categories.intersection({"unknown", "mixed"}) and categories not in compatible
        same_category = a.category == b.category and a.category not in {"unknown", "mixed"}
        source_value_variation = same_category and not names_differ and a.kind == b.kind and a.raw_value != b.raw_value
        if not names_differ and not changed_use and not source_value_variation:
            continue
        if a.kind == b.kind == "modeled_occupancy" and a.source.provider == b.source.provider:
            continue  # Legitimate mixed/stacked modeled occupancy is not discarded.
        qualifications = []
        if a.scope != b.scope:
            qualifications.append("scope_difference")
        if a.source.temporal_status != b.source.temporal_status:
            statuses = {a.source.temporal_status, b.source.temporal_status}
            historical_and_current = bool(statuses & {"event_snapshot", "event_year", "pre_event_historical"}) and bool(
                statuses & {"current_only", "current_modeled_not_event_aligned"})
            qualifications.append("historical_current_difference" if historical_and_current else "temporal_difference")
        elif same_record and not same_snapshot:
            qualifications.append("historical_current_difference")
        if a.source.modeled != b.source.modeled:
            qualifications.append("modeled_vs_mapped_difference")

        if same_normalized_name and not changed_use:
            classification = "source_label_variation"
            reason = "normalized_name_equivalent"
        elif qualifications:
            classification = "scope_time_difference"
            reason = qualifications[0]
        elif source_value_variation:
            classification = "source_label_variation"
            reason = "same_normalized_category"
        else:
            classification = "semantic_conflict"
            reason = "potential_use_conflict" if changed_use else "building_identity_conflict"
        differences.append({"claim_indices": [i, j], "classification": classification, "reason": reason,
                            "qualifications": qualifications, "requires_review": classification == "semantic_conflict",
                            "resolution": "preserved_separately"})
    return differences
