"""
dataset.py
----------
PyTorch Dataset for the xBD building-damage manifest.

The manifest CSV (e.g. manifest_train.csv) has one row per building crop:
    building_id, scene_id, split, disaster_type, damage_label,
    pre_crop_path, post_crop_path, original_bbox,
    original_crop_width, original_crop_height

`pre_crop_path` / `post_crop_path` are POSIX-style paths *relative to a data
root* (e.g. "processed/tier1/pre/xxx.png"). Point `--data-root` at the
directory that contains the `processed/...` tree.
"""

import ast
from pathlib import Path

import pandas as pd
from PIL import Image
from torch.utils.data import Dataset

# Canonical xBD damage classes. "un-classified" is excluded by default since
# it is a small, ambiguous bucket (see utils.load_manifest).
DAMAGE_CLASSES = ["no-damage", "minor-damage", "major-damage", "destroyed"]
CLASS_TO_IDX = {c: i for i, c in enumerate(DAMAGE_CLASSES)}
IDX_TO_CLASS = {i: c for c, i in CLASS_TO_IDX.items()}


class XBDDamageDataset(Dataset):
    """Loads (pre_image, post_image, label) triples.

    Parameters
    ----------
    dataframe : pd.DataFrame
        A slice of the manifest (already filtered/split by the caller).
    data_root : str | Path
        Directory that the `pre_crop_path` / `post_crop_path` columns are
        relative to.
    transform : callable, optional
        Applied identically to both pre and post crops (should NOT include
        random crop offsets that would misalign the pair; random flips/
        rotations are fine as long as the same seed/state is used - we
        apply the transform to a stacked pair to guarantee this, see below).
    """

    def __init__(self, dataframe: pd.DataFrame, data_root, transform=None):
        self.df = dataframe.reset_index(drop=True)
        self.data_root = Path(data_root)
        self.transform = transform

        missing = set(self.df["damage_label"]) - set(CLASS_TO_IDX)
        if missing:
            raise ValueError(
                f"Found labels not in DAMAGE_CLASSES: {missing}. "
                f"Filter these out before constructing the dataset."
            )

    def __len__(self):
        return len(self.df)

    def _load(self, rel_path: str) -> Image.Image:
        img_path = self.data_root / rel_path
        with Image.open(img_path) as img:
            return img.convert("RGB")

    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        pre_img = self._load(row["pre_crop_path"])
        post_img = self._load(row["post_crop_path"])

        if self.transform is not None:
            pre_img, post_img = self.transform(pre_img, post_img)

        label = CLASS_TO_IDX[row["damage_label"]]
        return pre_img, post_img, label

    @property
    def labels(self):
        """Integer labels for the whole dataset (used for class weighting)."""
        return self.df["damage_label"].map(CLASS_TO_IDX).to_numpy()


def parse_bbox(bbox_str: str):
    """Utility: turn the manifest's '(x0, y0, x1, y1)' string into a tuple."""
    return ast.literal_eval(bbox_str)
