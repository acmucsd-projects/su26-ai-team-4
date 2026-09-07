"""Checkpoint loading and paired-image inference shared by application entry points."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image
import torch
from torchvision import transforms
from torchvision.transforms import functional as transform_functional

from .model import PrePostResNet18


EXPECTED_MODEL_NAME = "prepost_resnet18_plaince"
EXPECTED_CLASS_NAMES = (
    "no-damage",
    "minor-damage",
    "major-damage",
    "destroyed",
)
IMAGENET_MEAN = torch.tensor([0.485, 0.456, 0.406], dtype=torch.float32).view(3, 1, 1)
IMAGENET_STD = torch.tensor([0.229, 0.224, 0.225], dtype=torch.float32).view(3, 1, 1)


class CheckpointCompatibilityError(RuntimeError):
    """Raised when a checkpoint is not a supported released baseline checkpoint."""


@dataclass(frozen=True)
class LoadedClassifier:
    """A loaded model and the checkpoint metadata needed for deterministic inference."""

    model: PrePostResNet18
    device: torch.device
    class_names: list[str]
    image_size: int
    val_metrics: dict[str, Any]


def select_device() -> torch.device:
    """Choose the same device preference as the baseline inference CLI."""

    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def load_classifier(checkpoint_path: str | Path, device: torch.device | None = None) -> LoadedClassifier:
    """Load a released PRE+POST plain-CE checkpoint with strict compatibility checks."""

    checkpoint_path = Path(checkpoint_path)
    if not checkpoint_path.is_file():
        raise FileNotFoundError(
            f"Checkpoint not found at {checkpoint_path}. Download "
            "resnet18_prepost_plaince_xbd_128_seed17.pt from the project's GitHub Release "
            "and set MODEL_PATH to its local path."
        )

    selected_device = device or select_device()
    checkpoint = torch.load(checkpoint_path, map_location=selected_device, weights_only=False)
    if checkpoint.get("model_name") != EXPECTED_MODEL_NAME:
        raise CheckpointCompatibilityError(
            f"Expected checkpoint model_name {EXPECTED_MODEL_NAME!r}, "
            f"got {checkpoint.get('model_name')!r}."
        )

    class_names = checkpoint.get("class_names")
    if class_names != list(EXPECTED_CLASS_NAMES):
        raise CheckpointCompatibilityError(
            f"Expected class_names {list(EXPECTED_CLASS_NAMES)!r}, got {class_names!r}."
        )

    image_size = checkpoint.get("config", {}).get("image_size")
    if not isinstance(image_size, int) or image_size < 1:
        raise CheckpointCompatibilityError("Checkpoint is missing a valid config.image_size.")

    model = PrePostResNet18(num_classes=len(class_names)).to(selected_device)
    try:
        model.load_state_dict(checkpoint["model_state_dict"], strict=True)
    except KeyError as error:
        raise CheckpointCompatibilityError("Checkpoint is missing model_state_dict.") from error
    model.eval()

    val_metrics = checkpoint.get("val_metrics", {})
    if not isinstance(val_metrics, dict):
        val_metrics = {}
    return LoadedClassifier(
        model=model,
        device=selected_device,
        class_names=class_names,
        image_size=image_size,
        val_metrics=val_metrics,
    )


def preprocess_image(image: Image.Image, image_size: int) -> torch.Tensor:
    """Apply the baseline's deterministic RGB, resize, tensor, and normalization steps."""

    rgb_image = image.convert("RGB")
    resized_image = transform_functional.resize(
        rgb_image,
        [image_size, image_size],
        interpolation=transforms.InterpolationMode.BILINEAR,
        antialias=True,
    )
    tensor = transform_functional.to_tensor(resized_image)
    return (tensor - IMAGENET_MEAN) / IMAGENET_STD


@torch.inference_mode()
def predict_images(
    classifier: LoadedClassifier,
    pre_image: Image.Image,
    post_image: Image.Image,
) -> dict[str, Any]:
    """Predict damage for one aligned PRE/POST building-crop pair."""

    pre_tensor = preprocess_image(pre_image, classifier.image_size).unsqueeze(0).to(classifier.device)
    post_tensor = preprocess_image(post_image, classifier.image_size).unsqueeze(0).to(classifier.device)
    probabilities = torch.softmax(classifier.model(pre_tensor, post_tensor), dim=1)[0].cpu()
    predicted_index = int(probabilities.argmax().item())

    return {
        "predicted_class": classifier.class_names[predicted_index],
        "confidence": float(probabilities[predicted_index]),
        "probabilities": {
            class_name: float(probability)
            for class_name, probability in zip(classifier.class_names, probabilities.tolist())
        },
    }
