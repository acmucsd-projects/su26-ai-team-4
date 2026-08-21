"""
transforms.py
-------------
Paired transforms for (pre_image, post_image) so that random augmentations
(flip, rotation) are applied *identically* to both crops - otherwise the
model would learn from misaligned pre/post pairs.
"""

import random

import torchvision.transforms.functional as F
from torchvision import transforms as T

IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


class PairedTransform:
    def __init__(self, image_size=128, train=True):
        self.image_size = image_size
        self.train = train
        self.normalize = T.Normalize(IMAGENET_MEAN, IMAGENET_STD)

    def __call__(self, pre_img, post_img):
        pre_img = F.resize(pre_img, [self.image_size, self.image_size])
        post_img = F.resize(post_img, [self.image_size, self.image_size])

        if self.train:
            if random.random() < 0.5:
                pre_img = F.hflip(pre_img)
                post_img = F.hflip(post_img)
            if random.random() < 0.5:
                pre_img = F.vflip(pre_img)
                post_img = F.vflip(post_img)
            angle = random.choice([0, 90, 180, 270])
            if angle:
                pre_img = F.rotate(pre_img, angle)
                post_img = F.rotate(post_img, angle)
            # mild color jitter (independent is fine - lighting differs
            # naturally between pre/post capture anyway)
            jitter = T.ColorJitter(brightness=0.15, contrast=0.15, saturation=0.1)
            pre_img = jitter(pre_img)
            post_img = jitter(post_img)

        pre_t = self.normalize(F.to_tensor(pre_img))
        post_t = self.normalize(F.to_tensor(post_img))
        return pre_t, post_t


def build_transforms(image_size=128):
    return {
        "train": PairedTransform(image_size, train=True),
        "val": PairedTransform(image_size, train=False),
    }
