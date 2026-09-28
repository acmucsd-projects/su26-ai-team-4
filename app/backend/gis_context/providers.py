"""Four bounded provider extracts; no network calls from normal app runtime."""

from dataclasses import replace
from collections import Counter

from shapely.errors import GEOSException
from shapely.geometry import LineString, Point, Polygon, shape
from shapely.ops import polygonize_full, unary_union

from .cache import CachedClient
from .geometry import Projection, utc_timestamp, validate_geographic
from .models import Feature, Source


HCAD_URL = "https://geohwp.houstontx.gov/arcgis/rest/services/03_BaseData_External/Parcels_Historic/FeatureServer/19"
NSI_URL = "https://nsi.sec.usace.army.mil/nsiapi/structures"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
HCAD_FIELDS = (
    "OBJECTID", "PARCEL_ID", "Tax_Year", "ADDRESS", "CITY", "ZIP_CODE", "STATECLASS",
    "LANDUSE_DS", "landuse_cd", "ECON_CLASS", "IMPROVTYPE", "BLDTYPE_DS", "BLDG_STYCD",
    "BLDG_STYDS", "YEAR_BUILT", "BUILDCOUNT", "PROP_NAME",
)
OSM_KEYS = "building|building:use|amenity|healthcare|emergency|office|shop|tourism|leisure|landuse|name|addr:.*|site|social_facility"


def source_info(provider: str, snapshot: str) -> Source:
    if provider == "hcad":
        return Source("hcad", "Houston HCAD Parcels 2017, layer 19", "2017", snapshot,
                      "event_year", "HCAD / City of Houston GIS", "https://mycity.houstontx.gov/about.html", HCAD_URL)
    if provider == "nsi":
        return Source("nsi", "NSI public Base inventory", "2026 (documented; API unversioned)", snapshot,
                      "current_modeled_not_event_aligned", "USACE National Structure Inventory",
                      "https://www.hec.usace.army.mil/confluence/nsi/technicalreferences/2026/technical-documentation", NSI_URL, True)
    return Source("osm", provider, "Overpass snapshot", snapshot,
                  "event_snapshot" if provider == "osm_historical" else "current_only",
                  "© OpenStreetMap contributors; ODbL 1.0", "https://www.openstreetmap.org/copyright", OVERPASS_URL)


def hcad_schema(client: CachedClient) -> dict:
    schema = client.get_json(HCAD_URL, provider="hcad_schema", release="2017", params={"f": "json"})
    names = {field["name"] for field in schema.get("fields", [])}
    missing = set(HCAD_FIELDS) - names
    if schema.get("name") != "HCAD Parcels 2017" or missing:
        raise ValueError("HCAD schema changed; missing fields: " + str(sorted(missing)))
    return schema


def fetch_hcad(client: CachedClient, bbox, snapshot: str) -> tuple[dict, Source]:
    schema = hcad_schema(client)
    limit = schema.get("maxRecordCount", 2000)
    payload = client.get_json(HCAD_URL + "/query", provider="hcad", release="2017", bbox=bbox, snapshot=snapshot, params={
        "f": "geojson", "where": "1=1", "geometry": ",".join(map(str, bbox)),
        "geometryType": "esriGeometryEnvelope", "inSR": "4326", "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects", "outFields": ",".join(HCAD_FIELDS),
        "returnGeometry": "true", "orderByFields": "OBJECTID", "resultRecordCount": limit,
    })
    if payload.get("exceededTransferLimit") or payload.get("properties", {}).get("exceededTransferLimit") or len(payload.get("features", [])) >= limit:
        raise ValueError("HCAD scene extract may be truncated; no partial coverage will be reported.")
    return payload, source_info("hcad", snapshot)


def fetch_nsi(client: CachedClient, bbox, snapshot: str) -> tuple[dict, Source]:
    west, south, east, north = bbox
    # NSI bbox is a closed coordinate ring, not the usual four-number envelope.
    ring = (west, south, west, north, east, north, east, south, west, south)
    payload = client.get_json(NSI_URL, provider="nsi", release="2026_documented_unversioned_api",
                              bbox=bbox, snapshot=snapshot, params={"bbox": ",".join(map(str, ring)), "fmt": "fc"})
    return payload, source_info("nsi", snapshot)


def overpass_query(bbox, historical_time: str | None) -> str:
    west, south, east, north = bbox
    date = f'[date:"{utc_timestamp(historical_time)}"]' if historical_time else ""
    bounds = f"({south},{west},{north},{east})"
    # Include semantic objects, enclosing site relations, and relation members.
    # Do not manufacture campus boundaries from a centroid or convex hull.
    return (f"[out:json][timeout:45]{date};"
            f'(nwr[~"^({OSM_KEYS})$"~"."]{bounds};rel["type"="site"]{bounds};)->.seed;'
            "(.seed;rel(bw.seed);rel(bn.seed);rel(br.seed););(._;>>;);out meta geom;")


def fetch_osm(client: CachedClient, bbox, snapshot: str, historical: bool) -> tuple[dict, Source]:
    provider = "osm_historical" if historical else "osm_current"
    payload = client.get_json(OVERPASS_URL, provider=provider, release="Overpass attic" if historical else "current",
                              bbox=bbox, snapshot=snapshot, form={"data": overpass_query(bbox, snapshot if historical else None)})
    if not isinstance(payload.get("elements"), list) or not payload.get("osm3s", {}).get("timestamp_osm_base"):
        raise ValueError("Incomplete Overpass response or missing source timestamp.")
    source = source_info(provider, snapshot if historical else payload["osm3s"]["timestamp_osm_base"])
    return payload, source


def geojson_features(payload: dict, source: Source, projection: Projection) -> tuple[list[Feature], list[dict]]:
    if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
        raise ValueError("Provider did not return a GeoJSON FeatureCollection.")
    id_field = "OBJECTID" if source.provider == "hcad" else "fd_id"
    identifiers = Counter(str((row.get("properties") or {}).get(id_field)) for row in payload["features"])
    result, issues = [], []
    for row in payload["features"]:
        properties = row.get("properties") or {}
        record_id = str(properties.get(id_field))
        try:
            if record_id == "None" or identifiers[record_id] != 1:
                raise ValueError("Missing or duplicate provider record ID")
            geometry = shape(row["geometry"])
            validate_geographic(geometry, polygon=source.provider == "hcad")
            if source.provider == "nsi" and (geometry.geom_type != "Point" or "occtype" not in properties):
                raise ValueError("NSI requires point geometry and occtype")
            feature_source = source
            record_date = None
            if source.provider == "hcad":
                record_date = str(properties.get("Tax_Year") or "unknown")
                if record_date != "2017":
                    feature_source = replace(source, temporal_status="tax_year_unverified")
            result.append(Feature(record_id, projection.project(geometry), properties, feature_source, record_date=record_date))
        except (ValueError, TypeError, KeyError, GEOSException) as error:
            issues.append({"record_id": record_id, "reason": str(error)})
    return result, issues


def _coordinates(element: dict) -> list[tuple[float, float]]:
    return [(point["lon"], point["lat"]) for point in element.get("geometry", [])]


def _relation_polygon(element: dict):
    groups = {"outer": [], "inner": []}
    for member in element.get("members", []):
        role = member.get("role") or "outer"
        if member.get("type") != "way" or role not in groups:
            raise ValueError("Unsupported polygon relation member; needs manual review")
        coordinates = _coordinates(member)
        if len(coordinates) < 2:
            raise ValueError("Incomplete polygon relation member geometry")
        groups[role].append(LineString(coordinates))
    polygons = {}
    for role, lines in groups.items():
        faces, cuts, dangles, invalid = polygonize_full(lines)
        if not cuts.is_empty or not dangles.is_empty or not invalid.is_empty:
            raise ValueError("Unclosed relation geometry")
        polygons[role] = unary_union(faces)
    return polygons["outer"].difference(polygons["inner"])


def osm_features(payload: dict, source: Source, projection: Projection) -> tuple[dict[str, list[Feature]], list[dict]]:
    layers = {"footprint": [], "place": [], "site": []}
    issues = []
    elements = payload.get("elements", [])
    lookup = {(element["type"], element["id"]): element for element in elements}
    for element in elements:
        tags = element.get("tags") or {}
        if not tags:
            continue
        record_id = f'{element["type"]}/{element["id"]}'
        try:
            geometry = None
            layer = None
            if element["type"] == "node":
                if not any(k in tags for k in ("name", "amenity", "healthcare", "emergency", "shop", "office", "tourism", "social_facility")):
                    continue
                geometry, layer = Point(element["lon"], element["lat"]), "place"
            elif element["type"] == "way":
                coordinates = _coordinates(element)
                if len(coordinates) < 4 or coordinates[0] != coordinates[-1] or tags.get("area") == "no":
                    continue  # No invented point at a street/line centroid.
                if "highway" in tags or "waterway" in tags or "boundary" in tags:
                    continue
                geometry = Polygon(coordinates)
            elif tags.get("type") == "multipolygon":
                geometry = _relation_polygon(element)
            elif tags.get("type") == "site":
                members = []
                for member in element.get("members", []):
                    if member.get("type") != "way":
                        continue
                    way = lookup.get(("way", member["ref"]), member)
                    coordinates = _coordinates(way)
                    if len(coordinates) >= 4 and coordinates[0] == coordinates[-1]:
                        polygon = Polygon(coordinates)
                        validate_geographic(polygon, polygon=True)
                        members.append(polygon)
                if not members:
                    raise ValueError("Site relation has no usable areal members; no invented boundary")
                geometry, layer = unary_union(members), "site"
            if geometry is None:
                continue
            if layer is None:
                if tags.get("building") not in (None, "no"):
                    layer = "footprint"
                elif any(key in tags for key in ("site", "amenity", "healthcare", "emergency", "landuse", "leisure", "tourism", "shop", "office")):
                    layer = "site"
                else:
                    continue
            validate_geographic(geometry, polygon=layer != "place")
            feature = Feature(record_id, projection.project(geometry), tags, source,
                              str(element.get("version")) if element.get("version") is not None else None,
                              element.get("timestamp"))
            layers[layer].append(feature)
        except (ValueError, TypeError, KeyError, GEOSException) as error:
            issues.append({"record_id": record_id, "reason": str(error)})
    return layers, issues
