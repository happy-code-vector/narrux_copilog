"""KB lookup tool — programmatic lookups for param class, filter info, input index.

NO pydantic_ai imports. Pure Python + Pydantic.
Loaded from kb_content/parameters/module_registry.json at startup.
For now, uses a hardcoded fallback registry until Frank delivers the YAML.

These are exact-match lookups with authoritative answers — must be 100% correct,
not 95% via LLM retrieval.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import structlog

from tools.schemas import ParameterClass

logger = structlog.get_logger(__name__)

# Hardcoded fallback — replace with module_registry.json when Frank delivers
_FALLBACK_REGISTRY: dict[str, dict] = {
    # Alpha filters
    "D1": {"name": "CVD Filter", "class": "C", "default": "ON", "strategy": "alpha", "description": "Cumulative Volume Delta — regime-coupled, non-stationary"},
    "D2": {"name": "MFI Filter", "class": "C", "default": "OFF", "strategy": "alpha", "description": "Money Flow Index — volume-based, regime-coupled"},
    "D3": {"name": "RSI Corridor", "class": "A", "default": "ON", "strategy": "alpha", "description": "RSI corridor filter — stationary"},
    "D7": {"name": "BB Width Filter", "class": "B", "default": "OFF", "strategy": "alpha", "description": "Bollinger Band Width — quarterly drift"},
    "D17": {"name": "S/R Proximity", "class": "A", "default": "ON", "strategy": "alpha", "description": "Support/Resistance proximity — stationary"},
    "F19": {"name": "Multi-day S/R", "class": "A", "default": "OFF", "strategy": "alpha", "description": "Multi-day support/resistance proximity filter"},
    "F23": {"name": "ADX Filter", "class": "B", "default": "OFF", "strategy": "master", "description": "ADX trend strength — quarterly drift"},
    "F24": {"name": "MACD Filter", "class": "B", "default": "OFF", "strategy": "master", "description": "MACD signal — quarterly drift"},
    "F25": {"name": "Volume Filter", "class": "C", "default": "OFF", "strategy": "master", "description": "Volume threshold — regime-coupled"},
    "F26": {"name": "ATR Filter", "class": "A", "default": "OFF", "strategy": "master", "description": "ATR volatility — stationary"},
    "F27": {"name": "Supertrend Filter", "class": "A", "default": "OFF", "strategy": "master", "description": "Supertrend signal — stationary"},
    "F28": {"name": "EMA Filter", "class": "A", "default": "OFF", "strategy": "master", "description": "EMA trend — stationary"},
    "F29": {"name": "Time Filter", "class": "A", "default": "OFF", "strategy": "master", "description": "Time-of-day filter — stationary"},
    "F30": {"name": "Spike Filter", "class": "C", "default": "OFF", "strategy": "master", "description": "Price spike detection — regime-coupled"},
    # Parameters
    "bbLength": {"class": "A", "strategy": "alpha", "index": 4},
    "rsiLength": {"class": "A", "strategy": "alpha", "index": 5},
    "atrLength": {"class": "A", "strategy": "alpha", "index": 6},
    "adxThreshold": {"class": "B", "strategy": "alpha", "index": 7},
    "cvdThreshold": {"class": "C", "strategy": "alpha", "index": 8},
    "trailingStopPct": {"class": "B", "strategy": "alpha", "index": 9},
    "be1Trigger": {"class": "B", "strategy": "alpha", "index": 10},
    "be2Trigger": {"class": "B", "strategy": "alpha", "index": 11},
}


@lru_cache(maxsize=1)
def _load_registry() -> dict[str, dict]:
    """Load the module registry from JSON file, or use fallback."""
    registry_path = Path(__file__).parent.parent / "kb_content" / "parameters" / "module_registry.json"
    if registry_path.exists():
        try:
            data = json.loads(registry_path.read_text(encoding="utf-8"))
            logger.info("loaded_module_registry", path=str(registry_path), entries=len(data))
            return data
        except Exception as e:
            logger.warning("failed_to_load_registry", error=str(e))

    logger.info("using_fallback_registry", entries=len(_FALLBACK_REGISTRY))
    return _FALLBACK_REGISTRY


def get_param_class(param_name: str, strategy: str = "alpha") -> ParameterClass | None:
    """Return Class A/B/C for a named parameter. None if not in registry."""
    registry = _load_registry()
    key = param_name.lower()
    for name, entry in registry.items():
        if name.lower() == key and entry.get("strategy", "").lower() == strategy.lower():
            cls = entry.get("class")
            if cls:
                return ParameterClass(cls)
    return None


def get_filter_info(filter_id: str, strategy: str = "alpha") -> dict | None:
    """Return {class, default, description} for a filter ID (D1, F19, etc.)."""
    registry = _load_registry()
    key = filter_id.upper()
    entry = registry.get(key)
    if entry and entry.get("strategy", "").lower() == strategy.lower():
        return entry
    # Try without strategy filter
    if entry:
        return entry
    return None


def get_input_index(param_name: str, strategy: str = "alpha") -> int | None:
    """Return the 0-based input index for a named parameter."""
    registry = _load_registry()
    key = param_name.lower()
    for name, entry in registry.items():
        if name.lower() == key and entry.get("strategy", "").lower() == strategy.lower():
            return entry.get("index")
    return None


def validate_param_bounds(param_name: str, value: float, strategy: str = "alpha") -> bool:
    """Check proposed value is within allowed bounds for a parameter.

    Returns True if within bounds, False otherwise.
    Currently uses hardcoded bounds — replace with param_class_master.yaml when available.
    """
    # Hardcoded bounds for common parameters
    bounds: dict[str, tuple[float, float]] = {
        "bblength": (10, 50),
        "rsilength": (7, 21),
        "atrlength": (7, 21),
        "adxthreshold": (15, 35),
        "cvdthreshold": (50, 200),
        "trailingstoppct": (0.5, 5.0),
        "be1trigger": (0.5, 3.0),
        "be2trigger": (1.0, 5.0),
    }

    key = param_name.lower()
    if key in bounds:
        lo, hi = bounds[key]
        return lo <= value <= hi

    # If no bounds defined, allow (pass-through)
    return True
