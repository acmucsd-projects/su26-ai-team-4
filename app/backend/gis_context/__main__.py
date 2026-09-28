"""Run with python -m app.backend.gis_context; no model dependencies."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .audit import run_audit
from .geometry import SCENE_ID
from .report import write_reports
from .review import apply_review
from .scenes import SCENE_COUNTS


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORK = ROOT / "local_experiments" / "gis_context_v2"


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline GIS feasibility audit (never modifies scene manifests).")
    parser.add_argument("--scene", choices=SCENE_COUNTS, default=SCENE_ID)
    parser.add_argument("--post-label", type=Path, help="Original geographic POST label; defaults to data/train/labels/<scene>_post_disaster.json.")
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--snapshot", default=datetime.now(timezone.utc).date().isoformat(), help="Cache snapshot label for current sources; reuse it for replay.")
    parser.add_argument("--fetch", action="store_true", help="Allow cache misses to query public providers; otherwise offline only.")
    parser.add_argument("--qa-review", type=Path, help="Replay recorded manual findings only when all input/provider hashes match.")
    args = parser.parse_args()
    work = args.work_dir.resolve()
    # Generated provider data must never be placed in canonical static assets.
    if work != DEFAULT_WORK.resolve() and not work.is_relative_to(DEFAULT_WORK.resolve()):
        parser.error("--work-dir must remain under ignored local_experiments/gis_context_v2/")
    manifest = ROOT / "app" / "demo_scenes" / args.scene / "scene.json"
    label = args.post_label or ROOT / "data" / "train" / "labels" / (args.scene + "_post_disaster.json")
    report = run_audit(manifest, label, work / "cache", args.snapshot, args.fetch)
    if args.qa_review:
        try:
            report = apply_review(report, json.loads(args.qa_review.read_bytes()))
        except (OSError, ValueError, KeyError, TypeError) as error:
            parser.error(str(error))
    output = work / args.scene
    write_reports(report, output)
    print(report["status"] + ": " + str(output / "summary.md"))
    for reason in report["blockers"]:
        print(reason)
    return 0 if report["status"] in {"awaiting_manual_qa", "reviewed_with_findings"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
