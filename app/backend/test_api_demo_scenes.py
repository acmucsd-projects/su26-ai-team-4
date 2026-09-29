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


class DemoSceneApiTests(unittest.TestCase):
    @contextmanager
    def client_for(self, root: Path):
        classifier = SimpleNamespace(device="cpu", class_names=[], val_metrics={})
        environment = {"DEMO_SCENE_ROOT": str(root)}
        with patch.dict(os.environ, environment, clear=False):
            with patch("app.backend.api.load_classifier", return_value=classifier):
                with TestClient(create_app(model_path=Path("unused-checkpoint.pt"))) as client:
                    yield client

    def test_scene_listing_manifest_and_assets(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_demo_scene(root)
            with self.client_for(root) as client:
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
            with self.client_for(Path(temporary_directory) / "missing") as client:
                self.assertEqual(client.get("/health").status_code, 200)
                self.assertEqual(client.get("/demo-scenes").json(), {"scenes": []})
                self.assertEqual(client.get(f"/demo-scenes/{SCENE_ID}").status_code, 404)

    def test_versioned_deployment_assets_are_served(self) -> None:
        with self.client_for(DEPLOYMENT_DEMO_SCENE_ROOT) as client:
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


if __name__ == "__main__":
    unittest.main()
