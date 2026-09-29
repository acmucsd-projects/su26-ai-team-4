"""Provider adapter tests use a local fake Responses client only."""

from __future__ import annotations

import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.backend.assessment import PROMPT_VERSION
from app.backend.scene_assessment import SCENE_ASSESSMENT_PROMPT_VERSION
from app.backend.assessment_openai import (
    AssessmentOutput,
    AssessmentProviderError,
    MAX_ASSESSMENT_LENGTH,
    MAX_LIMITATION_LENGTH,
    MAX_LIMITATIONS,
    MAX_OUTPUT_TOKENS,
    MAX_SUPPORTING_DETAILS,
    MAX_SUPPORTING_DETAIL_LENGTH,
    MAX_SECTION_LENGTH,
    MAX_SCENE_FINDINGS,
    MAX_SCENE_FINDING_EXPLANATION_LENGTH,
    MAX_SCENE_FINDING_TITLE_LENGTH,
    MAX_SCENE_OVERVIEW_LENGTH,
    OpenAIAssessmentProvider,
    SceneAssessmentOutput,
    configured_assessment_provider,
    normalize_scene_assessment_result,
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


def scene_prompt():
    return {
        "version": SCENE_ASSESSMENT_PROMPT_VERSION,
        "system": "Use only supplied deterministic scene evidence.",
        "user": "Summarize this scene evidence packet.",
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

    def test_invalid_scene_prompt_version_is_rejected_before_provider_call(self):
        client = FakeClient(response({"overview": "Fine."}))
        bad_prompt = {**scene_prompt(), "version": "unknown"}
        with self.assertRaises(AssessmentProviderError) as caught:
            OpenAIAssessmentProvider(client=client).generate_scene(bad_prompt)
        self.assertEqual(caught.exception.code, "assessment_prompt_version_unsupported")
        self.assertIsNone(client.responses.arguments)


class OpenAIResponsesAdapterTests(unittest.TestCase):
    def test_success_uses_small_nonpersistent_structured_responses_request(self):
        client = FakeClient(response({
            "assessment": "  No Damage leads, but Minor retains similar model support; current mapped context applies to the site rather than confirming this building's use.  ",
            "recommended_review": "Review the PRE/POST pair for subtle changes rather than only obvious structural loss.",
            "supporting_details": ["The selected class is common in this scene."],
            "limitations": ["  GIS context does not establish individual identity.  "],
        }))
        result = OpenAIAssessmentProvider("gpt-6-luna", client=client).generate(prompt())

        self.assertEqual(set(result), {
            "assessment", "recommended_review", "supporting_details", "limitations",
            "prompt_version", "generated_by",
        })
        self.assertTrue(result["assessment"].startswith("No Damage leads"))
        self.assertEqual(result["recommended_review"], "Review the PRE/POST pair for subtle changes rather than only obvious structural loss.")
        self.assertEqual(result["supporting_details"], ["The selected class is common in this scene."])
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

    def test_scene_generation_reuses_nonpersistent_structured_responses_path(self):
        client = FakeClient(response({
            "overview": "Severe predictions make up a meaningful share of this scene, while several leading classes are closely separated.",
            "findings": [{
                "title": "Classification ambiguity",
                "explanation": "The leading classes are close, so the selected examples are useful for review.",
                "candidate_keys": ["most_ambiguous_1"],
            }],
            "recommended_review": "Can PRE/POST comparison distinguish the leading classes for the most ambiguous candidates?",
            "limitations": ["Predictions are not verified ground truth."],
        }))
        result = OpenAIAssessmentProvider("gpt-6-luna", client=client).generate_scene(scene_prompt())
        self.assertEqual(result["overview"].split()[0], "Severe")
        self.assertEqual(result["findings"][0]["candidate_keys"], ["most_ambiguous_1"])
        self.assertEqual(result["prompt_version"], SCENE_ASSESSMENT_PROMPT_VERSION)
        self.assertEqual(result["generated_by"], "openai/gpt-6-luna")
        self.assertEqual(client.responses.arguments["text_format"], SceneAssessmentOutput)
        self.assertFalse(client.responses.arguments["store"])
        self.assertEqual(client.responses.arguments["input"], [
            {"role": "system", "content": scene_prompt()["system"]},
            {"role": "user", "content": scene_prompt()["user"]},
        ])
        self.assertFalse({"tools", "previous_response_id", "image"} & set(client.responses.arguments))

    def test_scene_output_bounds_and_candidate_references_are_structured(self):
        invalid_outputs = (
            {"overview": ""},
            {"overview": "x" * (MAX_SCENE_OVERVIEW_LENGTH + 1)},
            {"overview": "Valid.", "findings": [{"title": "x" * (MAX_SCENE_FINDING_TITLE_LENGTH + 1), "explanation": "Text."}]},
            {"overview": "Valid.", "findings": [{"title": "Title", "explanation": "x" * (MAX_SCENE_FINDING_EXPLANATION_LENGTH + 1)}]},
            {"overview": "Valid.", "findings": [{"title": "Title", "explanation": "Text."}] * (MAX_SCENE_FINDINGS + 1)},
            {"overview": "Valid.", "candidate_building_ids": ["invented"]},
        )
        for output in invalid_outputs:
            with self.subTest(output=type(output).__name__):
                with self.assertRaises(AssessmentProviderError) as caught:
                    OpenAIAssessmentProvider(client=FakeClient(response(output))).generate_scene(scene_prompt())
                self.assertEqual(caught.exception.code, "assessment_provider_invalid_output")

        with self.assertRaises(ValidationError):
            SceneAssessmentOutput.model_validate({"overview": "Valid.", "findings": [{
                "title": "Title", "explanation": "Text.", "candidate_keys": ["x"] * 4,
            }]}, strict=True)

    def test_scene_normalizer_ignores_unknown_candidate_keys_and_identifier_prose(self):
        scene_evidence = {"candidates": {"most_ambiguous_1": {"building_id": "scene_000001_b0001"}}}
        result = normalize_scene_assessment_result({
            "overview": "A concise scene overview.",
            "findings": [
                {"title": "Ambiguity", "explanation": "The leading classes are close.", "candidate_keys": ["most_ambiguous_1"]},
                {"title": "Unknown", "explanation": "This refers to no supplied candidate.", "candidate_keys": ["invented_key"]},
                {"title": "Untrusted identifier", "explanation": "Inspect scene_000001_b9999 next.", "candidate_keys": []},
                {"title": "Scene-wide pattern", "explanation": "The class distribution is uneven.", "candidate_keys": []},
            ],
            "recommended_review": None,
            "limitations": [],
            "prompt_version": SCENE_ASSESSMENT_PROMPT_VERSION,
            "generated_by": "openai/gpt-6-luna",
        }, scene_evidence)
        self.assertEqual([finding["title"] for finding in result["findings"]], ["Ambiguity", "Scene-wide pattern"])
        self.assertEqual(result["candidate_buildings"], {"most_ambiguous_1": "scene_000001_b0001"})

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
            {"assessment": "Looks fine.", "recommended_review": "x" * (MAX_SECTION_LENGTH + 1)},
            {"assessment": "Looks fine.", "recommended_review": 123},
            {"assessment": "Looks fine.", "supporting_details": ["x"] * (MAX_SUPPORTING_DETAILS + 1)},
            {"assessment": "Looks fine.", "supporting_details": ["x" * (MAX_SUPPORTING_DETAIL_LENGTH + 1)]},
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
        self.assertIsNone(output.recommended_review)
        self.assertEqual(output.supporting_details, [])
        self.assertEqual(output.limitations, [])

        output = AssessmentOutput.model_validate({
            "assessment": "Valid.",
            "recommended_review": "  ",
            "supporting_details": ["Useful context."],
        }, strict=True)
        self.assertIsNone(output.recommended_review)
        self.assertEqual(output.supporting_details, ["Useful context."])


if __name__ == "__main__":
    unittest.main()
