# AI-Assisted Assessment

The backend keeps a deterministic evidence flow:

**packaged evidence -> deterministic SceneEvidence -> scene overview or building drill-down -> structured assessment**

`GET /demo-scenes/{scene_id}/buildings/{building_id}/assessment-preview` returns
the packet, exact prompt, and output contract. It makes no provider call and
continues to work without an API key or the OpenAI SDK. Its `provider_status`
remains `disabled` because the preview does not generate text.

`POST /demo-scenes/{scene_id}/buildings/{building_id}/assessment` generates one
assessment from that same packet. The v2 response requires `assessment` and may
populate `recommended_review`, `supporting_details`, and `limitations`. Empty
optional sections are returned as `null` or empty arrays. It also returns
`prompt_version`, `generated_by`, and an application-generated `evidence_used`
list containing only evidence families actually present. Prompt version is
`building-assessment-v2.3`; its deterministic evidence packet uses schema
version 5. If the provider is not configured, the endpoint
returns HTTP 503 with `assessment_provider_unavailable`; it never substitutes
mock text.

`GET /demo-scenes/{scene_id}/assessment-preview` returns deterministic
`SceneEvidence`, the exact scene prompt, and its output contract without a
provider call. `POST /demo-scenes/{scene_id}/assessment` generates a scene
overview using prompt version `scene-assessment-v2`. It returns `overview`, up
to four `findings`, optional `recommended_review`, `limitations`,
`prompt_version`, and `generated_by`. Findings refer only through
application-selected `candidate_keys`. The API drops findings with unknown
keys or building IDs in finding prose, rejects scene-level prose containing
building IDs, and supplies an application-generated
`candidate_buildings` map from candidate keys to known building-ID arrays, plus
candidate finding types for single-building, multi-building, and group actions.
Scene previews work
without an API key or OpenAI SDK; generation returns the same safe unavailable
response as the building endpoint.

Run the offline all-scene evidence inventory from the repository root with:

```powershell
python -m app.backend.scene_evidence_diagnostic
```

It prints prediction/uncertainty summaries, geometry availability and units,
adaptive proximity-group and neighborhood counts, reviewed GIS/site coverage,
candidate finding types, and evidence layers that are missing or deferred. It
reads only packaged manifests/overlays and makes no network requests.

The optional provider uses the OpenAI Responses API with Structured Outputs.
Set `OPENAI_API_KEY` in the process environment or the repo-root `.env`;
`python-dotenv` loads that file at backend startup without replacing values set
by the shell. `OPENAI_ASSESSMENT_MODEL` selects the model and defaults to
`gpt-6-luna`. Without a non-empty key, the provider stays unavailable and the
application starts normally. The Responses
request contains only the existing system and user prompt text, sends no images
or tools, sets `store=false`, and does not retain conversation history.

The provider validates every structured section locally, bounds field and
limitation lengths, rejects extra fields, and attaches `prompt_version` and
`generated_by` in application code. The UI derives the visible model name from
that backend metadata. The evidence-used list is derived from the packet, not
from model-authored output. Refusals, incomplete output, invalid output,
timeouts, and provider errors produce clean application errors without exposing
raw provider details.

Both assessment levels derive from the same `SceneEvidence` v2 builder. Its
structured source contains event metadata, model damage distribution,
probability/confidence distributions, per-building uncertainty ranks, spatial
summary and per-building geometry, reviewed GIS coverage, explicitly named
site groups, bounded candidate findings, and provenance. Scene prompts receive
a compact projection without all per-building rows. Building prompts receive
the selected building's local neighborhood, uncertainty ranks, relevant severe
proximity group and named site membership, not other candidates or scene-model
prose. Neither assessment consumes the other's generated text.

Evidence provenance separates `MODEL_DERIVED`, `SPATIAL_DERIVED`,
`SOURCE_METADATA`, `REVIEWED_GIS`, `IMAGE_DERIVED`, and
`DEMO_REFERENCE_ONLY`. Packaged `demo_metadata.ground_truth` labels are
evaluation references only. They are never read by SceneEvidence, candidate
selection, or either AI prompt. Tests mutate those labels and verify that both
scene and building AI packets remain byte-for-byte equivalent.

The local audit found all 610 demo buildings have valid PRE/POST pixel
footprints, but no packaged geographic coordinates, transform, sensor/catalog
metadata, or physical footprint units. Spatial analysis uses POST polygon
centroids and areas in scene pixels/pixel-squared, with relative position
normalized to the analyzed-footprint bounds. If a future scene has complete
geographic polygons, those take precedence and distances use haversine meters;
mixed geographic/pixel coordinates are never compared. The neighborhood is the
five nearest other centroids (up to five where fewer exist), a presentation
rule rather than a scientific parameter. Local disagreement records explicit
class counts and strict severity-family majority; it does not identify which
prediction is wrong. Severe proximity groups are connected components where
centroid distance is at most 1.5 times the scene median nearest-neighbor
distance. They are descriptive proximity groups, not statistically validated
clusters. All methods, coordinate spaces, and distance units travel with the
evidence.

The seven scene images are packaged 1024-by-1024 RGB PNGs and all 610 buildings
have paired 224-by-224 PRE/POST crops. Their image metadata has no geotransform,
sensor/catalog details, or registration/illumination quality data. Raw xBD is
not in this checkout (`data/README.md` documents that it is not stored in the
repository); the packaged `demo_metadata.ground_truth` class is the only
reference label field found. No additional raw xBD environmental annotations,
acquisition fields, or geographic extent can be audited locally. The curated
registry therefore keeps unknown dates and locations null and does not infer
scene centroids or geographic bounds from pixels.

Named site groups require a reviewed displayable site-scope `school_site` or
`site_use` claim with an explicit name and at least two analyzed buildings.
Separate source associations are combined only when their name and exact
analyzed-building membership match. Their prediction mixes are descriptive;
site membership does not prove individual roof identity or use. Parcel,
property, modeled-use, and area evidence keep their existing scopes and
qualifications.

Scene metadata comes from one curated registry. Event names are checked
against each manifest. County-level locations are included only where tracked
reviewed GIS audits/overlays identify the jurisdiction: Harris, Bay, Sonoma,
and Duplin counties. POST xBD acquisition timestamps are included for Harvey,
Michael, and Santa Rosa from their tracked audit records. PRE timestamps and
remaining locations/dates stay null where repository evidence does not verify
them. No values are guessed from event names, provider coverage, or the web.
The building packet also contains the selected damage prediction, confidence,
all four probabilities, deterministic top-two classes/probabilities/gap, and
only displayable normalized GIS claims with scope, source, temporal relation,
modeled/mapped status, qualifications, and conflicts. Raw GIS payloads are
omitted.

The scene overview synthesizes the model-derived distribution, uncertainty,
nearby prediction patterns, and reviewed context without repeating obvious
dashboard counts. Building assessments use the same facts only when they
materially change the selected building's interpretation. Neither prompt
inspects imagery directly or produces field-verified damage determinations.
PRE/POST image-change indicators were audited and deferred: the packaged pairs
have no validated registration or illumination controls, so raw differences
could reflect alignment, view geometry, lighting, season, or vegetation rather
than damage. Both prompts prohibit visual-observation claims, preserve GIS
scope and timing, treat modeled occupancy as unverified, and bar unsupported
critical-facility claims and operational decisions. Missing GIS context remains
missing.

API secrets must stay in environment configuration and must never be committed
to the repository or placed in tests. Automated provider tests use fake
Responses clients and make no paid API calls. Live assessment calls are
intentional external operations and should be limited to selected demo
buildings.
