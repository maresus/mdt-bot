"""Clinic KB management for admin editing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from app.rag.rag_engine import rag_engine


CLINIC_INFO_KEYS = [
    "parking",
    "cenik",
    "delovni_cas",
    "kontakt",
    "lokacija",
]


def _knowledge_path() -> Path:
    return Path(__file__).resolve().parents[2] / "knowledge.jsonl"


def _load_jsonl() -> list[dict[str, Any]]:
    path = _knowledge_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    items: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except Exception:
            continue
    return items


def _write_jsonl(items: list[dict[str, Any]]) -> None:
    path = _knowledge_path()
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False))
            f.write("\n")
    tmp.replace(path)


def get_clinic_info() -> Dict[str, str]:
    """Return clinic info text for editable keys."""
    items = _load_jsonl()
    result = {k: "" for k in CLINIC_INFO_KEYS}

    for item in items:
        metadata = item.get("metadata", {}) if isinstance(item, dict) else {}
        category = metadata.get("category") or item.get("category")
        text = item.get("text") or item.get("content") or ""
        if category in result and text:
            result[category] = text

    return result


def update_clinic_info(payload: Dict[str, str]) -> Dict[str, str]:
    """Update clinic info in knowledge.jsonl and reload RAG."""
    items = _load_jsonl()

    updated_keys = {k: v.strip() for k, v in payload.items() if k in CLINIC_INFO_KEYS}

    # Keep non-clinic entries + rebuild clinic entries
    kept: list[dict[str, Any]] = []
    for item in items:
        metadata = item.get("metadata", {}) if isinstance(item, dict) else {}
        category = metadata.get("category") or item.get("category")
        if category in CLINIC_INFO_KEYS:
            continue
        kept.append(item)

    for key in CLINIC_INFO_KEYS:
        text = updated_keys.get(key, "").strip()
        if not text:
            continue
        kept.append(
            {
                "text": text,
                "metadata": {
                    "category": key,
                    "title": f"clinic_{key}",
                    "source": "admin_kb",
                },
            }
        )

    _write_jsonl(kept)
    try:
        rag_engine.reload()
    except Exception as exc:
        print(f"[KB] Failed to reload RAG after update: {exc}")

    return get_clinic_info()
