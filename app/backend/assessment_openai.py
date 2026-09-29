"""OpenAI Responses API adapter for analyst-assist assessments.

The SDK is imported only when a key is configured, so preview-only installs
can start without the optional provider dependency.
"""

from __future__ import annotations

from typing import Annotated, Any
import os
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .assessment import AssessmentPrompt, AssessmentResult, PROMPT_VERSION
from .scene_assessment import (
    SCENE_ASSESSMENT_PROMPT_VERSION,
    SceneAssessmentPrompt,
)

DEFAULT_MODEL = "gpt-6-luna"
MAX_OUTPUT_TOKENS = 900
MAX_ASSESSMENT_LENGTH = 1200
MAX_SECTION_LENGTH = 500
MAX_SUPPORTING_DETAILS = 4
MAX_SUPPORTING_DETAIL_LENGTH = 300
MAX_LIMITATIONS = 4
MAX_LIMITATION_LENGTH = 300
MAX_SCENE_OVERVIEW_LENGTH = 1200
MAX_SCENE_FINDINGS = 4
MAX_SCENE_FINDING_TITLE_LENGTH = 100
MAX_SCENE_FINDING_EXPLANATION_LENGTH = 500
MAX_SCENE_CANDIDATE_REFERENCES = 3

OptionalAssessmentSection = Annotated[str | None, Field(max_length=MAX_SECTION_LENGTH)]


class AssessmentOutput(BaseModel):
    """The only model-authored fields accepted from the structured response."""

    model_config = ConfigDict(extra="forbid", strict=True)

    assessment: Annotated[str, Field(min_length=1, max_length=MAX_ASSESSMENT_LENGTH)]
    recommended_review: OptionalAssessmentSection = None
    supporting_details: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=MAX_SUPPORTING_DETAIL_LENGTH)]],
        Field(max_length=MAX_SUPPORTING_DETAILS),
    ] = Field(default_factory=list)
    limitations: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=MAX_LIMITATION_LENGTH)]],
        Field(max_length=MAX_LIMITATIONS),
    ] = Field(default_factory=list)

    @field_validator("assessment")
    @classmethod
    def assessment_is_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("assessment must contain text")
        return value

    @field_validator("recommended_review")
    @classmethod
    def empty_optional_review_is_omitted(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("supporting_details", "limitations")
    @classmethod
    def list_sections_are_nonblank(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("supporting details and limitations must contain non-empty text")
        return normalized


class SceneFindingOutput(BaseModel):
    """A finding may refer only through deterministic candidate keys."""

    model_config = ConfigDict(extra="forbid", strict=True)

    title: Annotated[str, Field(min_length=1, max_length=MAX_SCENE_FINDING_TITLE_LENGTH)]
    explanation: Annotated[str, Field(min_length=1, max_length=MAX_SCENE_FINDING_EXPLANATION_LENGTH)]
    candidate_keys: Annotated[list[Annotated[str, Field(min_length=1, max_length=80)]], Field(max_length=MAX_SCENE_CANDIDATE_REFERENCES)] = Field(default_factory=list)

    @field_validator("title", "explanation")
    @classmethod
    def finding_text_is_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("finding text must contain text")
        return value

    @field_validator("candidate_keys")
    @classmethod
    def candidate_keys_are_unique(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("candidate keys must be unique non-empty values")
        return normalized


class SceneAssessmentOutput(BaseModel):
    """Structured, model-authored fields for one scene overview."""

    model_config = ConfigDict(extra="forbid", strict=True)

    overview: Annotated[str, Field(min_length=1, max_length=MAX_SCENE_OVERVIEW_LENGTH)]
    findings: Annotated[list[SceneFindingOutput], Field(max_length=MAX_SCENE_FINDINGS)] = Field(default_factory=list)
    recommended_review: OptionalAssessmentSection = None
    limitations: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=MAX_LIMITATION_LENGTH)]],
        Field(max_length=MAX_LIMITATIONS),
    ] = Field(default_factory=list)

    @field_validator("overview")
    @classmethod
    def overview_is_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("overview must contain text")
        return value

    @field_validator("recommended_review")
    @classmethod
    def empty_optional_review_is_omitted(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("limitations")
    @classmethod
    def limitations_are_nonblank(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("limitations must contain non-empty text")
        return normalized


class AssessmentProviderError(Exception):
    """Safe, client-facing provider failure metadata; contains no SDK details."""

    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class OpenAIAssessmentProvider:
    """Generate building or scene assessments through one structured provider path."""

    def __init__(self, model: str = DEFAULT_MODEL, *, client: Any | None = None) -> None:
        self.model = model
        if client is None:
            try:
                from openai import (
                    APIConnectionError,
                    APIStatusError,
                    APITimeoutError,
                    AuthenticationError,
                    OpenAI,
                    RateLimitError,
                )
            except ImportError:
                raise RuntimeError("OpenAI SDK is not installed") from None

            self._timeout_errors = (APITimeoutError, TimeoutError)
            self._connection_errors = (APIConnectionError,)
            self._authentication_errors = (AuthenticationError,)
            self._rate_limit_errors = (RateLimitError,)
            self._api_errors = (APIStatusError,)
            try:
                client = OpenAI(timeout=20.0, max_retries=0)
            except Exception:
                raise RuntimeError("OpenAI client could not be configured") from None
        else:
            self._timeout_errors = (TimeoutError,)
            self._connection_errors = ()
            self._authentication_errors = ()
            self._rate_limit_errors = ()
            self._api_errors = ()
        self.client = client

    def generate(self, prompt: AssessmentPrompt) -> AssessmentResult:
        if prompt.get("version") != PROMPT_VERSION:
            raise AssessmentProviderError(
                "assessment_prompt_version_unsupported",
                "Assessment generation could not use the requested prompt version.",
                400,
            )

        output = self._request_structured_output(prompt, AssessmentOutput, "assessment")

        # Only these application-controlled fields are returned publicly.
        return {
            "assessment": output.assessment,
            "recommended_review": output.recommended_review,
            "supporting_details": output.supporting_details,
            "limitations": output.limitations,
            "prompt_version": PROMPT_VERSION,
            "generated_by": f"openai/{self.model}",
        }

    def generate_scene(self, prompt: SceneAssessmentPrompt) -> dict:
        if prompt.get("version") != SCENE_ASSESSMENT_PROMPT_VERSION:
            raise AssessmentProviderError(
                "assessment_prompt_version_unsupported",
                "Scene assessment generation could not use the requested prompt version.",
                400,
            )

        output = self._request_structured_output(prompt, SceneAssessmentOutput, "scene overview")
        return {
            **output.model_dump(),
            "prompt_version": SCENE_ASSESSMENT_PROMPT_VERSION,
            "generated_by": f"openai/{self.model}",
        }

    def _request_structured_output(self, prompt: dict, output_schema: type[BaseModel], label: str) -> BaseModel:
        """Share the same non-persistent Responses API handling for each output schema."""

        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": prompt["system"]},
                    {"role": "user", "content": prompt["user"]},
                ],
                text_format=output_schema,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                reasoning={"effort": "none"},
                store=False,
            )
        except self._timeout_errors:
            raise AssessmentProviderError(
                "assessment_provider_timeout",
                "Assessment generation timed out. Please try again later.",
                504,
            ) from None
        except self._authentication_errors:
            raise AssessmentProviderError(
                "assessment_provider_authentication_failed",
                "Assessment generation is not available because provider authentication failed.",
                503,
            ) from None
        except self._rate_limit_errors:
            raise AssessmentProviderError(
                "assessment_provider_rate_limited",
                "Assessment generation is temporarily rate limited. Please try again later.",
                503,
            ) from None
        except self._connection_errors:
            raise AssessmentProviderError(
                "assessment_provider_unreachable",
                "Assessment generation could not reach the provider. Please try again later.",
                502,
            ) from None
        except self._api_errors:
            raise AssessmentProviderError(
                "assessment_provider_failed",
                "Assessment generation failed at the provider.",
                502,
            ) from None
        except Exception:
            raise AssessmentProviderError(
                "assessment_provider_failed",
                "Assessment generation failed. Please try again later.",
                502,
            ) from None

        if self._contains_refusal(response):
            raise AssessmentProviderError(
                "assessment_provider_refused",
                f"The provider declined to generate this {label}.",
                422,
            )

        status = getattr(response, "status", None)
        if status == "incomplete" or getattr(response, "incomplete_details", None):
            raise AssessmentProviderError(
                "assessment_provider_incomplete",
                f"The provider returned an incomplete {label}.",
                502,
            )
        if status != "completed":
            raise AssessmentProviderError(
                "assessment_provider_failed",
                "The provider did not complete the assessment.",
                502,
            )

        parsed = getattr(response, "output_parsed", None)
        if isinstance(parsed, BaseModel):
            parsed = parsed.model_dump()
        try:
            if not isinstance(parsed, dict):
                raise ValueError("structured output is missing")
            output = output_schema.model_validate(parsed, strict=True)
        except (ValidationError, ValueError, TypeError):
            raise AssessmentProviderError(
                "assessment_provider_invalid_output",
                f"The provider returned an invalid {label} response.",
                502,
            ) from None
        return output

    @staticmethod
    def _contains_refusal(response: Any) -> bool:
        for item in getattr(response, "output", ()) or ():
            if getattr(item, "type", None) != "message":
                continue
            for content in getattr(item, "content", ()) or ():
                if getattr(content, "type", None) == "refusal":
                    return True
        return False


def normalize_scene_assessment_result(result: object, scene_evidence: dict) -> dict:
    """Validate scene output and resolve only application-supplied candidate keys."""

    if not isinstance(result, dict):
        raise AssessmentProviderError(
            "assessment_provider_invalid_output",
            "The provider returned an invalid scene overview response.",
            502,
        )
    if result.get("prompt_version") != SCENE_ASSESSMENT_PROMPT_VERSION:
        raise AssessmentProviderError(
            "assessment_provider_invalid_output",
            "The provider returned an invalid scene overview response.",
            502,
        )
    generated_by = result.get("generated_by")
    if not isinstance(generated_by, str) or not generated_by.strip() or len(generated_by) > 120:
        raise AssessmentProviderError(
            "assessment_provider_invalid_output",
            "The provider returned an invalid scene overview response.",
            502,
        )
    try:
        output = SceneAssessmentOutput.model_validate(
            {key: result[key] for key in ("overview", "findings", "recommended_review", "limitations") if key in result},
            strict=True,
        )
    except (ValidationError, ValueError, TypeError, KeyError):
        raise AssessmentProviderError(
            "assessment_provider_invalid_output",
            "The provider returned an invalid scene overview response.",
            502,
        ) from None

    candidates = scene_evidence.get("candidates")
    candidates = candidates if isinstance(candidates, dict) else {}
    building_id_pattern = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9_-]*_b\d+\b")
    global_text = [output.overview, output.recommended_review or "", *output.limitations]
    if any(building_id_pattern.search(text) for text in global_text):
        raise AssessmentProviderError(
            "assessment_provider_invalid_output",
            "The provider returned an invalid scene overview response.",
            502,
        )
    findings = []
    referenced_candidate_keys: list[str] = []
    for finding in output.findings:
        if building_id_pattern.search(finding.title) or building_id_pattern.search(finding.explanation):
            continue
        if any(key not in candidates for key in finding.candidate_keys):
            # Ignore the complete finding so an invalid key cannot turn a
            # building-specific claim into an apparently scene-wide one.
            continue
        findings.append(finding.model_dump())
        for key in finding.candidate_keys:
            if key not in referenced_candidate_keys:
                referenced_candidate_keys.append(key)

    candidate_buildings = {}
    for key in referenced_candidate_keys:
        candidate = candidates.get(key)
        building_id = candidate.get("building_id") if isinstance(candidate, dict) else None
        if isinstance(building_id, str) and building_id:
            candidate_buildings[key] = building_id

    return {
        "overview": output.overview,
        "findings": findings,
        "recommended_review": output.recommended_review,
        "limitations": output.limitations,
        "prompt_version": SCENE_ASSESSMENT_PROMPT_VERSION,
        "generated_by": generated_by.strip(),
        "candidate_buildings": candidate_buildings,
    }


def _api_key_is_configured() -> bool:
    """Check key presence without returning, logging, or formatting its value."""

    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def configured_assessment_provider() -> OpenAIAssessmentProvider | None:
    """Create the optional provider only when a key and SDK are available."""

    if not _api_key_is_configured():
        return None
    configured_model = os.environ.get("OPENAI_ASSESSMENT_MODEL", DEFAULT_MODEL).strip()
    model = configured_model or DEFAULT_MODEL
    try:
        return OpenAIAssessmentProvider(model)
    except (ImportError, RuntimeError):
        return None
