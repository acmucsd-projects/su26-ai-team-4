"""Synthetic reviewed exports and optional API overlays; no provider/model calls."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.backend.api import create_app
from app.backend import api
from app.backend.building_context import SCHEMA_VERSION, load_context_overlay
from app.backend.gis_context.export_dashboard import CLASSIFICATION_FIELDS, build_overlay, present_claim
from app.backend.gis_context.presentation import normalize_context
from app.backend.test_api_demo_scenes import SCENE_ID, write_demo_scene


def claim(kind="modeled_occupancy", scope="building", provider="nsi", temporal="current_modeled_not_event_aligned",
          label="Modeled use (NSI): Single-family residential", **changes):
    return {"kind": kind, "scope": scope, "label": label,
            "source": {"provider": provider, "dataset": provider, "snapshot": "2026-09-28", "temporal_status": temporal},
            "displayable": True, "spatial_confidence": "strong", "spatial_evidence": {}, "mapped_name": None,
            "source_record_id": "synthetic-record", "raw_value": {"med_yr_blt": 1950}, **changes}


def evidence(claims):
    manifest = json.dumps({"scene_id": SCENE_ID, "buildings": [{"uid": "test-uid", "id": "test-building"}]}).encode()
    inputs = {"scene_manifest": hashlib.sha256(manifest).hexdigest()}
    report = {"scene_id": SCENE_ID, "status": "reviewed_with_findings", "input_sha256": inputs,
              "providers": {"nsi": {"status": "complete"}},
              "qa": {"status": "completed_with_findings", "input_sha256": inputs,
                     "reviewed_uids": ["test-uid"], "claim_actions": []},
              "buildings": [{"uid": "test-uid", "building_id": "test-building", "qa_status": "reviewed",
                             "evaluation_status": "evaluated", "claims": claims,
                             "candidates": [{"label": "Rejected raw candidate", "accepted": False}]}]}
    return report, manifest


def export(report, manifest):
    return build_overlay(report, manifest, json.dumps(report).encode())


class ReviewedExportTests(unittest.TestCase):
    def test_only_displayable_claims_and_no_raw_metadata(self):
        report, manifest = evidence([claim(), claim(displayable=False, label="Held use"),
                                     claim(spatial_confidence="weak", label="Ambiguous use")])
        overlay = export(report, manifest)
        claims = overlay["buildings"]["test-uid"]["claims"]
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["title"], "Modeled use")
        self.assertEqual(claims[0]["value"], "Single-family residential")
        self.assertIn("not event-aligned", claims[0]["timing"])
        serialized = json.dumps(overlay)
        for forbidden in ("Held use", "Ambiguous use", "Rejected raw candidate", "med_yr_blt", "synthetic-record", "spatial_confidence"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(export(report, manifest), overlay)

    def test_record_and_kind_holds_override_display_flag(self):
        report, manifest = evidence([claim(), claim(kind="structure_use", label="Structure use: Single family"),
                                     claim(kind="property_use", scope="parcel", label="Property use: Single family")])
        report["qa"]["claim_actions"] = [{"uid": "test-uid", "provider": "nsi", "record_id": "synthetic-record",
                                         "action": "withhold_claim", "kind": "structure_use"}]
        self.assertEqual([c["kind"] for c in export(report, manifest)["buildings"]["test-uid"]["claims"]],
                         ["modeled_occupancy", "property_use"])
        report["qa"]["claim_actions"][0].pop("kind")
        self.assertEqual(export(report, manifest)["buildings"]["test-uid"]["claims"], [])

    def test_name_hold_never_reconstructs_stale_identity_from_raw_tags(self):
        dental = claim("mapped_place", "place", "osm", "current_only",
                       "Current mapped place: dentist (name withheld after QA)", raw_value={"name": "Stale Dental"})
        report, manifest = evidence([dental])
        report["qa"]["claim_actions"] = [{"uid": "test-uid", "provider": "osm", "record_id": "synthetic-record", "action": "withhold_name"}]
        result = export(report, manifest)
        self.assertNotIn("Stale Dental", json.dumps(result))
        self.assertEqual(result["buildings"]["test-uid"]["claims"][0]["value"], "dentist")
        dental["mapped_name"] = "Stale Dental"
        with self.assertRaises(ValueError):
            export(report, manifest)
        dental.update(kind="mapped_name", mapped_name=None, label="Current mapped name (place): Stale Dental (name withheld after QA)")
        self.assertEqual(export(report, manifest)["buildings"]["test-uid"]["claims"], [])

    def test_temporal_and_scope_wording(self):
        prop = present_claim(claim("property_use", "parcel", "bay_2017", "pre_event_historical",
                                   "2017 pre-event property context: SINGLE FAMILY",
                                   spatial_evidence={"structure_association": "multi_structure"}))
        self.assertEqual(prop["timing"], "2017 pre-event property record")
        self.assertEqual(prop["title"], "Property context")
        self.assertIn("multiple structures", prop["qualifier"])
        school = present_claim(claim("school_site", "site", "sonoma_schools", "pre_event_reference_vintage_unverified",
                                     "Within mapped school property: Example School (advertised July 2017; vintage unverified)"))
        self.assertEqual(school["value"], "Within Example School")
        self.assertIn("vintage unverified", school["timing"])
        historical = present_claim(claim("site_use", "site", "osm", "event_snapshot", "Within disaster-time mapped site: Example School"))
        current = present_claim(claim("mapped_name", "building", "osm", "current_only", "Current mapped name (building): ACC"))
        self.assertIn("near disaster date", historical["timing"])
        self.assertIn("Current context", current["timing"])
        self.assertEqual(current["value"], "ACC")
        self.assertEqual(current["title"], "Mapped building name")
        harvey = present_claim(claim("property_use", "parcel", "hcad", "event_year", "2017 property context: Residential"))
        self.assertIn("event-year", harvey["timing"])

    def test_multiple_occupancies_grouped_but_dates_and_scopes_stay_distinct(self):
        report, manifest = evidence([claim(), claim(), claim(label="Modeled use (NSI): Retail"),
                                     claim("site_use", "site", "osm", "event_snapshot", "Site: Example Park"),
                                     claim("site_use", "site", "osm", "current_only", "Site: Example Park")])
        context = export(report, manifest)["buildings"]["test-uid"]
        self.assertEqual(len(context["claims"]), 5)  # Individually inspectable, including duplicates.
        self.assertEqual(len(context["contexts"]), 3)
        self.assertEqual(context["contexts"][0]["category"], "mixed_use")
        self.assertEqual(len(context["contexts"][0]["concepts"]), 2)
        self.assertNotEqual(context["contexts"][1]["temporal_relation"], context["contexts"][2]["temporal_relation"])

    def test_reject_unreviewed_partial_stale_or_misaligned_input(self):
        original, manifest = evidence([claim()])
        changes = [lambda r: r.update(status="awaiting_manual_qa"),
                   lambda r: r["qa"].update(reviewed_uids=[]),
                   lambda r: r["providers"]["nsi"].update(status="failed"),
                   lambda r: r["buildings"][0].update(qa_status="needs_review"),
                   lambda r: r["buildings"][0].update(evaluation_status="partially_evaluated"),
                   lambda r: r["buildings"][0].update(building_id="wrong-building"),
                   lambda r: r["buildings"].append(deepcopy(r["buildings"][0]))]
        for change in changes:
            with self.subTest(change=change):
                report = deepcopy(original)
                change(report)
                with self.assertRaises(ValueError):
                    export(report, manifest)
        with self.assertRaises(ValueError):
            export(original, manifest + b" ")


class LocalOverlayApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.scenes = self.root / "scenes"
        write_demo_scene(self.scenes)
        self.manifest_path = self.scenes / SCENE_ID / "scene.json"
        self.manifest = json.loads(self.manifest_path.read_text())
        self.manifest["buildings"][0].update(uid="test-uid", prediction={"predicted_class": "major-damage", "confidence": 0.8})
        self.manifest["buildings"].append({"id": "second-building", "uid": "second-uid"})
        self.original = json.dumps(self.manifest).encode()
        self.manifest_path.write_bytes(self.original)
        self.overlays = self.root / "overlays"
        self.overlays.mkdir()
        self.overlay = {"schema_version": SCHEMA_VERSION, "review_status": "reviewed", "scene_id": SCENE_ID,
                        "scene_manifest_sha256": hashlib.sha256(self.original).hexdigest(),
                        "buildings": {"test-uid": normalize_context([present_claim(claim())]), "second-uid": normalize_context([])}}
        self.overlay_path = self.overlays / f"{SCENE_ID}.json"

    def write_overlay(self):
        self.overlay_path.write_text(json.dumps(self.overlay), encoding="utf-8")

    def test_optional_api_join_never_changes_files_or_predictions(self):
        self.write_overlay()
        for enabled in (False, True):
            with self.subTest(enabled=enabled), patch.dict(os.environ, {
                "DEMO_SCENE_ROOT": str(self.scenes), "GIS_CONTEXT_ROOT": str(self.overlays if enabled else self.root / "missing"),
                "DEMO_SCENES_ONLY": "1",
            }), patch("app.backend.api.load_classifier") as load, patch("app.backend.api.predict_images") as predict:
                with TestClient(create_app()) as client:
                    result = client.get(f"/demo-scenes/{SCENE_ID}").json()
                    self.assertEqual("building_context" in result["buildings"][0], enabled)
                    self.assertNotIn("building_context", result["buildings"][1])
                    self.assertEqual(result["buildings"][0]["prediction"], self.manifest["buildings"][0]["prediction"])
                    self.assertFalse(client.get("/health").json()["inference_available"])
                    response = client.post("/predict", files={"pre_image": ("pre.png", b"test"), "post_image": ("post.png", b"test")})
                    self.assertEqual(response.status_code, 503)
                    self.assertIn("Scene-only", response.json()["detail"])
                    self.assertEqual(client.get(f"/demo-scenes/{SCENE_ID}/overlays/{SCENE_ID}.json").status_code, 404)
                load.assert_not_called()
                predict.assert_not_called()
        self.assertEqual(self.manifest_path.read_bytes(), self.original)

    def test_missing_malformed_stale_or_unsafe_overlays_are_optional(self):
        self.assertEqual(load_context_overlay(self.overlays, SCENE_ID, self.manifest_path, self.manifest), {})
        for payload in ("[]", "null", "{broken", json.dumps({**self.overlay, "review_status": "unreviewed"}),
                        json.dumps({**self.overlay, "scene_manifest_sha256": "stale"}),
                        json.dumps({**self.overlay, "buildings": {"wrong-uid": {"claims": []}}})):
            with self.subTest(payload=payload), self.assertLogs("app.backend.building_context", level="WARNING"):
                self.overlay_path.write_text(payload)
                self.assertEqual(load_context_overlay(self.overlays, SCENE_ID, self.manifest_path, self.manifest), {})
        self.write_overlay()
        self.assertEqual(load_context_overlay(self.overlays, "../" + SCENE_ID, self.manifest_path, self.manifest), {})
        self.assertEqual(load_context_overlay(None, SCENE_ID, self.manifest_path, self.manifest), {})
        self.overlay["buildings"]["test-uid"]["claims"][0]["displayable"] = False
        self.write_overlay()
        with self.assertLogs("app.backend.building_context", level="WARNING"):
            self.assertEqual(load_context_overlay(self.overlays, SCENE_ID, self.manifest_path, self.manifest), {})


class PortableDemoContextTests(unittest.TestCase):
    scenes = {"hurricane-harvey_00000177": 76, "hurricane-michael_00000247": 175,
              "santa-rosa-wildfire_00000014": 48, "hurricane-florence_00000459": 40,
              "socal-fire_00000663": 47}

    def test_default_demo_context_is_displayable_and_preserves_predictions(self):
        self.assertEqual({p.stem for p in api.DEFAULT_GIS_CONTEXT_ROOT.glob("*.json")}, set(self.scenes))
        with patch.dict(os.environ, {"GIS_CONTEXT_ROOT": "", "DEMO_SCENE_ROOT": str(api.DEFAULT_DEMO_SCENE_ROOT),
                                     "DEMO_SCENES_ONLY": "1"}), patch("app.backend.api.load_classifier") as load:
            with TestClient(create_app()) as client:
                for scene, count in self.scenes.items():
                    package = json.loads((api.DEFAULT_GIS_CONTEXT_ROOT / f"{scene}.json").read_text(encoding="utf-8"))
                    manifest = json.loads((api.DEFAULT_DEMO_SCENE_ROOT / scene / "scene.json").read_text(encoding="utf-8"))
                    response = client.get(f"/demo-scenes/{scene}")
                    self.assertEqual(response.status_code, 200)
                    buildings = response.json()["buildings"]
                    self.assertEqual(sum("building_context" in b for b in buildings), count)
                    for original, actual in zip(manifest["buildings"], buildings):
                        self.assertEqual(actual["prediction"], original["prediction"])
                        context = package["buildings"][actual["uid"]]
                        if context["claims"]:
                            displayed_context = actual["building_context"]
                            self.assertEqual(displayed_context["claims"], context["claims"])
                            semantic_conflicts = [conflict for conflict in context["conflicts"]
                                                  if conflict["reason"] not in {
                                                      "historical_current_difference",
                                                      "modeled_vs_mapped_difference",
                                                  }]
                            self.assertEqual(displayed_context["conflicts"], semantic_conflicts)
                        else:
                            self.assertNotIn("building_context", actual)
                            semantic_conflicts = []
                        normalized = normalize_context(displayed_context["claims"], displayed_context["conflicts"]) if context["claims"] else normalize_context([], [])
                        displayed_notes = actual.get("building_context", {}).get("notes", [])
                        if displayed_notes != normalized["notes"]:
                            self.assertEqual(displayed_notes, sorted(set(normalized["notes"] + [
                                "Historical OSM was unavailable; event-time mapped context could not be assessed."
                            ])))
                            normalized["notes"] = displayed_notes
                        if context["claims"]:
                            self.assertEqual(normalized, displayed_context)
                        for claim in context["claims"]:
                            self.assertTrue(claim["displayable"])
                            self.assertLessEqual(set(claim["original_values"]), CLASSIFICATION_FIELDS)
                    for forbidden in ('"candidates":', '"source_record_id":', '"spatial_evidence":', '"raw_value":', '"med_yr_blt":'):
                        self.assertNotIn(forbidden, json.dumps(package))
                self.assertFalse(client.get("/health").json()["inference_available"])
            load.assert_not_called()

    def test_relocated_data_works_with_lf_and_crlf_without_audit_workspace(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            overlays, scenes = root / "app/demo_gis_context", root / "app/demo_scenes"
            shutil.copytree(api.DEFAULT_GIS_CONTEXT_ROOT, overlays)
            for scene in self.scenes:
                path = scenes / scene / "scene.json"
                path.parent.mkdir(parents=True)
                source = (api.DEFAULT_DEMO_SCENE_ROOT / scene / "scene.json").read_bytes().replace(b"\r\n", b"\n")
                for ending in (b"\n", b"\r\n"):
                    with self.subTest(scene=scene, ending=ending):
                        path.write_bytes(source.replace(b"\n", ending))
                        self.assertEqual(len(load_context_overlay(overlays, scene, path, json.loads(source))), self.scenes[scene])
                path.write_bytes(source + b" ")
                with self.assertLogs("app.backend.building_context", level="WARNING"):
                    self.assertEqual(load_context_overlay(overlays, scene, path, json.loads(source)), {})
                path.write_bytes(source)
            with patch.dict(os.environ, {"GIS_CONTEXT_ROOT": "", "DEMO_SCENE_ROOT": str(scenes), "DEMO_SCENES_ONLY": "1"}), \
                    patch("app.backend.api.DEFAULT_GIS_CONTEXT_ROOT", overlays):
                with TestClient(create_app()) as client:
                    for scene, count in self.scenes.items():
                        self.assertEqual(sum("building_context" in b for b in client.get(f"/demo-scenes/{scene}").json()["buildings"]), count)
            self.assertFalse((root / "local_experiments").exists())

    def test_explicit_override_and_missing_default_do_not_fall_back(self):
        with TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing"
            for override in (True, False):
                with self.subTest(override=override), patch.dict(os.environ, {
                    "GIS_CONTEXT_ROOT": str(missing) if override else "", "DEMO_SCENES_ONLY": "1",
                    "DEMO_SCENE_ROOT": str(api.DEFAULT_DEMO_SCENE_ROOT),
                }), patch("app.backend.api.DEFAULT_GIS_CONTEXT_ROOT", api.DEFAULT_GIS_CONTEXT_ROOT if override else missing):
                    with TestClient(create_app()) as client:
                        for scene in self.scenes:
                            response = client.get(f"/demo-scenes/{scene}")
                            self.assertEqual(response.status_code, 200)
                            self.assertTrue(all("building_context" not in b for b in response.json()["buildings"]))


if __name__ == "__main__":
    unittest.main()
