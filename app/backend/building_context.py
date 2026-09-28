"""Optional, local reviewed context overlays. No provider or inference dependencies."""

import hashlib
import json
import logging
from pathlib import Path
import re

from .gis_context.presentation import CATEGORIES, SCOPE_LABELS, TEMPORAL_LABELS


LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = 2
SCOPES = {
    "modeled_occupancy": {"building"},
    "structure_use": {"building"},
    "structure_type": {"building"},
    "property_use": {"parcel"},
    "mapped_place": {"place"},
    "mapped_name": {"building", "place", "site"},
    "school_site": {"site"},
    "site_use": {"site"},
    "area_use": {"site"},
}
CLAIM_FIELDS = {"id", "kind", "scope", "title", "value", "source", "timing", "qualifier", "osm", "displayable",
                "original_value", "original_values", "name", "category_hint", "source_key", "source_family",
                "source_dataset", "source_release", "source_snapshot", "attribution", "terms_url", "temporal_relation",
                "modeled", "multi_structure", "qualifications"}


def text_list(value):
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def valid_claim(claim: object) -> bool:
    """Accept only the compact export schema, never raw audit/provider records."""
    return (
        isinstance(claim, dict) and set(claim) == CLAIM_FIELDS
        and isinstance(claim["kind"], str) and isinstance(claim["scope"], str)
        and claim["scope"] in SCOPES.get(claim["kind"], set())
        and claim["displayable"] is True and type(claim["osm"]) is bool
        and all(isinstance(claim[key], str) and 0 < len(claim[key]) <= 2000
                for key in ("title", "value", "source", "timing"))
        and isinstance(claim["qualifier"], str) and len(claim["qualifier"]) <= 2000
        and all(isinstance(claim[k], str) for k in ("id", "original_value", "category_hint", "source_key", "source_family",
                                                  "source_dataset", "source_release", "source_snapshot", "attribution", "terms_url"))
        and (claim["name"] is None or isinstance(claim["name"], str))
        and isinstance(claim["original_values"], dict)
        and all(isinstance(k, str) and isinstance(v, str) for k, v in claim["original_values"].items())
        and isinstance(claim["temporal_relation"], str) and claim["temporal_relation"] in TEMPORAL_LABELS
        and type(claim["modeled"]) is bool and type(claim["multi_structure"]) is bool
        and text_list(claim["qualifications"])
    )


def valid_context(context: object) -> bool:
    """Validate v2 structure and evidence links before exposing optional local data."""
    if not isinstance(context, dict) or set(context) != {
        "version", "primary_category", "primary_label", "primary_statement_ids", "area_only",
        "has_multiple_supporting_sources", "contexts", "statements", "claims", "conflicts", "notes",
    }:
        return False
    try:
        if (context["version"] != SCHEMA_VERSION or context["primary_category"] not in CATEGORIES
                or not isinstance(context["primary_label"], str) or not text_list(context["notes"])
                or type(context["area_only"]) is not bool or type(context["has_multiple_supporting_sources"]) is not bool
                or any(not isinstance(context[k], list) for k in ("contexts", "statements", "claims", "conflicts"))
                or not all(valid_claim(c) for c in context["claims"])):
            return False
        claims = {c["id"] for c in context["claims"]}
        contexts = {c["id"] for c in context["contexts"]}
        statements = {s["id"] for s in context["statements"]}
        if any(len(ids) != len(context[field]) for ids, field in ((claims, "claims"), (contexts, "contexts"), (statements, "statements"))):
            return False

        def references(values, allowed, empty=False):
            return text_list(values) and (empty or bool(values)) and set(values) <= allowed

        for item in context["contexts"]:
            if (item["scope"] not in SCOPE_LABELS or item["category"] not in CATEGORIES
                    or item["temporal_relation"] not in TEMPORAL_LABELS
                    or not references(item["supporting_claims"], claims)
                    or type(item["modeled"]) is not bool or type(item["multi_structure"]) is not bool
                    or not text_list(item["qualifications"]) or not isinstance(item["label"], str)
                    or not isinstance(item["concepts"], list) or not item["concepts"]):
                return False
            for concept in item["concepts"]:
                if (concept["category"] not in CATEGORIES or not isinstance(concept["label"], str)
                        or not (concept["subtype"] is None or isinstance(concept["subtype"], str))
                        or not references(concept["supporting_claims"], set(item["supporting_claims"]))):
                    return False
        for item in context["statements"]:
            if (item["scope"] not in SCOPE_LABELS or item["category"] not in CATEGORIES
                    or not all(isinstance(item[k], str) for k in ("id", "label", "text", "temporal_label", "corroboration_basis"))
                    or not isinstance(item.get("support_label", ""), str)
                    or type(item["modeled"]) is not bool or type(item["has_multiple_sources"]) is not bool
                    or not text_list(item["supporting_sources"])
                    or not references(item["context_ids"], contexts)
                    or not references(item["supporting_claims"], claims)
                    or not references(item["corroborating_claims"], claims, empty=True)):
                return False
        return (references(context["primary_statement_ids"], statements, empty=not claims)
                and all(isinstance(c["reason"], str) and isinstance(c["resolution"], str)
                        and references(c["supporting_claims"], claims) for c in context["conflicts"]))
    except (KeyError, TypeError):
        return False


def load_context_overlay(root: Path | None, scene_id: str, manifest_path: Path, manifest: dict) -> dict:
    """Fail closed on absent, stale, mismatched or malformed optional local data."""
    if root is None or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", scene_id):
        return {}
    try:
        path = (root / f"{scene_id}.json").resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("overlay path escapes root")
        if not path.exists():
            return {}
        overlay = json.loads(path.read_text(encoding="utf-8"))
        if (overlay["schema_version"] != SCHEMA_VERSION or overlay["review_status"] != "reviewed"
                or overlay["scene_id"] != scene_id
                or overlay["scene_manifest_sha256"] != hashlib.sha256(manifest_path.read_bytes()).hexdigest()):
            raise ValueError("overlay is unreviewed or belongs to a different manifest")
        buildings = overlay["buildings"]
        uids = [b["uid"] for b in manifest["buildings"]]
        if not isinstance(buildings, dict) or set(buildings) != set(uids) or len(uids) != len(buildings):
            raise ValueError("overlay must cover exactly the manifest UIDs")
        for context in buildings.values():
            if not valid_context(context):
                raise ValueError("invalid reviewed context")
        return {uid: context for uid, context in buildings.items() if context["claims"]}
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        LOGGER.warning("Ignoring local GIS overlay for %s: %s", scene_id, error)
        return {}
