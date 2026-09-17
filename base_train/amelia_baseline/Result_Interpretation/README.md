# Result Interpretation

Takes the raw prediction from `inference.py` and adds a confidence level,
a flag for borderline predictions, and a plain-language note.

Model struggles most with minor vs major damage (F1 0.55 / 0.69), so this
flags predictions where the top two classes are close together, rather
than just reporting a raw probability.

## Usage

```bash
python result_interpretation.py \
  --checkpoint path/to/checkpoint.pt \
  --pre path/to/pre.png \
  --post path/to/post.png
```

Add `--json` to get the full structured output instead of the plain-text summary.