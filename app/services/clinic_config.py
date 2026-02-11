from __future__ import annotations

import os
import random
import re
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
        self._domain_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._registry: set[str] | None = None

    def _scan_registry(self) -> set[str]:
        if self._registry is not None:
            return self._registry
        registry: set[str] = set()
        if self.base_dir.exists():
            for path in self.base_dir.glob("*.yaml"):
                registry.add(path.stem)
            for path in self.base_dir.iterdir():
                if path.is_dir():
                    registry.add(path.name)
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

    def get_domain_config(self, clinic_id: str, domain: str) -> dict[str, Any]:
        cache_key = (clinic_id, domain)
        if cache_key in self._domain_cache:
            return self._domain_cache[cache_key]
        config: dict[str, Any] = {}
        domain_path = self.base_dir / clinic_id / f"{domain}.yaml"
        if domain_path.exists():
            try:
                config = yaml.safe_load(domain_path.read_text(encoding="utf-8")) or {}
            except Exception:
                config = {}
        self._domain_cache[cache_key] = config
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

    def get_domain_response(
        self,
        clinic_id: str,
        domain: str,
        key: str,
        default: Any | None = None,
    ) -> Any:
        def _pick_variant(value: Any) -> Any:
            if isinstance(value, list):
                options = [item for item in value if item is not None]
                if options:
                    return random.choice(options)
                return None
            return value

        def _resolve_path(data: Any, path: str) -> Any | None:
            if not isinstance(data, dict):
                return None
            current = data
            for part in path.split("."):
                if not isinstance(current, dict):
                    return None
                current = current.get(part)
            if isinstance(current, dict):
                variants = current.get("variants")
                if isinstance(variants, list) and variants:
                    return _pick_variant(variants)
                text = current.get("text")
                if isinstance(text, list):
                    return _pick_variant(text)
                if text is not None:
                    return text
                return current
            if isinstance(current, list):
                return _pick_variant(current)
            return current

        if domain == "info":
            info_cfg = self.get_domain_config(clinic_id, "info")
            facts = info_cfg.get("facts", {}) if isinstance(info_cfg, dict) else {}
            entry = facts.get(key) if isinstance(facts, dict) else None
            if isinstance(entry, dict):
                response = entry.get("response")
                if response is not None:
                    return response
            return self.get_info_response(clinic_id, key, default)

        if domain == "general":
            general_cfg = self.get_domain_config(clinic_id, "general")
            messages = general_cfg.get("messages", {}) if isinstance(general_cfg, dict) else {}
            resolved = _resolve_path(messages, key)
            return resolved if resolved is not None else default

        if domain == "booking":
            booking_cfg = self.get_domain_config(clinic_id, "booking")
            if isinstance(booking_cfg, dict):
                messages = booking_cfg.get("messages", {})
                resolved = _resolve_path(messages, key)
                if resolved is not None:
                    return resolved
                flow = booking_cfg.get("flow", {})
                resolved = _resolve_path(flow, key)
                if resolved is not None:
                    if isinstance(resolved, dict) and "prompt" in resolved:
                        return resolved.get("prompt")
                    return resolved
            return default

        return default


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


def get_domain_response(
    domain: str,
    key: str,
    default: Any | None = None,
    clinic_id: str | None = None,
) -> Any:
    resolved = resolve_clinic_id(clinic_id)
    return _provider.get_domain_response(resolved, domain, key, default)


def get_fast_pass_match(message: str, clinic_id: str | None = None) -> dict[str, Any] | None:
    resolved = resolve_clinic_id(clinic_id)
    info_cfg = _provider.get_domain_config(resolved, "info")
    facts = info_cfg.get("facts", {}) if isinstance(info_cfg, dict) else {}
    if not isinstance(facts, dict):
        return None
    lowered = message.lower().strip()
    if len(lowered) < 3:
        return None
    tokens = re.findall(r"[a-zčšž0-9]+", lowered, flags=re.IGNORECASE)
    try:
        from thefuzz import fuzz  # type: ignore
    except Exception:
        fuzz = None
    for key, entry in facts.items():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("priority", "")).lower() != "fast":
            continue
        keywords = entry.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [keywords]
        if not isinstance(keywords, list):
            continue
        for kw in keywords:
            if not kw:
                continue
            kw_lower = str(kw).lower()
            # Short single-word keywords should match tokens, not substrings.
            if " " not in kw_lower and len(kw_lower) <= 3:
                if kw_lower in tokens:
                    response = entry.get("response")
                    if isinstance(response, str) and response.strip():
                        return {
                            "response": response,
                            "category": entry.get("category"),
                            "key": key,
                            "match": kw_lower,
                            "score": 100,
                        }
                continue
            if kw_lower in lowered:
                response = entry.get("response")
                if isinstance(response, str) and response.strip():
                    return {
                        "response": response,
                        "category": entry.get("category"),
                        "key": key,
                        "match": kw_lower,
                        "score": 100,
                    }
            if fuzz is not None and len(kw_lower) >= 5 and len(lowered) >= 5:
                score = fuzz.partial_ratio(kw_lower, lowered)
                if score >= 85:
                    response = entry.get("response")
                    if isinstance(response, str) and response.strip():
                        return {
                            "response": response,
                            "category": entry.get("category"),
                            "key": key,
                            "match": kw_lower,
                            "score": score,
                        }
    return None
