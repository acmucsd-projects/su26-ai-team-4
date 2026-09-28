# Harvey first-milestone finding

**Inconclusive: the real 76-building GIS audit is blocked by missing raw input.**

The checkout's curated Harvey pack has 76 building UIDs and pixel polygons, but
no geographic polygons or acquisition timestamp. The packager expects
`data/train/labels/hurricane-harvey_00000177_post_disaster.json`; this checkout's
`data/` contains only its README and placeholder. No alternate dataset path was
provided during implementation. Geographic coordinates and a generic hurricane
date were not substituted.

| Required measurement | Real Harvey result |
|---|---|
| HCAD parcel/use/single-vs-multiple structures | Not evaluated / 76 unknown |
| NSI candidates, matches, normalized occupancy | Not evaluated / 76 unknown |
| Historical OSM semantics | Not evaluated / 76 unknown |
| Current OSM semantics | Not evaluated / 76 unknown |
| Combined semantic, event-aligned, broad-use coverage | Unknown; no percentage |
| Mapped names, facilities, sites | Unknown |
| Conflicts, ambiguity/rejection, no-context rate | Unknown |

Successfully queried: **official Houston HCAD Parcels 2017 layer 19 schema**,
verified and cached. Official NSI 2026 API/taxonomy, OSM history querying, and
provider terms were inspected. **No spatial feature dataset was queried for
Harvey**, because its location cannot be established from the available input.
HCAD's contribution and NSI/OSM incremental coverage therefore remain unmeasured.

No real useful-match examples, critical-facility results, provider conflicts,
or rejected spatial examples exist to manually validate yet. The generated
CSV/HTML/GeoJSON enumerate all real demo UIDs as unevaluated. The QA status says
`not_performed`. Synthetic unit/integration test matches are software checks,
not Harvey findings and are not included in those artifacts.

The reusable implementation is ready for a first controlled real-data run:
UID-linked geographic input validation, metric matchers, separate scope/time/
modeled claims, four provider adapters, deterministic caches, coverage reports,
and QA selection. 38 focused synthetic tests passed, including a full mocked
four-provider run. Provider feature adapters still need real Harvey validation.
No model inference/training was run. Frontend, damage predictions, UIDs, pixel
polygons, crop URLs, and scene manifests were unchanged.

**Decision: do not claim GIS v2 outperforms the prior OSM experiment, and do not
proceed to Michael, Santa Rosa, or UI integration on this evidence.** Obtain the
exact raw POST label, run the cached audit, review all mandatory QA results and
representative samples, then decide using semantic coverage and observed errors.
The previous aggregate 610-building OSM figures are context, not a directly
comparable measured Harvey baseline.

Provider attribution and redistribution limits are recorded in [README.md](README.md).
Provider extracts and generated review files remain ignored and uncommitted.
