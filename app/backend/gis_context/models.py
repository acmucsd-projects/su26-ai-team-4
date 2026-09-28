"""Separate spatial relationships, provenance, and semantic claims."""

from dataclasses import asdict, dataclass, field
from typing import Any

from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class Source:
    provider: str
    dataset: str
    release: str
    snapshot: str
    temporal_status: str
    attribution: str
    terms_url: str
    endpoint: str
    modeled: bool = False


@dataclass
class Feature:
    record_id: str
    geometry: BaseGeometry  # Always projected meters at the matching boundary.
    properties: dict[str, Any]
    source: Source
    version: str | None = None
    record_date: str | None = None


@dataclass
class Match:
    record_id: str
    relationship: str
    accepted: bool
    spatial_confidence: str
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)
    ambiguous: bool = False


@dataclass
class Claim:
    kind: str
    scope: str
    category: str
    label: str
    raw_value: dict[str, Any]
    source: Source
    source_record_id: str
    source_record_version: str | None
    source_record_date: str | None
    spatial_confidence: str
    spatial_evidence: dict[str, Any]
    semantic_confidence: str
    ambiguity: list[str] = field(default_factory=list)
    mapped_name: str | None = None
    critical_facility: bool = False
    displayable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
