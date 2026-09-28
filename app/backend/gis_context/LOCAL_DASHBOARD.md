# Local Building Context review

The dashboard can display reviewed GIS v2 context for Harvey (76 buildings),
Michael (177), Santa Rosa (49), Florence (56), and SoCal (48). The five overlays
cover 406 buildings; 386 have displayable context. Some have only surrounding-
area context. No-context selections show no GIS section.

## Start or rebuild locally (PowerShell)

The five reviewed overlays are versioned under `app/demo_gis_context` and loaded
by default. A fresh checkout needs only the environment setup in the
[backend README](../README.md#portable-scene-only-demo), with no GIS audit files.
`GIS_CONTEXT_ROOT` remains an explicit development override.

From the repository root, start/restart the local demo in the background:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\app\backend\run_local_gis_demo.ps1 -Restart
```

This uses a process-only execution-policy override because this Windows machine
disables `.ps1` files by default; it does not change the machine policy. The helper
checks that the saved PID belongs to this environment's local uvicorn server
before restarting its process tree. Logs and PID stay in the ignored GIS folder,
created if absent. The helper prefers the root `.venv`, with the older ignored
GIS environment as a fallback. It exports only with `-RebuildLocalOverlays`, which
requires the existing reviewed audits and selects the resulting local overlays.
Omit `-Restart` to reuse a running instance. Open **http://127.0.0.1:8000/**.

For a foreground server (after stopping any server already using port 8000), or
to run the export separately, use the existing ignored GIS environment:

```powershell
$demoPython = '.\local_experiments\gis_context_v2\.venv\Scripts\python.exe'
& $demoPython -B -m app.backend.gis_context.export_dashboard
$env:GIS_CONTEXT_ROOT = (Resolve-Path '.\local_experiments\gis_context_v2\overlays').Path
$env:DEMO_SCENES_ONLY = '1'
& $demoPython -B -m uvicorn app.backend.api:app --host 127.0.0.1 --port 8000
```

Stop a foreground server with Ctrl+C before restarting on that port.

If setting up another environment, install the lightweight server dependencies:

```powershell
python -m venv local_experiments/gis_context_v2/.venv
& .\local_experiments\gis_context_v2\.venv\Scripts\python.exe -m pip install -r app/backend/requirements-demo.txt
```

The exporter uses only Python's standard library and the three existing reviewed
`local_experiments/gis_context_v2/<scene-id>/audit.json` files. It performs no source
queries and does not rerun the audits. These ignored audit files must already be
available; a fresh clone alone does not contain the county records.

`DEMO_SCENES_ONLY=1` skips the checkpoint and inference imports. Scene crops and
results work normally. Uploads and examples still preview and clear context, but
requesting a new prediction returns an explicit 503 explaining scene-only mode.
`/health` reports `mode: scenes_only` and `inference_available: false`. Normal
startup with this variable unset still loads the classifier, and the normal
prediction request/response contract is unchanged.

## What to inspect

Use Previous/Next to find each scene, then click or keyboard-select a footprint.
The selected building ID appears in the scene status; IDs below are existing
demo-building IDs, not GIS provider IDs.

| Scene | Selection | Expected context |
| --- | --- | --- |
| Harvey | `b0006` | Parcel-linked single-family structure use and separately modeled residential use |
| Harvey | `b0004` | Mapped use: Dental office; Property use: Low-rise office; then Modeled use: Commercial / Healthcare / Professional services |
| Harvey | `b0009` | Historical and current mapped place claims with separate timing |
| Harvey | `b0069` | Compact, muted area-only residential context |
| Michael | `b0010` | Residential: multifamily property, up to 10 units, **2017 pre-event** |
| Michael | `b0032` | Commercial: retail property, **2017 pre-event** |
| Michael | `b0148` | No context section; damage result remains visible |
| Santa Rosa | `b0000` | One Education/campus statement; **School-site record · date uncertain**; category support from multiple sources |
| Santa Rosa | `b0006` | One named campus statement plus a separate mixed modeled-use statement and a visible disagreement note |
| Santa Rosa | `b0018` | Roseland Collegiate Prep, without redundant "Educational institution"; site: Within Roseland Collegiate Prep / St. Rose campus |
| Santa Rosa | `b0048` | No context section |

The collapsed section shows a category and up to three short, scope-labeled
statements. Short timing labels remain visible. **Data sources & limitations**
expands source names, original classifications, dates and scope qualifications;
it also holds lower-priority context such as a surrounding neighborhood. Area-only
selections use a smaller, muted presentation. OpenStreetMap attribution remains
visible. No facility badges are added.

School-site technical timing (including **vintage unverified**) stays in the
disclosure and structured temporal relation. Verified historical/current mapping
uses a short combined label. The disclosure has a rounded blue keyboard
`:focus-visible` state in both its collapsed and expanded states.

Context clears on no-context selections, Clear, scene changes, filters that remove
the selected footprint, manual uploads and crop examples. PRE/POST modes preserve
the selected building and its context.

## Optional overlay boundary

The exporter writes deterministic `<scene-id>.json` sidecars under the ignored
`local_experiments/gis_context_v2/overlays/` directory. It validates completed
provider/row/manual-review status, reviewed UID coverage and the canonical manifest
hash before writing. It consumes final displayable claims only, excludes weak
matches, enforces recorded claim holds (including kind-specific holds), and uses
reviewed labels rather than raw tags to avoid resurrecting withheld names. It
rejects a name hold whose reviewed name has not been cleared.

Raw audits are unchanged. Sidecars retain each approved claim with its reviewed
label, original classification values, source/dataset/release/snapshot,
attribution and qualifications. Classification fields are allowlisted: stale raw
names, candidates, geometry, GIS record IDs, free-form QA notes, scores and modeled
years-built are excluded. The header includes manifest and audit SHA-256 values
for traceability. Committed tests use synthetic evidence.

When `GIS_CONTEXT_ROOT` is explicitly configured, `GET /demo-scenes/{scene_id}`
validates the optional sidecar schema, reviewed status, exact manifest hash and UID
coverage, then joins nonempty context into `building.building_context`. It never
modifies `prediction` or writes canonical scene files. Missing, stale, malformed
or unreviewed sidecars are ignored; invalid sidecars emit a server warning. Sidecar
files and raw audits are outside the static asset routes. With no override, the
committed overlays supply context for five reviewed scenes; Matthew and Palu
have no GIS context. Packaged manifest hashes normalize CRLF/LF checkout
differences; other manifest changes still fail closed.

## Normalization and future reporting

`presentation.py` is a deterministic standard-library layer between the reviewed
claim export and the frontend. Its small alias table recognizes the current
classification vocabulary, preserves useful subtypes, and falls back to the
audited broad category or Unknown. It never guesses a use from a name, changes a
match/threshold, calls an external API, or invokes an LLM.

The canonical taxonomy is Residential, Education, Medical / Healthcare,
Commercial, Professional Services, Industrial, Warehouse, Government / Civic,
Emergency Services, Religious, Lodging, Recreation / Community, Transportation,
Agricultural, Mixed Use and Unknown. Reserved categories do not create new claims
or critical-facility labels. Area is a **scope**, not a building-use category.

Each schema-v2 `building_context` includes:

- `claims`: individual approved evidence with original classification and provenance.
- `contexts`: canonical category and subtype concepts, readable labels, name,
  scope, modeled flag, temporal relation, multi-structure flag, qualifications and
  references to supporting claims. Each concept retains its own evidence links.
- `statements`: deterministic UI wording and references to its supporting contexts,
  direct supporting claims and separately identified corroborating claims. The
  optional `support_label` distinguishes category support from shared site identity.
- `primary_category`, `primary_label`, `primary_statement_ids`, `area_only`,
  source-support indicators, structured reviewed `conflicts` and readable notes.

Aliases such as generic office plus low-rise office consolidate within one scope
and time; all original evidence remains. A parcel claim identical to its approved
single-structure promotion is not repeated or counted as a second source.
Named school-site statements can combine the **same name** across dated contexts;
their separate dates remain structured and the combined timing stays qualified.
Unnamed school use can support the Education category across scopes, explicitly
recorded as `education_category_only`; it does not establish a roof's identity.
Historical/current OSM and multiple Sonoma layers count as one provider family
each when showing multiple-source support, not as independent observations.

The final vocabulary review covered the distinct approved classifications in all
three scenes. Bare OSM `house` remains **House**, rather than implying single-family
occupancy; **Mobile home** and **Rural residential** retain their source distinctions.
`dentist` becomes **Dental office** with the scope label **Mapped use** when unnamed.
Redundant category wording is omitted from named-place summaries; raw names,
classifications and all subtype concepts remain available in evidence.

Mixed modeled occupancies keep all concepts and their claim links. A modeled
School component can corroborate Education while its commercial component remains
in a separate mixed-use statement. Conflicting categories, differing names and
reviewed disagreements remain inspectable and are not merged into agreement.
Areas never corroborate building use and stay outside the primary view when
stronger context exists. Direct identities, structure use, modeled use, properties,
sites and areas otherwise determine order; mixed modeled use follows property
context and keeps a short category list. Consolidated education inherits the
priority of its useful supporting context without inheriting that context's scope.
The heading uses the highest-priority classified evidence, with equally useful
different categories producing **Mixed Use**. A name-only claim cannot determine
use or block a category supported by separate evidence. Date/category/text ordering
breaks display ties consistently without depending on provider input order.

A future assessment can consume `contexts`, `conflicts` and their evidence links
alongside the existing, separate prediction probabilities. It need not parse UI
wording or provider strings. This milestone contains no LLM/report implementation.

## Validation

```powershell
node app/frontend/test_scene_dashboard.js
node app/frontend/test_scene_inspection.js
node app/frontend/test_scene_page_integration.js
& .\local_experiments\gis_context_v2\.venv\Scripts\python.exe -B -m unittest app.backend.test_building_context app.backend.test_api_demo_scenes app.backend.gis_context.test_gis_context app.backend.gis_context.test_presentation
```

The integration was checked in local headless Chrome at desktop and 390-pixel
mobile widths, including all examples above, clearing, filtering, scene switching,
imagery modes, expanded context, uploads and examples. Screenshots and the local
browser verification report for the cleaned presentation are ignored under
`local_experiments/gis_context_v2/final-context-review/`. All 77 Python tests and
three frontend Node tests pass. Keyboard Tab/Enter, collapsed/expanded focus,
original wording and school timing were also checked in real Chrome. No model
inference is needed.

Portability checks also cover the committed default overlays, a relocated data
directory without an audit workspace, LF/CRLF manifests, stale-manifest rejection,
and development overrides. The packaged contexts equal the reviewed local export.

## Publication boundary

External GIS sources may have attribution, redistribution, or licensing
requirements that should be reviewed before broader/public/commercial use.
Development sidecars and raw extracts remain ignored; the compact reviewed demo
overlays are versioned. Canonical scene manifests and
production deployment configuration are unchanged.
