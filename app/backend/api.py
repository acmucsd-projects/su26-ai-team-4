"""FastAPI entry point for paired PRE/POST building-damage inference."""

from __future__ import annotations

from contextlib import asynccontextmanager
import copy
import io
import json
import os
from pathlib import Path
from typing import AsyncIterator
import re

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

from .building_context import load_context_overlay
from .assessment import build_assessment_preview, build_evidence_packet, build_prompt
from .assessment_openai import AssessmentProviderError, configured_assessment_provider
from .local_env import load_repo_dotenv
from .scene_assessment import (
    build_scene_assessment_preview,
    build_scene_assessment_prompt,
)
from .scene_evidence import build_scene_evidence
from .scene_evidence import build_scene_metadata


load_repo_dotenv()


def load_classifier(model_path):
    # Scene-only review needs neither a checkpoint nor the inference dependencies.
    from .inference import load_classifier as load
    return load(model_path)


def predict_images(classifier, pre_image, post_image):
    from .inference import predict_images as predict
    return predict(classifier, pre_image, post_image)


DEFAULT_CHECKPOINT_NAME = "resnet18_prepost_plaince_xbd_128_seed17.pt"
DEFAULT_CHECKPOINT_PATH = Path(__file__).resolve().parents[2] / "checkpoints" / DEFAULT_CHECKPOINT_NAME
DEFAULT_FRONTEND_PATH = Path(__file__).resolve().parents[1] / "frontend"
DEFAULT_DEMO_SCENE_ROOT = Path(__file__).resolve().parents[1] / "demo_scenes"
DEFAULT_GIS_CONTEXT_ROOT = Path(__file__).resolve().parents[1] / "demo_gis_context"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class PredictResponse(BaseModel):
    predicted_class: str
    confidence: float
    probabilities: dict[str, float]


def configured_model_path() -> Path:
    """Resolve MODEL_PATH, defaulting to the documented local checkpoints directory."""

    return Path(os.environ.get("MODEL_PATH", DEFAULT_CHECKPOINT_PATH))


def configured_frontend_path() -> Path:
    """Resolve the static demo frontend directory."""

    return Path(os.environ.get("FRONTEND_PATH", DEFAULT_FRONTEND_PATH))


def configured_demo_scene_root() -> Path:
    """Resolve the optional packaged dashboard-scene root."""

    return Path(os.environ.get("DEMO_SCENE_ROOT", DEFAULT_DEMO_SCENE_ROOT))


def is_safe_scene_id(scene_id: str) -> bool:
    """Allow only simple directory names, never path fragments."""

    return re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", scene_id) is not None


def demo_scene_directory(demo_scene_root: Path, scene_id: str) -> Path:
    """Resolve a packaged scene directory while rejecting traversal attempts."""

    if not is_safe_scene_id(scene_id):
        raise HTTPException(status_code=404, detail="Demo scene not found.")
    scene_directory = (demo_scene_root / scene_id).resolve()
    root = demo_scene_root.resolve()
    if not scene_directory.is_relative_to(root) or not scene_directory.is_dir():
        raise HTTPException(status_code=404, detail="Demo scene not found.")
    return scene_directory


def load_demo_scene_manifest(scene_directory: Path, scene_id: str) -> dict[str, object]:
    """Load one scene manifest, treating absent or malformed local packs as unavailable."""

    manifest_path = scene_directory / "scene.json"
    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=404, detail="Demo scene not found.") from error
    if not isinstance(manifest, dict) or manifest.get("scene_id") != scene_id:
        raise HTTPException(status_code=404, detail="Demo scene not found.")
    return manifest


def scene_asset_url(scene_id: str, relative_asset_path: object) -> str:
    """Turn a pack-relative asset reference into its public API URL."""

    if not isinstance(relative_asset_path, str):
        raise HTTPException(status_code=404, detail="Demo scene not found.")
    return f"/demo-scenes/{scene_id}/{relative_asset_path.lstrip('/')}"


def public_demo_scene_manifest(manifest: dict[str, object], scene_id: str) -> dict[str, object]:
    """Return a manifest copy with pack-relative image URLs expanded for clients."""

    public_manifest = copy.deepcopy(manifest)
    image = public_manifest.get("image")
    if isinstance(image, dict):
        for key in ("pre_url", "post_url"):
            if key in image:
                image[key] = scene_asset_url(scene_id, image[key])
    buildings = public_manifest.get("buildings")
    if isinstance(buildings, list):
        for building in buildings:
            if not isinstance(building, dict):
                continue
            crops = building.get("crops")
            if isinstance(crops, dict):
                for key in ("pre_url", "post_url"):
                    if key in crops:
                        crops[key] = scene_asset_url(scene_id, crops[key])
    return public_manifest


def resolve_demo_scene_asset(scene_directory: Path, asset_path: str) -> Path:
    """Resolve one relative scene asset without exposing other filesystem paths."""

    asset = Path(asset_path)
    if not asset_path or asset.is_absolute() or any(part in {"", ".", ".."} for part in asset.parts):
        raise HTTPException(status_code=404, detail="Demo scene asset not found.")
    resolved_asset = (scene_directory / asset).resolve()
    if not resolved_asset.is_relative_to(scene_directory.resolve()) or not resolved_asset.is_file():
        raise HTTPException(status_code=404, detail="Demo scene asset not found.")
    return resolved_asset


def decode_image(raw_bytes: bytes, field_name: str) -> Image.Image:
    """Decode one upload as an independent RGB image."""

    try:
        with Image.open(io.BytesIO(raw_bytes)) as image:
            return image.convert("RGB").copy()
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"'{field_name}' is not a valid image file.") from error


def create_app(model_path: Path | None = None) -> FastAPI:
    """Create an app that loads its checkpoint once during process startup."""

    selected_model_path = model_path or configured_model_path()
    frontend_path = configured_frontend_path()
    demo_scene_root = configured_demo_scene_root()
    context_root = Path(os.environ["GIS_CONTEXT_ROOT"]) if os.environ.get("GIS_CONTEXT_ROOT") else DEFAULT_GIS_CONTEXT_ROOT
    scenes_only = os.environ.get("DEMO_SCENES_ONLY") == "1"

    def assessment_target(scene_id: str, building_id: str):
        """Resolve one selected building and its validated optional GIS context."""

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", building_id):
            raise HTTPException(status_code=404, detail="Demo building not found.")
        scene_directory = demo_scene_directory(demo_scene_root, scene_id)
        manifest_path = scene_directory / "scene.json"
        manifest = load_demo_scene_manifest(scene_directory, scene_id)
        buildings = manifest.get("buildings")
        if not isinstance(buildings, list):
            raise HTTPException(status_code=404, detail="Demo building not found.")
        matches = [building for building in buildings
                   if isinstance(building, dict) and building.get("id") == building_id]
        if len(matches) != 1:
            raise HTTPException(status_code=404, detail="Demo building not found.")
        building = matches[0]
        overlay = load_context_overlay(context_root, scene_id, manifest_path, manifest)
        uid = building.get("uid")
        context = overlay.get(uid) if isinstance(uid, str) else None
        return manifest, building, context, overlay

    def scene_assessment_target(scene_id: str):
        """Resolve one packaged manifest and its reviewed optional overlay."""

        scene_directory = demo_scene_directory(demo_scene_root, scene_id)
        manifest_path = scene_directory / "scene.json"
        manifest = load_demo_scene_manifest(scene_directory, scene_id)
        overlay = load_context_overlay(context_root, scene_id, manifest_path, manifest)
        return manifest, overlay

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.classifier = None if scenes_only else load_classifier(selected_model_path)
        yield

    app = FastAPI(title="Building Damage Classifier API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", include_in_schema=False)
    async def frontend() -> FileResponse:
        return FileResponse(frontend_path / "index.html")

    @app.get("/health")
    async def health() -> dict[str, object]:
        classifier = app.state.classifier
        if scenes_only:
            return {"status": "ok", "mode": "scenes_only", "inference_available": False}
        return {
            "status": "ok",
            "device": str(classifier.device),
            "classes": classifier.class_names,
            "val_accuracy": classifier.val_metrics.get("accuracy"),
            "val_macro_f1": classifier.val_metrics.get("macro_f1"),
        }

    @app.get("/demo-scenes")
    async def list_demo_scenes() -> dict[str, list[dict[str, object]]]:
        """List valid locally packaged dashboard demo scenes, if any are available."""

        if not demo_scene_root.is_dir():
            return {"scenes": []}
        scenes: list[dict[str, object]] = []
        for scene_directory in sorted(demo_scene_root.iterdir(), key=lambda path: path.name):
            if not scene_directory.is_dir() or not is_safe_scene_id(scene_directory.name):
                continue
            try:
                manifest = load_demo_scene_manifest(scene_directory, scene_directory.name)
            except HTTPException:
                continue
            buildings = manifest.get("buildings")
            scenes.append(
                {
                    "scene_id": scene_directory.name,
                    "event_name": manifest.get("event_name"),
                    "building_count": len(buildings) if isinstance(buildings, list) else 0,
                }
            )
        return {"scenes": scenes}

    @app.get("/demo-scenes/{scene_id}")
    async def get_demo_scene(scene_id: str) -> dict[str, object]:
        """Return one packaged scene manifest with client-ready asset URLs."""

        scene_directory = demo_scene_directory(demo_scene_root, scene_id)
        manifest = load_demo_scene_manifest(scene_directory, scene_id)
        overlay = load_context_overlay(context_root, scene_id, scene_directory / "scene.json", manifest)
        public_manifest = public_demo_scene_manifest(manifest, scene_id)
        if overlay:
            for building in public_manifest["buildings"]:
                if building["uid"] in overlay:
                    building["building_context"] = overlay[building["uid"]]
        event_context = build_scene_metadata(manifest)
        public_manifest["scene_evidence_context"] = {
            key: event_context[key]
            for key in ("event_name", "location", "location_scope", "post_acquisition_date")
        }
        return public_manifest

    @app.get("/demo-scenes/{scene_id}/buildings/{building_id}/assessment-preview")
    async def preview_building_assessment(scene_id: str, building_id: str) -> dict[str, object]:
        """Preview the exact evidence packet and prompt; no LLM provider is called."""

        manifest, building, context, overlay = assessment_target(scene_id, building_id)
        scene_evidence = build_scene_evidence(manifest, overlay)
        return build_assessment_preview(manifest, building, context, scene_evidence=scene_evidence)

    @app.get("/demo-scenes/{scene_id}/assessment-preview")
    async def preview_scene_assessment(scene_id: str) -> dict[str, object]:
        """Return shared scene evidence and exact prompt without provider work."""

        manifest, contexts = scene_assessment_target(scene_id)
        return build_scene_assessment_preview(manifest, contexts)

    @app.post("/demo-scenes/{scene_id}/buildings/{building_id}/assessment")
    def generate_building_assessment(scene_id: str, building_id: str) -> dict[str, object]:
        """Generate one paid, structured assessment from the canonical evidence packet."""

        manifest, building, context, overlay = assessment_target(scene_id, building_id)
        provider = getattr(app.state, "assessment_provider", None)
        if provider is None:
            provider = configured_assessment_provider()
            if provider is not None:
                app.state.assessment_provider = provider
        if provider is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "assessment_provider_unavailable",
                    "message": "Assessment generation is not configured.",
                },
            )

        scene_evidence = build_scene_evidence(manifest, overlay)
        packet = build_evidence_packet(manifest, building, context, scene_evidence=scene_evidence)
        prompt = build_prompt(packet)
        try:
            result = provider.generate(prompt)
            evidence_used = []
            prediction = packet["damage_prediction"]
            if prediction["predicted_class"] is not None:
                evidence_used.append("model")
            if packet["scene_context"].get("spatial_context"):
                evidence_used.append("spatial")
            if packet["event_context"].get("event_name"):
                evidence_used.append("event")
            if packet["context"]["available"]:
                evidence_used.append("reviewed_gis")
            return {**result, "evidence_used": evidence_used}
        except AssessmentProviderError as error:
            raise HTTPException(
                status_code=error.status_code,
                detail={"code": error.code, "message": error.message},
            ) from None
        except Exception:
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "assessment_provider_failed",
                    "message": "Assessment generation failed. Please try again later.",
                },
            ) from None

    @app.post("/demo-scenes/{scene_id}/assessment")
    def generate_scene_assessment(scene_id: str) -> dict[str, object]:
        """Generate one scene overview from deterministic evidence only."""

        manifest, contexts = scene_assessment_target(scene_id)
        provider = getattr(app.state, "assessment_provider", None)
        if provider is None:
            provider = configured_assessment_provider()
            if provider is not None:
                app.state.assessment_provider = provider
        if provider is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "assessment_provider_unavailable",
                    "message": "Assessment generation is not configured.",
                },
            )

        scene_evidence = build_scene_evidence(manifest, contexts)
        prompt = build_scene_assessment_prompt(scene_evidence)
        try:
            result = provider.generate_scene(prompt)
            from .assessment_openai import normalize_scene_assessment_result

            normalized = normalize_scene_assessment_result(result, scene_evidence)
            evidence_used = ["model"]
            if scene_evidence["spatial_summary"]["usable_geometry_buildings"]:
                evidence_used.append("spatial")
            if scene_evidence["event"].get("event_name") or scene_evidence["event"].get("hazard_type"):
                evidence_used.append("event")
            if scene_evidence["gis_summary"]["buildings_with_reviewed_context"]:
                evidence_used.append("reviewed_gis")
            return {**normalized, "evidence_used": evidence_used}
        except AssessmentProviderError as error:
            raise HTTPException(
                status_code=error.status_code,
                detail={"code": error.code, "message": error.message},
            ) from None
        except Exception:
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "assessment_provider_failed",
                    "message": "Assessment generation failed. Please try again later.",
                },
            ) from None
    @app.get("/demo-scenes/{scene_id}/{asset_path:path}")
    async def get_demo_scene_asset(scene_id: str, asset_path: str) -> FileResponse:
        """Serve a packaged scene image or crop via a validated relative path."""

        scene_directory = demo_scene_directory(demo_scene_root, scene_id)
        return FileResponse(resolve_demo_scene_asset(scene_directory, asset_path))

    @app.post("/predict", response_model=PredictResponse)
    async def predict(
        pre_image: UploadFile = File(..., description="PRE-disaster crop of the building"),
        post_image: UploadFile = File(..., description="POST-disaster crop of the same building"),
    ) -> PredictResponse:
        if scenes_only:
            raise HTTPException(status_code=503, detail="Scene-only demo: select a scene building to view its precomputed result. New predictions are disabled.")
        uploads = (("pre_image", pre_image), ("post_image", post_image))
        image_bytes: dict[str, bytes] = {}
        for field_name, upload in uploads:
            raw_bytes = await upload.read()
            if not raw_bytes:
                raise HTTPException(status_code=400, detail=f"'{field_name}' is empty.")
            if len(raw_bytes) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail=f"'{field_name}' exceeds max size.")
            image_bytes[field_name] = raw_bytes

        prediction = predict_images(
            app.state.classifier,
            decode_image(image_bytes["pre_image"], "pre_image"),
            decode_image(image_bytes["post_image"], "post_image"),
        )
        return PredictResponse(**prediction)

    # Mount last so the explicit API routes above keep precedence.
    app.mount("/", StaticFiles(directory=frontend_path), name="frontend")

    return app


app = create_app()
