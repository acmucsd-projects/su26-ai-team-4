"""Focused tests for the offline, canonical AI input-size diagnostic."""

import json
from pathlib import Path
import unittest

from .building_context import load_context_overlay
from .scene_assessment import build_scene_assessment_prompt
from .scene_evidence import build_scene_evidence
from .assessment_input_diagnostic import build_assessment_input_diagnostics
from .assessment import build_assessment_preview


ROOT = Path(__file__).resolve().parents[1]


class AssessmentInputDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_assessment_input_diagnostics()

    def test_all_demo_scenes_and_representative_buildings_are_measured_offline(self):
        report = self.report
        self.assertEqual(report["provider_calls"], 0)
        self.assertEqual(len(report["scene_assessment"]["by_scene"]), 7)
        self.assertTrue(report["building_assessment"]["representative_buildings"])
        sample_types = {
            sample_type
            for row in report["building_assessment"]["representative_buildings"]
            for sample_type in row["sample_types"]
        }
        self.assertTrue({"most_ambiguous", "high_confidence_severe", "local_severity_contrast_outlier", "context_rich", "no_gis"} <= sample_types)
        self.assertEqual(
            report["largest_request_overall"]["complete_textual_input_utf8_bytes"],
            max(
                row["complete_textual_input_utf8_bytes"]
                for row in [
                    *report["scene_assessment"]["by_scene"],
                    *report["building_assessment"]["representative_buildings"],
                ]
            ),
        )
        for row in report["scene_assessment"]["by_scene"] + report["building_assessment"]["representative_buildings"]:
            self.assertGreater(row["serialized_evidence_json_characters"], 0)
            self.assertGreater(row["serialized_evidence_json_utf8_bytes"], 0)
            self.assertGreater(row["instruction_prompt_characters"], 0)
            self.assertGreater(row["complete_textual_input_characters"], row["serialized_evidence_json_characters"])

    def test_scene_evidence_size_comes_from_the_canonical_prompt_json(self):
        report = self.report
        row = report["scene_assessment"]["by_scene"][0]
        manifest_path = ROOT / "demo_scenes" / row["scene_id"] / "scene.json"
        scene = json.loads(manifest_path.read_text(encoding="utf-8"))
        contexts = load_context_overlay(ROOT / "demo_gis_context", row["scene_id"], manifest_path, scene)
        prompt = build_scene_assessment_prompt(build_scene_evidence(scene, contexts))
        evidence_json = prompt["user"].partition("\n")[2]
        self.assertEqual(row["serialized_evidence_json_characters"], len(evidence_json))
        self.assertEqual(row["serialized_evidence_json_utf8_bytes"], len(evidence_json.encode("utf-8")))
        self.assertEqual(row["complete_textual_input_characters"], len(prompt["system"]) + len(prompt["user"]))
        self.assertEqual(row["complete_textual_input_utf8_bytes"], len(prompt["system"].encode()) + len(prompt["user"].encode()))

    def test_building_size_comes_from_the_production_assessment_preview(self):
        row = self.report["building_assessment"]["representative_buildings"][0]
        manifest_path = ROOT / "demo_scenes" / row["scene_id"] / "scene.json"
        scene = json.loads(manifest_path.read_text(encoding="utf-8"))
        contexts = load_context_overlay(ROOT / "demo_gis_context", row["scene_id"], manifest_path, scene)
        building = next(building for building in scene["buildings"] if building["id"] == row["building_id"])
        evidence = build_scene_evidence(scene, contexts)
        prompt = build_assessment_preview(scene, building, contexts.get(building.get("uid")), scene_evidence=evidence)["prompt"]
        evidence_json = prompt["user"].partition("\n")[2]
        self.assertEqual(row["serialized_evidence_json_characters"], len(evidence_json))
        self.assertEqual(row["serialized_evidence_json_utf8_bytes"], len(evidence_json.encode("utf-8")))
        self.assertEqual(row["complete_textual_input_characters"], len(prompt["system"]) + len(prompt["user"]))


if __name__ == "__main__":
    unittest.main()
