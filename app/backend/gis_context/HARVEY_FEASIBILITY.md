# Harvey GIS v2: real feasibility audit

**GO for separate Michael and Santa Rosa source-feasibility pilots, with the
same scope, temporal labels, conservative matching and manual QA.** Harvey
supports useful property/use context, but does not validate definitive building
identity or emergency-facility detection. No other scene or frontend integration
was performed in this run.

The completed real-data audit covers the canonical **76 Harvey buildings**.
Combined unique displayable semantic context is **76/76 (100%)**, including nine
buildings with **only current neighborhood land-use context**. Excluding these
broad areas, coverage is **67/76 (88.16%)**. Direct building/place context is
**48/76 (63.16%)**, including qualified assessor links and modeled occupancy.
These tiers must remain separate; 100% does not mean every building has an
identified use or name.

## Input and reproducibility

- Found raw POST JSON:
  `data/tier1/labels/hurricane-harvey_00000177_post_disaster.json`.
- Raw schema: `features.lng_lat` contains 76 UID-keyed geographic WKT polygons;
  `features.xy` contains 76 pixel polygons. All **76/76 packaged UIDs join
  exactly once**, with identical UID sets. The demo manifest was not regenerated.
- Actual `metadata.capture_date`: **2017-08-31T17:38:50.685Z**. Overpass uses
  **2017-08-31T17:38:50Z**, flooring 0.685 seconds to its documented timestamp
  precision; the original precision remains in the audit.
- All geometry calculations use **EPSG:32615**, meters and square meters.
  Bbox: `(-95.64524509351139, 29.765651909698388,
  -95.63979591472028, 29.770967079713326)`, derived from all raw roofs plus
  50 m. This is not an image geotransform or full image extent.
- Raw label SHA256:
  `7a26b61a641fc8509107250f34d0c022c97e5179972b4c8fdd3d681b8bb715f7`.
  Canonical scene manifest SHA256:
  `c2e064df86704e606447cd11406ca25e1403fa31083f10247c9a7d590248f6ba`.

Final successful scene-wide extracts: HCAD **155 parcels**, NSI **136 public
records**, historical OSM **437 raw objects / 10 parsed spatial features**, and
current OSM **571 / 25**. All four adapters completed with zero parse issues.
HCAD and NSI were fetched on 2026-09-28 at approximately 07:37 UTC. Current OSM
database time is **2026-09-28T07:59:11Z**. Exact request, source, fetch time,
response hash and cache directory are in `audit.json` and cache metadata.

Several Overpass attempts failed with timeouts/504s. Recursive named-route
expansion produced 15,083 current objects, including long highway routes.
A bounded all-object bbox with `out meta geom` succeeded for both snapshots;
semantic filtering occurs locally. A successful diagnostic historical GET
response was reused only after checking that its URL, query, bbox and snapshot
were identical; original fetch/hash/request provenance is retained. Failed
requests never became zero-coverage results. Queries were scene-wide, never
one request per roof. The final extracts use the main Overpass service.

Offline replay, using the ignored environment/cache already on this machine:

```powershell
& 'local_experiments/gis_context_v2/.venv/Scripts/python.exe' -B `
  -m app.backend.gis_context `
  --post-label data/tier1/labels/hurricane-harvey_00000177_post_disaster.json `
  --snapshot 2026-09-28 --qa-review app/backend/gis_context/HARVEY_QA.json
```

The reviewed status is `reviewed_with_findings`. [HARVEY_QA.json](HARVEY_QA.json)
records the actual manual decisions and all reviewed UIDs. Input, provider and
normalized-evidence hashes must match before those decisions can be replayed.
Omit `--qa-review` to reproduce automated results awaiting a new review; add
`--fetch` only for missing extracts. See [README.md](README.md) for setup.

## Coverage after manual review

Every percentage below uses 76 real packaged buildings. Counts overlap.

| Measurement | Count / 76 | Percent |
|---|---:|---:|
| HCAD accepted parcel association | 67 | 88.16% |
| HCAD useful property context | 64 | 84.21% |
| HCAD single-structure links / qualified structure descriptions | 28 | 36.84% |
| HCAD multi-structure parcel associations | 39 | 51.32% |
| HCAD useful context that remains parcel-only | 36 | 47.37% |
| HCAD multiple-plausible-parcel ambiguity | 0 | 0% |
| NSI candidate present | 74 | 97.37% |
| NSI automated accepted spatial association | 44 | 57.89% |
| NSI displayable modeled occupancy after two holds | 42 | 55.26% |
| Historical OSM useful context | 4 | 5.26% |
| Current OSM useful context | 66 | 86.84% |
| **Combined unique displayable context** | **76** | **100%** |
| **Combined excluding neighborhood land-use areas** | **67** | **88.16%** |
| Direct building/place context, including modeled/qualified links | 48 | 63.16% |
| Event-aligned useful context (2017 property + historical OSM) | 67 | 88.16% |
| Event-aligned direct building/place context | 28 | 36.84% |
| Broad-use category, all scopes | 76 | 100% |
| Broad-use category excluding land-use areas | 67 | 88.16% |
| Neighborhood land-use area context | 61 | 80.26% |
| Only neighborhood area context | 9 | 11.84% |
| No context of any supported scope | 0 | 0% |
| Direct mapped name retained after QA | 3 | 3.95% |
| Any mapped name, including neighborhood/park names | 37 | 48.68% |
| Site/area context, including neighborhoods | 64 | 84.21% |
| Site context excluding neighborhoods (one park) | 3 | 3.95% |
| Critical/emergency facility candidates or labels | 0 | 0% |
| Buildings with an explicitly ambiguous candidate | 11 | 14.47% |
| Buildings with any rejected/ambiguous candidate | 69 | 90.79% |

HCAD's three nonsemantic parcel matches are b0002, b0003 and b0075. Descriptive
attributes support no use claim there. All accepted parcels have a known
single/multiple-structure classification; no zoning claim was generated.

NSI supplies 50 accepted records on 44 buildings before QA and 48 displayable
records on 42 buildings afterward. b0004 and b0005 each retain four linked
occupancies (professional, medical office, wholesale and retail), without
forcing a primary use. All remain modeled; `med_yr_blt` stays in raw evidence
and never becomes an exact building year.

Thirty buildings (39.47%) have NSI candidates but no accepted spatial match.
There are 125 rejected candidate associations: 30 unlinked interior records,
87 outside direct association, five near points needing independent evidence,
and three near points with competing roofs. Nine buildings have multiple
unlinked NSI records; two additional buildings have ambiguous near points.
HCAD rejects all parcel candidates for nine buildings (11.84%): eight roofs
span several narrow parcels, and b0069 straddles parcel edges. The 90.79%
rejection figure includes neighboring candidates around otherwise successful
matches; it is **not a false-match/error rate**.

## Provider overlap and incremental value

| Provider | Useful buildings after QA | Exclusive to provider | Increment in stated order |
|---|---:|---:|---:|
| HCAD | 64 (84.21%) | 3 (3.95%) | +64 (84.21%) |
| NSI | 42 (55.26%) | 0 (0%) | +1 (1.32%) |
| Historical OSM | 4 (5.26%) | 1 (1.32%) | +2 (2.63%) |
| Current OSM | 66 (86.84%) | 9 (11.84%) | +9 (11.84%) |

Order is HCAD -> NSI -> historical OSM -> current OSM. Cumulative coverage is
64 -> 65 -> 67 -> 76. All nine final additions are neighborhood-area context
(b0032, b0033, b0039-b0044, b0069), not newly identified building uses.
NSI still adds modeled detail on overlapping buildings even when unique
coverage barely increases.

Pairwise semantic overlaps: HCAD/NSI **41 (53.95%)**, HCAD/historical OSM
**1 (1.32%)**, HCAD/current OSM **56 (73.68%)**, NSI/historical OSM
**2 (2.63%)**, NSI/current OSM **36 (47.37%)**, historical/current OSM
**2 (2.63%)**. Pre-QA NSI overlaps were 43 with HCAD and 38 with current OSM.

## Names, time differences and manual QA

Codex manually inspected projected spatial sheets for all 76 roofs, raw
candidate/claim evidence, all **38 initially named-result buildings**, all
critical candidates (**none**), both automated conflict cases, 20 designated
representative contexts and ten designated rejection cases. This is agent
review of source associations and semantics, not independent field validation.
The selected IDs and individual notes are in [HARVEY_QA.json](HARVEY_QA.json).

There were five current direct named records on four buildings: Prosperity
Bank, Mills Dental Group, Bicycles and Smoothies, Trill Terpz and Allstate.
Historical direct naming adds Allstate Insurance on the same Allstate record.
Terraces on Memorial names **31 neighborhood memberships**, not 31 buildings.
Another residential polygon covers 30 roofs without a name. Terry Hershey Park
adds historical site membership to b0002, b0003 and b0075; current membership
passes only for b0075. No explicit campus or critical-facility result exists.

| Reviewed example | Finding / disposition |
|---|---|
| b0001, Prosperity Bank | Moderate OSM footprint link: 57.04% roof coverage, IoU .495, centroid 5.75 m. HCAD Bank and the [official 1070 Highway 6 S location](https://locations.prosperitybankusa.com/prosperity-bank-highway-6-103f76096969) corroborate use/address. Current mapped name retained, never backdated. |
| b0004, mapped Mills Dental Group | Interior point; the linked site now redirects to [Four Hills Dentistry at 1011 South Texas 6](https://www.fourhillsdentistry.com/). Withhold the old name; retain explicit dental-use context. No replacement business identity was added. |
| b0008, bicycle rental and tobacco shop | Same mapped street address, potentially stale POI versus co-tenancy. The [bicycle business page](https://bicyclesandsmoothies.weebly.com/) discusses reopening elsewhere. Hold its current claim; retain Trill Terpz only as an unverified current mapped shop. |
| b0008, historical bicycle point | Exists in the 2017 extract but is **5.075 m** outside the roof and fails the unchanged 5 m rule. Current point is **0.727 m** away. Current-only association does not mean the business opened after Harvey. |
| b0009, Allstate | Stable node: Allstate Insurance in 2017 vs Allstate now. Same office category; name variation, not material use conflict. The [official agency page](https://agents.allstate.com/john-burroughs-houston-tx.html) corroborates Suite 216 at 14515 Briarhills Parkway. |
| b0062, NSI 123541931 | Point falls within a 33.03 m2 xBD roof; NSI reports a 218.97 m2 footprint, amid several nearby roofs. Association unresolved: modeled claim withheld. |
| b0066, NSI 123541959 | 87.85 m2 xBD roof vs 204.20 m2 source footprint, multi-roof parcel and nearby alternatives. Modeled claim withheld pending independent footprint validation. |
| b0032/b0033/b0039-b0044 | Multiple parcels and unlinked NSI points under each roof. Rejections upheld; only neighborhood-area context remains. |
| b0017 / b0027-b0028 | Shared parcels do not establish individual structure use. Neighboring or competing NSI points remain rejected. |
| b0002/b0003/b0075, park | Historical/current boundary differences preserved; b0002/b0003 are historical memberships only. b0075 retains both dated memberships; raw leisure changes park -> nature_reserve. No park name is promoted to roof identity. |

Automated comparison initially flagged **two buildings (2.63%)**: the b0008
tenant-use difference and the b0009 historical/current name variation. After
holds, one displayable comparison flag remains (**1/76, 1.32%**, Allstate).
Manual review additionally records changed park inclusion at b0002/b0003, the
bicycle point relocation at b0008 and the park tag change at b0075. These are
time/geometry differences, not proof of physical use changes. Attribute
comparison alone does not detect every historical/current disagreement.

Before holds, four direct OSM records on three buildings have current-only
associations; one is the already-historical bicycle record at a different point.
The other three records (bank footprint, dental POI, tobacco shop) do not appear
in the event snapshot for this bbox. Absence here does not establish a record's
creation date or when a business opened. After QA, two current-only names
remain, plus unnamed dental-use context.

**Apparent review-intervention rate: 4/76 buildings (5.26%)**, comprising two
suspicious NSI associations (**2/44, 4.55%** of automated NSI-covered buildings)
and two names/activity assertions requiring holds (**2/5, 40%** of current direct
named records). One name differs from its current official website; the other
activity assertion is unresolved. These are not four proven spatial errors.
Independent semantic false-positive rate remains unmeasured. No additional
obvious scope/matching error was found in retained claims during this review;
that does not establish zero real-world error.

## Limitations, validation and decision

Visible xBD/parcel/OSM offsets, roofs crossing parcel lines, coarse historical
park boundaries and modeled NSI point locations limit identity precision.
No geometry was shifted and no matching threshold was relaxed. Area was used
to question geometric correspondence, never to infer a roof's purpose.
The 2017 assessor release is event-year evidence, not a capture-time survey.
OSM history means what was mapped at capture, not verified ground truth.

The bbox extract can miss enclosing polygons with no node/direct member in
the bbox. There were no usable site relations in this scene, so relation/campus
capability is tested synthetically but not validated by a real Harvey campus.
Results are dominated by residential/property context and cannot establish
performance on the other disasters or critical-facility recall.

**45 focused GIS tests pass**, including regressions for real timestamp
precision, excessive relation expansion, Bank/compound assessor descriptions,
duplicate dental tags, neighborhood scope, and replayable QA holds that refuse
changed input/provider/normalized evidence. The actual four-provider audit and
reviewed replay run offline successfully. Synthetic tests are not coverage
evidence. No inference, training or unrelated regression suite was run.

All bulky extracts, maps and generated JSON/CSV/HTML/GeoJSON remain ignored in
`local_experiments/gis_context_v2/`. The flattened CSV reports every required
flag for all 76 UIDs. Original claims, withheld values, spatial candidates,
pre-QA metrics and findings remain reviewable. Only concise findings and review
decisions are versioned. Frontend, scene assets/manifests and model/research
code are unchanged; no push, deployment or production action was taken.

Attribute **City of Houston GIS / HCAD**, **USACE NSI**, and
**© OpenStreetMap contributors**. OSM-derived distribution must respect
[ODbL](https://www.openstreetmap.org/copyright); Houston requests source citation
and independent verification under its [GIS terms](https://mycity.houstontx.gov/about.html).
Use only public NSI data and confirm field-specific redistribution rights before
publishing extracts; public API availability is not a blanket license for every
underlying source field. Detailed provider terms remain in [README.md](README.md).
