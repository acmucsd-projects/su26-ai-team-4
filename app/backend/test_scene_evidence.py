"""Focused tests for deterministic shared SceneEvidence v2."""

import copy
import json
from pathlib import Path
import unittest

from app.backend.building_context import load_context_overlay
from app.backend.scene_evidence import (
    DAMAGE_CLASSES,
    MAX_SCENE_CANDIDATES,
    SCENE_EVIDENCE_SCHEMA_VERSION,
    _geometry,
    build_scene_evidence,
    building_scene_context,
    scene_evidence_for_prompt,
)
from app.backend.scene_evidence_diagnostic import build_demo_scene_diagnostics


ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "demo_scenes"
OVERLAYS = ROOT / "demo_gis_context"
SCENE_IDS = [path.name for path in sorted(SCENES.iterdir()) if path.is_dir() and (path / "scene.json").exists()]


def load_scene(scene_id: str) -> tuple[dict, dict]:
    manifest_path = SCENES / scene_id / "scene.json"
    scene = json.loads(manifest_path.read_text(encoding="utf-8"))
    contexts = load_context_overlay(OVERLAYS, scene_id, manifest_path, scene)
    return scene, contexts


def synthetic_scene(classes: list[str]) -> dict:
    buildings = []
    for index, predicted_class in enumerate(classes):
        probabilities = {name: 0.02 for name in DAMAGE_CLASSES}
        probabilities[predicted_class] = 0.94
        buildings.append({"id": f"test_000001_b{index:04d}", "uid": f"u{index}",
                          "post_pixel_polygon": [[index * 10, 0], [index * 10 + 4, 0], [index * 10 + 4, 4], [index * 10, 4]],
                          "prediction": {"predicted_class": predicted_class, "confidence": 0.94, "probabilities": probabilities},
                          "demo_metadata": {"ground_truth": "never-use-this-label"}})
    return {"scene_id": "test_000001", "event_name": "test", "buildings": buildings}


class SceneEvidenceTests(unittest.TestCase):
    def test_legacy_historical_current_label_variation_is_not_exposed_as_conflict(self):
        scene, contexts = load_scene("hurricane-harvey_00000177")
        matched = [(uid, context) for uid, context in contexts.items()
                   if any(claim.get("name") == "Allstate Insurance" for claim in context["claims"])]
        self.assertEqual(len(matched), 1)
        _uid, context = matched[0]
        names = {claim["name"] for claim in context["claims"]
                 if isinstance(claim.get("name"), str) and claim["name"].startswith("Allstate")}
        self.assertEqual(names, {"Allstate Insurance", "Allstate"})
        self.assertFalse(any(conflict["reason"] == "historical_current_difference" for conflict in context["conflicts"]))
        self.assertNotIn("Historical and current records differ; both are retained.", context["notes"])

    def test_exact_scene_distribution_and_uncertainty_distributions(self):
        scene, contexts = load_scene("hurricane-michael_00000247")
        evidence = build_scene_evidence(scene, contexts)
        summary = evidence["model_summary"]
        expected = {name: 0 for name in DAMAGE_CLASSES}
        for building in scene["buildings"]:
            expected[building["prediction"]["predicted_class"]] += 1
        self.assertEqual(evidence["schema_version"], SCENE_EVIDENCE_SCHEMA_VERSION)
        self.assertEqual(summary["class_counts"], expected)
        self.assertEqual(summary["total_buildings"], len(scene["buildings"]))
        self.assertEqual(summary["severe_count"], expected["major-damage"] + expected["destroyed"])
        uncertainty = evidence["uncertainty_summary"]
        self.assertEqual(uncertainty["top_two_gap"]["count"], len(scene["buildings"]))
        self.assertLessEqual(uncertainty["top_two_gap"]["min"], uncertainty["top_two_gap"]["median"])
        self.assertLessEqual(uncertainty["top_two_gap"]["median"], uncertainty["top_two_gap"]["max"])
        self.assertTrue(uncertainty["top_competing_class_pairs"])
        self.assertEqual(evidence, build_scene_evidence(scene, contexts))

    def test_v2_contract_candidates_are_bounded_deterministic_and_prediction_based(self):
        scene, contexts = load_scene("santa-rosa-wildfire_00000014")
        evidence = build_scene_evidence(scene, contexts)
        self.assertEqual(set(evidence), {"schema_version", "event", "model_summary", "uncertainty_summary", "spatial_summary", "gis_summary", "site_groups", "candidate_order", "candidate_findings", "provenance"})
        self.assertLessEqual(len(evidence["candidate_findings"]), MAX_SCENE_CANDIDATES)
        self.assertEqual(evidence["candidate_order"], list(evidence["candidate_findings"]))
        candidate_types = {row["type"] for row in evidence["candidate_findings"].values()}
        self.assertIn("REPRESENTATIVE_SEVERE", candidate_types)
        self.assertIn("REPRESENTATIVE_LOW_DAMAGE", candidate_types)
        self.assertIn("MULTI_BUILDING_SITE", candidate_types)
        for key, candidate in evidence["candidate_findings"].items():
            self.assertTrue(key)
            self.assertTrue(candidate["building_ids"])
            self.assertIn("MODEL_DERIVED", candidate["evidence_provenance"])
            self.assertNotIn("ground_truth", json.dumps(candidate).lower())

    def test_verified_metadata_is_centralized_and_unknown_values_stay_null(self):
        expected = {
            "hurricane-harvey_00000177": ("Harris County, Texas", "2017-08-31T17:38:50.685Z"),
            "hurricane-michael_00000247": ("Bay County, Florida", "2018-10-13T16:48:15.000Z"),
            "hurricane-matthew_00000060": ("Les Cayes, Sud, Haiti", "2016-10-09T15:32:03.000Z"),
            "hurricane-florence_00000459": ("Duplin County, North Carolina", "2018-09-20T16:04:41.000Z"),
            "palu-tsunami_00000065": ("Palu, Central Sulawesi, Indonesia", "2018-10-01T02:26:02.000Z"),
            "santa-rosa-wildfire_00000014": ("Sonoma County, California", "2017-10-11T19:19:41.000Z"),
            "socal-fire_00000663": ("Los Angeles County, California", "2018-11-14T18:42:58.000Z"),
        }
        for scene_id, (location, post_date) in expected.items():
            event = build_scene_evidence(*load_scene(scene_id))["event"]
            self.assertEqual((event["location"], event["post_acquisition_date"]), (location, post_date))
            self.assertEqual(event["location_scope"], "scene" if location else None)
            self.assertEqual(bool(event["location_source"]), bool(location))
            self.assertTrue(event["acquisition_date_source"])
        for scene_id in SCENE_IDS:
            scene, contexts = load_scene(scene_id)
            self.assertEqual(build_scene_evidence(scene, contexts)["event"]["scene_id"], scene_id)
        unknown = {"scene_id": "unknown_000001", "event_name": "unknown-event", "location": " explicit ", "location_scope": "event",
                   "pre_acquisition_date": "2020-02-29", "post_acquisition_date": "2020-2-30", "buildings": []}
        event = build_scene_evidence(unknown)["event"]
        self.assertEqual(event["location"], "explicit")
        self.assertEqual(event["location_scope"], "event")
        self.assertEqual(event["pre_acquisition_date"], "2020-02-29")
        self.assertIsNone(event["post_acquisition_date"])

    def test_spatial_neighborhood_and_adaptive_severe_groups_are_exact_and_stable(self):
        scene = synthetic_scene(["destroyed", "major-damage", "no-damage", "minor-damage", "no-damage"])
        evidence = build_scene_evidence(scene)
        spatial = evidence["spatial_summary"]
        self.assertEqual(spatial["coordinate_space"], "scene_pixel")
        self.assertEqual(spatial["distance_unit"], "scene_pixels")
        self.assertEqual(spatial["usable_geometry_buildings"], 5)
        self.assertEqual(spatial["per_building"][scene["buildings"][0]["id"]]["neighbor_class_counts"]["major-damage"], 1)
        self.assertEqual(spatial["per_building"][scene["buildings"][0]["id"]]["neighborhood_count"], 4)
        self.assertTrue(spatial["severe_proximity_groups"])
        second = build_scene_evidence(scene)
        self.assertEqual([g["group_id"] for g in spatial["severe_proximity_groups"]], [g["group_id"] for g in second["spatial_summary"]["severe_proximity_groups"]])
        self.assertEqual(spatial["severe_group_method"]["scale_factor"], 1.5)
        self.assertIn("not statistical clusters", spatial["severe_group_method"]["interpretation"])

    def test_local_severity_contrast_contains_exact_rule_and_supporting_counts(self):
        scene = synthetic_scene(["destroyed", "no-damage", "minor-damage", "no-damage", "no-damage", "major-damage"])
        evidence = build_scene_evidence(scene)
        types = [candidate["type"] for candidate in evidence["candidate_findings"].values()]
        self.assertIn("LOCAL_SEVERITY_OUTLIER", types)
        outlier = next(c for c in evidence["candidate_findings"].values() if c["type"] == "LOCAL_SEVERITY_OUTLIER")
        self.assertEqual(outlier["reason"]["rule"], "strict majority of k-nearest predictions has opposing severity family")
        self.assertEqual(sum(outlier["reason"]["neighbor_classes"].values()), outlier["reason"]["neighbor_count"])

    def test_local_severity_outliers_require_a_strict_majority(self):
        scene = synthetic_scene(["destroyed", "no-damage", "major-damage"])
        evidence = build_scene_evidence(scene)
        self.assertNotIn("LOCAL_SEVERITY_OUTLIER", {row["type"] for row in evidence["candidate_findings"].values()})

    def test_missing_geometry_fails_closed_without_spatial_claims(self):
        scene = synthetic_scene(["destroyed", "no-damage", "major-damage"])
        for building in scene["buildings"]:
            building.pop("post_pixel_polygon")
        evidence = build_scene_evidence(scene)
        self.assertEqual(evidence["spatial_summary"]["usable_geometry_buildings"], 0)
        self.assertEqual(evidence["spatial_summary"]["severe_group_count"], 0)
        self.assertIsNone(evidence["spatial_summary"]["coordinate_space"])
        self.assertFalse(any("spatial_context" in row and row["spatial_context"] for row in evidence["candidate_findings"].values()))

    def test_geometry_rejects_nonfinite_degenerate_and_self_crossing_rings(self):
        self.assertIsNone(_geometry([[0, 0], [1, 1], [2, 2]]))
        self.assertIsNone(_geometry([[0, 0], [1, 1], [0, 1], [1, 0]]))
        self.assertIsNone(_geometry([[0, 0], [1, 0], [float("nan"), 1]]))
        self.assertEqual(_geometry([[0, 0], [2, 0], [2, 2], [0, 2]])["centroid"], [1, 1])

    def test_geographic_geometry_is_used_only_when_complete_and_reports_meters(self):
        scene = synthetic_scene(["major-damage", "no-damage"])
        for index, building in enumerate(scene["buildings"]):
            building["geographic_polygon"] = [[-120 + index * .001, 35], [-119.999 + index * .001, 35], [-119.999 + index * .001, 35.001], [-120 + index * .001, 35.001]]
        evidence = build_scene_evidence(scene)
        self.assertEqual(evidence["spatial_summary"]["coordinate_space"], "geographic_lon_lat")
        self.assertEqual(evidence["spatial_summary"]["distance_unit"], "meters")
        scene["buildings"][1].pop("geographic_polygon")
        fallback = build_scene_evidence(scene)
        self.assertEqual(fallback["spatial_summary"]["coordinate_space"], "scene_pixel")

    def test_reviewed_gis_and_site_groups_preserve_scope_and_prediction_mix(self):
        scene, contexts = load_scene("santa-rosa-wildfire_00000014")
        evidence = build_scene_evidence(scene, contexts)
        gis = evidence["gis_summary"]
        self.assertEqual(gis["buildings_with_reviewed_context"], len(contexts))
        self.assertGreater(gis["buildings_with_direct_building_or_place_evidence"], 0)
        self.assertGreater(gis["buildings_with_parcel_or_property_evidence"], 0)
        self.assertGreater(gis["buildings_with_named_site_evidence"], 0)
        self.assertTrue(evidence["site_groups"])
        for site in evidence["site_groups"]:
            self.assertEqual(site["scope"], "site")
            self.assertEqual(sum(site["prediction_counts"].values()), site["building_count"])
            self.assertIn("REVIEWED_GIS", site["provenance"])
        cardinal = [site for site in evidence["site_groups"] if site["name"] == "Cardinal Newman High School"]
        self.assertEqual(sorted(site["building_count"] for site in cardinal), [18, 19])
        self.assertNotEqual(cardinal[0]["building_ids"], cardinal[1]["building_ids"])

    def test_scene_and_building_packets_exclude_ground_truth_and_candidate_sprawl(self):
        scene, contexts = load_scene("hurricane-michael_00000247")
        changed = copy.deepcopy(scene)
        for row in changed["buildings"]:
            row["demo_metadata"]["ground_truth"] = "changed-hidden-reference"
        first = build_scene_evidence(scene, contexts)
        second = build_scene_evidence(changed, contexts)
        self.assertEqual(first, second)
        prompt = scene_evidence_for_prompt(first)
        self.assertEqual(prompt, scene_evidence_for_prompt(second))
        encoded = json.dumps(prompt).lower()
        self.assertNotIn("changed-hidden-reference", encoded)
        self.assertNotIn('"ground_truth"', encoded)
        building_id = scene["buildings"][0]["id"]
        subset = building_scene_context(first, building_id)
        self.assertIn("spatial_context", subset)
        self.assertIn("model_summary", subset)
        self.assertNotIn("candidate_findings", subset)
        self.assertNotIn("building_rankings", json.dumps(prompt))

    def test_all_seven_scene_diagnostics_have_sensible_complete_coverage(self):
        report = build_demo_scene_diagnostics(ROOT.parent)
        diagnostics = report["scenes"]
        self.assertEqual(report["mode"], "offline_deterministic_diagnostic")
        self.assertEqual(len(diagnostics), 7)
        self.assertEqual({row["scene_id"] for row in diagnostics}, set(SCENE_IDS))
        self.assertEqual(sum(row["building_count"] for row in diagnostics), 610)
        for diag in diagnostics:
            self.assertEqual(diag["spatial_geometry"]["PRE_valid"], diag["building_count"])
            self.assertEqual(diag["spatial_geometry"]["POST_valid"], diag["building_count"])
            self.assertEqual(diag["spatial_geometry"]["coordinate_space"], "scene_pixel")
            self.assertGreaterEqual(diag["spatial_summary"]["severe_group_count"], 0)
            self.assertLessEqual(diag["spatial_summary"]["severe_group_count"], diag["building_count"])


if __name__ == "__main__":
    unittest.main()
