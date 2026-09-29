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
list. Prompt version is `building-assessment-v2.2`; its deterministic evidence
packet uses schema version 4. If the provider is not configured, the endpoint
returns HTTP 503 with `assessment_provider_unavailable`; it never substitutes
mock text.

`GET /demo-scenes/{scene_id}/assessment-preview` returns deterministic
`SceneEvidence`, the exact scene prompt, and its output contract without a
provider call. `POST /demo-scenes/{scene_id}/assessment` generates a scene
overview using prompt version `scene-assessment-v1`. It returns `overview`, up
to four `findings`, optional `recommended_review`, `limitations`,
`prompt_version`, and `generated_by`. Findings refer only through
application-selected `candidate_keys`. The API drops findings with unknown
keys or building IDs in finding prose, rejects scene-level prose containing
building IDs, and supplies an application-generated
`candidate_buildings` map for valid interactive references. Scene previews work
without an API key or OpenAI SDK; generation returns the same safe unavailable
response as the building endpoint.

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

Both assessment levels derive from the same deterministic `SceneEvidence`
builder. Its versioned JSON structure includes damage counts and percentages,
severe share, stable probability rankings, reviewed GIS coverage, and a bounded
set of keyed candidate buildings. Scene prompts receive a compact projection
of those facts and candidates; building prompts receive scene distribution and
the selected building's deterministic scene-relative ranks, not other
candidates or scene-model prose. Neither assessment consumes the other's
generated text.

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

The scene overview explains the model-derived damage picture and may surface
notable distribution, ambiguity, or context patterns. Building assessments
remain concise drill-downs from the same scene facts. Recommended review is
framed around the question or ambiguity an analyst can resolve. Neither prompt
supports spatial concentration claims, inspects imagery directly, or produces
field-verified damage determinations. Both prohibit visual-observation claims,
preserve GIS scope and timing, treat modeled occupancy as unverified, and bar
unsupported critical-facility claims and operational decisions. Missing GIS
context remains missing.

API secrets must stay in environment configuration and must never be committed
to the repository or placed in tests. Automated provider tests use fake
Responses clients and make no paid API calls. Live assessment calls are
intentional external operations and should be limited to selected demo
buildings.
