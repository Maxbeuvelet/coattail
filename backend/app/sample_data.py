"""Bundled sample snapshot, used as a dev fallback when the live (sometimes
geoblocked) data-api can't be reached. Keeps the dashboard populated offline."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_SAMPLE_PATH = Path(__file__).parent / "sample_snapshot.json"


@lru_cache
def load_sample() -> dict | None:
    try:
        with _SAMPLE_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
