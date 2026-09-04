"""
Modal deployment for the building damage classifier API.

Setup (one-time):
    pip install modal
    modal setup                     # authenticates your CLI with your Modal account

Deploy:
    modal deploy modal_app.py

This prints a permanent public URL like:
    https://<your-workspace>--building-damage-classifier-fastapi-app.modal.run

Test locally against Modal's infra without deploying (spins up a temp URL):
    modal serve modal_app.py

Files expected next to this script:
    model.py                                     (architecture definition)
    resnet18_prepost_plaince_xbd_128_seed17_modal.pt   (checkpoint)
"""

import modal

app = modal.App("building-damage-classifier")

MODEL_FILENAME = "ACM/backend_modal/resnet18_prepost_plaince_xbd_128_seed17_modal.pt"
MODEL_REMOTE_PATH = f"/root/model/{MODEL_FILENAME}"

# --- Container image: system deps, Python deps, then our own code/weights ---
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "fastapi[standard]",
        "torch",
        "torchvision",
        "pillow",
        "python-multipart",
        "pydantic",
    )
    # Ship the checkpoint file itself (baked into the image layer so cold
    # starts don't need to fetch it separately)
    .add_local_file(MODEL_FILENAME, MODEL_REMOTE_PATH, copy=True)
    # Ship our local model.py so it's importable inside the container.
    # This must be the LAST add_local_* call: it defaults to copy=False
    # (mounted at container startup rather than baked into the image), and
    # Modal requires any copy=False local add to be the final build step.
    .add_local_python_source("model")
)


@app.function(
    image=image,
    # CPU is plenty for ResNet-18 at 128x128; add gpu="T4" here if you need
    # lower latency under heavy concurrent load.
    min_containers=0,          # scales to zero when idle (cheapest); set to 1
                                # to keep a warm instance and avoid cold starts
    scaledown_window=300,      # keep a container alive 5 min after last request
)
@modal.concurrent(max_inputs=10)  # let one container serve several requests at once
@modal.asgi_app()
def fastapi_app():
    import io

    import torch
    import torchvision.transforms as transforms
    from fastapi import FastAPI, File, HTTPException, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from PIL import Image as PILImage
    from pydantic import BaseModel

    from model import load_model

    IMAGE_SIZE = 128
    MAX_UPLOAD_BYTES = 10 * 1024 * 1024

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Loaded once when the container starts, reused across all requests it serves.
    model, CLASS_NAMES, VAL_METRICS = load_model(MODEL_REMOTE_PATH, device)

    preprocess = transforms.Compose([
        transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

    web_app = FastAPI(title="Building Damage Classifier API", version="1.0.0")

    # Set this to your actual published Webstudio domain before going live.
    web_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    class PredictResponse(BaseModel):
        predicted_class: str
        confidence: float
        probabilities: dict[str, float]

    def _load_image(raw_bytes: bytes, field_name: str) -> "PILImage.Image":
        try:
            return PILImage.open(io.BytesIO(raw_bytes)).convert("RGB")
        except Exception:
            raise HTTPException(status_code=400, detail=f"'{field_name}' is not a valid image file.")

    @web_app.get("/health")
    async def health():
        return {
            "status": "ok",
            "device": str(device),
            "classes": CLASS_NAMES,
            "val_accuracy": VAL_METRICS.get("accuracy"),
            "val_macro_f1": VAL_METRICS.get("macro_f1"),
        }

    @web_app.post("/predict", response_model=PredictResponse)
    async def predict(
        pre_image: UploadFile = File(...),
        post_image: UploadFile = File(...),
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

    return web_app
