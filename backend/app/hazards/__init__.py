"""Hazard registry. Adding a hazard = add a module with NAME/LABEL/VARIABLE/DEFAULTS/
METRICS/PRIMARY_METRIC/detect() and register it here. Nothing else changes."""
from __future__ import annotations

from types import ModuleType

from . import heatwave, heavy_rain

REGISTRY: dict[str, ModuleType] = {m.NAME: m for m in (heatwave, heavy_rain)}


def get(name: str) -> ModuleType:
    return REGISTRY[name]


def describe() -> list[dict]:
    return [
        {
            "name": m.NAME,
            "label": m.LABEL,
            "variable": m.VARIABLE,
            "defaults": m.DEFAULTS,
            "primary_metric": m.PRIMARY_METRIC,
            "metrics": [vars(x) for x in m.METRICS],
            "definition": (m.__doc__ or "").strip(),
        }
        for m in REGISTRY.values()
    ]
