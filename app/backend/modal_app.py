"""Modal deployment wrapper for the canonical paired-image FastAPI backend.

Set MODEL_PATH to the downloaded released checkpoint before deploying. The
checkpoint is copied into the Modal image; application behavior remains in
app.backend.api and app.backend.inference.
"""

from __future__ import annotations

import os
from pathlib import Path

import modal


APP_NAME = "building-damage-classifier-128"
CHECKPOINT_NAME = "resnet18_prepost_plaince_xbd_128_seed17.pt"
DEFAULT_SOURCE_CHECKPOINT_PATH = Path("checkpoints") / CHECKPOINT_NAME
REMOTE_CHECKPOINT_PATH = f"/models/{CHECKPOINT_NAME}"

base_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "fastapi==0.141.1",
        "python-multipart==0.0.32",
        "pillow",
        "torch",
        "torchvision",
        "pydantic==2.13.5",
    )
)

if modal.is_local():
    CHECKPOINT_SOURCE_PATH = Path(
        os.environ.get("MODEL_PATH", str(DEFAULT_SOURCE_CHECKPOINT_PATH))
    )
    if not CHECKPOINT_SOURCE_PATH.is_file():
        raise FileNotFoundError(
            f"Modal deployment checkpoint not found at {CHECKPOINT_SOURCE_PATH}. "
            "Download the released checkpoint and set MODEL_PATH to its local path before deploying."
        )
    image = (
        base_image.add_local_file(CHECKPOINT_SOURCE_PATH, REMOTE_CHECKPOINT_PATH, copy=True)
        .add_local_python_source("app.backend", copy=True)
    )
else:
    # The checkpoint was packaged during local deployment. Set the canonical
    # backend configuration before Modal imports this module in the container.
    os.environ.setdefault("MODEL_PATH", REMOTE_CHECKPOINT_PATH)
    image = base_image

app = modal.App(APP_NAME)


@app.function(image=image, min_containers=0, scaledown_window=300)
@modal.concurrent(max_inputs=10)
@modal.asgi_app()
def fastapi_app():
    """Expose the canonical FastAPI application as a Modal web function."""

    os.environ["MODEL_PATH"] = REMOTE_CHECKPOINT_PATH

    from app.backend.api import create_app

    return create_app()
