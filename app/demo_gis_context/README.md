# Reviewed GIS demo context

These five versioned, derived overlays reproduce the reviewed Building Context
for Harvey (`hurricane-harvey_00000177`), Michael (`hurricane-michael_00000247`),
Santa Rosa (`santa-rosa-wildfire_00000014`), and Florence
(`hurricane-florence_00000459`), plus SoCal (`socal-fire_00000663`). They cover
406 buildings, with displayable context on 76, 175, 48, 40, and 47 respectively.
Total JSON size is about 2.0 MB.

Florence is partial: its 40 reviewed claims are current NSI modeled occupancy,
not event-aligned observations. No direct mapped building/place evidence or
documented Duplin property-use semantics were retained. The incomplete Duplin
parcel source, including one invalid geometry, is excluded from the overlay.
Unknown context remains empty. The raw xBD label is needed only to regenerate
the GIS audit, not to display this tracked overlay.

SoCal is partial: its context combines 2026 current OSM evidence and NSI modeled
occupancy, with surrounding residential-area context kept separate from mapped
building type. Historical OSM and Los Angeles County parcel evidence were
unavailable; the overlay explicitly notes that event-time context could not be
assessed. One building has no context. No property, named-place, or critical-
facility claims are included.

The app loads this directory by default. `GIS_CONTEXT_ROOT` selects a development
overlay directory instead; missing or invalid overrides do not fall back here.
No raw downloads, audit workspace, GIS packages, provider requests, or regeneration
are needed. Canonical `app/demo_scenes/*/scene.json` files remain unchanged.

Only final approved/displayable evidence is included, preserving normalized
categories, subtypes, scope, timing, qualifications, conflicts, original approved
classifications, and source attribution/provenance. Held names, rejected candidates,
provider record IDs, geometry, caches, and raw audit artifacts are excluded. The
existing completed-review exporter was used to verify equivalence before packaging.

Each overlay retains its source audit fingerprint. Packaged manifest hashes use
`scene_manifest_hash_format: lf`, normalizing only CRLF to LF so Git checkout line
endings cannot disable context on another machine. Other manifest changes still
invalidate the overlay. One building per JSON line keeps the data compact.

For startup commands, see [the backend README](../backend/README.md#portable-scene-only-demo).
Development exports remain ignored under `local_experiments/gis_context_v2/overlays`;
updating this reviewed snapshot is an explicit versioned change.

External GIS data has attribution, redistribution, and licensing considerations
that should be reviewed if this project expands beyond this presentation/demo.
Existing source attribution and terms references are retained; this packaging
step does not make a new licensing determination.
