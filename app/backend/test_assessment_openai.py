"""Provider adapter tests use a local fake Responses client only."""

from __future__ import annotations

import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.backend.assessment import PROMPT_VERSION
from app.backend.assessment_openai import (
    AssessmentOutput,
    AssessmentProviderError,
    MAX_ASSESSMENT_LENGTH,
    MAX_LIMITATION_LENGTH,
    MAX_LIMITATIONS,
    MAX_OUTPUT_TOKENS,
    MAX_SECTION_LENGTH,
    OpenAIAssessmentProvider,
    configured_assessment_provider,
)


class FakeResponses:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.arguments = None

    def parse(self, **kwargs):
        self.arguments = kwargs
        if self.error:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response=None, error=None):
        self.responses = FakeResponses(response=response, error=error)


def prompt():
    return {
        "version": PROMPT_VERSION,
        "system": "Use only supplied evidence.",
        "user": "Summarize this evidence packet.",
        "output_contract": {},
    }


def response(parsed, *, status="completed", output=None, incomplete_details=None):
    return SimpleNamespace(
        status=status,
        output=output or [],
        output_parsed=parsed,
        incomplete_details=incomplete_details,
    )


class AssessmentProviderConfigurationTests(unittest.TestCase):
    def test_missing_key_keeps_provider_unavailable_without_importing_sdk(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            with patch("app.backend.assessment_openai.OpenAIAssessmentProvider") as constructor:
                self.assertIsNone(configured_assessment_provider())
                constructor.assert_not_called()

    def test_configured_provider_uses_default_and_configured_model(self):
        with patch("app.backend.assessment_openai._api_key_is_configured", return_value=True):
            with patch.dict(os.environ, {"OPENAI_ASSESSMENT_MODEL": " "}, clear=False):
                with patch("app.backend.assessment_openai.OpenAIAssessmentProvider", return_value=object()) as constructor:
                    configured_assessment_provider()
                    constructor.assert_called_once_with("gpt-6-luna")
            with patch.dict(os.environ, {"OPENAI_ASSESSMENT_MODEL": "model-for-review"}, clear=False):
                with patch("app.backend.assessment_openai.OpenAIAssessmentProvider", return_value=object()) as constructor:
                    configured_assessment_provider()
                    constructor.assert_called_once_with("model-for-review")

    def test_invalid_prompt_version_is_rejected_before_provider_call(self):
        client = FakeClient(response({"assessment": "Fine.", "limitations": []}))
        bad_prompt = {**prompt(), "version": "unknown"}
        with self.assertRaises(AssessmentProviderError) as caught:
            OpenAIAssessmentProvider(client=client).generate(bad_prompt)
        self.assertEqual(caught.exception.code, "assessment_prompt_version_unsupported")
        self.assertIsNone(client.responses.arguments)


class OpenAIResponsesAdapterTests(unittest.TestCase):
    def test_success_uses_small_nonpersistent_structured_responses_request(self):
        client = FakeClient(response({
            "assessment": "  The model predicts minor damage. Current mapped context is available.  ",
            "what_stands_out": "A nearby competing class is close.",
            "uncertainty": "Minor damage is nearly as likely as no damage.",
            "context_interpretation": "Current mapped context describes the site, not this building.",
            "suggested_review": "Compare the PRE and POST crops manually.",
            "evidence_gaps": None,
            "limitations": ["  GIS context does not establish individual identity.  "],
        }))
        result = OpenAIAssessmentProvider("gpt-6-luna", client=client).generate(prompt())

        self.assertEqual(set(result), {
            "assessment", "what_stands_out", "uncertainty", "context_interpretation",
            "suggested_review", "evidence_gaps", "limitations", "prompt_version", "generated_by",
        })
        self.assertEqual(result["assessment"], "The model predicts minor damage. Current mapped context is available.")
        self.assertEqual(result["what_stands_out"], "A nearby competing class is close.")
        self.assertEqual(result["uncertainty"], "Minor damage is nearly as likely as no damage.")
        self.assertEqual(result["context_interpretation"], "Current mapped context describes the site, not this building.")
        self.assertEqual(result["suggested_review"], "Compare the PRE and POST crops manually.")
        self.assertIsNone(result["evidence_gaps"])
        self.assertEqual(result["limitations"], ["GIS context does not establish individual identity."])
        self.assertEqual(result["prompt_version"], PROMPT_VERSION)
        self.assertEqual(result["generated_by"], "openai/gpt-6-luna")

        arguments = client.responses.arguments
        self.assertEqual(arguments["model"], "gpt-6-luna")
        self.assertIs(arguments["text_format"], AssessmentOutput)
        self.assertEqual(arguments["max_output_tokens"], MAX_OUTPUT_TOKENS)
        self.assertEqual(arguments["reasoning"], {"effort": "none"})
        self.assertFalse(arguments["store"])
        self.assertEqual(arguments["input"], [
            {"role": "system", "content": prompt()["system"]},
            {"role": "user", "content": prompt()["user"]},
        ])
        self.assertFalse({"tools", "previous_response_id", "image"} & set(arguments))

    def test_model_cannot_supply_application_metadata_or_extra_fields(self):
        client = FakeClient(response({
            "assessment": "The model predicts minor damage.",
            "limitations": [],
            "prompt_version": "untrusted-version",
            "generated_by": "untrusted-provider",
        }))
        with self.assertRaises(AssessmentProviderError) as caught:
            OpenAIAssessmentProvider(client=client).generate(prompt())
        self.assertEqual(caught.exception.code, "assessment_provider_invalid_output")

    def test_refusal_is_a_clean_provider_error(self):
        refusal = SimpleNamespace(type="message", content=[SimpleNamespace(type="refusal", refusal="private provider text")])
        client = FakeClient(response(None, output=[refusal]))
        with self.assertRaises(AssessmentProviderError) as caught:
            OpenAIAssessmentProvider(client=client).generate(prompt())
        self.assertEqual(caught.exception.code, "assessment_provider_refused")
        self.assertNotIn("private provider text", caught.exception.message)

    def test_incomplete_response_is_rejected(self):
        client = FakeClient(response(None, status="incomplete", incomplete_details=object()))
        with self.assertRaises(AssessmentProviderError) as caught:
            OpenAIAssessmentProvider(client=client).generate(prompt())
        self.assertEqual(caught.exception.code, "assessment_provider_incomplete")

    def test_malformed_and_unexpected_structured_output_are_rejected(self):
        for parsed in (
            None,
            {"assessment": "", "limitations": []},
            {"assessment": "A" * (MAX_ASSESSMENT_LENGTH + 1), "limitations": []},
            {"assessment": "Looks fine.", "limitations": ["x"] * (MAX_LIMITATIONS + 1)},
            {"assessment": "Looks fine.", "limitations": ["x" * (MAX_LIMITATION_LENGTH + 1)]},
            {"assessment": "Looks fine.", "limitations": [], "extra": "field"},
            {"assessment": "Looks fine.", "what_stands_out": "x" * (MAX_SECTION_LENGTH + 1)},
            {"assessment": "Looks fine.", "what_stands_out": 123},
        ):
            with self.subTest(parsed=type(parsed).__name__):
                with self.assertRaises(AssessmentProviderError) as caught:
                    OpenAIAssessmentProvider(client=FakeClient(response(parsed))).generate(prompt())
                self.assertEqual(caught.exception.code, "assessment_provider_invalid_output")

    def test_timeout_and_provider_errors_hide_exception_details(self):
        for failure, code, status in (
            (TimeoutError("transport internals"), "assessment_provider_timeout", 504),
            (RuntimeError("provider internals"), "assessment_provider_failed", 502),
        ):
            with self.subTest(code=code):
                with self.assertRaises(AssessmentProviderError) as caught:
                    OpenAIAssessmentProvider(client=FakeClient(error=failure)).generate(prompt())
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.status_code, status)
                self.assertNotIn("internals", caught.exception.message)

    def test_structured_schema_rejects_whitespace_only_fields(self):
        with self.assertRaises(ValidationError):
            AssessmentOutput.model_validate({"assessment": "   ", "limitations": []})
        with self.assertRaises(ValidationError):
            AssessmentOutput.model_validate({"assessment": "Valid.", "limitations": ["  "]})

    def test_optional_sections_accept_missing_null_or_empty_content(self):
        output = AssessmentOutput.model_validate({"assessment": "Valid."}, strict=True)
        self.assertIsNone(output.what_stands_out)
        self.assertIsNone(output.uncertainty)
        self.assertEqual(output.limitations, [])

        output = AssessmentOutput.model_validate({
            "assessment": "Valid.",
            "what_stands_out": "  ",
            "uncertainty": None,
            "context_interpretation": "Useful context.",
        }, strict=True)
        self.assertIsNone(output.what_stands_out)
        self.assertIsNone(output.uncertainty)
        self.assertEqual(output.context_interpretation, "Useful context.")


if __name__ == "__main__":
    unittest.main()
