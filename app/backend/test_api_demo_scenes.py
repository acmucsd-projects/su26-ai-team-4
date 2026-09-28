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

    def test_packaged_gis_context_coverage_and_socal_semantics(self) -> None:
        expected_context = {
            "hurricane-harvey_00000177": (76, 76),
            "hurricane-michael_00000247": (177, 175),
            "santa-rosa-wildfire_00000014": (49, 48),
            "hurricane-florence_00000459": (56, 40),
            "socal-fire_00000663": (48, 47),
            "hurricane-matthew_00000060": (75, 0),
            "palu-tsunami_00000065": (129, 0),
        }
        with self.client_for(DEPLOYMENT_DEMO_SCENE_ROOT) as client:
            for scene_id, (building_count, context_count) in expected_context.items():
                response = client.get(f"/demo-scenes/{scene_id}")
                self.assertEqual(response.status_code, 200, scene_id)
                buildings = response.json()["buildings"]
                self.assertEqual(len(buildings), building_count, scene_id)
                self.assertEqual(sum("building_context" in row for row in buildings), context_count, scene_id)

            socal = client.get("/demo-scenes/socal-fire_00000663").json()["buildings"]
            contexts = [row["building_context"] for row in socal if "building_context" in row]
            claims = [claim for context in contexts for claim in context["claims"]]
            current_roof = [c for c in claims if c["kind"] == "structure_type"]
            modeled = [c for c in claims if c["kind"] == "modeled_occupancy"]
            areas = [c for c in claims if c["kind"] == "area_use"]
            self.assertTrue(current_roof)
            self.assertTrue(all(c["source_dataset"] == "osm_current" and c["temporal_relation"] == "current_only" and not c["modeled"] for c in current_roof))
            self.assertTrue(modeled)
            self.assertTrue(all(c["source_key"] == "nsi" and c["modeled"] and c["temporal_relation"] == "current_modeled_not_event_aligned" for c in modeled))
            self.assertTrue(areas)
            self.assertTrue(all(c["scope"] == "site" and "surrounding_area" in c["qualifications"] for c in areas))
            self.assertTrue(all(any("Historical OSM was unavailable" in note for note in context["notes"]) for context in contexts))
            self.assertEqual(sum("building_context" not in row for row in socal), 1)
            self.assertEqual(sum(c["kind"] == "mapped_name" for c in claims), 0)
            self.assertEqual(sum(c["kind"] in {"property_use", "structure_use", "parcel_reference"} for c in claims), 0)


if __name__ == "__main__":
    unittest.main()
