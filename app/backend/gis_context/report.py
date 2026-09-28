"""Local JSON, CSV, GeoJSON, and self-contained HTML review artifacts."""

import csv
from html import escape
import json
from pathlib import Path


def summary_text(report: dict) -> str:
    count = report["building_count"]
    lines = ["# GIS v2 feasibility audit: " + report["scene_id"], "", "Status: " + report["status"], "",
             f"{count} packaged xBD buildings. Null means not evaluated, not zero coverage.", "",
             f"| Metric | Count | % of {count} | Unknown |", "|---|---:|---:|---:|"]
    for metric, value in report["metrics"].items():
        count = value["count"] if value["count"] is not None else "N/A"
        percent = value.get("percent_of_scene", value.get("percent_of_76"))
        percent = percent if percent is not None else "N/A"
        lines.append(f"| {metric} | {count} | {percent} | {value['unknown_buildings']} |")
    lines += ["", "Provider status:", ""]
    lines += [f"- {key}: {value['status']}" for key, value in report["providers"].items()]
    if report.get("provider_overlap"):
        lines += ["", "Provider overlap and ordered incremental semantic contribution:", "",
                  "```json", json.dumps(report["provider_overlap"], indent=2), "```"]
    if report.get("pre_qa_metrics"):
        lines += ["", "Counts above reflect recorded manual holds. Pre-QA metrics, claims, and conflicts remain in audit.json.",
                  "QA notes: " + report["qa"].get("summary", ""), ""]
    lines += ["", "Blockers:", ""] + ["- " + reason for reason in report["blockers"]]
    lines += ["", "Manual QA: " + report["qa"]["status"], "", "Decision: " + report["decision"], "",
              "See review.html for claims/evidence and review.geojson for geographic inspection.",
              "OSM-derived records: © OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright).",
              "Provider extracts and generated artifacts are local and are not committed.", ""]
    for value in report["providers"].values():
        source = value.get("source")
        if source:
            lines.append(f"- {source['dataset']}: {source['attribution']}. Terms: {source['terms_url']}")
    if any(p.startswith("sonoma_") for p in report["providers"]):
        lines += ["", "Sonoma item terms specify CC BY-ND 3.0. This local feasibility audit does not establish permission to redistribute derived building associations."]
    lines += ["", "NSI occupancy is modeled, not a verified building identity.", ""]
    return "\n".join(lines)


def write_reports(report: dict, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    summary = summary_text(report)
    (output / "summary.md").write_text(summary, encoding="utf-8")
    flag_columns = list(report["metrics"])
    columns = ["building_id", "uid", "evaluation_status", *flag_columns, "nsi_occupancies", "displayable_context",
               "claims", "conflicts", "candidates", "qa_status", "qa_reasons", "qa_notes"]
    with (output / "review.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in report["buildings"]:
            values = {**row, **row["flags"]}
            writer.writerow({key: json.dumps(values.get(key), ensure_ascii=False) if isinstance(values.get(key), (dict, list)) else values.get(key) for key in columns})
    features, seen = [], set()
    cards = []
    for index, row in enumerate(report["buildings"]):
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
        qa_notes = "<p>QA findings: " + escape("; ".join(row["qa_notes"])) + "</p>" if row.get("qa_notes") else ""
        map_name = f"qa-map-{index // 9 + 1:02d}.png"
        map_link = f"<p><a href='{map_name}'>Local spatial review sheet</a> (automated candidate matches; manual holds below)</p>" if (output / map_name).is_file() else ""
        cards.append("<article><h2>" + escape(row["building_id"]) + "</h2><p>UID: " + escape(row["uid"]) + "</p><p>"
                     + escape(labels) + "</p><p>QA: " + escape(row["qa_status"] + " / " + ", ".join(row["qa_reasons"]))
                     + "</p>" + qa_notes + map_link + "<details><summary>Claims, location, raw values, and matching evidence</summary><pre>"
                     + escape(json.dumps(row, indent=2, ensure_ascii=False)) + "</pre></details></article>")
    (output / "review.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    html = ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            "<title>GIS v2 review</title><style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 20px}"
            "article{border:1px solid #aaa;border-radius:8px;padding:16px;margin:12px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}"
            "h2{font-size:18px}</style><h1>GIS v2 review</h1><pre>" + escape(summary) + "</pre>"
            "<p>Use the adjacent GeoJSON in a GIS viewer to inspect footprint and candidate geometry. This report makes no external requests.</p>"
            + "".join(cards) + "</html>")
    (output / "review.html").write_text(html, encoding="utf-8")
