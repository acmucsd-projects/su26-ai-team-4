# AI-Assisted Assessment

The backend keeps a deterministic evidence flow:

**demo prediction -> validated normalized GIS context -> evidence packet -> versioned prompt -> optional provider -> structured assessment**

`GET /demo-scenes/{scene_id}/buildings/{building_id}/assessment-preview` returns
the packet, exact prompt, and output contract. It makes no provider call and
continues to work without an API key or the OpenAI SDK. Its `provider_status`
remains `disabled` because the preview does not generate text.

`POST /demo-scenes/{scene_id}/buildings/{building_id}/assessment` generates one
assessment from that same packet. The v2 response requires `assessment` and may
populate `recommended_review`, `supporting_details`, and `limitations`. Empty
optional sections are returned as `null` or empty arrays. It also returns
`prompt_version`, `generated_by`, and an application-generated `evidence_used`
list. Prompt version is `building-assessment-v2.1`; its deterministic evidence
packet uses schema version 3. If the provider is not configured, the endpoint
returns HTTP 503 with `assessment_provider_unavailable`; it never substitutes
mock text.

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

The packet includes explicit event context, deterministic scene prediction
counts, the selected damage prediction, confidence, all four probabilities,
deterministic top-two classes/probabilities/gap when all values are valid, and
only displayable normalized GIS claims with their scope, source, temporal
relation, modeled/mapped status, qualifications, and conflicts. Event hazard
categories use an allowlisted mapping from each packaged manifest's
`event_name`. A scene `location` or PRE/POST acquisition date is included only
when explicitly present in the manifest; current manifests contain none, so
those fields are omitted. The packet omits raw GIS payloads.

The assessment is a concise analyst briefing that synthesizes classifier,
scene, and normalized GIS evidence. Recommended review uses the deterministic
hazard type and evidence ambiguity to suggest a specific analytical check. It
does not inspect imagery directly or produce field-verified damage
determinations. The prompt prohibits visual-observation claims without supplied
observations, preserves GIS scope and timing, treats modeled occupancy as
unverified, and bars unsupported critical-facility claims and operational
decisions. Missing GIS context remains missing.

API secrets must stay in environment configuration and must never be committed
to the repository or placed in tests. Automated provider tests use fake
Responses clients and make no paid API calls. Live assessment calls are
intentional external operations and should be limited to selected demo
buildings.
