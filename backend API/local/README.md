# Building Damage Classifier API

Serves `resnet18_prepost_plaince_xbd_128_seed17.pt` — a ResNet-18-based
model that classifies building damage severity from a **pair** of images
(pre-disaster and post-disaster) into 4 classes:

`no-damage`, `minor-damage`, `major-damage`, `destroyed`

Validation performance from the checkpoint's saved metrics: **88.5% accuracy**,
**0.756 macro-F1**. Note it's noticeably weaker on `minor-damage` and
`major-damage` (F1 ~0.56–0.69) than on `no-damage` and `destroyed`
(F1 ~0.83–0.94) — worth surfacing to end users if precision on the middle
classes matters for your use case.

## Files
- `model.py` — model architecture (verified to load the checkpoint with
  `strict=True`, zero missing/unexpected keys)
- `main.py` — FastAPI app with `/health` and `/predict` endpoints
- `requirements.txt` — Python dependencies
- `frontend_example.html` — minimal vanilla JS demo page
- `resnet18_prepost_plaince_xbd_128_seed17.pt` — the checkpoint (place here,
  or set `MODEL_PATH` env var)

## Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Then open `frontend_example.html` in a browser (or serve it), or test directly:

```bash
curl -X POST http://localhost:8000/predict \
  -F "pre_image=@path/to/pre.png" \
  -F "post_image=@path/to/post.png"
```

Response:
```json
{
  "predicted_class": "destroyed",
  "confidence": 0.80,
  "probabilities": {
    "no-damage": 0.06,
    "minor-damage": 0.02,
    "major-damage": 0.12,
    "destroyed": 0.80
  }
}
```

## Deploying
1. **Containerize** (recommended) — Dockerfile sketch:
   ```dockerfile
   FROM python:3.11-slim
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY . .
   CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
   ```
2. **Lock down CORS** — `main.py` currently allows all origins
   (`allow_origins=["*"]`). Change this to your actual frontend domain
   before going to production.
3. **GPU vs CPU** — the model auto-detects CUDA (`torch.cuda.is_available()`).
   CPU inference at 128x128 with ResNet-18 is fast enough for low/moderate
   traffic; use a GPU instance if you expect high volume.
4. Host on Render, Railway, Fly.io, AWS (ECS/EC2), GCP Cloud Run, etc.
   Put Nginx or a managed gateway in front for TLS and rate limiting.

## Important input details
- Both images should be roughly-aligned crops of the **same building**
  (pre- and post-disaster), matching how the model was trained on xBD-style
  chip pairs.
- Images are resized to 128x128 and normalized with standard ImageNet
  stats — this happens automatically server-side; the frontend just needs
  to send the raw image files.
