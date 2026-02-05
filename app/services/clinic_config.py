from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml


class ClinicConfigProvider:
    """Load per-clinic configuration from YAML files."""

    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is None:
            base_dir = Path(__file__).resolve().parents[2] / "config" / "clinics"
        self.base_dir = base_dir
        self._cache: dict[str, dict[str, Any]] = {}

    def get_config(self, clinic_id: str, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        if clinic_id in self._cache:
            return self._cache[clinic_id]

        config: dict[str, Any] = {}
        path = self.base_dir / f"{clinic_id}.yaml"
        if path.exists():
            try:
                config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception:
                config = {}

        if defaults:
            merged = {**defaults, **config}
            # Merge nested dicts where applicable
            for key in ("services", "service_map", "contact", "info_responses"):
                if key in defaults and key in config and isinstance(defaults[key], dict) and isinstance(config[key], dict):
                    merged[key] = {**defaults[key], **config[key]}
            config = merged

        self._cache[clinic_id] = config
        return config


_provider = ClinicConfigProvider()


def get_clinic_config(defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    clinic_id = os.getenv("CLINIC_ID", "lj_center")
    return _provider.get_config(clinic_id, defaults=defaults)
