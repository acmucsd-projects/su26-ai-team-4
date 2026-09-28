"""Replay recorded manual findings only against the exact reviewed evidence."""

from copy import deepcopy
import hashlib

from .audit import aggregate, build_row, source_coverage
from .cache import canonical
from .models import Claim, Source


def evidence_sha256(report: dict) -> str:
    evidence = [{key: row[key] for key in ("uid", "geometry", "claims", "candidates")} for row in report["buildings"]]
    return hashlib.sha256(canonical(evidence)).hexdigest()


def apply_review(report: dict, review: dict) -> dict:
    if report["status"] != "awaiting_manual_qa":
        raise ValueError("Manual findings require a complete, unreviewed provider audit.")
    hashes = {entry["request"]["provider"]: entry["sha256"] for entry in report["cache_entries"]}
    if (review["input_sha256"] != report["input_sha256"] or review["cache_response_sha256"] != hashes
            or review["evidence_sha256"] != evidence_sha256(report)):
        raise ValueError("Manual review evidence hashes differ; review the new inputs before applying findings.")
    uids = [row["uid"] for row in report["buildings"]]
    if len(review["reviewed_uids"]) != len(uids) or set(review["reviewed_uids"]) != set(uids):
        raise ValueError("This review must explicitly cover all scene UIDs.")
    result = deepcopy(report)
    result["pre_qa_metrics"] = deepcopy(report["metrics"])
    result["pre_qa_source_contribution"] = deepcopy(report["source_contribution"])
    result["pre_qa_provider_overlap"] = deepcopy(report["provider_overlap"])
    actions = review["claim_actions"]
    used = set()
    for row in result["buildings"]:
        claims = [Claim(**{**claim, "source": Source(**claim["source"])}) for claim in row["claims"]]
        findings = []
        for index, action in enumerate(actions):
            if action["uid"] != row["uid"]:
                continue
            selected = [c for c in claims if c.source_record_id == action["record_id"] and
                        (c.source.dataset if c.source.provider == "osm" else c.source.provider) == action["provider"]]
            if not selected:
                raise ValueError("Manual action does not identify an existing claim.")
            for claim in selected:
                if action["action"] == "withhold_claim":
                    claim.displayable = False
                elif action["action"] == "withhold_name" and claim.mapped_name:
                    claim.label = claim.label.removesuffix(" (" + claim.mapped_name + ")") + " (name withheld after QA)"
                    claim.mapped_name = None
                else:
                    raise ValueError("Unsupported manual action or missing mapped name.")
                claim.ambiguity.append("manual_qa: " + action["reason"])
            findings.append(action["reason"])
            used.add(index)
        original_conflicts = deepcopy(row["conflicts"])
        updated = build_row({"id": row["building_id"], "uid": row["uid"]}, row["geometry"], claims,
                            row["candidates"], result["providers"])
        reasons = row["qa_reasons"]
        row.update(updated)
        row["qa_reasons"] = reasons
        row["pre_qa_conflicts"] = original_conflicts
        row["qa_status"] = "reviewed_with_hold" if findings else "reviewed"
        row["qa_notes"] = findings + review.get("building_notes", {}).get(row["uid"], [])
    if used != set(range(len(actions))):
        raise ValueError("Manual action refers to an unknown scene UID.")
    result["metrics"] = aggregate(result["buildings"])
    result["source_contribution"], result["provider_overlap"] = source_coverage(result["buildings"], result["providers"])
    result["qa"] = {**review, "status": "completed_with_findings", "selected_uids": report["qa"]["selected_uids"]}
    result["status"] = "reviewed_with_findings"
    result["decision"] = review["decision"]
    return result
