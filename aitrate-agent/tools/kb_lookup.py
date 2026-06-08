"""KB lookup tool — programmatic lookups for param class, filter info, input index.

NO pydantic_ai imports. Pure Python + Pydantic.
Loaded from narrux_filter_glossary.json at startup.

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

# Path to the authoritative filter glossary JSON
_GLOSSARY_PATH = Path(__file__).parent.parent.parent / "Strategy Docs" / "narrux_filter_glossary.json"


@lru_cache(maxsize=1)
def _load_glossary() -> dict:
    """Load the filter glossary JSON. Returns raw dict."""
    # Try multiple paths
    candidates = [
        _GLOSSARY_PATH,
        Path(__file__).parent.parent / "kb_content" / "parameters" / "narrux_filter_glossary.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                logger.info("loaded_filter_glossary", path=str(path))
                return data
            except Exception as e:
                logger.warning("failed_to_load_glossary", path=str(path), error=str(e))

    logger.warning("filter_glossary_not_found", candidates=[str(p) for p in candidates])
    return {}


def _build_filter_index(glossary: dict) -> dict[str, dict]:
    """Build a lookup index from filter ID to filter info."""
    index: dict[str, dict] = {}

    # Alpha filters (D1-D20) — uppercase keys
    for f in glossary.get("alpha_filters", []):
        index[f["id"].upper()] = {
            "name": f["name"],
            "class": f["class"],
            "default": f.get("default", "OFF"),
            "strategy": "alpha",
            "fnum": f.get("fnum"),
        }

    # Sentinel filters (F1-F16) — uppercase keys
    for f in glossary.get("sentinel_filters", []):
        index[f["id"].upper()] = {
            "name": f["name"],
            "class": f["class"],
            "default": f.get("default", "OFF"),
            "strategy": "sentinel",
        }

    # Master core filters (F1-F20 + StochRSI + MStruct) — prefixed, case-preserved
    for f in glossary.get("master_filters_core", []):
        index[f"master_{f['id'].upper()}"] = {
            "name": f["name"],
            "class": f["class"],
            "strategy": "master",
            "adaptive": f.get("adaptive", False),
        }

    # Master new filters (N1-N8) — prefixed
    for f in glossary.get("master_filters_new", []):
        index[f"master_{f['id'].upper()}"] = {
            "name": f["name"],
            "class": f["class"],
            "strategy": "master",
        }

    # NRX filters (E1-E9) — uppercase keys
    for f in glossary.get("nrx_filters", []):
        index[f["id"].upper()] = {
            "name": f["name"],
            "class": f["class"],
            "strategy": "nrx",
        }

    return index


@lru_cache(maxsize=1)
def _get_filter_index() -> dict[str, dict]:
    """Cached filter index."""
    glossary = _load_glossary()
    return _build_filter_index(glossary)


def get_filter_info(filter_id: str, strategy: str | None = None) -> dict | None:
    """Return {name, class, default, strategy} for a filter ID.

    Args:
        filter_id: Filter identifier (D1, F1, E1, N1, etc.)
        strategy: Optional strategy filter (alpha, sentinel, master, nrx)
    """
    index = _get_filter_index()
    fid = filter_id.upper()

    # Direct lookup
    entry = index.get(fid)
    if entry:
        if strategy and entry.get("strategy", "").lower() != strategy.lower():
            # Strategy mismatch — try prefixed lookup for Master
            if strategy and strategy.lower() == "master":
                prefixed = f"master_{fid}"
                entry2 = index.get(prefixed)
                if entry2:
                    return entry2
            return None
        return entry

    # Try with strategy prefix for Master filters (F1-F20 + N1-N8)
    if strategy and strategy.lower() == "master":
        prefixed = f"master_{fid}"
        entry = index.get(prefixed)
        if entry:
            return entry

    return None


def get_param_class(param_name: str, strategy: str = "alpha") -> ParameterClass | None:
    """Return Class A/B/C for a named parameter.

    Looks up the parameter in the glossary's parameter_classes section.
    """
    glossary = _load_glossary()
    param_classes = glossary.get("parameter_classes", {})

    name_lower = param_name.lower()

    for cls_letter, cls_info in param_classes.items():
        for member in cls_info.get("members", []):
            if name_lower in member.lower() or member.lower() in name_lower:
                return ParameterClass(cls_letter)

    return None


def get_input_index(param_name: str, strategy: str = "alpha") -> int | None:
    """Return the 0-based input index for a named parameter.

    Returns None if not found — the input index must come from
    the strategy's input_index CSV or the param_class_master.yaml.
    """
    # Input indices are strategy-specific and not in the glossary JSON.
    # They come from the input_index CSV files (master_v14_3_input_index.csv, etc.)
    # Return None until those are loaded.
    return None


def validate_param_bounds(param_name: str, value: float, strategy: str = "alpha") -> bool:
    """Check proposed value is within allowed bounds for a parameter.

    Returns True if within bounds (or if bounds are unknown).
    Bounds come from param_class_master.yaml — not yet loaded.
    """
    # Until param_class_master.yaml is loaded, allow all values
    return True
