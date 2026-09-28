"""Optional, local reviewed context overlays. No provider or inference dependencies."""

import hashlib
import json
import logging
from pathlib import Path
import re


LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = 1
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
CLAIM_FIELDS = {"kind", "scope", "title", "value", "source", "timing", "qualifier", "osm", "displayable"}


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
    )


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
            if (not isinstance(context, dict) or set(context) != {"claims"}
                    or not isinstance(context["claims"], list)
                    or not all(valid_claim(c) for c in context["claims"])):
                raise ValueError("invalid reviewed context")
        return {uid: context for uid, context in buildings.items() if context["claims"]}
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        LOGGER.warning("Ignoring local GIS overlay for %s: %s", scene_id, error)
        return {}
