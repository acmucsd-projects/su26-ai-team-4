# AI-Assisted Assessment (backend preview)

The backend preview defines a deterministic boundary for a future language
model:

**demo prediction -> normalized GIS context -> evidence packet -> versioned prompt
-> future LLM provider -> short assessment**

`GET /demo-scenes/{scene_id}/buildings/{building_id}/assessment-preview` returns
the packet, exact prompt, and output contract. It is a prompt preview only:
`provider_status` is `disabled`, and no assessment is generated or sent outside
the app. No API key or LLM SDK is required. `app/backend/assessment.py` defines
the `AssessmentProvider` boundary for a later adapter.

The packet contains the model's predicted damage class, confidence, and all four
class probabilities, plus only displayable normalized GIS claims. It keeps each
claim's category, type, scope, source, source release/snapshot, temporal
relationship, modeled/mapped status, and qualifications. Raw provider values,
record IDs, and source tag payloads are excluded. Missing GIS context stays
empty; optional prediction fields are represented as unknown with a limitation.

Any eventual assessment is AI-generated analyst-assist output, not an official
damage assessment. Damage predictions are not ground truth, and confidence is
not established as calibrated real-world certainty. Parcel/property, site, and
area context do not establish individual-building identity. Modeled occupancy
is not verified use, and current GIS does not establish disaster-time context.
The prompt prohibits unsupported critical-facility claims and operational
instructions, and requires meaningful limitations in a concise response.

The preview and packet tests use local fixtures and packaged scenes. A real
provider, output validation against provider responses, privacy/retention review,
and user-facing disclosure should be reviewed before enabling generation.
