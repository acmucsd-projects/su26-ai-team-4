# GIS v2 milestone 2: Michael and Santa Rosa

**GO for a separately authorized frontend integration milestone using reviewed,
source-scoped claims.** Michael materially resolves the earlier zero-semantic
result. Santa Rosa supports school-site membership without naming every roof as
the school. No matching thresholds were relaxed.

**Distribution constraint:** the two Sonoma county items specify CC BY-ND 3.0.
Exclude their derived building associations from distributable frontend assets
until permitted reuse is resolved. Bay's public 2017 archive has no explicit
license in its item metadata; confirm reuse terms before distributing those
extracts/associations. This audit establishes feasibility, not redistribution
permission. Even with all new county claims excluded, reviewed NSI/OSM supplies
context beyond neighborhoods to **85/177 Michael (48.02%)** and **42/49 Santa Rosa
(85.71%)**. That supports starting integration with the reviewed fallback.

The branch is `feature/gis-building-context-v2`; implementation commit
`d5e07e6`. No frontend integration, manifest regeneration, training, inference,
other-scene expansion, push or deployment was performed.

## Real inputs and extracts

| Scene | Original POST label | Actual capture time (UTC) | Packaged UID linkage | Raw footprints | Metric CRS |
|---|---|---|---|---|---|
| Michael | `data/tier1/labels/hurricane-michael_00000247_post_disaster.json` | 2018-10-13T16:48:15.000Z | 177/177, each exactly once | 178 | EPSG:32616 |
| Santa Rosa | `data/tier1/labels/santa-rosa-wildfire_00000014_post_disaster.json` | 2017-10-11T19:19:41.000Z | 49/49, each exactly once | 50 | EPSG:32610 |

No missing/duplicate packaged UID or invalid polygon was found. Each extra raw
roof remains a competing geometry; canonical demo manifests are unchanged.
Query bounds are all raw roofs plus 50 m, not a claimed full image extent:

- Michael: `-85.62071911931032, 30.147931052562292, -85.61466078826449, 30.15319614156762`.
- Santa Rosa: `-122.7417104476279, 38.49161053250444, -122.73529158778541, 38.49642581923881`.

All sources completed without parse issues. Snapshot label: **2026-09-28**.
Scene-wide queries returned:

| Scene | County parcels | County school properties | NSI records | Historical OSM raw / parsed | Current OSM raw / parsed |
|---|---:|---:|---:|---:|---:|
| Michael | 216 | — | 163 | 70 / 0 | 2,819 / 235 |
| Santa Rosa | 18 | 2 | 77 | 173 / 3 | 2,525 / 144 |

Michael's initial OSM attempts timed out; the identical bounded queries succeeded
on retry. Failed responses were never counted as empty coverage. Historical OSM
uses the actual capture timestamp to whole seconds. Current OSM database times:
Michael **2026-09-28T08:48:31Z**; Santa Rosa **2026-09-28T08:45:25Z**.
Exact request URLs, timestamps, response hashes and raw records remain in cache
metadata and the local audits.

## Comparison after manual QA

Counts and percentages use each complete packaged scene. Overlapping rows must
not be added. Harvey is the existing reviewed reference, replayed for regression.

| Metric | Harvey (76) | Michael (177) | Santa Rosa (49) |
|---|---:|---:|---:|
| Useful local property | 64 (84.21%) | 160 (90.40%) | 48 (97.96%) |
| NSI modeled occupancy | 42 (55.26%) | 84 (47.46%) | 14 (28.57%) |
| Historical OSM | 4 (5.26%) | 0 (0.00%) | 18 (36.73%) |
| Current OSM, including neighborhoods | 66 (86.84%) | 164 (92.66%) | 40 (81.63%) |
| Direct building/place | 48 (63.16%) | 97 (54.80%) | 21 (42.86%) |
| Site/campus, excluding neighborhoods | 3 (3.95%) | 0 (0.00%) | 42 (85.71%) |
| Neighborhood-only | 9 (11.84%) | 11 (6.21%) | 0 (0.00%) |
| Combined excluding neighborhoods | 67 (88.16%) | 164 (92.66%) | 48 (97.96%) |
| No context | 0 (0.00%) | 2 (1.13%) | 1 (2.04%) |
| Buildings with selective QA holds | 4 (5.26%) | 11 (6.21%) | 8 (16.33%) |

Direct context includes qualified assessor links and **modeled** NSI occupancy.
Site/campus excludes neighborhood land use; Harvey's three are park memberships.
Neither metric measures verified building identity. Current OSM's large Michael
coverage is primarily neighborhood context, so it is not the semantic benchmark.

## Complete milestone metrics

| Measurement | Michael / 177 | Santa Rosa / 49 |
|---|---:|---:|
| Local parcel match | 167 (94.35%) | 49 (100.00%) |
| Useful local property context | 160 (90.40%) | 48 (97.96%) |
| Automated single-structure parcel association | 57 (32.20%) | 2 (4.08%) |
| Multi-structure parcel association | 106 (59.89%) | 46 (93.88%) |
| Unknown structure count on accepted parcel | 4 (2.26%) | 1 (2.04%) |
| Qualified building promotion after holds | 50 (28.25%) | 2 (4.08%) |
| NSI candidate | 148 (83.62%) | 31 (63.27%) |
| NSI accepted spatial association (before semantic holds) | 89 (50.28%) | 20 (40.82%) |
| NSI displayable modeled occupancy | 84 (47.46%) | 14 (28.57%) |
| Historical OSM useful context | 0 (0.00%) | 18 (36.73%) |
| Current OSM useful context (including neighborhoods) | 164 (92.66%) | 40 (81.63%) |
| Mapped name, any scope | 1 (0.56%) | 42 (85.71%) |
| Direct mapped name | 1 (0.56%) | 9 (18.37%) |
| Site/campus, excluding neighborhoods | 0 (0.00%) | 42 (85.71%) |
| Site/area, including neighborhoods | 164 (92.66%) | 42 (85.71%) |
| School site membership, all sources | 0 (0.00%) | 42 (85.71%) |
| Nonmodeled facility context, any scope | 0 (0.00%) | 42 (85.71%) |
| Critical/emergency label | 0 (0.00%) | 0 (0.00%) |
| Exact event snapshot / event-year context | 0 (0.00%) | 18 (36.73%) |
| Verified pre-event release context | 160 (90.40%) | 0 (0.00%) |
| Event or verified pre-event context | 160 (90.40%) | 18 (36.73%) |
| Advertised historical reference, vintage unverified | 0 (0.00%) | 41 (83.67%) |
| Direct building/place (includes modeled/qualified links) | 97 (54.80%) | 21 (42.86%) |
| Only parcel context beyond neighborhoods | 67 (37.85%) | 3 (6.12%) |
| Neighborhood-only context | 11 (6.21%) | 0 (0.00%) |
| Automated comparable conflicts after holds | 1 (0.56%) | 9 (18.37%) |
| Ambiguous candidate | 3 (1.69%) | 1 (2.04%) |
| Rejected/ambiguous candidate | 164 (92.66%) | 40 (81.63%) |
| Combined unique context | 175 (98.87%) | 48 (97.96%) |
| Combined excluding neighborhoods | 164 (92.66%) | 48 (97.96%) |
| No context | 2 (1.13%) | 1 (2.04%) |

Single/multi/unknown are building associations to parcels, not counts of unique
parcels. Michael has 116 accepted unique parcels; Santa Rosa has eight.
Useful local claims remain exclusively parcel-scoped on **110/177 (62.15%)**
Michael and **46/49 (93.88%)** Santa Rosa roofs; some of those roofs independently
have NSI or OSM direct context. Across all providers, only-parcel context beyond
neighborhoods is 67/177 and 3/49 respectively.

Michael improves from the reported old experiment's **66 footprint matches and
zero useful semantics** to **164/177 (92.66%)** beyond-neighborhood contexts,
including **97/177 (54.80%)** direct contexts and **67/177 (37.85%)** parcel-only
contexts. Eleven roofs have only neighborhood context, and two remain unknown.
The new current OSM extract has 129 accepted footprint associations, but just
one directly useful named place. Different date/query data makes 66 versus 129
an unsuitable accuracy comparison. The material gain comes from semantic county
and NSI attributes, not more generic `building=yes` matches.

## Provider overlap and incremental value

Order matters. These tables use local parcels, school properties if applicable,
NSI, historical OSM, then current OSM. Exclusive means a provider is the only
source of any displayable context; increment means newly covered roofs in the
stated order.

Michael:

| Provider | Useful coverage | Exclusive | Ordered increment |
|---|---:|---:|---:|
| bay_2017 | 160 (90.40%) | 9 (5.08%) | +160 (90.40%) |
| nsi | 84 (47.46%) | 0 (0.00%) | +4 (2.26%) |
| osm_historical | 0 (0.00%) | 0 (0.00%) | +0 (0.00%) |
| osm_current | 164 (92.66%) | 11 (6.21%) | +11 (6.21%) |

Cumulative coverage: **160 → 164 → 164 → 175**. All eleven last-step additions are
neighborhood-only. Current OSM's AMI Stores claim adds detail to an already
covered roof. Bay contributes 79 additional beyond-neighborhood roofs over
the reviewed NSI/OSM fallback (160 county plus 85 fallback, overlap 81).

Pairwise semantic overlaps: bay\_2017+nsi: **80 (45.20%)**; bay\_2017+osm\_historical: **0 (0.00%)**; bay\_2017+osm\_current: **149 (84.18%)**; nsi+osm\_historical: **0 (0.00%)**; nsi+osm\_current: **82 (46.33%)**; osm\_historical+osm\_current: **0 (0.00%)**.

Santa Rosa:

| Provider | Useful coverage | Exclusive | Ordered increment |
|---|---:|---:|---:|
| sonoma_parcels | 48 (97.96%) | 3 (6.12%) | +48 (97.96%) |
| sonoma_schools | 41 (83.67%) | 0 (0.00%) | +0 (0.00%) |
| nsi | 14 (28.57%) | 0 (0.00%) | +0 (0.00%) |
| osm_historical | 18 (36.73%) | 0 (0.00%) | +0 (0.00%) |
| osm_current | 40 (81.63%) | 0 (0.00%) | +0 (0.00%) |

Parcels already cover all 48 useful results. School, NSI and OSM therefore add
**zero unique roofs in this order**, while adding names, modeled uses, direct
building evidence and event-time site context. County schools alone provide
41/49 named property memberships. Reviewed NSI/OSM without either county source
covers 42/49; adding school-property membership raises that to 45/49, and
current parcels add the final three.

Pairwise semantic overlaps: sonoma\_parcels+sonoma\_schools: **41 (83.67%)**; sonoma\_parcels+nsi: **14 (28.57%)**; sonoma\_parcels+osm\_historical: **18 (36.73%)**; sonoma\_parcels+osm\_current: **40 (81.63%)**; sonoma\_schools+nsi: **13 (26.53%)**; sonoma\_schools+osm\_historical: **17 (34.69%)**; sonoma\_schools+osm\_current: **37 (75.51%)**; nsi+osm\_historical: **9 (18.37%)**; nsi+osm\_current: **12 (24.49%)**; osm\_historical+osm\_current: **18 (36.73%)**.

## School, property and temporal findings

[Bay County's 2017 parcel layer](https://gis.baycountyfl.gov/arcgis/rest/services/InternalUse/ArchiveParcels/MapServer/17)
provides human-readable property descriptions, building counts and structure
attributes. It is **2017 pre-event property context**, not an October 2018
observation. Unknown ownership/vacancy descriptions such as COUNTY and VACANT
do not become building uses. Literal MOBILE HOME, VEH SALE/REPAIR,
REPAIR SERVICE and STORES, 1 STORY descriptions are now recognized; no numeric
code guessing or threshold adjustment was used.

[Sonoma public parcels](https://www.arcgis.com/home/item.html?id=4a3809ba63674b179f5c639547b95163)
are current records. Their 2025 roll and 2026 record edits stay in raw evidence;
record edit timestamps are also carried on claims. Primary plus secondary
building counts are used only when both are known. Missing counts are not zero.

[School_Parcels](https://www.arcgis.com/home/item.html?id=b9bf5d61fa7147ce9f5481989ef78ede)
advertises **July 20, 2017**, but its live schema reports a **June 10, 2022**
data edit. Its 41 memberships are therefore labeled **advertised July 2017;
vintage unverified**, separately from verified event/pre-event coverage.
They comprise 22 in the combined Roseland Collegiate Prep, St Rose property and
19 in the Cardinal Newman High School property. No individual building claim or
critical-infrastructure flag is generated from these areas.

Historical OSM independently supplies **18/49 (36.73%)** event-snapshot Cardinal
Newman campus memberships. Current OSM school sites cover **37/49 (75.51%)**:
18 Cardinal Newman, eight St Rose Elementary and eleven in an unnamed school
site. The all-source union is **42/49 (85.71%)**, with **zero critical labels**.
County and OSM boundaries/names differ around adjacent schools and the former
Ursuline property. These differences remain dated, scoped assertions rather
than one canonical campus identity. In particular, the broad school-property
polygon also covers the mapped convent; membership does not establish roof use.

## Manual QA and concrete findings

The agent inspected **all 226 claim rows and projected building overlays**,
26 nine-panel sheets plus two scene overviews. This covered every named-place
and site result, all comparable conflicts, suspicious NSI records, and
rejected/ambiguous candidates. There were no explicit emergency/critical
candidates in either scene. This is source/spatial review, not field validation,
and no semantic error rate or critical-facility accuracy is claimed.

**Michael: 11/177 buildings (6.21%), eleven selective actions.**

- Six building promotions held at b0000, b0001, b0002, b0122, b0129 and b0166.
  Image-edge competition, partial roofs and source offsets mean one labeled
  roof plus assessor `BLDCNT=1` does not prove the primary structure. Useful
  dated parcel claims remain displayable.
- Five NSI claims held: b0060 (unresolved government/residential use), b0098
  (2.1× footprint area and neighboring-roof uncertainty), b0157/b0158
  (unresolved agricultural model versus retail property), b0164 (modeled
  residential versus mapped convenience store and historical warehouse).
- b0164 retains current mapped **AMI Stores**, a moderate OSM footprint
  association: 67.81% target coverage, IoU 0.399, 6.57 m centroid offset.
  The business name remains an unverified current map assertion, not event-era
  truth. Historical warehouse property covers three raw roofs and stays parcel-scoped.
- b0051 retains linked residential/retail NSI occupancies. A dated residential
  parcel description does not justify deleting a possible mixed current model.
  Automated comparable conflicts fall from three to one.
- b0006/b0169 retain rejected unlinked NSI records; b0166 retains a rejected
  competing near point. Unknowns remain b0148 and b0159.

**Santa Rosa: 8/49 buildings (16.33%), ten selective actions.**

- b0002: **The Quad** is an open-area `location=plot` node 3.845 m outside
  the roof. Its direct name claim is held; independent school-site context remains.
- b0017: **Marian Sisters** POI lies 2.881 m outside an accessory roof.
  The [official contact](https://www.mariansisters.com/contact.html) and
  [convent description](https://www.mariansisters.com/growth.html) support the
  neighboring Mater Dei Convent complex at 400 Angela Drive, not an exact
  association to this roof. The POI claim is held; b0016's mapped convent name remains.
- Six buildings have NSI holds: b0013 (agriculture/house disagreement), b0014
  (3.2× footprint), b0016 (unresolved industrial/school stack at convent),
  b0020 (larger footprint at adjoining-roof edge), b0030 (2.3× footprint),
  b0043 (3.3× footprint amid connected roofs). Both entries of the b0016 and
  b0043 stacks are preserved in evidence, with display withheld.
- Eleven other roofs retain linked EDU1/COM3 modeled stacks. Nine comparable
  school-building/model differences remain visible for review; mixed modeled
  occupancy is not silently collapsed or treated as a verified retail tenant.
- b0018's current Roseland Collegiate Prep place has a 1.848 m gap and
  38.955 m competitor margin. The [official school site](https://rcp.roselandsd.org/privacy-policy)
  confirms 80 Ursuline Road. It stays a moderate current mapped place;
  `office=educational_institution` now normalizes to education.
- b0031 fails the county school's 80% overlap threshold but independently
  qualifies for historical/current OSM campus membership. b0047 remains
  unknown: a current vacant-homesite parcel is not evidence of roof use.

Overall intervention rate: **19/226 (8.41%)**, not measured error. Spatial
acceptance counts deliberately remain pre-hold counts; displayable semantics,
overlap and incremental coverage are recomputed after holds. Rejected
neighbor candidates on otherwise successful roofs are not false matches.

## Licensing, implementation and validation

OSM needs attribution to OpenStreetMap contributors and compliance with
[ODbL terms](https://www.openstreetmap.org/copyright). NSI is USACE modeled
inventory; retain its attribution, release qualification and
[technical source limitations](https://www.hec.usace.army.mil/confluence/nsi/technicalreferences/2026/technical-documentation).
County source credits and terms URLs are carried on every claim and report.

Both Sonoma item metadata license sections explicitly include No Derivatives
terms. This is a distribution gate for derived associations; do not assume
a public FeatureServer grants unrestricted reuse. Bay archive item metadata has
blank license text, which also does not establish blanket redistribution
permission. The local downloads, feature exports, review images and detailed
manual-review JSON remain ignored. No provider extracts are committed.

The existing architecture was sufficient. Changes are a three-scene allowlist,
bounded Bay/Sonoma adapters, scene-sized metrics/report attribution, conservative
literal description mappings, the education-office normalization fix, and an
optional claim-kind selector for manual holds so a doubtful structure promotion
can be withheld without deleting sound parcel context. Geometry thresholds,
caching design and independent relationship matchers are unchanged.

**50 focused tests pass** (45 existing plus five targeted tests). Added coverage
checks county schema/truncation, count/description normalization, school-site
scope and uncertain vintage, pre-event labels/selective promotion holds, and
education-office semantics. Both completed audits replay offline against exact
review hashes. Harvey's existing QA file also replays unchanged, including its
evidence hash and original coverage. Canonical inputs and all model/frontend
assets remain untouched.

## Artifacts and replay

For each scene, local artifacts are under
`local_experiments/gis_context_v2/<scene>/`:

- `audit.json`, `summary.md`, `review.html`, `review.csv`, `review.geojson`;
- `manual-review.json`: all reviewed UIDs, selective actions and exact input,
  provider-response and normalized-evidence hashes;
- `qa-map-*.png`, `qa-overview.png`, `qa-evidence.json`.

The HTML links the adjacent spatial sheets. The sheets show automated candidates;
the HTML/JSON also show the manual holds. Review files and caches are required
to replay these completed decisions on another checkout; without them, fetch
and perform a new review. Changed evidence cannot reuse an old review.

```powershell
$gisPython = 'local_experiments/gis_context_v2/.venv/Scripts/python.exe'
& $gisPython -B -m app.backend.gis_context `
  --scene hurricane-michael_00000247 `
  --post-label data/tier1/labels/hurricane-michael_00000247_post_disaster.json `
  --snapshot 2026-09-28 `
  --qa-review local_experiments/gis_context_v2/hurricane-michael_00000247/manual-review.json
& $gisPython -B -m app.backend.gis_context `
  --scene santa-rosa-wildfire_00000014 `
  --post-label data/tier1/labels/santa-rosa-wildfire_00000014_post_disaster.json `
  --snapshot 2026-09-28 `
  --qa-review local_experiments/gis_context_v2/santa-rosa-wildfire_00000014/manual-review.json
& $gisPython -B -m unittest app.backend.gis_context.test_gis_context -v
```

SHA256 checkpoints:

| Input/evidence | Michael | Santa Rosa |
|---|---|---|
| Canonical manifest | `89d910f2dce1b13709c088af977a88ee9902b285c98bb4cfaf12c6fe7b4cbb0c` | `15797def71df27edc6b8808d641d8f6e4abab701a6630f71c00d0c28167d4902` |
| Raw POST label | `d191f1c0bc1f0cd63211c7ec20dd5c08eb21d97235f1a2e99cc6453221c1dfcb` | `90c746543078ca01c03f9f8040f91e18820f6685c69a3e406f352c12aa60390c` |
| Normalized pre-QA evidence | `d1d8e7089dccc158dead8b83e44b5bed11b6b792d26c0a9badade954f7048dce` | `7e68f25dbf1f87939ad384f1e405179cf40d149dadd91943ad2a4260cccf2fbd` |
| Local manual-review file | `0f81043fcc5fa2e3a232949b00891591061c7b213fc3ca1b7071686cfdcf8b65` | `cfc9e780d644e3e8610039183d31395d07f912bdc2bd1f05ae0559388ab4b1b7` |

Stop here for review. This GO does not authorize implementation of the frontend,
publication of county-derived data, or expansion to the remaining scenes.

