from __future__ import annotations

from typing import Dict, List

import pandas as pd


_CATEGORY_BUILD_OPTION = "Build Option"
_CATEGORY_TARGET_MISSING = "Target Function Missing"
_CATEGORY_DEAD_CODE = "Possible DeadCode"


def _split_reason_entries(reason: str) -> List[str]:
    text = str(reason or "").strip()
    if not text:
        return []
    return [item.strip() for item in text.split(";") if item.strip()]


def _classify_entry(entry: str) -> tuple[str, str]:
    location, detail = (entry.split("=", 1) + [""])[:2]
    location = location.strip()
    detail = detail.strip()

    if "call removed by BuildOptionReaper" in detail:
        return _CATEGORY_BUILD_OPTION, f"{location}: {detail}"

    if (
        "call chain exists but no interface-exposed caller" in detail
        or "caller interface list empty" in detail
    ):
        return _CATEGORY_DEAD_CODE, f"{location}: {detail}"

    if (
        "no call to target function" in detail
        or "code path map miss" in detail
        or "code file missing from path map" in detail
    ):
        return _CATEGORY_TARGET_MISSING, f"{location}: {detail}"

    return _CATEGORY_TARGET_MISSING, entry


def create_suspect_entry(component: str, unit: str, function_name: str, reason: str) -> Dict[str, str]:
    categories: List[str] = []
    notes: List[str] = []

    for entry in _split_reason_entries(reason):
        category, note = _classify_entry(entry)
        if category not in categories:
            categories.append(category)
        notes.append(note)

    return {
        "Component": component,
        "Unit": unit,
        "Function": function_name,
        "ResolutionFail": "\n".join(categories),
        "Note": "\n".join(notes),
    }


def export_suspect_interfaces(path: str, rows: List[Dict[str, str]]) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows, columns=["Component", "Unit", "Function", "ResolutionFail", "Note"])
    df.to_excel(path, index=False)
