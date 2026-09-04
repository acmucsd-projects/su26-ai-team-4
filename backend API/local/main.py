"""
FastAPI service for the pre/post-disaster building damage classifier.

Endpoints:
  GET  /health   - liveness + model info
  POST /predict  - upload a PRE-disaster and POST-disaster image of the
                    SAME building -> returns predicted damage class +
                    per-class probabilities.

Run locally:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

The checkpoint file (resnet18_prepost_plaince_xbd_128_seed17.pt) must sit
next to this file, or set MODEL_PATH env var to point elsewhere.
"""

import io
import os

import torch
import torchvision.transforms as transforms
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel

from model import load_model

MODEL_PATH = os.environ.get(
    "MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "resnet18_prepost_plaince_xbd_128_seed17.pt"),
)
IMAGE_SIZE = 128  # matches training config
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB per image, adjust as needed

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

app = FastAPI(title="Building Damage Classifier API", version="1.0.0")

# Restrict this to your actual frontend origin(s) before going to production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Load model once at startup ---
model, CLASS_NAMES, VAL_METRICS = load_model(MODEL_PATH, device)

# Standard ImageNet normalization -- matches ResNet18_Weights.DEFAULT
# preprocessing used during training.
preprocess = transforms.Compose([
    transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])


class PredictResponse(BaseModel):
    predicted_class: str
    confidence: float
    probabilities: dict[str, float]


def _load_image(raw_bytes: bytes, field_name: str) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail=f"'{field_name}' is not a valid image file.")
    return img


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "device": str(device),
        "classes": CLASS_NAMES,
        "val_accuracy": VAL_METRICS.get("accuracy"),
        "val_macro_f1": VAL_METRICS.get("macro_f1"),
    }


@app.post("/predict", response_model=PredictResponse)
async def predict(
    pre_image: UploadFile = File(..., description="Pre-disaster image of the building"),
    post_image: UploadFile = File(..., description="Post-disaster image of the same building"),
):
    pre_bytes = await pre_image.read()
    post_bytes = await post_image.read()

    for name, b in (("pre_image", pre_bytes), ("post_image", post_bytes)):
        if len(b) == 0:
            raise HTTPException(status_code=400, detail=f"'{name}' is empty.")
        if len(b) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"'{name}' exceeds max size.")

    pre_img = _load_image(pre_bytes, "pre_image")
    post_img = _load_image(post_bytes, "post_image")

    pre_tensor = preprocess(pre_img).unsqueeze(0).to(device)
    post_tensor = preprocess(post_img).unsqueeze(0).to(device)

    with torch.no_grad():
        logits = model(pre_tensor, post_tensor)
        probs = torch.softmax(logits, dim=1)[0]

    top_idx = int(torch.argmax(probs).item())

    return PredictResponse(
        predicted_class=CLASS_NAMES[top_idx],
        confidence=float(probs[top_idx]),
        probabilities={CLASS_NAMES[i]: float(probs[i]) for i in range(len(CLASS_NAMES))},
    )
