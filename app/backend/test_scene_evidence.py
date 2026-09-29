"""Deterministic tests for the reusable demo SceneEvidence model."""

import json
from pathlib import Path
import unittest

from app.backend.building_context import load_context_overlay
from app.backend.scene_evidence import (
    DAMAGE_CLASSES,
    MAX_SCENE_CANDIDATES,
    SCENE_EVIDENCE_SCHEMA_VERSION,
    build_scene_evidence,
    building_scene_context,
    scene_evidence_for_prompt,
)


ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "demo_scenes"
OVERLAYS = ROOT / "demo_gis_context"


def load_scene(scene_id: str) -> tuple[dict, dict]:
    manifest_path = SCENES / scene_id / "scene.json"
    scene = json.loads(manifest_path.read_text(encoding="utf-8"))
    contexts = load_context_overlay(OVERLAYS, scene_id, manifest_path, scene)
    return scene, contexts


class SceneEvidenceTests(unittest.TestCase):
    def test_exact_distribution_counts_percentages_and_severe_share(self):
        scene, contexts = load_scene("hurricane-michael_00000247")
        evidence = build_scene_evidence(scene, contexts)
        distribution = evidence["damage_distribution"]
        expected_counts = {name: 0 for name in DAMAGE_CLASSES}
        for building in scene["buildings"]:
            expected_counts[building["prediction"]["predicted_class"]] += 1

        self.assertEqual(evidence["schema_version"], SCENE_EVIDENCE_SCHEMA_VERSION)
        self.assertEqual(distribution["total_buildings"], len(scene["buildings"]))
        self.assertEqual(distribution["classified_buildings"], len(scene["buildings"]))
        self.assertEqual(distribution["class_counts"], expected_counts)
        self.assertEqual(sum(distribution["class_percentages"].values()), 100.0)
        expected_severe = expected_counts["major-damage"] + expected_counts["destroyed"]
        self.assertEqual(distribution["severe_count"], expected_severe)
        self.assertEqual(distribution["severe_percentage"], round(expected_severe / len(scene["buildings"]) * 100, 2))
        self.assertEqual(distribution["percentage_denominator"], "all packaged buildings")

    def test_uncertainty_and_decisiveness_rankings_are_complete_and_stable(self):
        scene, contexts = load_scene("hurricane-michael_00000247")
        first = build_scene_evidence(scene, contexts)
        second = build_scene_evidence(scene, contexts)
        self.assertEqual(first["model_uncertainty"], second["model_uncertainty"])
        uncertainty = first["model_uncertainty"]["uncertainty_ranking"]
        decisiveness = first["model_uncertainty"]["decisiveness_ranking"]
        self.assertEqual(len(uncertainty), len(scene["buildings"]))
        self.assertEqual([row["rank"] for row in uncertainty], list(range(1, len(uncertainty) + 1)))
        self.assertEqual([row["top_two_gap"] for row in uncertainty], sorted(row["top_two_gap"] for row in uncertainty))
        self.assertEqual([row["top_probability"] for row in decisiveness], sorted((row["top_probability"] for row in decisiveness), reverse=True))
        self.assertEqual(uncertainty[0]["building_id"], "hurricane-michael_00000247_b0009")

    def test_candidate_keys_are_stable_bounded_and_carry_reasons_predictions_and_context(self):
        scene, contexts = load_scene("santa-rosa-wildfire_00000014")
        evidence = build_scene_evidence(scene, contexts)
        self.assertLessEqual(len(evidence["candidates"]), MAX_SCENE_CANDIDATES)
        self.assertEqual(evidence["candidate_order"], list(evidence["candidates"]))
        self.assertIn("most_ambiguous_1", evidence["candidates"])
        self.assertIn("most_decisive_1", evidence["candidates"])
        self.assertIn("representative_severe", evidence["candidates"])
        self.assertIn("representative_low_damage", evidence["candidates"])
        self.assertIn("context_rich_1", evidence["candidates"])
        for candidate_key, candidate in evidence["candidates"].items():
            self.assertTrue(candidate_key)
            self.assertIn(candidate["building_id"], {building["id"] for building in scene["buildings"]})
            self.assertIn("type", candidate["reason"])
            self.assertIn("probabilities", candidate["damage_prediction"])
            self.assertIn("reviewed_context", candidate)
        self.assertEqual(evidence["candidates"], build_scene_evidence(scene, contexts)["candidates"])

    def test_gis_summary_preserves_context_coverage_categories_and_scopes(self):
        scene, contexts = load_scene("hurricane-harvey_00000177")
        evidence = build_scene_evidence(scene, contexts)
        summary = evidence["context_summary"]
        self.assertEqual(summary["buildings_with_reviewed_context"], len(contexts))
        self.assertEqual(summary["buildings_without_reviewed_context"], len(scene["buildings"]) - len(contexts))
        self.assertGreater(summary["buildings_with_building_or_place_evidence"], 0)
        self.assertGreater(summary["buildings_with_parcel_evidence"], 0)
        self.assertGreater(summary["buildings_with_site_evidence"], 0)
        self.assertGreater(summary["buildings_with_area_evidence"], 0)
        self.assertGreater(summary["buildings_with_modeled_use_evidence"], 0)
        self.assertGreater(summary["buildings_with_context_conflicts"], 0)
        self.assertTrue(summary["primary_category_counts"])

    def test_curated_metadata_uses_audit_provenance_and_leaves_unknowns_null(self):
        expected = {
            "hurricane-harvey_00000177": ("Harris County, Texas", "2017-08-31T17:38:50.685Z"),
            "hurricane-michael_00000247": ("Bay County, Florida", "2018-10-13T16:48:15.000Z"),
            "santa-rosa-wildfire_00000014": ("Sonoma County, California", "2017-10-11T19:19:41.000Z"),
        }
        for scene_id, (location, post_date) in expected.items():
            with self.subTest(scene_id=scene_id):
                scene, contexts = load_scene(scene_id)
                metadata = build_scene_evidence(scene, contexts)["scene_metadata"]
                self.assertEqual(metadata["location"], location)
                self.assertEqual(metadata["post_acquisition_date"], post_date)
                self.assertIsNone(metadata["pre_acquisition_date"])
                self.assertTrue(metadata["location_source"])
                self.assertTrue(metadata["acquisition_date_source"])

        for scene_id in ("hurricane-matthew_00000060", "hurricane-florence_00000459", "palu-tsunami_00000065", "socal-fire_00000663"):
            with self.subTest(scene_id=scene_id):
                scene, contexts = load_scene(scene_id)
                metadata = build_scene_evidence(scene, contexts)["scene_metadata"]
                self.assertIsNone(metadata["pre_acquisition_date"])
                self.assertIsNone(metadata["post_acquisition_date"])
                if scene_id in {"palu-tsunami_00000065", "socal-fire_00000663", "hurricane-matthew_00000060"}:
                    self.assertIsNone(metadata["location"])

    def test_building_subset_uses_scene_source_without_other_candidate_records(self):
        scene, contexts = load_scene("hurricane-michael_00000247")
        evidence = build_scene_evidence(scene, contexts)
        building_id = "hurricane-michael_00000247_b0009"
        subset = building_scene_context(evidence, building_id)
        selected = subset["uncertainty_summary"]["selected_building"]
        self.assertEqual(selected["uncertainty_rank"], 1)
        self.assertIn("most_ambiguous_1", selected["candidate_keys"])
        self.assertEqual(subset["damage_distribution"], evidence["damage_distribution"])
        self.assertNotIn("candidates", subset)
        prompt_evidence = scene_evidence_for_prompt(evidence)
        self.assertNotIn("uncertainty_ranking", prompt_evidence["model_uncertainty"])
        self.assertLessEqual(len(prompt_evidence["candidates"]), MAX_SCENE_CANDIDATES)

    def test_unknown_scene_uses_only_explicit_metadata(self):
        scene = {
            "scene_id": "unknown_000001",
            "event_name": "unknown-event",
            "location": "  Explicit reviewed label  ",
            "pre_acquisition_date": "2020-02-29",
            "post_acquisition_date": "2020-2-30",
            "buildings": [],
        }
        evidence = build_scene_evidence(scene)
        metadata = evidence["scene_metadata"]
        self.assertEqual(metadata["location"], "Explicit reviewed label")
        self.assertEqual(metadata["pre_acquisition_date"], "2020-02-29")
        self.assertIsNone(metadata["post_acquisition_date"])
        self.assertIsNone(metadata["hazard_type"])


if __name__ == "__main__":
    unittest.main()
