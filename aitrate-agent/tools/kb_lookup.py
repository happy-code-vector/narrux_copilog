"""KB lookup tool — programmatic lookups for param class, filter info, input index.

NO pydantic_ai imports. Pure Python + Pydantic.

Data source:
  - registry.db — SQLite parameter registry (parameters + filter glossary)

These are exact-match lookups with authoritative answers — must be 100% correct,
not 95% via LLM retrieval.
"""

from __future__ import annotations

import json
import sqlite3
from functools import lru_cache
from pathlib import Path

import structlog

from tools.schemas import ParameterClass

logger = structlog.get_logger(__name__)

# Paths — canonical location is kb_content/
_PACKAGE_DIR = Path(__file__).parent.parent
_KB_DIR = _PACKAGE_DIR / "kb_content"

_DB_PATH = _KB_DIR / "parameters" / "registry.db"


# ── Database connection ───────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    """Return a read-only connection to the parameter registry DB."""
    if not _DB_PATH.exists():
        logger.warning("registry_db_not_found", path=str(_DB_PATH))
        raise FileNotFoundError(f"Parameter registry DB not found: {_DB_PATH}")
    conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ── Agent queries (point lookups) ────────────────────────────────────────────

def get_input_info(param_name: str, strategy: str = "master", version: str | None = None) -> dict | None:
    """Return full parameter info from the registry.

    Args:
        param_name: PineScript key (e.g. "bbLength") or human name.
        strategy: Strategy name (alpha, sentinel, master, nrx).
        version: Specific version, or None for latest.

    Returns:
        Dict with: index, name, key, type, default, group, category,
        filter_class, valid_range, min, max, step, options, description, basis,
        strategy, version. Or None if not found.
    """
    try:
        conn = _get_conn()
    except FileNotFoundError:
        return None

    try:
        if version:
            row = conn.execute(
                "SELECT * FROM parameters WHERE strategy=? AND version=? AND (key=? COLLATE NOCASE OR name=? COLLATE NOCASE)",
                (strategy, version, param_name, param_name),
            ).fetchone()
        else:
            # Latest version
            row = conn.execute(
                """SELECT * FROM parameters
                   WHERE strategy=? AND (key=? COLLATE NOCASE OR name=? COLLATE NOCASE)
                   ORDER BY version DESC LIMIT 1""",
                (strategy, param_name, param_name),
            ).fetchone()

        if row:
            return _row_to_dict(row)

        # Partial match fallback
        name_lower = param_name.lower()
        if version:
            rows = conn.execute(
                "SELECT * FROM parameters WHERE strategy=? AND version=?",
                (strategy, version),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM parameters WHERE strategy=?
                   AND version=(SELECT MAX(version) FROM parameters WHERE strategy=?)""",
                (strategy, strategy),
            ).fetchall()

        for r in rows:
            if name_lower in r["key"].lower() or name_lower in r["name"].lower():
                return _row_to_dict(r)

        return None
    finally:
        conn.close()


def get_input_index(param_name: str, strategy: str = "master", version: str | None = None) -> int | None:
    """Return the 0-based input index for a parameter."""
    info = get_input_info(param_name, strategy, version)
    return info["index"] if info else None


def get_param_class(param_name: str, strategy: str = "alpha", version: str | None = None) -> ParameterClass | None:
    """Return Class A/B/C for a parameter.

    Checks registry first (direct filter_class lookup), falls back to
    glossary fuzzy matching.
    """
    # Fast path: registry lookup
    info = get_input_info(param_name, strategy, version)
    if info and info.get("filter_class") in ("A", "B", "C"):
        return ParameterClass(info["filter_class"])

    # Fallback: glossary fuzzy matching
    return _param_class_from_glossary(param_name)


def validate_param_bounds(param_name: str, value: float, strategy: str = "alpha", version: str | None = None) -> bool:
    """Check proposed value is within allowed bounds.

    Returns True if within bounds (or if bounds are unknown).
    """
    info = get_input_info(param_name, strategy, version)
    if not info:
        return True

    lo = info.get("min")
    hi = info.get("max")

    if lo is None and hi is None:
        return True

    try:
        val = float(value)
    except (TypeError, ValueError):
        return True

    if lo is not None and val < float(lo):
        logger.warning("param_below_bounds", param=param_name, value=value, min=lo)
        return False

    if hi is not None and val > float(hi):
        logger.warning("param_above_bounds", param=param_name, value=value, max=hi)
        return False

    return True


# ── User queries (cross-strategy, version diffs) ─────────────────────────────

def query_params_by_class(filter_class: str, strategy: str | None = None, version: str | None = None) -> list[dict]:
    """Return all parameters with the given filter class.

    Args:
        filter_class: "A", "B", or "C".
        strategy: Optional strategy filter. None = all strategies.
        version: Optional version filter. None = latest per strategy.

    Returns:
        List of parameter dicts.
    """
    try:
        conn = _get_conn()
    except FileNotFoundError:
        return []

    try:
        if strategy and version:
            rows = conn.execute(
                "SELECT * FROM parameters WHERE filter_class=? AND strategy=? AND version=? ORDER BY strategy, position_index",
                (filter_class, strategy, version),
            ).fetchall()
        elif strategy:
            rows = conn.execute(
                """SELECT p.* FROM parameters p
                   INNER JOIN (SELECT strategy, MAX(version) as max_ver FROM parameters WHERE strategy=? GROUP BY strategy) mv
                   ON p.strategy=mv.strategy AND p.version=mv.max_ver
                   WHERE p.filter_class=? ORDER BY p.position_index""",
                (strategy, filter_class),
            ).fetchall()
        elif version:
            rows = conn.execute(
                "SELECT * FROM parameters WHERE filter_class=? AND version=? ORDER BY strategy, position_index",
                (filter_class, version),
            ).fetchall()
        else:
            # Latest per strategy
            rows = conn.execute(
                """SELECT p.* FROM parameters p
                   INNER JOIN (SELECT strategy, MAX(version) as max_ver FROM parameters GROUP BY strategy) mv
                   ON p.strategy=mv.strategy AND p.version=mv.max_ver
                   WHERE p.filter_class=? ORDER BY p.strategy, p.position_index""",
                (filter_class,),
            ).fetchall()

        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def query_version_diff(strategy: str, version_a: str, version_b: str) -> dict:
    """Compare two versions of a strategy's parameters.

    Returns:
        {
            "added": [...],      # params in B but not A
            "removed": [...],    # params in A but not B
            "changed": [...],    # params in both but different values
            "unchanged": int,    # count of identical params
        }
    """
    try:
        conn = _get_conn()
    except FileNotFoundError:
        return {"added": [], "removed": [], "changed": [], "unchanged": 0}

    try:
        rows_a = conn.execute(
            "SELECT * FROM parameters WHERE strategy=? AND version=?",
            (strategy, version_a),
        ).fetchall()
        rows_b = conn.execute(
            "SELECT * FROM parameters WHERE strategy=? AND version=?",
            (strategy, version_b),
        ).fetchall()

        map_a = {r["key"]: _row_to_dict(r) for r in rows_a}
        map_b = {r["key"]: _row_to_dict(r) for r in rows_b}

        keys_a = set(map_a.keys())
        keys_b = set(map_b.keys())

        added = [map_b[k] for k in (keys_b - keys_a)]
        removed = [map_a[k] for k in (keys_a - keys_b)]

        changed = []
        unchanged = 0
        for k in (keys_a & keys_b):
            a, b = map_a[k], map_b[k]
            diffs = {}
            for field in ("default", "filter_class", "min", "max", "valid_range", "group"):
                if str(a.get(field)) != str(b.get(field)):
                    diffs[field] = {"from": a.get(field), "to": b.get(field)}
            if diffs:
                changed.append({"key": k, "name": a["name"], "diffs": diffs})
            else:
                unchanged += 1

        return {
            "added": sorted(added, key=lambda x: x.get("position_index", 0)),
            "removed": sorted(removed, key=lambda x: x.get("position_index", 0)),
            "changed": sorted(changed, key=lambda x: x["key"]),
            "unchanged": unchanged,
        }
    finally:
        conn.close()


def query_params_by_category(category: str, strategy: str | None = None) -> list[dict]:
    """Return all parameters in a semantic category.

    Args:
        category: e.g. "Filter / Signal", "Capital & Sizing", "Exit Mechanism"
        strategy: Optional strategy filter.
    """
    try:
        conn = _get_conn()
    except FileNotFoundError:
        return []

    try:
        if strategy:
            rows = conn.execute(
                """SELECT p.* FROM parameters p
                   INNER JOIN (SELECT strategy, MAX(version) as max_ver FROM parameters WHERE strategy=? GROUP BY strategy) mv
                   ON p.strategy=mv.strategy AND p.version=mv.max_ver
                   WHERE p.category=? ORDER BY p.position_index""",
                (strategy, category),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT p.* FROM parameters p
                   INNER JOIN (SELECT strategy, MAX(version) as max_ver FROM parameters GROUP BY strategy) mv
                   ON p.strategy=mv.strategy AND p.version=mv.max_ver
                   WHERE p.category=? ORDER BY p.strategy, p.position_index""",
                (category,),
            ).fetchall()

        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def list_versions(strategy: str | None = None) -> list[dict]:
    """Return available versions, optionally filtered by strategy."""
    try:
        conn = _get_conn()
    except FileNotFoundError:
        return []

    try:
        if strategy:
            rows = conn.execute(
                "SELECT * FROM param_versions WHERE strategy=? ORDER BY version",
                (strategy,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM param_versions ORDER BY strategy, version"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_registry_stats() -> dict:
    """Return registry statistics."""
    try:
        conn = _get_conn()
    except FileNotFoundError:
        return {"error": "DB not found"}

    try:
        total = conn.execute("SELECT COUNT(*) FROM parameters").fetchone()[0]
        versions = conn.execute("SELECT COUNT(*) FROM param_versions").fetchone()[0]

        by_strategy = {}
        for row in conn.execute(
            "SELECT strategy, COUNT(DISTINCT version) as ver_count, COUNT(*) as param_count FROM parameters GROUP BY strategy"
        ):
            by_strategy[row["strategy"]] = {"versions": row["ver_count"], "params": row["param_count"]}

        by_class = {}
        for row in conn.execute(
            "SELECT filter_class, COUNT(*) as cnt FROM parameters WHERE filter_class IS NOT NULL GROUP BY filter_class"
        ):
            by_class[row["filter_class"] or "unclassified"] = row["cnt"]

        return {
            "total_parameters": total,
            "total_versions": versions,
            "by_strategy": by_strategy,
            "by_class": by_class,
        }
    finally:
        conn.close()


# ── RAG text generation ──────────────────────────────────────────────────────

def generate_rag_text(param: dict) -> str:
    """Generate a RAG-ready text chunk for a parameter.

    Same format as the old retrieval_cards text, derived from param data.
    """
    parts = [f"[{param.get('strategy', '?')} {param.get('version', '?')} . pos {param.get('index', '?')}]"]

    name = param.get("name", param.get("key", "?"))
    ptype = param.get("type", "")
    default = param.get("default", "")
    rng = param.get("valid_range", "")
    cls = param.get("filter_class")

    text = f"{name} {ptype}, default {default}"
    if rng:
        text += f", range {rng}"
    parts.append(text)

    if cls:
        parts.append(f"Class {cls}")

    group = param.get("group", "")
    if group:
        parts.append(f"Group: {group}.")

    return ". ".join(parts)


# ── Internal helpers ─────────────────────────────────────────────────────────

def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain dict with the public API shape."""
    d = dict(row)
    # Map DB column names to the public API names
    return {
        "index": d.get("position_index"),
        "name": d.get("name"),
        "key": d.get("key"),
        "type": d.get("type"),
        "default": d.get("default_value"),
        "group": d.get("group_name"),
        "category": d.get("category"),
        "filter_class": d.get("filter_class"),
        "valid_range": d.get("valid_range"),
        "min": d.get("min_value"),
        "max": d.get("max_value"),
        "step": d.get("step"),
        "options": json.loads(d["options"]) if d.get("options") else None,
        "description": d.get("description"),
        "basis": d.get("basis"),
        "strategy": d.get("strategy"),
        "version": d.get("version"),
    }


def _normalize(s: str) -> str:
    """Lowercase and strip spaces for fuzzy comparison."""
    return s.lower().replace(" ", "")


def _param_class_from_glossary(param_name: str) -> ParameterClass | None:
    """Fallback: fuzzy match against the filter_classes members in DB."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT class_id, members FROM filter_classes").fetchall()
    finally:
        conn.close()

    name_norm = _normalize(param_name)
    candidates: list[tuple[str, str, str]] = []
    for row in rows:
        members = json.loads(row["members"]) if row["members"] else []
        for member in members:
            candidates.append((_normalize(member), member, row["class_id"]))

    # Pass 1: Exact match
    exact = [(m, c) for mn, m, c in candidates if name_norm == mn]
    if exact:
        return ParameterClass(exact[0][1])

    # Pass 2: Param name is substring of member
    param_in_member = [(m, c) for mn, m, c in candidates if name_norm in mn]
    if param_in_member:
        param_in_member.sort(key=lambda x: len(x[0]), reverse=True)
        return ParameterClass(param_in_member[0][1])

    # Pass 3: Member is substring of param name
    member_in_param = [(m, c) for mn, m, c in candidates if mn in name_norm]
    if member_in_param:
        member_in_param.sort(key=lambda x: len(x[0]), reverse=True)
        return ParameterClass(member_in_param[0][1])

    return None


def get_filter_info(filter_id: str, strategy: str | None = None) -> dict | None:
    """Return {name, class, default, strategy, fnum?} for a filter ID.

    Args:
        filter_id: Filter identifier (D1, F1, E1, N1, etc.)
        strategy: Optional strategy filter (alpha, sentinel, master, nrx)
    """
    conn = _get_conn()
    try:
        fid = filter_id.upper()

        # For master, the DB stores them with prefixed group names
        if strategy and strategy.lower() == "master":
            row = conn.execute(
                """SELECT name, filter_class, default_value, strategy, fnum, filter_group
                   FROM strategy_filters
                   WHERE strategy = 'master' AND filter_id = ?""",
                (fid,),
            ).fetchone()
            if row:
                return {
                    "name": row["name"],
                    "class": row["filter_class"],
                    "default": row["default_value"] or "OFF",
                    "strategy": row["strategy"],
                    "fnum": row["fnum"],
                }
            return None

        # Non-master: try exact match first
        if strategy:
            row = conn.execute(
                """SELECT name, filter_class, default_value, strategy, fnum
                   FROM strategy_filters
                   WHERE strategy = ? AND filter_id = ?""",
                (strategy.lower(), fid),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT name, filter_class, default_value, strategy, fnum
                   FROM strategy_filters
                   WHERE filter_id = ?""",
                (fid,),
            ).fetchone()

        if row:
            return {
                "name": row["name"],
                "class": row["filter_class"],
                "default": row["default_value"] or "OFF",
                "strategy": row["strategy"],
                "fnum": row["fnum"],
            }

        return None
    finally:
        conn.close()


def get_governance_rules() -> dict[str, str]:
    """Return all governance rules from the filter glossary."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT rule_key, rule_text FROM governance_rules").fetchall()
        return {row["rule_key"]: row["rule_text"] for row in rows}
    finally:
        conn.close()


def get_filter_class_defs() -> dict[str, dict]:
    """Return filter class definitions (A, B, C) from the DB."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM filter_classes ORDER BY class_id").fetchall()
        result = {}
        for row in rows:
            result[row["class_id"]] = {
                "name": row["name"],
                "retune_cadence_months": row["retune_cadence_months"],
                "stationary": bool(row["stationary"]),
                "members": json.loads(row["members"]) if row["members"] else [],
            }
        return result
    finally:
        conn.close()
