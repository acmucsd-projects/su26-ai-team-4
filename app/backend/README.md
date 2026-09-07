# Application backend

FastAPI backend for the released paired PRE+POST ResNet-18 plain-cross-entropy xBD checkpoint.

## Input contract

POST /predict accepts multipart fields named pre_image and post_image. Each must be a PRE/POST satellite building crop of the same building, aligned as an xBD-style pair. This backend does not detect buildings in full satellite scenes.

The response contains predicted_class, confidence, and probabilities for no-damage, minor-damage, major-damage, and destroyed.

## Local startup

Install the backend dependencies from the repository root:

~~~bash
pip install -r app/backend/requirements.txt
~~~

Download resnet18_prepost_plaince_xbd_128_seed17.pt from the project's GitHub Release. You may place it in checkpoints/ (the default path), or set MODEL_PATH to its local path:

~~~powershell
$env:MODEL_PATH = "C:\\path\\to\\resnet18_prepost_plaince_xbd_128_seed17.pt"
uvicorn app.backend.api:app --host 127.0.0.1 --port 8000
~~~

The checkpoint is loaded once at application startup. If it is unavailable or incompatible, startup fails with an actionable message. Do not commit checkpoint binaries.

## Endpoints

- GET /health returns the loaded model's device, classes, and saved validation summary.
- POST /predict accepts pre_image and post_image; each upload is limited to 10 MiB.
