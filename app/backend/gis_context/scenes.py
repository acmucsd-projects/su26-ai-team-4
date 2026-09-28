"""Explicitly authorized GIS-v2 feasibility scenes; no automatic expansion."""

SCENE_COUNTS = {
    "hurricane-harvey_00000177": 76,
    "hurricane-michael_00000247": 177,
    "santa-rosa-wildfire_00000014": 49,
    "hurricane-florence_00000459": 56,
    "socal-fire_00000663": 48,
}
SCENE_PROVIDERS = {
    "hurricane-harvey_00000177": ("hcad", "nsi", "osm_historical", "osm_current"),
    "hurricane-michael_00000247": ("bay_2017", "nsi", "osm_historical", "osm_current"),
    "santa-rosa-wildfire_00000014": ("sonoma_parcels", "sonoma_schools", "nsi", "osm_historical", "osm_current"),
    "hurricane-florence_00000459": ("duplin_parcels", "nsi", "osm_historical", "osm_current"),
    "socal-fire_00000663": ("osm_historical", "osm_current", "nsi"),
}
OPTIONAL_PROVIDERS = {"socal-fire_00000663": {"osm_historical"}}
LOCAL_PARCELS = {"hcad", "bay_2017", "sonoma_parcels", "duplin_parcels"}
