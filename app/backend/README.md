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

## Local demo-scene packager

The scene packager creates a local, ignored asset pack for the future scene-dashboard UI. It is an offline application utility: it reads one raw xBD scene, its POST pixel geometry, and the existing paired cache manifest, then uses the canonical application inference loader and preprocessing to write precomputed predictions.

It does not add an API route, modify source imagery/crops, or run at application startup. Run it from the repository root with an explicit compatible checkpoint:

~~~powershell
python -m app.backend.package_demo_scene `
  --checkpoint C:\path\to\resnet18_prepost_plaince_xbd_128_seed17.pt
~~~

By default, it packages `hurricane-michael_00000247` into `local_experiments/demo_scene_pack/`. The output contains `scene.json`, the full PRE/POST scene images, and cached PRE/POST crops for every supported building. It refuses to overwrite an existing pack.

## Endpoints

- GET /health returns the loaded model's device, classes, and saved validation summary.
- POST /predict accepts pre_image and post_image; each upload is limited to 10 MiB.
- GET /demo-scenes lists valid local demo packs under `DEMO_SCENE_ROOT`. The default is `local_experiments/demo_scene_pack/`; an absent directory simply returns an empty list.
- GET /demo-scenes/{scene_id} returns the pack's scene manifest with its image and crop URLs expanded to `/demo-scenes/{scene_id}/...`.
- GET /demo-scenes/{scene_id}/{asset_path} serves validated pack-relative scene and crop assets. This is local demo support only; Modal packaging is intentionally not part of this step.

## Modal deployment

Install and authenticate the Modal CLI once:

~~~bash
pip install modal
modal setup
~~~

Download the released 128x128 checkpoint locally, set MODEL_PATH to that file, then deploy from the repository root. The wrapper copies that checkpoint into the Modal image and sets the same MODEL_PATH configuration for the canonical app inside the container.

~~~powershell
$env:MODEL_PATH = "C:\\path\\to\\resnet18_prepost_plaince_xbd_128_seed17.pt"
modal deploy app/backend/modal_app.py
~~~

Modal prints the web-function URL. Test it with:

~~~bash
curl https://<workspace>--building-damage-classifier-128-fastapi-app.modal.run/health
curl -X POST https://<workspace>--building-damage-classifier-128-fastapi-app.modal.run/predict -F "pre_image=@path/to/pre.png" -F "post_image=@path/to/post.png"
~~~
