"""Export completed manual QA into ignored, compact dashboard sidecars (offline)."""

import argparse
from collections import OrderedDict
import hashlib
import json
from pathlib import Path

from app.backend.building_context import SCHEMA_VERSION, valid_claim
from .scenes import SCENE_COUNTS


REPO = Path(__file__).resolve().parents[3]
LOCAL_ROOT = REPO / "local_experiments" / "gis_context_v2"
SOURCE_NAMES = {
    "hcad": "HCAD / City of Houston",
    "bay_2017": "Bay County Property Appraiser",
    "sonoma_parcels": "Sonoma County property records",
    "sonoma_schools": "Sonoma County school parcels · CC BY-ND 3.0",
    "nsi": "USACE National Structure Inventory",
    "osm": "OpenStreetMap",
}
TITLES = {
    "modeled_occupancy": "Modeled use",
    "structure_use": "Parcel-linked structure use",
    "structure_type": "Mapped building use",
    "property_use": "Property context",
    "mapped_place": "Mapped place",
    "school_site": "School site context",
    "site_use": "Site context",
    "area_use": "Surrounding area",
}
ORDER = ["mapped_name", "mapped_place", "modeled_occupancy", "structure_type", "structure_use",
         "school_site", "site_use", "property_use", "area_use"]


def timing(source: dict) -> str:
    date = source["snapshot"][:10]
    return {
        "event_year": "2017 event-year property record",
        "pre_event_historical": "2017 pre-event property record",
        "current_only": f"Current context · retrieved {date}",
        "event_snapshot": f"Mapped near disaster date · {date}",
        "current_modeled_not_event_aligned": f"Current modeled inventory · retrieved {date}; not event-aligned",
        "pre_event_reference_vintage_unverified": "Advertised July 2017 · vintage unverified",
    }[source["temporal_status"]]


def present_claim(claim: dict) -> dict:
    """Use the reviewed label, never reconstruct identities from raw tags."""
    kind, scope, source = claim["kind"], claim["scope"], claim["source"]
    value = claim["label"].split(": ", 1)[-1].removesuffix(" (name withheld after QA)")
    value = value.removesuffix(" (advertised July 2017; vintage unverified)")
    title = TITLES.get(kind)
    qualifier = ""
    if kind == "mapped_name":
        title = {"building": "Mapped building name", "place": "Mapped place name", "site": "Site context"}[scope]
    if kind == "area_use":
        value = value.replace("Within current mapped ", "").replace("Within disaster-time mapped ", "")
        qualifier = "Surrounding land use; applies to the area."
    elif scope == "site":
        value = "Within mapped school site" if kind == "site_use" and value == "school" else "Within " + value
        qualifier = "Site membership; individual building use may differ."
    elif scope == "parcel":
        qualifier = "Applies to the parcel."
        if claim["spatial_evidence"].get("structure_association") == "multi_structure":
            qualifier = "Shared property context across multiple structures."
    elif kind == "structure_use":
        qualifier = "Linked through a single-structure parcel record."
    elif kind == "modeled_occupancy":
        qualifier = "Modeled occupancy; individual building use is unverified."
    if kind == "property_use" or kind == "structure_use":
        # Keep names/acronyms as reviewed; assessor descriptions often arrive in all caps.
        if value.isupper():
            value = value.capitalize()
    result = {"kind": kind, "scope": scope, "title": title, "value": value,
              "source": SOURCE_NAMES[source["provider"]], "timing": timing(source),
              "qualifier": qualifier, "osm": source["provider"] == "osm", "displayable": True}
    if not valid_claim(result):
        raise ValueError("Unsupported claim presentation")
    return result


def build_overlay(report: dict, manifest_bytes: bytes, audit_bytes: bytes) -> dict:
    manifest = json.loads(manifest_bytes)
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    qa = report.get("qa", {})
    rows = report["buildings"]
    uids = [b["uid"] for b in manifest["buildings"]]
    row_uids = [b["uid"] for b in rows]
    if (report["status"] != "reviewed_with_findings" or qa.get("status") != "completed_with_findings"
            or report["scene_id"] != manifest["scene_id"]
            or report["input_sha256"]["scene_manifest"] != digest
            or qa.get("input_sha256") != report["input_sha256"]
            or len(uids) != len(set(uids)) or len(row_uids) != len(uids) or set(row_uids) != set(uids)
            or sorted(qa.get("reviewed_uids", [])) != sorted(uids)
            or any(p["status"] != "complete" for p in report["providers"].values())):
        raise ValueError("Export requires complete, reviewed evidence for exactly this manifest")
    manifest_ids = {b["uid"]: b["id"] for b in manifest["buildings"]}
    buildings = {}
    for row in rows:
        if (row["qa_status"] not in {"reviewed", "reviewed_with_hold"}
                or row["evaluation_status"] != "evaluated" or row["building_id"] != manifest_ids[row["uid"]]):
            raise ValueError("Unreviewed or mismatched building")
        claims = []
        for claim in row["claims"]:
            source = claim["source"]
            provider = source["dataset"] if source["provider"] == "osm" else source["provider"]
            actions = [a for a in qa["claim_actions"] if a["uid"] == row["uid"]
                       and a["provider"] == provider and a["record_id"] == claim["source_record_id"]
                       and ("kind" not in a or a["kind"] == claim["kind"])]
            if (claim.get("displayable") is not True or claim["spatial_confidence"] not in {"strong", "moderate"}
                    or any(a["action"] == "withhold_claim" for a in actions)):
                continue
            if any(a["action"] == "withhold_name" for a in actions):
                if claim.get("mapped_name"):
                    raise ValueError("Name hold has not been applied to reviewed evidence")
                if claim["kind"] == "mapped_name":
                    # Name-only claims have no independent use left after a name hold.
                    continue
            # Candidates, raw values, scores, IDs, years-built and QA notes are never exported.
            claims.append(present_claim(claim))
        groups = OrderedDict()
        for claim in sorted(claims, key=lambda c: ORDER.index(c["kind"])):
            key = tuple(claim[k] for k in ("kind", "scope", "title", "source", "timing", "qualifier"))
            if key not in groups:
                groups[key] = {**claim, "values": []}
            if claim["value"] not in groups[key]["values"]:
                groups[key]["values"].append(claim["value"])
        compact = []
        for claim in groups.values():
            claim["value"] = "; ".join(claim.pop("values"))
            if not valid_claim(claim):
                raise ValueError("Invalid grouped context")
            compact.append(claim)
        buildings[row["uid"]] = {"claims": compact}
    return {"schema_version": SCHEMA_VERSION, "review_status": "reviewed", "scene_id": report["scene_id"],
            "scene_manifest_sha256": digest, "audit_sha256": hashlib.sha256(audit_bytes).hexdigest(),
            "buildings": buildings}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-root", type=Path, default=LOCAL_ROOT)
    args = parser.parse_args()
    local_root = args.local_root.resolve()
    if not local_root.is_relative_to(LOCAL_ROOT.resolve()):
        parser.error("Artifacts must stay in ignored local_experiments/gis_context_v2")
    # Validate every scene before replacing any existing sidecar.
    overlays = []
    for scene_id, count in SCENE_COUNTS.items():
        audit_bytes = (local_root / scene_id / "audit.json").read_bytes()
        report = json.loads(audit_bytes)
        if len(report["buildings"]) != count:
            raise ValueError(f"Unexpected building count for {scene_id}")
        manifest_bytes = (REPO / "app" / "demo_scenes" / scene_id / "scene.json").read_bytes()
        overlays.append(build_overlay(report, manifest_bytes, audit_bytes))
    output = local_root / "overlays"
    output.mkdir(parents=True, exist_ok=True)
    for overlay in overlays:
        path = output / f"{overlay['scene_id']}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(overlay, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        populated = sum(bool(b["claims"]) for b in overlay["buildings"].values())
        print(f"{overlay['scene_id']}: {len(overlay['buildings'])} reviewed, {populated} with context -> {path}")


if __name__ == "__main__":
    main()
