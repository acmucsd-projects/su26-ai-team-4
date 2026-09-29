# AI-Assisted Assessment

The backend keeps a deterministic evidence flow:

**demo prediction -> validated normalized GIS context -> evidence packet -> versioned prompt -> optional provider -> structured assessment**

`GET /demo-scenes/{scene_id}/buildings/{building_id}/assessment-preview` returns
the packet, exact prompt, and output contract. It makes no provider call and
continues to work without an API key or the OpenAI SDK. Its `provider_status`
remains `disabled` because the preview does not generate text.

`POST /demo-scenes/{scene_id}/buildings/{building_id}/assessment` generates one
assessment from that same packet. It returns `assessment`, `limitations`,
`prompt_version`, and `generated_by`. If the provider is not configured, the
endpoint returns HTTP 503 with `assessment_provider_unavailable`; it never
substitutes mock text.

The optional provider uses the OpenAI Responses API with Structured Outputs.
Set `OPENAI_API_KEY` in the process environment. `OPENAI_ASSESSMENT_MODEL`
selects the model and defaults to `gpt-6-luna`. Without a non-empty key, the
provider stays unavailable and the application starts normally. The Responses
request contains only the existing system and user prompt text, sends no images
or tools, sets `store=false`, and does not retain conversation history.

The provider validates the structured response locally, bounds assessment and
limitation lengths, rejects extra fields, and attaches `prompt_version` and
`generated_by` in application code. Refusals, incomplete output, invalid output,
timeouts, and provider errors produce clean application errors without exposing
raw provider details.

The packet includes the predicted damage class, confidence, four probabilities,
and only displayable normalized GIS claims with their scope, source, temporal
relation, modeled/mapped status, and qualifications. It omits raw GIS payloads.
The versioned prompt requires predicted/model language, preserves uncertainty
and evidence scope, treats modeled occupancy as unverified, qualifies current
GIS, and prohibits unsupported critical-facility claims and operational
instructions. Missing GIS context remains missing.

API secrets must stay in environment configuration and must never be committed
to the repository or placed in tests. Automated provider tests use fake
Responses clients and make no paid API calls. Live assessment calls are
intentional external operations and should be limited to selected demo
buildings.
