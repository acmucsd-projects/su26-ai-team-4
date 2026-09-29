"""OpenAI Responses API adapter for analyst-assist assessments.

The SDK is imported only when a key is configured, so preview-only installs
can start without the optional provider dependency.
"""

from __future__ import annotations

from typing import Annotated, Any
import os

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .assessment import AssessmentPrompt, AssessmentResult, PROMPT_VERSION

DEFAULT_MODEL = "gpt-6-luna"
MAX_OUTPUT_TOKENS = 900
MAX_ASSESSMENT_LENGTH = 1200
MAX_SECTION_LENGTH = 500
MAX_SUPPORTING_DETAILS = 4
MAX_SUPPORTING_DETAIL_LENGTH = 300
MAX_LIMITATIONS = 4
MAX_LIMITATION_LENGTH = 300

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


class AssessmentProviderError(Exception):
    """Safe, client-facing provider failure metadata; contains no SDK details."""

    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class OpenAIAssessmentProvider:
    """Generate one assessment from the established versioned text prompt."""

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

        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": prompt["system"]},
                    {"role": "user", "content": prompt["user"]},
                ],
                text_format=AssessmentOutput,
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
                "The provider declined to generate this assessment.",
                422,
            )

        status = getattr(response, "status", None)
        if status == "incomplete" or getattr(response, "incomplete_details", None):
            raise AssessmentProviderError(
                "assessment_provider_incomplete",
                "The provider returned an incomplete assessment.",
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
            output = AssessmentOutput.model_validate(parsed, strict=True)
        except (ValidationError, ValueError, TypeError):
            raise AssessmentProviderError(
                "assessment_provider_invalid_output",
                "The provider returned an invalid assessment response.",
                502,
            ) from None

        # Only these application-controlled fields are returned publicly.
        return {
            "assessment": output.assessment,
            "recommended_review": output.recommended_review,
            "supporting_details": output.supporting_details,
            "limitations": output.limitations,
            "prompt_version": PROMPT_VERSION,
            "generated_by": f"openai/{self.model}",
        }

    @staticmethod
    def _contains_refusal(response: Any) -> bool:
        for item in getattr(response, "output", ()) or ():
            if getattr(item, "type", None) != "message":
                continue
            for content in getattr(item, "content", ()) or ():
                if getattr(content, "type", None) == "refusal":
                    return True
        return False


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
