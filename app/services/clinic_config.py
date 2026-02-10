from __future__ import annotations

import os
import random
from contextvars import ContextVar
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
        self._registry: set[str] | None = None

    def _scan_registry(self) -> set[str]:
        if self._registry is not None:
            return self._registry
        registry: set[str] = set()
        if self.base_dir.exists():
            for path in self.base_dir.glob("*.yaml"):
                registry.add(path.stem)
        self._registry = registry
        return registry

    def list_clinics(self) -> list[str]:
        return sorted(self._scan_registry())

    def has_clinic(self, clinic_id: str) -> bool:
        if not clinic_id:
            return False
        return clinic_id in self._scan_registry()

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

    def get_info_response(self, clinic_id: str, key: str, default: Any | None = None) -> Any:
        config = self.get_config(clinic_id)
        responses = config.get("info_responses", {}) if isinstance(config, dict) else {}
        variants = responses.get(f"{key}_variants")
        if isinstance(variants, list) and variants:
            return random.choice(variants)
        value = responses.get(key)
        if isinstance(value, list) and value:
            return random.choice(value)
        if value is None:
            return default
        return value


_provider = ClinicConfigProvider()
_current_clinic_id: ContextVar[str | None] = ContextVar("clinic_id", default=None)


def set_current_clinic_id(clinic_id: str | None):
    return _current_clinic_id.set(clinic_id)


def reset_current_clinic_id(token) -> None:
    _current_clinic_id.reset(token)


def get_current_clinic_id() -> str | None:
    return _current_clinic_id.get()

def list_available_clinics() -> list[str]:
    return _provider.list_clinics()

def resolve_clinic_id(
    clinic_id: str | None,
    fallback: str | None = None,
    strict: bool = False,
) -> str:
    resolved = clinic_id or get_current_clinic_id() or fallback or os.getenv("CLINIC_ID", "lj_center")
    if strict and not _provider.has_clinic(resolved):
        raise ValueError(f"Unknown clinic_id: {resolved}")
    return resolved


def get_clinic_config(
    clinic_id: str | None = None,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = resolve_clinic_id(clinic_id)
    return _provider.get_config(resolved, defaults=defaults)


def get_info_response(
    key: str,
    default: Any | None = None,
    clinic_id: str | None = None,
) -> Any:
    resolved = resolve_clinic_id(clinic_id)
    return _provider.get_info_response(resolved, key, default)
