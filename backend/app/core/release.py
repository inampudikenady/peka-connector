"""Release metadata shipped with the connector image."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.version import CONNECTOR_VERSION

QDRANT_VERSION = "1.14.1"


@lru_cache
def release_manifest() -> dict[str, Any]:
    candidates = (
        Path(__file__).resolve().parents[3] / "release.json",
        Path("/app/release.json"),
    )
    for path in candidates:
        if path.is_file():
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest.get("version") != CONNECTOR_VERSION:
                raise RuntimeError("Release manifest does not match the connector version")
            if (manifest.get("components") or {}).get("qdrant") != QDRANT_VERSION:
                raise RuntimeError("Release manifest does not match the bundled component version")
            return manifest
    return {
        "product": "PEKA Connector",
        "version": CONNECTOR_VERSION,
        "architecture": "customer-resident-data-plane",
        "components": {"qdrant": QDRANT_VERSION},
        "version_source": "VERSION",
    }
