# Building Damage Classifier API

This API references the 128x128 model, `resnet18_prepost_plaince_xbd_128_seed17.pt`, by default. If you'd like to use a different model, make sure that the `MODEL_PATH` env var in `main.py` points to wherever the model .pt file resides. If the model you choose has an image size that is not 128x128, make sure to also change the `IMAGE_SIZE` and `MAX_UPLOAD_BYTES` vars in `main.py` to accurately reflect the new resolution. 

## Files
- `model.py` — model architecture (verified to load the checkpoint with
  `strict=True`, zero missing/unexpected keys)
- `main.py` — FastAPI app with `/health` and `/predict` endpoints
- `requirements.txt` — Python dependencies
- `frontend_example.html` — minimal vanilla JS demo page
- `resnet18_prepost_plaince_xbd_128_seed17.pt` — default checkpoint (place here,
  or set `MODEL_PATH` env var)

## To run locally on your computer

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
Note that this is outlined for Windows OS
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
