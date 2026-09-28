# Local Building Context review

The dashboard can display the completed GIS v2 reviews for Harvey (76 buildings),
Michael (177), and Santa Rosa (49). All 302 buildings are represented in the local
overlays; 76, 175, and 48 respectively have displayable context. Some have only
surrounding-area context. No-context selections show no GIS section.

## Start or rebuild locally (PowerShell)

From the repository root, using the existing ignored GIS environment:

```powershell
$demoPython = '.\local_experiments\gis_context_v2\.venv\Scripts\python.exe'
& $demoPython -B -m app.backend.gis_context.export_dashboard
$env:GIS_CONTEXT_ROOT = (Resolve-Path '.\local_experiments\gis_context_v2\overlays').Path
$env:DEMO_SCENES_ONLY = '1'
& $demoPython -B -m uvicorn app.backend.api:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/**. If the local server is already running, open that
URL directly. Stop a foreground server with Ctrl+C before restarting on that port.

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
| Harvey | `b0006` | Modeled single-family residential, separate 2017 event-year property and parcel-linked structure context |
| Harvey | `b0004` | Current dental use with the held business name absent; multiple modeled occupancies retained |
| Harvey | `b0009` | Historical and current mapped place claims with separate timing |
| Michael | `b0003` | Modeled use and explicitly **2017 pre-event** property context |
| Michael | `b0148` | No context section; damage result remains visible |
| Santa Rosa | `b0000` | School site membership, advertised July 2017 / **vintage unverified**, plus current parcel and OSM site context |
| Santa Rosa | `b0048` | No context section |

The first three grouped claims appear directly below the damage result. More
claims use a collapsed disclosure. Claims group only when kind, scope, source,
timing and qualifications agree; multiple occupancies remain explicit. Historical
and current identities stay separate. OpenStreetMap attribution links to its
copyright/ODbL page whenever OSM context is present. No facility badges are added.

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

Only compact presentation fields survive: kind, scope, title, value, human-readable
source, timing, scope qualifier, OSM attribution flag and displayable state. Raw
candidates, geometry, GIS record IDs, QA notes, scores and modeled years-built are
excluded. The sidecar header includes canonical manifest and audit SHA-256 values
for traceability. No source records are embedded in committed code or tests.

When `GIS_CONTEXT_ROOT` is explicitly configured, `GET /demo-scenes/{scene_id}`
validates the optional sidecar schema, reviewed status, exact manifest hash and UID
coverage, then joins nonempty context into `building.building_context`. It never
modifies `prediction` or writes canonical scene files. Missing, stale, malformed
or unreviewed sidecars are ignored; invalid sidecars emit a server warning. Sidecar
files and raw audits are outside the static asset routes. With no configured root,
the existing seven scene packs work normally without any GIS data dependency.

## Validation

```powershell
node app/frontend/test_scene_dashboard.js
node app/frontend/test_scene_inspection.js
node app/frontend/test_scene_page_integration.js
& .\local_experiments\gis_context_v2\.venv\Scripts\python.exe -B -m unittest app.backend.test_building_context app.backend.test_api_demo_scenes app.backend.gis_context.test_gis_context
```

The integration was checked in local headless Chrome at desktop and 390-pixel
mobile widths, including all examples above, clearing, filtering, scene switching,
imagery modes, expanded context, uploads and examples. Screenshots and the local
browser verification report are ignored under
`local_experiments/gis_context_v2/dashboard-review/`. No model inference is needed.

## Publication boundary

County-derived sidecars are authorized for this local evaluation only. Bay County
redistribution terms remain unresolved; Sonoma county-derived restrictions need
review before publication (including the school layer's CC BY-ND 3.0 terms).
Neither these records nor raw extracts belong in versioned scene manifests or
static deployment assets. Production deployment configuration is unchanged.
