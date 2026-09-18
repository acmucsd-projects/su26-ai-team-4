#!/usr/bin/env python3
"""
Result interpretation layer for xBD damage predictions.

Takes the raw output of inference.predict() (predicted class + per-class
probabilities) and adds human-readable interpretation on top: a confidence
level, an ambiguity flag for borderline predictions, and a plain-language
note. Does not touch the model, the checkpoint, or the API - this is a
post-processing step that can be dropped in wherever predictions are
consumed (CLI, notebook, API response, batch report).

Usage as a library:

    from result_interpretation import interpret_prediction

    prediction = predict(loaded_model, pre_image, post_image)  # from inference.py
    report = interpret_prediction(prediction)

Usage as a CLI (chains directly off inference.py's predict()):

    python result_interpretation.py \
        --checkpoint path/to/checkpoint.pt \
        --pre path/to/pre.png \
        --post path/to/post.png
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Add inference.py's folder to the path
sys.path.append(str(Path(__file__).parent.parent / "ezekiel_resnet18_baseline"))


# Threshold for flagging a prediction as ambiguous. Chosen based on this
# model's known weak spots: minor-damage (F1 0.55) and major-damage (F1
# 0.69) are the two classes most often confused with each other. A small
# gap between the top two predicted classes is a signal the model itself
# is not confident, independent of the raw top-class probability.
AMBIGUITY_GAP_THRESHOLD = 0.15

# Thresholds for translating the top-class probability into a plain-language
# confidence label. These are reporting thresholds, not calibrated
# probabilities - they have not been tuned against a held-out reliability
# curve, and should be treated as a first pass rather than a validated
# calibration.
HIGH_CONFIDENCE_THRESHOLD = 0.75
MODERATE_CONFIDENCE_THRESHOLD = 0.50


def interpret_prediction(prediction: dict[str, Any]) -> dict[str, Any]:
    """Add confidence level, ambiguity flag, and a plain-language note to a
    raw prediction dict (as returned by inference.predict()).

    Parameters
    ----------
    prediction:
        Must contain a "probabilities" key mapping class name -> probability.
        This matches the return shape of inference.predict() in
        base_train/ezekiel_resnet18_baseline/inference.py.

    Returns
    -------
    A new dict with the interpreted report. The original "probabilities"
    dict is preserved under "raw_probabilities" so no information is lost.
    """
    probabilities = prediction["probabilities"]
    ranked = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)

    top_class, top_prob = ranked[0]
    second_class, second_prob = ranked[1]
    top_prob = round(top_prob, 3)
    second_prob = round(second_prob, 3)
    gap = top_prob - second_prob

    if top_prob > HIGH_CONFIDENCE_THRESHOLD:
        confidence_level = "High"
    elif top_prob > MODERATE_CONFIDENCE_THRESHOLD:
        confidence_level = "Moderate"
    else:
        confidence_level = "Low"

    flag_for_review = gap < AMBIGUITY_GAP_THRESHOLD

    if flag_for_review:
        note = (
            f"Model is uncertain between {top_class} ({top_prob:.0%}) and "
            f"{second_class} ({second_prob:.0%}) - recommend manual review."
        )
    else:
        note = (
            f"Model predicts {top_class} with {confidence_level.lower()} "
            f"confidence ({top_prob:.0%})."
        )

    return {
        "predicted_class": top_class,
        "confidence_level": confidence_level,
        "confidence_score": top_prob,
        "runner_up_class": second_class,
        "runner_up_score": second_prob,
        "flag_for_review": flag_for_review,
        "note": note,
        "raw_probabilities": probabilities,
    }


def summarize_batch(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up a list of interpret_prediction() outputs into a batch-level
    summary - useful once predictions are run over more than one building.
    """
    total = len(reports)
    if total == 0:
        return {"total": 0}

    flagged = sum(1 for r in reports if r["flag_for_review"])
    by_class: dict[str, int] = {}
    by_confidence: dict[str, int] = {"High": 0, "Moderate": 0, "Low": 0}

    for r in reports:
        by_class[r["predicted_class"]] = by_class.get(r["predicted_class"], 0) + 1
        by_confidence[r["confidence_level"]] += 1

    return {
        "total_assessed": total,
        "flagged_for_review": flagged,
        "flagged_pct": round(flagged / total, 3),
        "damage_breakdown": by_class,
        "confidence_breakdown": by_confidence,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run PRE+POST inference and print an interpreted, human-readable "
            "assessment report instead of raw probabilities."
        )
    )
    parser.add_argument("--checkpoint", type=Path, required=True, help="Path to a released .pt checkpoint.")
    parser.add_argument("--pre", type=Path, required=True, help="Path to the PRE-disaster building crop.")
    parser.add_argument("--post", type=Path, required=True, help="Path to the POST-disaster building crop.")
    parser.add_argument("--device", choices=("cuda", "mps", "cpu"), help="Override automatic device selection.")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON instead of plain text.")
    return parser.parse_args()


def main() -> None:
    # Imported here, not at module level, so this file can be imported as a
    # library (e.g. from the API later) without requiring inference.py's
    # heavier torch/torchvision imports unless the CLI path is actually used.
    from inference import load_model, predict

    args = parse_args()
    loaded_model = load_model(args.checkpoint, args.device)
    raw_prediction = predict(loaded_model, args.pre, args.post)
    report = interpret_prediction(raw_prediction)

    if args.json:
        print(json.dumps(report, indent=2))
        return

    print(f"Predicted damage level: {report['predicted_class']}")
    print(f"Confidence: {report['confidence_level']} ({report['confidence_score']:.0%})")
    if report["flag_for_review"]:
        print("Flagged for manual review: YES")
    else:
        print("Flagged for manual review: no")
    print(f"Note: {report['note']}")


if __name__ == "__main__":
    main()
