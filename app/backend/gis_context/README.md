# Offline GIS building context v2

This module audits **only `hurricane-harvey_00000177` (76 demo buildings)**. It is
an offline utility, independent of FastAPI, the frontend, and model inference.
It does not write scene manifests or guess geographic coordinates from pixels.
See [the current feasibility finding](HARVEY_FEASIBILITY.md) before interpreting
any generated report. The first real-data audit is blocked by missing raw labels.

## Run

From the repository root, use a separate GIS environment (Python 3.11+):

```powershell
python -m venv local_experiments/gis_context_v2/.venv
$gisPython = 'local_experiments/gis_context_v2/.venv/Scripts/python.exe'
& $gisPython -m pip install -r app/backend/gis_context/requirements.txt
& $gisPython -B -m unittest app.backend.gis_context.test_gis_context -v
```

Supply the **original** POST label with `metadata.capture_date` (timezone-aware
acquisition timestamp) and `features.lng_lat` WKT polygons keyed by
`properties.uid`. All 76 demo UIDs must join exactly once. Geometry outside the
demo is retained as competition for matches. Invalid/duplicate geographic data
fails closed. Neither the training cache nor a model checkpoint is required.

```powershell
& $gisPython -B -m app.backend.gis_context `
  --post-label 'D:/xbd/train/labels/hurricane-harvey_00000177_post_disaster.json' `
  --snapshot 2026-09-28 --fetch
```

The path above is illustrative; it is not a discovered dataset location. The
default is `data/train/labels/hurricane-harvey_00000177_post_disaster.json`, the
same raw-label layout used by `package_demo_scene.py`. Without the file, the
command writes a **blocked** report with 76 unevaluated rows and exits 2. Missing
provider data also exits 2. Exit 0 means provider evaluation finished, **not**
that manual QA or a feasibility decision succeeded.

Omit `--fetch` and reuse the same `--snapshot` to replay from cache without
network access. Use a new snapshot label deliberately to obtain a new current
extract; OSM's actual database timestamp is recorded separately. Requests are
content-keyed by endpoint, parameters, bbox, snapshot, release, and query version.
Cached response hashes are checked on replay. Failed/partial API responses are
not treated as empty successful extracts. TLS verification stays enabled.

## Data flow and relationships

`geometry.py` joins raw geographic polygons to the demo UIDs and selects a local
UTM CRS. `matching.py` uses meters and square meters throughout. The provider
query envelope includes **all raw POST geographic footprints plus 50 m**. It is
not claimed to be the full image's georeferenced extent: no image geotransform
is available in the packaged scene. This envelope supports the building audit;
verify it against the actual source metadata before interpreting scene-wide
context outside the labeled roofs.

`providers.py` fetches HCAD once for that envelope (plus a cached schema request),
NSI once, and Overpass once each for acquisition-time and current snapshots.
There are no requests per building. HCAD truncation fails the provider audit;
the code never silently accepts the first 2,000 records. Adapters preserve raw
values, source record IDs, versions/timestamps where supplied, and attribution.

Independent matchers handle these relationships:

| Relationship | Conservative starting rule |
|---|---|
| Footprint | Candidate within 15 m; strong coverage ≥ .65, IoU ≥ .40, centroid ≤ 8 m; moderate .45/.25/12 m. Score is mean coverage/IoU; winner margin ≥ .10. Shared external footprint winners rejected. |
| POI/place | Unique interior containment is strong. Boundary/near ≤ 5 m requires a ≥ 2 m nearest-building gap and stays moderate. 5–15 m candidates rejected for direct association. |
| Parcel | Coverage ≥ .80, or centroid inside with coverage ≥ .50. Multiple qualifying parcels rejected. Count all raw xBD structures with ≥ .20 parcel overlap. |
| NSI | Unique containment; nearby points remain rejected without independent corroboration. Preserve shared-footprint/coincident stacked records. Multiple unlinked records and footprint IDs shared across roofs rejected. |
| Site/campus | ≥ .80 coverage and centroid inside an explicit area, or the areal members of an explicit OSM site relation. No synthesized hull/bbox campus. |

Parcel attributes remain parcel claims. Only a single raw xBD structure **and**
HCAD `BUILDCOUNT=1` permit an additional parcel-linked structure-description
claim. `BUILDCOUNT` absent or greater than one does not support promotion.
No purpose is inferred from roof shape, size, imagery, or damage predictions.

The Overpass query includes semantic nodes, ways, relations, parent relations,
and their members. Multipolygon holes are preserved; unclosed/unsupported
relations are reported for review. It does not turn streets into centroid POIs.
POIs 5–15 m away never label roofs; any site context must independently satisfy
the site matcher. This deliberately sacrifices some coverage.

## Claims and interpretation

`models.py` and `normalize.py` keep `kind` and `scope` separate from broad use.
Each claim has provider/dataset, release/snapshot, record ID/date/version,
spatial confidence and evidence, semantic confidence, modeled status, temporal
status, raw values, ambiguity, and attribution. There is no single composite
confidence score or forced canonical building type.

HCAD descriptions are normalized conservatively; unknown codes are retained in
candidate raw values but not guessed. NSI occupancy claims say **Modeled use**.
`med_yr_blt` is never exposed as a building construction year. Multiple accepted
NSI occupancies remain separate claims. OSM current-only assertions never
become disaster-time identities. A name on a place is not a verified building
identity. Structure design tags and mapped tenant use remain distinct.

Critical-facility flags require explicit hospital/emergency-service OSM tags
and a strong spatial relationship. A modeled NSI hospital, an OSM structural
`building=hospital` tag alone, a moderate nearby POI, or a school alone does not
qualify. Site-scoped facilities remain site-scoped. Inactive/vacant tags do not
generate active-use claims.

Comparable use/name differences are retained for QA. Parcel-vs-tenant differences
and linked mixed NSI occupancies are not automatically called contradictions.
The comparison is a conservative review aid, not an exhaustive entity-resolution
or conflict-detection system. Historical/current name changes are linked only
when the OSM record identity is stable.

## Review outputs

Outputs live under ignored `local_experiments/gis_context_v2/`:

- `cache/`: raw provider responses and request/hash metadata.
- `hurricane-harvey_00000177/audit.json`: all 76 UIDs, claims, candidate geometry,
  raw values, accepted/rejected evidence, provider status, and metrics.
- `summary.md`: count/percentage table and blockers.
- `review.csv`, `review.html`, `review.geojson`: local manual review artifacts.
  HTML makes no remote requests; open GeoJSON in a GIS viewer for spatial QA.

All percentages use 76 buildings, not provider records. `null` means unknown,
not zero. Partial-data counts are marked as lower bounds, with unknown counts
and percentages withheld where coverage is incomplete. `no_context=true` is
only possible after all four providers completed. Raw footprint matches do not
count as semantic coverage. Source contribution includes exclusive additional
buildings only when all sources completed.

The QA selector includes every named-place, critical-facility, and conflict
result; up to 20 representative contexts spanning source/category/scope/time;
and up to 10 rejected/ambiguous buildings. **Selection is not completed review.**
Record actual findings separately and assess semantic errors before recommending
expansion to Michael or Santa Rosa. Tests use labeled synthetic fixtures only.

## Verified sources and terms

The adapter's HCAD fields were checked against the live official
[2017 layer 19](https://geohwp.houstontx.gov/arcgis/rest/services/03_BaseData_External/Parcels_Historic/FeatureServer/19).
The schema reports 54 fields, a 2,000-record limit, and a 2022 service update for
the historical dataset. Selected fields include `PARCEL_ID`, `Tax_Year`,
`LANDUSE_DS`, `landuse_cd`, `ECON_CLASS`, `IMPROVTYPE`, `BLDTYPE_DS`,
`BLDG_STYDS`, `YEAR_BUILT`, and `BUILDCOUNT`. Owner fields are not requested.
Record-level `Tax_Year` is checked before labeling a claim event-year aligned.

The [City of Houston GIS terms](https://mycity.houstontx.gov/about.html) describe
COHGIS information as public domain and request source citation. They also
require independent verification for specific uses and disclaim accuracy.
[HCAD's GIS documentation](https://hcad.org/assets/uploads/pdf/resources/2026/GIS-ReadMeV2-2.pdf)
warns that parcel boundaries are approximate, not surveys. Attribute HCAD and
City of Houston GIS; retain source provenance and verify historical-layer scope
before any distribution. No parcel extracts are committed here.

NSI uses the official [public API](https://www.hec.usace.army.mil/confluence/nsi/technicalreferences/2026/api-reference-guide).
Its `bbox` parameter is a closed longitude/latitude ring. The current
[2026 technical reference](https://www.hec.usace.army.mil/confluence/nsi/technicalreferences/2026/technical-documentation)
defines `fd_id`, `occtype`, `ftprntid`, `ftprntsrc`, modeled occupancy categories,
and the Census-tract meaning of `med_yr_blt`. The API URL is unversioned; the
documented release and extract timestamp are both retained rather than claiming
an API-guaranteed vintage. Its [2026 FAQ](https://www.hec.usace.army.mil/confluence/nsi/technicalreferences/2026/frequently-asked-questions)
explains stacked records and warns about modeled structure-level errors.

NSI's [2022 public-release FAQ](https://www.hec.usace.army.mil/confluence/nsi/technicalreferences/2022/frequently-asked-questions)
explicitly distinguishes releasable public fields from licensed private fields.
The current documentation maintains a public/private distinction; this adapter
only calls the public endpoint. A blanket unrestricted-redistribution license
for every 2026 source field was **not** established by this audit. Keep extracts
local and confirm terms for the precise public-derived output before publishing;
do not extrapolate private-data rights from public API availability.

Both OSM snapshots require **© OpenStreetMap contributors** attribution and the
[ODbL/copyright terms](https://www.openstreetmap.org/copyright). Future derived
database distribution must account for ODbL obligations, not only a UI credit.
Historical queries use the documented [Overpass date setting](https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL#Date)
at the raw POST acquisition timestamp. OSM snapshot date records what was mapped,
not independent proof of on-the-ground correctness at that instant.

Foursquare, Overture, USGS layers, runtime enrichment, and frontend integration
are intentionally outside this milestone.
