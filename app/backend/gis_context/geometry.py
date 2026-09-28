"""Raw xBD UID joins and metric geometry; never georeference pixel polygons."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from pyproj import CRS, Transformer
from shapely import wkt
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union


SCENE_ID = "hurricane-harvey_00000177"


def utc_timestamp(value: str) -> str:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("An acquisition timestamp with explicit timezone is required.")
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("Acquisition timestamp has no timezone; do not assume a date.")
    return date.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_geographic(geometry: BaseGeometry, polygon: bool = False) -> None:
    if geometry.is_empty or not geometry.is_valid:
        raise ValueError("Empty or invalid geographic geometry; automatic repair is disabled.")
    if polygon and geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("Expected a geographic polygon.")
    west, south, east, north = geometry.bounds
    if not all(math.isfinite(n) for n in geometry.bounds) or not (
        -180 <= west <= east <= 180 and -90 <= south <= north <= 90
    ):
        raise ValueError("Geometry is not in WGS84 longitude/latitude.")


@dataclass(frozen=True)
class Projection:
    epsg: int

    @classmethod
    def for_geometry(cls, geometry: BaseGeometry) -> "Projection":
        validate_geographic(geometry)
        point = geometry.centroid
        if not -80 <= point.y <= 84:
            raise ValueError("Local UTM projection is unavailable at this latitude.")
        zone = min(60, int((point.x + 180) // 6) + 1)
        return cls((32600 if point.y >= 0 else 32700) + zone)

    def project(self, geometry: BaseGeometry) -> BaseGeometry:
        validate_geographic(geometry)
        transformer = Transformer.from_crs(4326, CRS.from_epsg(self.epsg), always_xy=True)
        return transform(transformer.transform, geometry)

    def unproject(self, geometry: BaseGeometry) -> BaseGeometry:
        transformer = Transformer.from_crs(self.epsg, 4326, always_xy=True)
        return transform(transformer.transform, geometry)


@dataclass
class Scene:
    manifest: dict
    acquisition_time: str
    projection: Projection
    geographic: dict[str, BaseGeometry]
    metric: dict[str, BaseGeometry]
    query_bbox: tuple[float, float, float, float]
    label_sha256: str
    manifest_sha256: str


def load_scene(manifest_path: Path, post_label_path: Path, margin_m: float = 50) -> Scene:
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("scene_id") != SCENE_ID or len(manifest.get("buildings", [])) != 76:
        raise ValueError("This milestone accepts only the 76-building Harvey demo pack.")
    if post_label_path.name != SCENE_ID + "_post_disaster.json":
        raise ValueError("Expected the exact raw Harvey POST label filename.")
    label_bytes = post_label_path.read_bytes()
    raw = json.loads(label_bytes)
    acquisition = utc_timestamp(raw.get("metadata", {}).get("capture_date"))
    features = raw.get("features", {}).get("lng_lat")
    if not isinstance(features, list) or not features:
        raise ValueError("Raw POST features.lng_lat is missing; pixel polygons cannot substitute.")
    geographic = {}
    for feature in features:
        uid = feature.get("properties", {}).get("uid")
        if not uid or uid in geographic:
            raise ValueError("Missing or duplicate raw geographic building UID.")
        geometry = wkt.loads(feature.get("wkt", ""))
        validate_geographic(geometry, polygon=True)
        geographic[uid] = geometry
    uids = [b["uid"] for b in manifest["buildings"]]
    if len(set(uids)) != 76 or set(uids) - geographic.keys():
        raise ValueError("Demo UIDs must each join exactly once to raw POST lng_lat geometry.")
    extent = unary_union(list(geographic.values()))
    if extent.bounds[2] - extent.bounds[0] > 0.1 or extent.bounds[3] - extent.bounds[1] > 0.1:
        raise ValueError("Unexpectedly large scene extent; check raw label coordinates.")
    projection = Projection.for_geometry(extent)
    metric = {uid: projection.project(g) for uid, g in geographic.items()}
    # Includes ALL raw POST buildings, including those excluded from the demo.
    # This is the geographic footprint envelope, not a claimed image geotransform.
    query_area = box(*unary_union(list(metric.values())).bounds).buffer(margin_m).envelope
    bbox = projection.unproject(query_area).bounds
    return Scene(manifest, acquisition, projection, geographic, metric, bbox,
                 hashlib.sha256(label_bytes).hexdigest(), hashlib.sha256(manifest_bytes).hexdigest())


def overlap(a: BaseGeometry, b: BaseGeometry) -> dict[str, float]:
    if min(a.area, b.area) <= 0:
        raise ValueError("Overlap requires positive-area metric polygons.")
    intersection = a.intersection(b).area
    return {
        "intersection_m2": intersection,
        "xbd_area_m2": a.area,
        "external_area_m2": b.area,
        "xbd_coverage": intersection / a.area,
        "iou": intersection / (a.area + b.area - intersection),
        "centroid_distance_m": a.centroid.distance(b.centroid),
    }
