"""Measure the canonical assessment prompts offline for packaged demo scenes.

Run from the repository root with ``python -m app.backend.assessment_input_diagnostic``.
This calls the production packet/prompt builders and never invokes an LLM.
"""

from __future__ import annotations

import json
from pathlib import Path
import statistics

from .assessment import build_assessment_preview
from .assessment_openai import configured_assessment_model
from .building_context import load_context_overlay
from .local_env import load_repo_dotenv
from .scene_assessment import build_scene_assessment_prompt
from .scene_evidence import SEVERE_CLASSES, build_scene_evidence


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
INSTRUCTION_PREFIXES = {
    "scene": "Write the requested scene overview from this deterministic evidence only.",
    "building": "Write the requested short assessment from this evidence packet only.",
}
SAMPLE_TYPES = (
    "most_ambiguous",
    "high_confidence_severe",
    "local_severity_contrast_outlier",
    "context_rich",
    "no_gis",
)


def _token_encoder(model: str):
    """Use an installed compatible tokenizer if available; add no dependency."""
    try:
        import tiktoken

        return tiktoken.encoding_for_model(model)
    except (ImportError, KeyError, ValueError):
        return None


def _measure_prompt(prompt: dict, kind: str, model: str, encoder) -> dict:
    prefix = INSTRUCTION_PREFIXES[kind]
    user_instruction, separator, evidence_json = prompt["user"].partition("\n")
    if not separator or user_instruction != prefix:
        raise ValueError(f"The canonical {kind} prompt no longer has its expected evidence boundary.")
    # Parse the already-serialized canonical prompt payload; do not rebuild it.
    json.loads(evidence_json)
    textual_contents = (prompt["system"], prompt["user"])
    metric = {
        "serialized_evidence_json_characters": len(evidence_json),
        "serialized_evidence_json_utf8_bytes": len(evidence_json.encode("utf-8")),
        "system_instruction_characters": len(prompt["system"]),
        "user_instruction_prefix_characters": len(user_instruction),
        "instruction_prompt_characters": len(prompt["system"]) + len(user_instruction) + len(separator),
        "instruction_prompt_utf8_bytes": len(prompt["system"].encode("utf-8")) + len((user_instruction + separator).encode("utf-8")),
        "complete_textual_input_characters": sum(map(len, textual_contents)),
        "complete_textual_input_utf8_bytes": sum(len(value.encode("utf-8")) for value in textual_contents),
    }
    if encoder is not None:
        # Counts prompt text content only; provider message framing is not included.
        metric["estimated_input_tokens"] = sum(len(encoder.encode(value)) for value in textual_contents)
    return metric


def _distribution(records: list[dict], field: str) -> dict | None:
    values = [row[field] for row in records if isinstance(row.get(field), (int, float))]
    if not values:
        return None
    return {"min": min(values), "median": statistics.median(values), "max": max(values)}


def _sample_buildings(scene: dict, contexts: dict, evidence: dict) -> dict[str, dict]:
    buildings = [row for row in scene.get("buildings", []) if isinstance(row, dict) and isinstance(row.get("id"), str)]
    by_id = {row["id"]: row for row in buildings}
    selected: dict[str, dict] = {}

    def add(sample_type: str, building_id: str | None) -> None:
        if building_id in by_id:
            selected.setdefault(building_id, {"building": by_id[building_id], "sample_types": []})["sample_types"].append(sample_type)

    uncertain = evidence["uncertainty_summary"].get("smallest_gap_buildings", [])
    if uncertain:
        add("most_ambiguous", uncertain[0].get("building_id"))

    severe = [row for row in buildings if row.get("prediction", {}).get("predicted_class") in SEVERE_CLASSES]
    severe.sort(key=lambda row: (-float(row.get("prediction", {}).get("confidence", 0)), row["id"]))
    if severe:
        add("high_confidence_severe", severe[0]["id"])

    candidates = evidence.get("candidate_findings", {})
    for key in evidence.get("candidate_order", []):
        candidate = candidates.get(key, {})
        if candidate.get("type") in {"LOCAL_SEVERITY_OUTLIER", "LOCAL_LOW_DAMAGE_OUTLIER"}:
            ids = candidate.get("building_ids", [])
            if ids:
                add("local_severity_contrast_outlier", ids[0])
                break

    rich = []
    for building in buildings:
        context = contexts.get(building.get("uid"))
        if isinstance(context, dict) and context.get("claims"):
            rich.append((len(context["claims"]), len({claim.get("scope") for claim in context["claims"]}), building["id"]))
    if rich:
        rich.sort(key=lambda row: (-row[0], -row[1], row[2]))
        add("context_rich", rich[0][2])

    no_gis = next((row["id"] for row in buildings if row.get("uid") not in contexts), None)
    add("no_gis", no_gis)
    return selected


def build_assessment_input_diagnostics(repository_root: Path = REPOSITORY_ROOT) -> dict:
    load_repo_dotenv()
    scenes_root = repository_root / "app" / "demo_scenes"
    overlays_root = repository_root / "app" / "demo_gis_context"
    model = configured_assessment_model()
    encoder = _token_encoder(model)
    scene_rows, building_rows = [], []

    for manifest_path in sorted(scenes_root.glob("*/scene.json")):
        scene = json.loads(manifest_path.read_text(encoding="utf-8"))
        scene_id = scene["scene_id"]
        contexts = load_context_overlay(overlays_root, scene_id, manifest_path, scene)
        scene_evidence = build_scene_evidence(scene, contexts)

        # This is the same evidence object and canonical prompt builder used by the API.
        scene_prompt = build_scene_assessment_prompt(scene_evidence)
        scene_rows.append({"scene_id": scene_id, **_measure_prompt(scene_prompt, "scene", model, encoder)})

        selected = _sample_buildings(scene, contexts, scene_evidence)
        for building_id, sample in sorted(selected.items()):
            building = sample["building"]
            preview = build_assessment_preview(
                scene, building, contexts.get(building.get("uid")), scene_evidence=scene_evidence,
            )
            building_rows.append({
                "scene_id": scene_id,
                "building_id": building_id,
                "sample_types": sorted(set(sample["sample_types"])),
                **_measure_prompt(preview["prompt"], "building", model, encoder),
            })

    scene_fields = (
        "serialized_evidence_json_characters", "serialized_evidence_json_utf8_bytes",
        "instruction_prompt_characters", "instruction_prompt_utf8_bytes", "complete_textual_input_characters",
        "complete_textual_input_utf8_bytes", "estimated_input_tokens",
    )
    largest_scene = max(scene_rows, key=lambda row: row["complete_textual_input_utf8_bytes"], default=None)
    largest_building = max(building_rows, key=lambda row: row["complete_textual_input_utf8_bytes"], default=None)
    all_requests = [
        {"request_type": "scene_assessment", **row} for row in scene_rows
    ] + [
        {"request_type": "building_assessment", **row} for row in building_rows
    ]
    largest_overall = max(all_requests, key=lambda row: row["complete_textual_input_utf8_bytes"], default=None)
    per_sample_type = {}
    for sample_type in SAMPLE_TYPES:
        samples = [row for row in building_rows if sample_type in row["sample_types"]]
        per_sample_type[sample_type] = {
            field: _distribution(samples, field)
            for field in scene_fields if any(field in row for row in samples)
        }
    return {
        "schema_version": 1,
        "mode": "offline_canonical_assessment_input_diagnostic",
        "provider_calls": 0,
        "configured_model": model,
        "token_estimate_note": (
            "Estimated input tokens count prompt text content only; Responses API message framing is excluded."
            if encoder else "Estimated input tokens unavailable: no installed tokenizer supports the configured model."
        ),
        "scene_assessment": {
            "by_scene": scene_rows,
            "request_size_min_median_max": {
                field: _distribution(scene_rows, field) for field in scene_fields if any(field in row for row in scene_rows)
            },
            "largest_request": largest_scene,
        },
        "building_assessment": {
            "representative_buildings": building_rows,
            "request_size_min_median_max": {
                field: _distribution(building_rows, field) for field in scene_fields if any(field in row for row in building_rows)
            },
            "by_sample_type_utf8_bytes": per_sample_type,
            "sample_type_counts": {
                sample_type: sum(sample_type in row["sample_types"] for row in building_rows)
                for sample_type in SAMPLE_TYPES
            },
            "largest_request": largest_building,
        },
        "largest_request_overall": largest_overall,
    }


def main() -> None:
    print(json.dumps(build_assessment_input_diagnostics(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
