# ResNet-18 Baselines

This folder contains ResNet-18 experiments for xBD building-damage classification.

For environment and dataset setup, follow the repository-level [README](../../README.md) and data instructions.

## Quick start

From the repository root:

```bash
python src/build_manifest.py
```

Then prepare the local 224 x 224 cache:

```bash
python base_train/ezekiel_resnet18_baseline/prepare_xbd_cache.py
```

Then run one of the ResNet-18 experiments:

```bash
# POST-only with weighted cross-entropy
python base_train/ezekiel_resnet18_baseline/train_post_resnet18.py

# PRE+POST with weighted cross-entropy
python base_train/ezekiel_resnet18_baseline/train_prepost_resnet18.py

# PRE+POST with plain cross-entropy
python base_train/ezekiel_resnet18_baseline/train_prepost_resnet18_plaince.py
```

These experiments use ImageNet-pretrained ResNet-18 weights via `ResNet18_Weights.DEFAULT`; the first run may require Internet access if torchvision has not already cached them locally.

After preparing the cache, run the smoke-test suite to verify the pipeline:

```bash
python base_train/ezekiel_resnet18_baseline/smoke_test.py
```

The runner creates a small temporary subset from the existing cache, runs all three real training entry points for one epoch, and checks their normal artifacts. It does not overwrite normal experiment results and is only for pipeline verification, not meaningful model metrics.

To run one experiment instead:

```bash
python base_train/ezekiel_resnet18_baseline/smoke_test.py --experiment post
```

Training settings can be changed with command-line arguments. For example:

```bash
python base_train/ezekiel_resnet18_baseline/train_prepost_resnet18.py --epochs 2 --batch-size 32
```

All three experiments support `--image-size` for square inputs while reusing the 224×224 cache. For example:

```bash
python base_train/ezekiel_resnet18_baseline/train_prepost_resnet18.py --image-size 128
```

### Practical resolution guidance

224x224 remains the canonical default for baseline reproducibility. Use 128x128 for normal development, iteration, and fast experiments; use 224x224 for heavier validation or final comparisons when training time is less important. In these baseline experiments, 128x128 trained substantially faster and used much less VRAM while its validation Macro F1 was close to the 224x224 run. Treat that as practical guidance rather than a universal accuracy guarantee: results vary across runs and hardware.

For a fast paired plain-CE development run:

```bash
python base_train/ezekiel_resnet18_baseline/train_prepost_resnet18_plaince.py \
  --image-size 128 \
  --num-workers 8 \
  --batch-size 128 \
  --epochs 8
```

In our workstation testing, 8 workers was a useful operating point for this 128x128 command; the code default remains 4 for portability and stability.

Use `--help` to see the available options for any experiment:

```bash
python base_train/ezekiel_resnet18_baseline/train_prepost_resnet18.py --help
```

## Expected data layout

```text
data/
└── train/
    ├── images/
    ├── labels/
    ├── targets/
    └── metadata_stats/
```

This baseline requires `data/train/images/` and `data/train/labels/`. The broader xBD layout may also include `data/train/targets/` and `data/train/metadata_stats/`, but this preprocessing workflow does not require them.

`build_manifest.py` creates:

```text
data/manifest_train.csv
data/processed/tier1/pre/
data/processed/tier1/post/
```

The cache script creates:

```text
base_train/ezekiel_resnet18_baseline/cache/
```

The cache is shared by the ResNet-18 experiments in this folder.

## Experiments

### POST-only ResNet-18

`train_post_resnet18.py`

- POST-disaster crops only
- ImageNet-pretrained ResNet-18
- four damage classes
- inverse-frequency weighted cross-entropy
- scene-disjoint train/validation split
- validation Macro F1 checkpoint selection

Results are written to:

```text
base_train/ezekiel_resnet18_baseline/results/
```

### PRE+POST ResNet-18

`train_prepost_resnet18.py`

- paired PRE- and POST-disaster crops
- one shared ImageNet-pretrained ResNet-18 backbone
- PRE and POST images are passed through the same backbone
- 512-dimensional PRE and POST features are concatenated
- synchronized geometric augmentation for paired images
- inverse-frequency weighted cross-entropy
- scene-disjoint train/validation split
- validation Macro F1 checkpoint selection

Results are written to:

```text
base_train/ezekiel_resnet18_baseline/results_prepost/
```

### PRE+POST ResNet-18 with plain cross-entropy

`train_prepost_resnet18_plaince.py`

- same paired PRE+POST setup as the weighted PRE+POST experiment
- one shared ImageNet-pretrained ResNet-18 backbone
- synchronized geometric augmentation for paired images
- plain cross-entropy with no class weighting
- scene-disjoint train/validation split
- validation Macro F1 checkpoint selection

This experiment is intended to isolate the effect of class weighting relative to the weighted PRE+POST experiment.

Results are written to:

```text
base_train/ezekiel_resnet18_baseline/results_prepost_plaince/
```

## Hardware

Training automatically selects the best available PyTorch device in this order:

1. NVIDIA CUDA GPU
2. Apple MPS on supported Apple Silicon Macs
3. CPU

CUDA is the primary tested training environment.

Apple MPS is supported in FP32 but has not yet been validated on our hardware. Depending on the Mac and available unified memory, a smaller `--batch-size` may be required.

CPU training is supported as a fallback, but ResNet-18 training may be slow.

CUDA-specific features such as mixed precision, TF32, cuDNN tuning, and CUDA memory reporting are enabled only when training on CUDA.

**DataLoader workers:** The default remains 4 workers (capped by available CPU count) for portability and stability. Tune `--num-workers` for your hardware and selected image size: 128x128 runs can benefit more from additional workers because the GPU finishes batches faster and the CPU/data pipeline can become the bottleneck, while 224x224 runs may need fewer workers because GPU compute per batch is larger. Increase workers until throughput plateaus; beyond that, returns diminish and RAM use, scheduling overhead, or DataLoader instability can increase. If instability occurs, reduce the worker count.

**Machine-specific example, not a universal expectation:** one RTX 5090 workstation at 128x128 and batch size 128 measured:

```text
4 workers:  ~1,000 samples/s
8 workers:  ~1,800 samples/s
12 workers: ~1,830 samples/s
```

The preprocessing and cache scripts are platform-independent.

Training settings and available command-line options are documented through each experiment's `--help` output.

## Outputs

Each experiment writes the same standard set of training and evaluation artifacts to its corresponding results directory.

Running another seed into the same default results directory replaces previous output files; use `--results-dir` to preserve multiple runs.

Typical files include:

```text
best.pt
history.csv
result.json
summary.txt
confusion_matrix.csv
val_predictions.csv
split_manifest.csv
split_summary.csv
```

`best.pt` is selected using validation Macro F1. After training, the best checkpoint is reloaded before the final validation metrics and predictions are written.

The split manifest and summary record the train/validation split used for the run.

## Notes

Generated data, cache files, checkpoints, and experiment results should remain ignored by Git.

Each script invocation runs one experiment with one training seed and one split seed. Seeds can be changed using the command-line options when additional runs are needed.

The shared training, evaluation, splitting, device handling, and output logic is implemented in `train_common.py`. Each experiment entry point keeps its experiment-specific dataset, model, loss, and batch-forwarding behavior explicit.
