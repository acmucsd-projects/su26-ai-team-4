"""Focused endpoint tests for optional locally packaged dashboard scenes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.backend.api import create_app
from app.backend.assessment_openai import AssessmentProviderError


SCENE_ID = "hurricane-michael_00000247"
CURATED_SCENE_IDS = {
    "hurricane-michael_00000247",
    "hurricane-harvey_00000177",
    "hurricane-matthew_00000060",
    "hurricane-florence_00000459",
    "palu-tsunami_00000065",
    "santa-rosa-wildfire_00000014",
    "socal-fire_00000663",
}
DEPLOYMENT_DEMO_SCENE_ROOT = Path(__file__).resolve().parents[1] / "demo_scenes"


def write_demo_scene(root: Path) -> None:
    scene_directory = root / SCENE_ID
    crops_directory = scene_directory / "crops"
    crops_directory.mkdir(parents=True)
    for asset in (scene_directory / "pre.png", scene_directory / "post.png", crops_directory / "0000001_pre.png"):
        asset.write_bytes(b"demo asset")
    (scene_directory / "scene.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scene_id": SCENE_ID,
                "event_name": "hurricane-michael",
                "image": {"width": 1024, "height": 1024, "pre_url": "pre.png", "post_url": "post.png"},
                "buildings": [{"id": f"{SCENE_ID}_b0000", "crops": {"pre_url": "crops/0000001_pre.png"}}],
            }
        ),
        encoding="utf-8",
    )


@contextmanager
def client_for(root: Path):
    classifier = SimpleNamespace(device="cpu", class_names=[], val_metrics={})
    environment = {"DEMO_SCENE_ROOT": str(root)}
    with patch.dict(os.environ, environment, clear=False):
        with patch("app.backend.api.load_classifier", return_value=classifier):
            with TestClient(create_app(model_path=Path("unused-checkpoint.pt"))) as client:
                yield client


class DemoSceneApiTests(unittest.TestCase):
    def test_scene_listing_manifest_and_assets(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_demo_scene(root)
            with client_for(root) as client:
                self.assertEqual(client.get("/health").status_code, 200)
                self.assertEqual(client.get("/demo-scenes").json(), {"scenes": [{"scene_id": SCENE_ID, "event_name": "hurricane-michael", "building_count": 1}]})

                scene = client.get(f"/demo-scenes/{SCENE_ID}")
                self.assertEqual(scene.status_code, 200)
                self.assertEqual(scene.json()["image"]["post_url"], f"/demo-scenes/{SCENE_ID}/post.png")
                self.assertEqual(scene.json()["buildings"][0]["crops"]["pre_url"], f"/demo-scenes/{SCENE_ID}/crops/0000001_pre.png")
                self.assertEqual(client.get(f"/demo-scenes/{SCENE_ID}/post.png").status_code, 200)
                self.assertEqual(client.get(f"/demo-scenes/{SCENE_ID}/crops/0000001_pre.png").status_code, 200)
                self.assertEqual(client.get("/demo-scenes/not.a.scene").status_code, 404)
                self.assertEqual(client.get(f"/demo-scenes/{SCENE_ID}/crops/not-found.png").status_code, 404)
                self.assertEqual(client.get(f"/demo-scenes/{SCENE_ID}/crops/%2E%2E/scene.json").status_code, 404)

    def test_missing_demo_scene_root_does_not_prevent_startup(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            with client_for(Path(temporary_directory) / "missing") as client:
                self.assertEqual(client.get("/health").status_code, 200)
                self.assertEqual(client.get("/demo-scenes").json(), {"scenes": []})
                self.assertEqual(client.get(f"/demo-scenes/{SCENE_ID}").status_code, 404)

    def test_versioned_deployment_assets_are_served(self) -> None:
        with client_for(DEPLOYMENT_DEMO_SCENE_ROOT) as client:
            scenes = client.get("/demo-scenes").json()["scenes"]
            self.assertEqual({scene["scene_id"] for scene in scenes}, CURATED_SCENE_IDS)

            scene = client.get(f"/demo-scenes/{SCENE_ID}")
            self.assertEqual(scene.status_code, 200)
            manifest = scene.json()
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(client.get(manifest["image"]["pre_url"]).status_code, 200)
            self.assertEqual(client.get(manifest["image"]["post_url"]).status_code, 200)
            self.assertEqual(client.get(manifest["buildings"][0]["crops"]["pre_url"]).status_code, 200)

    def test_assessment_preview_uses_normalized_optional_context_without_provider_call(self) -> None:
        with patch.dict(os.environ, {
            "DEMO_SCENE_ROOT": str(DEPLOYMENT_DEMO_SCENE_ROOT),
            "GIS_CONTEXT_ROOT": "",
            "DEMO_SCENES_ONLY": "1",
        }, clear=False):
            with TestClient(create_app()) as client:
                florence = client.get("/demo-scenes/hurricane-florence_00000459").json()
                selected = next(b for b in florence["buildings"] if "building_context" in b)
                preview = client.get(
                    f"/demo-scenes/hurricane-florence_00000459/buildings/{selected['id']}/assessment-preview"
                )
                self.assertEqual(preview.status_code, 200)
                payload = preview.json()
                self.assertEqual(payload["status"], "preview_only")
                self.assertEqual(payload["provider_status"], "disabled")
                self.assertEqual(payload["evidence_packet"]["damage_prediction"]["predicted_class"],
                                 selected["prediction"]["predicted_class"])
                claim = payload["evidence_packet"]["context"]["claims"][0]
                self.assertTrue(claim["modeled"])
                self.assertEqual(claim["temporal_relation"], "current_modeled_not_event_aligned")
                self.assertNotIn("assessment", payload)

                matthew = client.get("/demo-scenes/hurricane-matthew_00000060").json()
                building = matthew["buildings"][0]
                no_context = client.get(
                    f"/demo-scenes/hurricane-matthew_00000060/buildings/{building['id']}/assessment-preview"
                )
                self.assertEqual(no_context.status_code, 200)
                self.assertFalse(no_context.json()["evidence_packet"]["context"]["available"])
                self.assertEqual(no_context.json()["evidence_packet"]["context"]["claims"], [])

                self.assertEqual(client.get("/demo-scenes/unknown_scene/buildings/id/assessment-preview").status_code, 404)
                self.assertEqual(client.get("/demo-scenes/hurricane-matthew_00000060/buildings/not-found/assessment-preview").status_code, 404)
                self.assertEqual(client.get("/demo-scenes/not.valid/buildings/id/assessment-preview").status_code, 404)
                self.assertEqual(client.get("/demo-scenes/hurricane-matthew_00000060/buildings/bad!/assessment-preview").status_code, 404)


class FakeAssessmentProvider:
    def __init__(self, result=None, error=None):
        self.result = result or {
            "assessment": "The model predicts minor damage.",
            "limitations": ["GIS context does not establish individual identity."],
            "prompt_version": "building-assessment-v1",
            "generated_by": "fake-provider-for-test",
        }
        self.error = error
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.result


class AssessmentGenerationApiTests(unittest.TestCase):
    def test_generation_endpoint_uses_normalized_florence_and_missing_context_packets(self) -> None:
        provider = FakeAssessmentProvider()
        environment = {
            "DEMO_SCENE_ROOT": str(DEPLOYMENT_DEMO_SCENE_ROOT),
            "GIS_CONTEXT_ROOT": "",
            "DEMO_SCENES_ONLY": "1",
            "OPENAI_API_KEY": "",
        }
        with patch.dict(os.environ, environment, clear=False):
            with patch("app.backend.api.configured_assessment_provider", return_value=provider):
                with TestClient(create_app()) as client:
                    florence_scene = client.get("/demo-scenes/hurricane-florence_00000459").json()
                    florence_building = next(
                        building for building in florence_scene["buildings"]
                        if "building_context" in building
                    )
                    florence = client.post(
                        f"/demo-scenes/hurricane-florence_00000459/buildings/{florence_building['id']}/assessment"
                    )
                    self.assertEqual(florence.status_code, 200)
                    self.assertEqual(florence.json(), provider.result)

                    matthew_scene = client.get("/demo-scenes/hurricane-matthew_00000060").json()
                    matthew_building = matthew_scene["buildings"][0]
                    matthew = client.post(
                        f"/demo-scenes/hurricane-matthew_00000060/buildings/{matthew_building['id']}/assessment"
                    )
                    self.assertEqual(matthew.status_code, 200)

                    self.assertEqual(len(provider.prompts), 2)
                    florence_packet = json.loads(provider.prompts[0]["user"].split("\n", 1)[1])
                    claim = florence_packet["context"]["claims"][0]
                    self.assertTrue(claim["modeled"])
                    self.assertEqual(claim["temporal_relation"], "current_modeled_not_event_aligned")
                    self.assertIn("not event-aligned", claim["timing"])
                    self.assertEqual(florence_packet["damage_prediction"]["predicted_class"],
                                     florence_building["prediction"]["predicted_class"])

                    matthew_packet = json.loads(provider.prompts[1]["user"].split("\n", 1)[1])
                    self.assertFalse(matthew_packet["context"]["available"])
                    self.assertEqual(matthew_packet["context"]["claims"], [])
                    self.assertIn("No reviewed GIS context", " ".join(matthew_packet["limitations"]))

    def test_generation_endpoint_preserves_parcel_site_and_area_scope(self) -> None:
        scene_id = "hurricane-harvey_00000177"
        scene = json.loads((DEPLOYMENT_DEMO_SCENE_ROOT / scene_id / "scene.json").read_text(encoding="utf-8"))
        overlay_path = Path(__file__).resolve().parents[1] / "demo_gis_context" / f"{scene_id}.json"
        contexts = json.loads(overlay_path.read_text(encoding="utf-8"))["buildings"]
        cases = (
            ("parcel", lambda claim: claim["scope"] == "parcel" and claim["kind"] == "property_use"),
            ("site", lambda claim: claim["scope"] == "site" and claim["kind"] == "site_use"),
            ("area", lambda claim: claim["scope"] == "site" and claim["kind"] == "area_use"),
        )
        selected = {}
        for name, predicate in cases:
            selected[name] = next(
                building for building in scene["buildings"]
                if building.get("uid") in contexts
                and any(predicate(claim) for claim in contexts[building["uid"]]["claims"])
            )

        provider = FakeAssessmentProvider()
        environment = {
            "DEMO_SCENE_ROOT": str(DEPLOYMENT_DEMO_SCENE_ROOT),
            "GIS_CONTEXT_ROOT": "",
            "DEMO_SCENES_ONLY": "1",
        }
        with patch.dict(os.environ, environment, clear=False):
            with patch("app.backend.api.configured_assessment_provider", return_value=provider):
                with TestClient(create_app()) as client:
                    for building in selected.values():
                        result = client.post(
                            f"/demo-scenes/{scene_id}/buildings/{building['id']}/assessment"
                        )
                        self.assertEqual(result.status_code, 200)

        self.assertEqual(len(provider.prompts), 3)
        packets = [json.loads(item["user"].split("\n", 1)[1]) for item in provider.prompts]
        for (name, _predicate), packet in zip(cases, packets, strict=True):
            if name == "parcel":
                claim = next(claim for claim in packet["context"]["claims"] if claim["scope"] == "parcel")
                self.assertIn("parcel_context", claim["qualifications"])
                self.assertIn("property", claim["normalized_context_scopes"])
            elif name == "site":
                claim = next(claim for claim in packet["context"]["claims"] if claim["type"] == "site_use")
                self.assertEqual(claim["scope"], "site")
            else:
                claim = next(claim for claim in packet["context"]["claims"] if claim["type"] == "area_use")
                self.assertEqual(claim["scope"], "site")
                self.assertIn("area", claim["normalized_context_scopes"])

    def test_missing_key_is_unavailable_but_preview_still_works(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_demo_scene(root)
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
                with client_for(root) as client:
                    preview = client.get(
                        f"/demo-scenes/{SCENE_ID}/buildings/{SCENE_ID}_b0000/assessment-preview"
                    )
                    response = client.post(
                        f"/demo-scenes/{SCENE_ID}/buildings/{SCENE_ID}_b0000/assessment"
                    )
                    self.assertEqual(preview.status_code, 200)
                    self.assertEqual(preview.json()["provider_status"], "disabled")
                    self.assertNotIn("assessment", preview.json())
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.json()["detail"]["code"], "assessment_provider_unavailable")
                    self.assertNotIn("key", response.text.lower())

    def test_invalid_scene_or_building_and_provider_errors_are_clean(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_demo_scene(root)
            provider = FakeAssessmentProvider(error=RuntimeError("provider internals"))
            with patch("app.backend.api.configured_assessment_provider", return_value=provider):
                with client_for(root) as client:
                    base = f"/demo-scenes/{SCENE_ID}/buildings"
                    self.assertEqual(client.post("/demo-scenes/unknown/buildings/id/assessment").status_code, 404)
                    self.assertEqual(client.post(f"{base}/not-found/assessment").status_code, 404)
                    result = client.post(f"{base}/{SCENE_ID}_b0000/assessment")
                    self.assertEqual(result.status_code, 502)
                    self.assertEqual(result.json()["detail"]["code"], "assessment_provider_failed")
                    self.assertNotIn("provider internals", result.text)


if __name__ == "__main__":
    unittest.main()
