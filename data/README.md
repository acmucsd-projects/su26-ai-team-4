# xBD data setup

Raw xBD data is not stored in this repository. Obtain the xBD challenge training data through [xView2](https://xview2.org/dataset), then extract the raw training files into this layout:

```text
data/
└── train/
    ├── images/
    └── labels/
```

Only `data/train/images/` and `data/train/labels/` are required by the implemented preprocessing workflow. Other directories present in a broader xBD distribution are not required here.

## Build the manifest and crops

From the repository root, run:

```bash
python src/build_manifest.py
```

This reads the raw images and POST-disaster labels, creates paired variable-size PRE/POST building crops, and writes:

```text
data/manifest_train.csv
data/processed/tier1/pre/
data/processed/tier1/post/
```

Do not create the manifest or processed crops manually. Normal reruns are refused when generated manifest/crop outputs already exist. If you intentionally change the raw source images or labels, regenerate them with:

```bash
python src/build_manifest.py --overwrite
```

`--overwrite` removes and rebuilds the generated PRE/POST crop directories for this manifest output; use it only for an intentional preprocessing rebuild.

## Build the ResNet cache

```bash
python base_train/ezekiel_resnet18_baseline/prepare_xbd_cache.py
```

This creates the shared ResNet cache and its cache manifest under `base_train/ezekiel_resnet18_baseline/cache/`. Do not create the cache manually. If the manifest or source crops change, rerun the cache command with `--rebuild`.

## Verify a new machine

Before starting a full training run, run the ResNet smoke test:

```bash
python base_train/ezekiel_resnet18_baseline/smoke_test.py
```

It runs a small end-to-end check of all three ResNet entry points using the prepared cache without overwriting normal experiment results.

## Train

After the smoke test passes, run one of the ResNet training scripts. See the [ResNet-18 baseline README](../base_train/ezekiel_resnet18_baseline/README.md) for experiment commands, resolution options, worker tuning, and output details.
