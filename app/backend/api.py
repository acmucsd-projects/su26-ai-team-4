"""FastAPI entry point for paired PRE/POST building-damage inference."""

from __future__ import annotations

from contextlib import asynccontextmanager
import io
import os
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

from .inference import LoadedClassifier, load_classifier, predict_images


DEFAULT_CHECKPOINT_NAME = "resnet18_prepost_plaince_xbd_128_seed17.pt"
DEFAULT_CHECKPOINT_PATH = Path(__file__).resolve().parents[2] / "checkpoints" / DEFAULT_CHECKPOINT_NAME
DEFAULT_FRONTEND_PATH = Path(__file__).resolve().parents[1] / "frontend"
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

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.classifier = load_classifier(selected_model_path)
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
        classifier: LoadedClassifier = app.state.classifier
        return {
            "status": "ok",
            "device": str(classifier.device),
            "classes": classifier.class_names,
            "val_accuracy": classifier.val_metrics.get("accuracy"),
            "val_macro_f1": classifier.val_metrics.get("macro_f1"),
        }

    @app.post("/predict", response_model=PredictResponse)
    async def predict(
        pre_image: UploadFile = File(..., description="PRE-disaster crop of the building"),
        post_image: UploadFile = File(..., description="POST-disaster crop of the same building"),
    ) -> PredictResponse:
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
