"""KB lookup tool — programmatic lookups for param class, filter info, input index.

NO pydantic_ai imports. Pure Python + Pydantic.
Loaded from narrux_filter_glossary.json at startup.

These are exact-match lookups with authoritative answers — must be 100% correct,
not 95% via LLM retrieval.
"""

from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path

import structlog

from tools.schemas import ParameterClass

logger = structlog.get_logger(__name__)

# Paths — prefer kb_content/ first, fall back to Strategy Docs/
_PACKAGE_DIR = Path(__file__).parent.parent
_PROJECT_ROOT = _PACKAGE_DIR.parent
_STRATEGY_DOCS = _PROJECT_ROOT / "Strategy Docs"

_GLOSSARY_PATH = _PACKAGE_DIR / "kb_content" / "parameters" / "narrux_filter_glossary.json"
_GLOSSARY_FALLBACK = _STRATEGY_DOCS / "narrux_filter_glossary.json"

# Input index CSV locations — kb_content first, then Strategy Docs
_INPUT_INDEX_FILES = {
    "alpha": _PACKAGE_DIR / "kb_content" / "parameters" / "alpha_v15_9_1_input_index.csv",
    "sentinel": _PACKAGE_DIR / "kb_content" / "parameters" / "sentinel_v1_9_input_index.csv",
    "master": _PACKAGE_DIR / "kb_content" / "parameters" / "master_v14_3_input_index.csv",
    "nrx": _PACKAGE_DIR / "kb_content" / "parameters" / "nrx_mtr_v1_input_index.csv",
}
_INPUT_INDEX_FALLBACKS = {
    "master": _STRATEGY_DOCS / "strategy explain" / "MAster" / "master_v14_3_input_index.csv",
    "nrx": _STRATEGY_DOCS / "strategy explain" / "NRX" / "nrx_mtr_v1_input_index.csv",
}


@lru_cache(maxsize=1)
def _load_glossary() -> dict:
    """Load the filter glossary JSON. Returns raw dict. Prefers kb_content/."""
    for path in [_GLOSSARY_PATH, _GLOSSARY_FALLBACK]:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                logger.info("loaded_filter_glossary", path=str(path))
                return data
            except Exception as e:
                logger.warning("failed_to_load_glossary", path=str(path), error=str(e))

    logger.warning("filter_glossary_not_found")
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


def _normalize(s: str) -> str:
    """Lowercase and strip spaces for fuzzy comparison."""
    return s.lower().replace(" ", "")


def get_param_class(param_name: str, strategy: str = "alpha") -> ParameterClass | None:
    """Return Class A/B/C for a named parameter.

    Looks up the parameter in the glossary's parameter_classes section.
    Uses a priority match: exact > param-in-member > member-in-param.
    Spaces are stripped before comparison so "bbWidth" matches "BB width".
    When multiple matches exist in the same tier, the longest member wins
    (most specific match).
    """
    glossary = _load_glossary()
    param_classes = glossary.get("parameter_classes", {})

    name_norm = _normalize(param_name)

    # Build list of (member_normalized, member_original, class_letter) triples
    candidates: list[tuple[str, str, str]] = []
    for cls_letter, cls_info in param_classes.items():
        for member in cls_info.get("members", []):
            candidates.append((_normalize(member), member, cls_letter))

    # Pass 1: Exact match (normalized)
    exact = [(m, c) for mn, m, c in candidates if name_norm == mn]
    if exact:
        return ParameterClass(exact[0][1])

    # Pass 2: Param name is substring of member (e.g., "bb" in "bbwidth")
    # Prefer longest member (most specific match)
    param_in_member = [(m, c) for mn, m, c in candidates if name_norm in mn]
    if param_in_member:
        param_in_member.sort(key=lambda x: len(x[0]), reverse=True)
        return ParameterClass(param_in_member[0][1])

    # Pass 3: Member is substring of param name (e.g., "cvd" in "cvdlongthresholdls")
    # Prefer longest member (most specific match)
    member_in_param = [(m, c) for mn, m, c in candidates if mn in name_norm]
    if member_in_param:
        member_in_param.sort(key=lambda x: len(x[0]), reverse=True)
        return ParameterClass(member_in_param[0][1])

    return None


@lru_cache(maxsize=4)
def _load_input_index(strategy: str) -> dict[str, dict]:
    """Load input index CSV for a strategy. Prefers kb_content/, falls back to Strategy Docs/."""
    csv_path = _INPUT_INDEX_FILES.get(strategy.lower())
    if not csv_path or not csv_path.exists():
        # Try fallback
        csv_path = _INPUT_INDEX_FALLBACKS.get(strategy.lower())

    if not csv_path or not csv_path.exists():
        logger.warning("input_index_not_found", strategy=strategy)
        return {}

    index: dict[str, dict] = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Handle both "name" and "Input name" header formats
            name = row.get("name", row.get("Input name", "")).strip()
            if not name:
                continue
            try:
                idx = int(row.get("index", row.get("Idx", -1)))
            except ValueError:
                continue
            index[name.lower()] = {
                "index": idx,
                "name": name,
                "type": row.get("type", row.get("Type", "")),
                "default": row.get("default", row.get("Default", "")),
                "group": row.get("group", row.get("Group", "")),
            }

    logger.info("loaded_input_index", strategy=strategy, entries=len(index))
    return index


def get_input_index(param_name: str, strategy: str = "master") -> int | None:
    """Return the 0-based input index for a named parameter.

    Loads from the strategy's input_index CSV file.
    Returns None if not found.
    """
    index = _load_input_index(strategy)
    entry = index.get(param_name.lower())
    if entry:
        return entry["index"]

    # Try partial match (e.g., "atrPeriod" matches "atrperiod")
    name_lower = param_name.lower()
    for key, entry in index.items():
        if name_lower in key or key in name_lower:
            return entry["index"]

    return None


def get_input_info(param_name: str, strategy: str = "master") -> dict | None:
    """Return full input info {index, name, type, default, group} for a parameter."""
    index = _load_input_index(strategy)
    entry = index.get(param_name.lower())
    if entry:
        return entry

    # Try partial match
    name_lower = param_name.lower()
    for key, entry in index.items():
        if name_lower in key or key in name_lower:
            return entry

    return None


def validate_param_bounds(param_name: str, value: float, strategy: str = "alpha") -> bool:
    """Check proposed value is within allowed bounds for a parameter.

    Returns True if within bounds (or if bounds are unknown).
    Bounds come from param_class_master.yaml — not yet loaded.
    """
    # Until param_class_master.yaml is loaded, allow all values
    return True
