"""
predict.py
----------
Run inference on a single pre/post image pair.

Example:
    python predict.py --checkpoint checkpoints/best_model.pt \
        --pre path/to/pre.png --post path/to/post.png
"""

import argparse

import torch
import torch.nn.functional as F
from PIL import Image

from dataset import DAMAGE_CLASSES
from model import SiameseDamageNet
from transforms import build_transforms


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--pre", required=True, help="Path to pre-disaster crop")
    p.add_argument("--post", required=True, help="Path to post-disaster crop")
    return p.parse_args()


def main():
    args = parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    ckpt = torch.load(args.checkpoint, map_location=device)
    train_args = ckpt["args"]
    num_classes = len(DAMAGE_CLASSES) + (1 if train_args.get("include_unclassified") else 0)

    model = SiameseDamageNet(num_classes=num_classes, backbone=train_args.get("backbone", "simple")).to(device)
    model.load_state_dict(ckpt["model_state"])
    model.eval()

    tfm = build_transforms(train_args.get("image_size", 128))["val"]
    pre_img = Image.open(args.pre).convert("RGB")
    post_img = Image.open(args.post).convert("RGB")
    pre_t, post_t = tfm(pre_img, post_img)
    pre_t, post_t = pre_t.unsqueeze(0).to(device), post_t.unsqueeze(0).to(device)

    with torch.no_grad():
        logits = model(pre_t, post_t)
        probs = F.softmax(logits, dim=1).squeeze(0).cpu().numpy()

    class_names = DAMAGE_CLASSES[:num_classes]
    pred_idx = probs.argmax()
    print(f"Predicted: {class_names[pred_idx]}  (confidence {probs[pred_idx]*100:.1f}%)")
    print("\nClass probabilities:")
    for name, p in sorted(zip(class_names, probs), key=lambda x: -x[1]):
        print(f"  {name:<15} {p*100:5.1f}%")


if __name__ == "__main__":
    main()
