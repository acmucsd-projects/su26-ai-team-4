"""Content-checked, deterministic request cache for offline reproducibility."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import ssl
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi


QUERY_VERSION = 1


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


class CachedClient:
    def __init__(self, root: Path, network: bool = False):
        self.root = root
        self.network = network
        self.used = []

    def get_json(self, url: str, *, provider: str, release: str, bbox=None, snapshot=None,
                 params=None, form=None) -> dict:
        request_info = {"provider": provider, "release": release, "query_bbox_wgs84": bbox,
                        "snapshot": snapshot, "query_schema_version": QUERY_VERSION,
                        "url": url, "params": params or {}, "form": form}
        key = hashlib.sha256(canonical(request_info)).hexdigest()
        directory = self.root / provider / key
        data_path, metadata_path = directory / "response.json", directory / "metadata.json"
        if data_path.is_file() and metadata_path.is_file():
            raw = data_path.read_bytes()
            metadata = json.loads(metadata_path.read_bytes())
            if metadata["sha256"] != hashlib.sha256(raw).hexdigest() or canonical(metadata["request"]) != canonical(request_info):
                raise ValueError("Cache integrity mismatch: " + str(directory))
        else:
            if not self.network:
                raise FileNotFoundError("No cached extract; use --fetch when raw labels are available: " + key)
            request_url = url + ("?" + urlencode(params) if params else "")
            body = urlencode(form).encode("utf-8") if form is not None else None
            request = Request(request_url, data=body, headers={
                "User-Agent": "disaster-triage-gis-feasibility/1.0 (offline scene audit)",
                "Accept": "application/json",
            })
            context = ssl.create_default_context()
            context.load_verify_locations(cafile=certifi.where())
            with urlopen(request, timeout=50, context=context) as response:
                raw = response.read(50 * 1024 * 1024 + 1)
                if len(raw) > 50 * 1024 * 1024:
                    raise ValueError("Provider extract exceeds the scene-audit size limit.")
            payload = json.loads(raw)
            self.validate_response(payload)
            metadata = {"request": request_info, "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "sha256": hashlib.sha256(raw).hexdigest(), "cache_key": key,
                        "osm_base_timestamp": payload.get("osm3s", {}).get("timestamp_osm_base")}
            directory.mkdir(parents=True, exist_ok=True)
            data_path.write_bytes(raw)
            metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        payload = json.loads(raw)
        self.validate_response(payload)
        self.used.append({**metadata, "cache_directory": str(directory)})
        return payload

    @staticmethod
    def validate_response(payload):
        if not isinstance(payload, dict) or payload.get("error") or payload.get("remark"):
            raise ValueError("Provider returned an error/partial response: " + str(payload)[:400])
