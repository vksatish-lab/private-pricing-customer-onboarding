"""Persistence: one JSON file, a dict of onboarding records keyed by id.

Deliberately not a database -- this is a prototype and the whole store is small.
Writes are atomic (temp file + rename) so a crash mid-write can't corrupt it.
Override the location with the PPCO_STORE env var (used by tests).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_DEFAULT = Path(__file__).parent / "data" / "onboardings.json"
STORE_PATH = Path(os.environ.get("PPCO_STORE", _DEFAULT))


def _load() -> dict:
    if STORE_PATH.exists():
        try:
            return json.loads(STORE_PATH.read_text() or "{}")
        except json.JSONDecodeError:
            return {"onboardings": {}}
    return {"onboardings": {}}


def _save(data: dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(STORE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(STORE_PATH)


def list_records() -> list[dict]:
    """Most-recently-updated first."""
    return sorted(_load()["onboardings"].values(), key=lambda r: r["updated_at"], reverse=True)


def get(record_id: str) -> dict | None:
    return _load()["onboardings"].get(record_id)


def upsert(record: dict) -> None:
    data = _load()
    data["onboardings"][record["id"]] = record
    _save(data)


def delete(record_id: str) -> None:
    data = _load()
    data["onboardings"].pop(record_id, None)
    _save(data)
