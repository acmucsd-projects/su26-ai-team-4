"""Focused tests for the deterministic analyst-assist evidence contract."""

import json
from pathlib import Path
import unittest

from app.backend.assessment import (
    DAMAGE_CLASSES,
    EVIDENCE_PACKET_SCHEMA_VERSION,
    OUTPUT_CONTRACT,
    PROMPT_VERSION,
    build_assessment_preview,
    build_evidence_packet,
    build_prompt,
)


ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "demo_scenes"
OVERLAYS = ROOT / "demo_gis_context"


def scene_and_context(scene_id: str) -> tuple[dict, dict]:
    scene = json.loads((SCENES / scene_id / "scene.json").read_text(encoding="utf-8"))
    overlay_path = OVERLAYS / f"{scene_id}.json"
    overlay = json.loads(overlay_path.read_text(encoding="utf-8")) if overlay_path.exists() else {"buildings": {}}
    return scene, overlay["buildings"]


def selected_building(scene: dict, contexts: dict, predicate=lambda _claim: True) -> tuple[dict, dict | None]:
    for building in scene["buildings"]:
        context = contexts.get(building.get("uid"))
        if context and any(predicate(claim) for claim in context["claims"]):
            return building, context
    raise AssertionError("No building in the fixture matches the requested evidence")


class AssessmentEvidenceTests(unittest.TestCase):
    def test_class_contract_lists_all_four_model_classes(self):
        self.assertEqual(DAMAGE_CLASSES, ("no-damage", "minor-damage", "major-damage", "destroyed"))

    def test_case_a_direct_mapped_building_context(self):
        scene, contexts = scene_and_context("santa-rosa-wildfire_00000014")
        building, context = selected_building(
            scene, contexts, lambda claim: claim["scope"] == "building" and claim["kind"] == "structure_type"
        )
        packet = build_evidence_packet(scene, building, context)
        self.assertEqual(packet["schema_version"], EVIDENCE_PACKET_SCHEMA_VERSION)
        claim = next(c for c in packet["context"]["claims"] if c["type"] == "structure_type")
        source_claim = next(c for c in context["claims"] if c["kind"] == "structure_type")
        self.assertEqual(claim["scope"], "building")
        self.assertEqual(claim["statement"]["value"], source_claim["value"])
        self.assertFalse(claim["modeled"])
        self.assertTrue(claim["mapped_from_osm"])

    def test_case_b_florence_nsi_occupancy_stays_modeled_and_current(self):
        scene, contexts = scene_and_context("hurricane-florence_00000459")
        building, context = selected_building(scene, contexts, lambda claim: claim["modeled"])
        packet = build_evidence_packet(scene, building, context)
        claim = packet["context"]["claims"][0]
        self.assertEqual(claim["scope"], "building")
        self.assertTrue(claim["modeled"])
        self.assertEqual(claim["temporal_relation"], "current_modeled_not_event_aligned")
        self.assertIn("not event-aligned", claim["timing"])
        self.assertIn("modeled occupancy is not verified use", " ".join(build_prompt(packet)["system"].lower().split()))

    def test_case_c_property_and_area_scopes_are_preserved(self):
        scene, contexts = scene_and_context("hurricane-harvey_00000177")
        building, property_context = selected_building(
            scene, contexts,
            lambda claim: claim["scope"] == "parcel" and claim["kind"] == "property_use"
        )
        property_packet = build_evidence_packet(scene, building, property_context)
        property_claim = property_packet["context"]["claims"][0]
        self.assertEqual(property_claim["scope"], "parcel")
        self.assertIn("parcel_context", property_claim["qualifications"])
        self.assertIn("property", property_claim["normalized_context_scopes"])

        for kind in ("site_use", "area_use"):
            site_building, site_context = selected_building(
                scene, contexts, lambda claim: claim["scope"] == "site" and claim["kind"] == kind
            )
            site_packet = build_evidence_packet(scene, site_building, site_context)
            site_claim = next(claim for claim in site_packet["context"]["claims"] if claim["type"] == kind)
            self.assertEqual(site_claim["scope"], "site")
            if kind == "area_use":
                self.assertIn("area", site_claim["normalized_context_scopes"])

    def test_case_d_no_gis_context_still_has_model_evidence_only(self):
        scene, _ = scene_and_context("hurricane-matthew_00000060")
        packet = build_evidence_packet(scene, scene["buildings"][0])
        self.assertFalse(packet["context"]["available"])
        self.assertEqual(packet["context"]["claims"], [])
        self.assertIsNotNone(packet["damage_prediction"]["predicted_class"])
        self.assertIn("No reviewed GIS context", " ".join(packet["limitations"]))

    def test_case_e_current_and_event_time_relations_are_not_collapsed(self):
        scene, contexts = scene_and_context("hurricane-harvey_00000177")
        event_building, event_context = selected_building(
            scene, contexts, lambda claim: claim["temporal_relation"] == "event_year"
        )
        event_packet = build_evidence_packet(scene, event_building, event_context)
        event_claim = next(c for c in event_packet["context"]["claims"] if c["temporal_relation"] == "event_year")
        self.assertIn("event-year", event_claim["timing"])

        current_building, current_context = selected_building(
            scene, contexts, lambda claim: claim["temporal_relation"] == "current_only"
        )
        current_packet = build_evidence_packet(scene, current_building, current_context)
        current_claim = next(c for c in current_packet["context"]["claims"] if c["temporal_relation"] == "current_only")
        self.assertIn("Current", current_claim["timing"])

    def test_case_f_missing_optional_fields_are_safe_and_explicit(self):
        packet = build_evidence_packet({}, {"id": "fixture", "prediction": {"predicted_class": "unknown"}}, {"claims": []})
        self.assertEqual(packet["damage_prediction"]["predicted_class"], None)
        self.assertEqual(tuple(packet["damage_prediction"]["probabilities"]), DAMAGE_CLASSES)
        self.assertTrue(all(v is None for v in packet["damage_prediction"]["probabilities"].values()))
        self.assertFalse(packet["context"]["available"])
        self.assertIn("recognized predicted damage class is unavailable", " ".join(packet["limitations"]))

    def test_v2_florence_case_keeps_decisive_prediction_separate_from_current_modeled_use(self):
        scene, contexts = scene_and_context("hurricane-florence_00000459")
        building = next(row for row in scene["buildings"] if row["id"] == "hurricane-florence_00000459_b0000")
        packet = build_evidence_packet(scene, building, contexts[building["uid"]])
        prediction = packet["damage_prediction"]
        claim = packet["context"]["claims"][0]

        self.assertEqual(prediction["predicted_class"], "major-damage")
        self.assertAlmostEqual(prediction["probabilities"]["major-damage"], 0.9936821460723877)
        self.assertEqual(prediction["probability_ranking"]["most_likely_class"], "major-damage")
        self.assertTrue(claim["modeled"])
        self.assertEqual(claim["temporal_relation"], "current_modeled_not_event_aligned")
        instructions = " ".join(build_prompt(packet)["system"].split())
        self.assertIn("Modeled occupancy is not verified use", instructions)
        self.assertIn("Current evidence is not event-time truth", instructions)

    def test_v2_michael_case_exposes_close_top_two_values_without_threshold(self):
        scene, contexts = scene_and_context("hurricane-michael_00000247")
        building = next(row for row in scene["buildings"] if row["id"] == "hurricane-michael_00000247_b0009")
        packet = build_evidence_packet(scene, building, contexts[building["uid"]])
        prediction = packet["damage_prediction"]
        ranking = prediction["probability_ranking"]

        self.assertEqual(prediction["predicted_class"], "no-damage")
        self.assertEqual(ranking["most_likely_class"], "no-damage")
        self.assertEqual(ranking["second_most_likely_class"], "minor-damage")
        self.assertEqual(ranking["top_probability"], prediction["probabilities"]["no-damage"])
        self.assertEqual(ranking["second_probability"], prediction["probabilities"]["minor-damage"])
        self.assertAlmostEqual(ranking["top_two_gap"], 0.0006180107593536)
        self.assertIn("do not invent a confidence cutoff", build_prompt(packet)["system"].lower())

    def test_v2_santa_rosa_case_preserves_scope_time_status_and_conflicts(self):
        scene, contexts = scene_and_context("santa-rosa-wildfire_00000014")
        building = next(row for row in scene["buildings"] if row["id"] == "santa-rosa-wildfire_00000014_b0006")
        source_context = contexts[building["uid"]]
        packet = build_evidence_packet(scene, building, source_context)

        self.assertEqual(len(packet["context"]["claims"]), len(source_context["claims"]))
        claims = packet["context"]["claims"]
        self.assertIn("building", {claim["scope"] for claim in claims})
        self.assertIn("parcel", {claim["scope"] for claim in claims})
        self.assertIn("site", {claim["scope"] for claim in claims})
        self.assertTrue(any(claim["modeled"] for claim in claims))
        self.assertTrue(any(claim["mapped_from_osm"] for claim in claims))
        for claim, original in zip(claims, source_context["claims"], strict=True):
            self.assertEqual(claim["scope"], original["scope"])
            self.assertEqual(claim["temporal_relation"], original["temporal_relation"])
            self.assertEqual(claim["modeled"], original["modeled"])
            self.assertEqual(claim["qualifications"], original["qualifications"])
        expected_conflicts = [
            {"reason": item["reason"], "resolution": item["resolution"], "supporting_claims": item["supporting_claims"]}
            for item in source_context["conflicts"]
        ]
        self.assertEqual(packet["context"]["conflicts"], expected_conflicts)

    def test_v2_no_context_cases_have_only_prediction_evidence(self):
        for scene_id in ("hurricane-matthew_00000060", "palu-tsunami_00000065"):
            with self.subTest(scene_id=scene_id):
                scene, _ = scene_and_context(scene_id)
                building = next(row for row in scene["buildings"] if row["id"].endswith("_b0000"))
                packet = build_evidence_packet(scene, building)
                self.assertFalse(packet["context"]["available"])
                self.assertEqual(packet["context"]["claims"], [])
                self.assertIsNotNone(packet["damage_prediction"]["probability_ranking"])

    def test_probability_ranking_is_absent_without_four_valid_values_and_ties_are_stable(self):
        incomplete = build_evidence_packet({}, {"prediction": {"probabilities": {"no-damage": 0.5}}})
        self.assertIsNone(incomplete["damage_prediction"]["probability_ranking"])

        tied = build_evidence_packet({}, {"prediction": {"probabilities": dict.fromkeys(DAMAGE_CLASSES, 0.25)}})
        self.assertEqual(tied["damage_prediction"]["probability_ranking"]["most_likely_class"], "no-damage")
        self.assertEqual(tied["damage_prediction"]["probability_ranking"]["second_most_likely_class"], "minor-damage")
        self.assertEqual(tied["damage_prediction"]["probability_ranking"]["top_two_gap"], 0)

    def test_packet_excludes_raw_provider_payload_and_prompt_is_deterministic(self):
        scene, contexts = scene_and_context("hurricane-florence_00000459")
        building, context = selected_building(scene, contexts)
        packet = build_evidence_packet(scene, building, context)
        serialized = json.dumps(packet)
        for forbidden in ("original_values", "raw_value", "source_record_id", "occtype", "ValuationModel", "terms_url"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(build_prompt(packet), build_prompt(packet))
        self.assertEqual(build_prompt(packet)["version"], PROMPT_VERSION)
        self.assertEqual(build_prompt(packet)["output_contract"], OUTPUT_CONTRACT)

    def test_preview_is_not_a_mock_assessment(self):
        scene, contexts = scene_and_context("hurricane-florence_00000459")
        building, context = selected_building(scene, contexts)
        preview = build_assessment_preview(scene, building, context)
        self.assertEqual(preview["status"], "preview_only")
        self.assertEqual(preview["provider_status"], "disabled")
        self.assertEqual(preview["output_contract"], OUTPUT_CONTRACT)
        self.assertNotIn("assessment", preview)

    def test_prompt_contract_covers_scope_time_and_operational_limits(self):
        instructions = " ".join(build_prompt({})["system"].lower().split())
        for rule in (
            "use only the supplied evidence packet",
            "never verified physical damage",
            "describe probabilities as calibrated real-world certainty",
            "parcel, campus, site, and area evidence do not establish an individual building's identity or use",
            "modeled occupancy is not verified use",
            "current evidence is not",
            "do not infer critical-facility status",
            "evacuation, condemnation, dispatch",
            "not a chatbot, field inspection, or official damage assessment",
            "chain-of-thought",
            "you receive no image pixels",
            "never claim visual observations",
            "manually compare pre and post imagery",
            "never recommend evacuation",
            "null when no specific content is useful",
        ):
            self.assertIn(rule, instructions)
        self.assertEqual(PROMPT_VERSION, "building-assessment-v2")
        self.assertEqual(EVIDENCE_PACKET_SCHEMA_VERSION, 2)
        self.assertIn("what_stands_out", OUTPUT_CONTRACT)
        self.assertIn("suggested_review", OUTPUT_CONTRACT)


if __name__ == "__main__":
    unittest.main()
