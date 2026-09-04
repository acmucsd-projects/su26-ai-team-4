# Building Damage Classifier API deployed to a Modal Server

This folder contains the API files for upload to a public, useable URL. This allows for the API to be called on devices that are not the host computer. In this case, I'm using Modal as my infrastructure of choice to host the API.

_**I've already uploaded the 128x128 and 224x224 models from the `checkpoints` folder and the callable URLs are here:
```
https://edvu--building-damage-classifier-128-fastapi-app.modal.run
https://edvu--building-damage-classifier-224-fastapi-app.modal.run
```
- Include these commands to the end of the URL to run the API: `/health` to retrieve model info or `/predict` to run model inference

If you would like to upload and use a different model, the outlined guide is below

## Files
- `modal_app.py` - Setups the modal api app and upload trained model info onto a URL
- `model.py` - model architecture
- `resnet18_prepost_plaince_xbd_128_seed17.pt` — the checkpoint, (can replace with another checkpoint file)

## Set Up (one-time, on your own computer)
```bash
pip install modal
modal setup
```
This opens a browser to authenticate and saves a token locally.
Get the files onto your machine — put `modal_app.py`, `model.py`, and model's .pt file in the same folder.

To deloy, run:
```bash
modal deploy path\to\modal_app.py
```
This should output a object/"web function" containing your permanent API URL with the following layout: `https://<your-workspace>--building-damage-classifier-fastapi-app.modal.run`
Make sure that you are referencing *__THIS WEB FUNCTION URL__* and not the "View Deployment" URL


## Testing Installation
**First Test:**
```bash
curl https://<workspace>--building-damage-classifier-fastapi-app.modal.run/health
```
If working correctly, it should return a JSON describing “status”, “device”, “classes”, “val_accuracy”, “val_macro_f1”

**Second Test:**
```bash
curl -X POST https://<account_name>--building-damage-classifier-fastapi-app.modal.run/predict -F "pre_image=@path\to\pre_image.png" -F "post_image=@path\to\post_image.png"
```
This should return another JSON describing the model's prediction of the images


## Using API on a Website
You can use the same `frontend_example.html` file in `backend_API/local` folder and adjusting the `API_URL` to the web function on you recieved from either
