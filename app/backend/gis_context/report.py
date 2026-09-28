"""Local JSON, CSV, GeoJSON, and self-contained HTML review artifacts."""

import csv
from html import escape
import json
from pathlib import Path


def summary_text(report: dict) -> str:
    lines = ["# Harvey GIS v2 feasibility audit", "", "Status: " + report["status"], "",
             "76 packaged xBD buildings. Null means not evaluated, not zero coverage.", "",
             "| Metric | Count | % of 76 | Unknown |", "|---|---:|---:|---:|"]
    for metric, value in report["metrics"].items():
        count = value["count"] if value["count"] is not None else "N/A"
        percent = value["percent_of_76"] if value["percent_of_76"] is not None else "N/A"
        lines.append(f"| {metric} | {count} | {percent} | {value['unknown_buildings']} |")
    lines += ["", "Provider status:", ""]
    lines += [f"- {key}: {value['status']}" for key, value in report["providers"].items()]
    lines += ["", "Blockers:", ""] + ["- " + reason for reason in report["blockers"]]
    lines += ["", "Manual QA: " + report["qa"]["status"], "", "Decision: " + report["decision"], "",
              "See review.html for claims/evidence and review.geojson for geographic inspection.",
              "OSM-derived records: © OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright).",
              "HCAD: City of Houston GIS / HCAD. NSI: USACE; modeled estimates, not verified building identities.",
              "Provider extracts and generated artifacts are local and are not committed.", ""]
    return "\n".join(lines)


def write_reports(report: dict, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    summary = summary_text(report)
    (output / "summary.md").write_text(summary, encoding="utf-8")
    columns = ["building_id", "uid", "evaluation_status", "flags", "claims", "conflicts", "candidates", "qa_status", "qa_reasons"]
    with (output / "review.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in report["buildings"]:
            writer.writerow({key: json.dumps(row[key], ensure_ascii=False) if isinstance(row[key], (dict, list)) else row[key] for key in columns})
    features, seen = [], set()
    cards = []
    for row in report["buildings"]:
        features.append({"type": "Feature", "geometry": row["geometry"], "properties": {
            key: row[key] for key in ("uid", "building_id", "claims", "flags", "qa_status", "qa_reasons")}})
        for candidate in row["candidates"]:
            key = (candidate["provider"], candidate["record_id"])
            if key not in seen:
                seen.add(key)
                features.append({"type": "Feature", "geometry": candidate["geometry"], "properties": {
                    "provider": key[0], "record_id": key[1], "source": candidate["source"],
                    "raw_source_values": candidate["raw_source_values"]}})
        context = row["displayable_context"]
        labels = "Not evaluated" if context is None else "; ".join(context) or "No displayable context"
        cards.append("<article><h2>" + escape(row["building_id"]) + "</h2><p>UID: " + escape(row["uid"]) + "</p><p>"
                     + escape(labels) + "</p><p>QA: " + escape(row["qa_status"] + " / " + ", ".join(row["qa_reasons"]))
                     + "</p><details><summary>Claims, location, raw values, and matching evidence</summary><pre>"
                     + escape(json.dumps(row, indent=2, ensure_ascii=False)) + "</pre></details></article>")
    (output / "review.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    html = ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            "<title>Harvey GIS v2 review</title><style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 20px}"
            "article{border:1px solid #aaa;border-radius:8px;padding:16px;margin:12px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}"
            "h2{font-size:18px}</style><h1>Harvey GIS v2 review</h1><pre>" + escape(summary) + "</pre>"
            "<p>Use the adjacent GeoJSON in a GIS viewer to inspect footprint and candidate geometry. This report makes no external requests.</p>"
            + "".join(cards) + "</html>")
    (output / "review.html").write_text(html, encoding="utf-8")
