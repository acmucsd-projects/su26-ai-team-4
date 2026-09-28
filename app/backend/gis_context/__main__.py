"""Run with python -m app.backend.gis_context; no model dependencies."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

from .audit import run_audit
from .geometry import SCENE_ID
from .report import write_reports


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORK = ROOT / "local_experiments" / "gis_context_v2"


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline Harvey GIS feasibility audit (never modifies scene manifests).")
    parser.add_argument("--post-label", type=Path, default=ROOT / "data" / "train" / "labels" / (SCENE_ID + "_post_disaster.json"))
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--snapshot", default=datetime.now(timezone.utc).date().isoformat(), help="Cache snapshot label for current sources; reuse it for replay.")
    parser.add_argument("--fetch", action="store_true", help="Allow cache misses to query public providers; otherwise offline only.")
    args = parser.parse_args()
    work = args.work_dir.resolve()
    # Generated provider data must never be placed in canonical static assets.
    if work != DEFAULT_WORK.resolve() and not work.is_relative_to(DEFAULT_WORK.resolve()):
        parser.error("--work-dir must remain under ignored local_experiments/gis_context_v2/")
    manifest = ROOT / "app" / "demo_scenes" / SCENE_ID / "scene.json"
    report = run_audit(manifest, args.post_label, work / "cache", args.snapshot, args.fetch)
    output = work / SCENE_ID
    write_reports(report, output)
    print(report["status"] + ": " + str(output / "summary.md"))
    for reason in report["blockers"]:
        print(reason)
    return 0 if report["status"] == "awaiting_manual_qa" else 2


if __name__ == "__main__":
    raise SystemExit(main())
