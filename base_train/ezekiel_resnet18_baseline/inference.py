#!/usr/bin/env python3
"""Run inference with a released PRE+POST plain-CE ResNet-18 checkpoint."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image
import torch
from torchvision import transforms
from torchvision.transforms import functional as TF

from train_common import IMAGENET_MEAN, IMAGENET_STD, select_device
from train_prepost_resnet18_plaince import PrePostResNet18


EXPECTED_MODEL_NAME = "prepost_resnet18_plaince"


@dataclass(frozen=True)
class LoadedModel:
    """A loaded control model plus the checkpoint settings needed for inference."""

    model: PrePostResNet18
    device: torch.device
    class_names: list[str]
    image_size: int
    checkpoint: dict[str, Any]


def load_model(checkpoint_path: str | Path, device: torch.device | str | None = None) -> LoadedModel:
    """Load a released PRE+POST plain-CE checkpoint and its saved inference settings."""

    selected_device = select_device() if device is None else torch.device(device)
    if selected_device.type == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA was requested but is not available.")
    if selected_device.type == "mps" and not torch.backends.mps.is_available():
        raise ValueError("MPS was requested but is not available.")

    checkpoint_path = Path(checkpoint_path)
    if not checkpoint_path.is_file():
        raise FileNotFoundError(f"Checkpoint was not found: {checkpoint_path}")
    checkpoint = torch.load(checkpoint_path, map_location=selected_device, weights_only=False)
    if checkpoint.get("model_name") != EXPECTED_MODEL_NAME:
        raise ValueError(
            f"Expected a {EXPECTED_MODEL_NAME!r} checkpoint, got {checkpoint.get('model_name')!r}."
        )

    class_names = checkpoint.get("class_names")
    if not isinstance(class_names, list) or len(class_names) != 4:
        raise ValueError("Checkpoint is missing the expected four class names.")
    image_size = checkpoint.get("config", {}).get("image_size")
    if not isinstance(image_size, int) or image_size < 1:
        raise ValueError("Checkpoint is missing a valid image_size in config.")

    model = PrePostResNet18(weights=None).to(selected_device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    return LoadedModel(model, selected_device, class_names, image_size, checkpoint)


def preprocess_image(image_path: str | Path, image_size: int) -> torch.Tensor:
    """Apply deterministic validation preprocessing to one PRE or POST image path."""

    image_path = Path(image_path)
    if not image_path.is_file():
        raise FileNotFoundError(f"Image was not found: {image_path}")
    with Image.open(image_path) as image:
        image = image.convert("RGB").copy()
    image = TF.resize(
        image,
        [image_size, image_size],
        interpolation=transforms.InterpolationMode.BILINEAR,
        antialias=True,
    )
    tensor = TF.to_tensor(image)
    return (tensor - IMAGENET_MEAN) / IMAGENET_STD


@torch.inference_mode()
def predict(
    loaded_model: LoadedModel,
    pre_image: str | Path,
    post_image: str | Path,
) -> dict[str, Any]:
    """Predict one aligned PRE/POST pair without labels or training augmentation."""

    pre_tensor = preprocess_image(pre_image, loaded_model.image_size).unsqueeze(0).to(loaded_model.device)
    post_tensor = preprocess_image(post_image, loaded_model.image_size).unsqueeze(0).to(loaded_model.device)
    logits = loaded_model.model(pre_tensor, post_tensor)
    probabilities = torch.softmax(logits, dim=1)[0].cpu()
    predicted_index = int(probabilities.argmax().item())
    return {
        "predicted_index": predicted_index,
        "predicted_class": loaded_model.class_names[predicted_index],
        "probabilities": {
            class_name: float(probability)
            for class_name, probability in zip(loaded_model.class_names, probabilities.tolist())
        },
        "image_size": loaded_model.image_size,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run PRE+POST inference with a released plain-CE ResNet-18 checkpoint."
    )
    parser.add_argument("--checkpoint", type=Path, required=True, help="Path to a released .pt checkpoint.")
    parser.add_argument("--pre", type=Path, required=True, help="Path to the PRE-disaster building crop.")
    parser.add_argument("--post", type=Path, required=True, help="Path to the POST-disaster building crop.")
    parser.add_argument("--device", choices=("cuda", "mps", "cpu"), help="Override automatic device selection.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    loaded_model = load_model(args.checkpoint, args.device)
    prediction = predict(loaded_model, args.pre, args.post)
    print(f"Device: {loaded_model.device}")
    print(f"Image size: {prediction['image_size']}x{prediction['image_size']}")
    print(f"Prediction: {prediction['predicted_class']} ({prediction['predicted_index']})")
    print("Probabilities:")
    for class_name, probability in prediction["probabilities"].items():
        print(f"  {class_name}: {probability:.6f}")


if __name__ == "__main__":
    main()
