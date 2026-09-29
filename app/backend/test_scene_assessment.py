"""Prompt and packet tests for scene-level analyst overviews."""

import json
from pathlib import Path
import unittest

from app.backend.building_context import load_context_overlay
from app.backend.scene_assessment import (
    SCENE_ASSESSMENT_PACKET_SCHEMA_VERSION,
    SCENE_ASSESSMENT_PROMPT_VERSION,
    SCENE_OUTPUT_CONTRACT,
    build_scene_assessment_packet,
    build_scene_assessment_preview,
    build_scene_assessment_prompt,
)


ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "demo_scenes"
OVERLAYS = ROOT / "demo_gis_context"


def load_scene(scene_id: str) -> tuple[dict, dict]:
    path = SCENES / scene_id / "scene.json"
    scene = json.loads(path.read_text(encoding="utf-8"))
    return scene, load_context_overlay(OVERLAYS, scene_id, path, scene)


class SceneAssessmentPromptTests(unittest.TestCase):
    def test_scene_prompt_is_versioned_bounded_and_uses_shared_evidence(self):
        scene, contexts = load_scene("santa-rosa-wildfire_00000014")
        evidence = build_scene_assessment_packet(scene, contexts)
        prompt = build_scene_assessment_prompt(evidence)
        packet_json = prompt["user"].split("\n", 1)[1]
        prompt_packet = json.loads(packet_json)

        self.assertEqual(prompt["version"], SCENE_ASSESSMENT_PROMPT_VERSION)
        self.assertEqual(SCENE_ASSESSMENT_PROMPT_VERSION, "scene-assessment-v2")
        self.assertEqual(evidence["schema_version"], SCENE_ASSESSMENT_PACKET_SCHEMA_VERSION)
        self.assertEqual(prompt_packet["schema_version"], evidence["schema_version"])
        self.assertEqual(prompt["output_contract"], SCENE_OUTPUT_CONTRACT)
        self.assertEqual(prompt_packet["candidate_findings"], evidence["candidate_findings"])
        self.assertNotIn("building_rankings", prompt_packet["uncertainty_summary"])
        self.assertNotIn("per_building", prompt_packet["spatial_summary"])
        self.assertNotIn("image", prompt_packet)
        self.assertNotIn("coordinates", prompt_packet)
        serialized = json.dumps(prompt_packet, ensure_ascii=False)
        for raw_field in ("original_values", "source_record_id", "terms_url", "overpass_response"):
            self.assertNotIn(raw_field, serialized)

    def test_scene_prompt_contains_grounding_and_no_spatial_or_operational_claims(self):
        scene, contexts = load_scene("palu-tsunami_00000065")
        prompt = build_scene_assessment_prompt(build_scene_assessment_packet(scene, contexts))
        instructions = " ".join(prompt["system"].lower().split())
        for rule in (
            "2-4 sentence synthesis",
            "only from the supplied candidate_findings object",
            "do not invent, reproduce, or mention building identifiers",
            "rankings are ordinal summaries",
            "call connected nearby severe predictions proximity groups",
            "pixel distances and relative positions describe only the scene image frame",
            "preserve the distinction between building/place, parcel, site and area evidence",
            "never state that you observed collapse",
            "provide evacuation",
            "current gis is not event-time truth",
        ):
            self.assertIn(rule, instructions)

    def test_scene_preview_is_deterministic_and_does_not_generate(self):
        scene, contexts = load_scene("hurricane-harvey_00000177")
        first = build_scene_assessment_preview(scene, contexts)
        second = build_scene_assessment_preview(scene, contexts)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "preview_only")
        self.assertEqual(first["provider_status"], "disabled")
        self.assertNotIn("overview", first)
        self.assertEqual(first["scene_evidence"]["gis_summary"]["buildings_with_reviewed_context"], len(contexts))

    def test_no_gis_scene_retains_coordinate_supported_location(self):
        scene, contexts = load_scene("palu-tsunami_00000065")
        preview = build_scene_assessment_preview(scene, contexts)
        evidence = preview["scene_evidence"]
        self.assertEqual(evidence["gis_summary"]["buildings_with_reviewed_context"], 0)
        self.assertEqual(evidence["gis_summary"]["buildings_without_reviewed_context"], len(scene["buildings"]))
        self.assertEqual(evidence["event"]["location"], "Palu, Central Sulawesi, Indonesia")
        self.assertEqual(evidence["event"]["location_scope"], "scene")
        self.assertEqual(evidence["event"]["hazard_type"], "tsunami")


if __name__ == "__main__":
    unittest.main()
