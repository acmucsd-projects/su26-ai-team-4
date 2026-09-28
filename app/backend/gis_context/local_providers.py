"""Bounded official Bay/Sonoma extracts feeding the existing parcel/site matchers."""

from collections import Counter
from datetime import datetime, timezone

from shapely.geometry import shape
from shapely.errors import GEOSException

from .geometry import validate_geographic
from .models import Feature, Source
from .normalize import make_claim, property_category


LOCAL = {
    "bay_2017": {
        "url": "https://gis.baycountyfl.gov/arcgis/rest/services/InternalUse/ArchiveParcels/MapServer/17",
        "name": "2017 Parcels", "release": "2017", "temporal": "pre_event_historical",
        "credit": "Bay County GIS / Bay County Property Appraiser",
        "terms": "https://gis.baycountyfl.gov/arcgis/rest/services/InternalUse/ArchiveParcels/MapServer/info/iteminfo",
        "fields": ("OBJECTID", "A1RENUM", "RE_LABEL", "DORAPPCODE", "DORAPPDESC", "BLDCNT", "DSITEADDR",
                   "S1APPTYPE", "S1AREAHEAT", "S1AREATTL", "S1STORIES", "S1UNITS", "S1YRBLTACT", "S1YRBLTEFF"),
    },
    "sonoma_parcels": {
        "url": "https://services1.arcgis.com/P5Mv5GY5S66M8Z1Q/ArcGIS/rest/services/Parcels_Public/FeatureServer/0",
        "name": "Parcels Public", "release": "current public parcel inventory", "temporal": "current_only",
        "credit": "County of Sonoma, Clerk Recorder Assessor / ISD-GIS Central",
        "terms": "https://www.arcgis.com/home/item.html?id=4a3809ba63674b179f5c639547b95163",
        "fields": ("OBJECTID", "APN", "UseCode", "UseCodeDescription", "UseCodeType", "SitusFormatted1", "Value601RollYear",
                   "BuildingPrimaryCount", "BuildingSecondaryCount", "BuildingPrimarySize", "BuildingSecondarySize",
                   "BuildingPrimaryUnitCount", "BuildingPrimaryStories", "BuildingPrimaryYearBuilt", "BuildingPrimaryEffectiveYear", "last_edited_date"),
    },
    "sonoma_schools": {
        "url": "https://services1.arcgis.com/P5Mv5GY5S66M8Z1Q/arcgis/rest/services/School_Parcels/FeatureServer/0",
        "name": "School_Parcels", "release": "2017-07-20 advertised; live service edited 2022-06-10",
        "temporal": "pre_event_reference_vintage_unverified",
        "credit": "County of Sonoma / ISD GIS / Permit Sonoma; CC BY-ND 3.0",
        "terms": "https://www.arcgis.com/home/item.html?id=b9bf5d61fa7147ce9f5481989ef78ede",
        "fields": ("OBJECTID", "APN", "DISTRICT", "SCHOOLNAME"),
    },
    "duplin_parcels": {
        "url": "https://gis.duplinnc.gov/server/rest/services/TaxMapping/Parcels/FeatureServer/0",
        "name": "Parcels", "release": "current Duplin County tax parcel service; vintage not stated",
        "temporal": "current_only",
        "credit": "Duplin County GIS / Tax Mapping",
        "terms": "https://www.duplinnc.gov/277/GIS",
        # Avoid owner names and account/deed fields. The layer has no documented
        # parcel-use field; numeric ValuationModel values are retained unclassified.
        "fields": ("OBJECTID", "PIN", "CYPAR", "TOTAL_ACRES", "ActualYearBuilt",
                   "HeatedAreaCard", "ValuationModel", "Neighborhood", "NeighborhoodName"),
    },
}

# Literal descriptions seen in these providers; never infer use from an opaque
# use code, ownership class (e.g. COUNTY), or a vacant residential parcel.
LOCAL_DESCRIPTIONS = {
    "bay_2017": {
        "MOBILE HOME": "residential", "VEH SALE/REPAIR": "commercial_retail",
        "REPAIR SERVICE": "commercial_retail", "STORES, 1 STORY": "commercial_retail",
    },
    "sonoma_parcels": {
        "RURAL RES/SINGLE RES": "residential",
        "RURAL RES SFD W/GRANNY UNIT": "residential",
    },
}


def fetch_local(client, provider, bbox, snapshot):
    config = LOCAL[provider]
    schema = client.get_json(config["url"], provider=provider + "_schema", release=config["release"], snapshot=snapshot, params={"f": "json"})
    missing = set(config["fields"]) - {f["name"] for f in schema.get("fields", [])}
    if schema.get("name") != config["name"] or missing:
        raise ValueError(f"Unexpected {provider} schema; missing {sorted(missing)}")
    limit = schema.get("maxRecordCount", 1000)
    payload = client.get_json(config["url"] + "/query", provider=provider, release=config["release"], bbox=bbox, snapshot=snapshot, params={
        "f": "geojson", "where": "1=1", "geometry": ",".join(map(str, bbox)), "geometryType": "esriGeometryEnvelope",
        "inSR": "4326", "outSR": "4326", "spatialRel": "esriSpatialRelIntersects",
        "outFields": ",".join(config["fields"]), "returnGeometry": "true", "orderByFields": "OBJECTID", "resultRecordCount": limit,
    })
    if (payload.get("exceededTransferLimit") or payload.get("properties", {}).get("exceededTransferLimit")
            or len(payload.get("features", [])) >= limit):
        raise ValueError("Local provider extract may be truncated; partial coverage is not reported.")
    release = config["release"]
    if provider == "sonoma_schools":
        edited = schema.get("editingInfo", {}).get("dataLastEditDate")
        date = datetime.fromtimestamp(edited / 1000, timezone.utc).date().isoformat() if isinstance(edited, (int, float)) else "unknown"
        release = f"2017-07-20 advertised; live service edited {date}"
    source = Source(provider, config["name"], release, snapshot, config["temporal"],
                    config["credit"], config["terms"], config["url"])
    return payload, source


def local_features(payload, source, projection):
    if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
        raise ValueError("Local provider did not return a GeoJSON FeatureCollection.")
    counts = Counter(str((r.get("properties") or {}).get("OBJECTID")) for r in payload["features"])
    result, issues = [], []
    for row in payload["features"]:
        props = row.get("properties") or {}
        record_id = str(props.get("OBJECTID"))
        try:
            if record_id == "None" or counts[record_id] != 1:
                raise ValueError("Missing or duplicate local record ID")
            geometry = shape(row["geometry"])
            validate_geographic(geometry, polygon=True)
            # Internal matcher alias; every original provider field remains intact.
            props = dict(props)
            if source.provider == "bay_2017":
                props["BUILDCOUNT"] = props.get("BLDCNT")
            elif source.provider == "sonoma_parcels":
                primary, secondary = props.get("BuildingPrimaryCount"), props.get("BuildingSecondaryCount")
                props["BUILDCOUNT"] = (primary + secondary) if isinstance(primary, (int, float)) and isinstance(secondary, (int, float)) else None
            record_date = "2017" if source.provider == "bay_2017" else None
            edited = props.get("last_edited_date")
            if isinstance(edited, (int, float)):
                record_date = datetime.fromtimestamp(edited / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
            result.append(Feature(record_id, projection.project(geometry), props, source, record_date=record_date))
        except (ValueError, TypeError, KeyError, GEOSException) as error:
            issues.append({"record_id": record_id, "reason": str(error)})
    return result, issues


def local_claims(feature, match):
    if not match.accepted:
        return []
    provider, props = feature.source.provider, feature.properties
    if provider == "duplin_parcels":
        # Parcel geometry supports parcel-scope matching only. The source does
        # not publish a documented land-use classification for normalization.
        return []
    if provider == "sonoma_schools":
        name = str(props.get("SCHOOLNAME") or "").strip() or None
        return [make_claim(feature, match, "school_site", "site", "education",
                           "Within mapped school property: " + (name or "unnamed school") + " (advertised July 2017; vintage unverified)",
                           {key: props.get(key) for key in ("APN", "SCHOOLNAME", "DISTRICT")},
                           "official_school_property_not_individual_building_identity", mapped_name=name,
                           critical_facility=False, ambiguity=["Advertised 2017 layer; live service was edited in 2022. Not an exact event snapshot."])]
    field = "DORAPPDESC" if provider == "bay_2017" else "UseCodeDescription"
    raw = props.get(field)
    category = LOCAL_DESCRIPTIONS[provider].get(str(raw or "").strip().upper(), property_category(raw))
    if category == "unknown":
        return []
    period = "2017 pre-event" if provider == "bay_2017" else "Current"
    claims = [make_claim(feature, match, "property_use", "parcel", category,
                         f"{period} property context: {raw}", {field: raw}, "assessor_reported_property_attribute",
                         ambiguity=[] if match.evidence.get("building_promotion_allowed") else ["property_context_only: " + match.evidence["structure_association"]])]
    if match.evidence.get("building_promotion_allowed"):
        claims.append(make_claim(feature, match, "structure_use", "building", category,
                                 f"{period} single-structure parcel use: {raw}", {field: raw},
                                 "single_structure_parcel_link; not independently_verified"))
    return claims
