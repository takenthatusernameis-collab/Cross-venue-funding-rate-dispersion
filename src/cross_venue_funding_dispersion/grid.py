"""Frozen, deterministic enumeration and validation of the research grid."""
from __future__ import annotations
import itertools
import json
from pathlib import Path
from typing import Any


def load_grid(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as stream:
        return json.load(stream)


def expand_grid(config: dict[str, Any]) -> list[dict[str, Any]]:
    axes = config.get("axes")
    if not isinstance(axes, list) or not axes:
        raise ValueError("grid must declare a non-empty axes list")
    names = [axis.get("name") for axis in axes]
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError("every grid axis needs a non-empty name")
    if len(set(names)) != len(names):
        raise ValueError("grid axis names must be unique")
    values = [axis.get("values") for axis in axes]
    if any(not isinstance(items, list) or not items for items in values):
        raise ValueError("every grid axis needs a non-empty values list")
    return [dict(zip(names, combo)) for combo in itertools.product(*values)]


def config_id(index: int, config: dict[str, Any]) -> str:
    if index < 1:
        raise ValueError("configuration indices are one-based")
    spec = config.get("enumeration", {})
    return f"{spec.get('id_prefix', 'FVD')}{index:0{int(spec.get('id_width', 3))}d}"


def validate_grid(config: dict[str, Any]) -> list[str]:
    try:
        combos = expand_grid(config)
    except (TypeError, ValueError) as exc:
        return [str(exc)]
    errors: list[str] = []
    if len(combos) != config.get("expected_combinations"):
        errors.append(f"expected {config.get('expected_combinations')} combinations, found {len(combos)}")
    canonical = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in combos]
    if len(set(canonical)) != len(canonical):
        errors.append("duplicate configurations found")
    enum = config.get("enumeration", {})
    anchor = enum.get("primary_anchor")
    anchor_id = enum.get("primary_anchor_id")
    matches = [config_id(i, config) for i, item in enumerate(combos, 1) if item == anchor]
    if matches != [anchor_id]:
        errors.append(f"primary anchor mismatch: expected {anchor_id}, found {matches}")
    if len(combos) == 108 and anchor_id != "FVD053":
        errors.append("the registered 108-config experiment must keep FVD053 as primary anchor")
    return errors
