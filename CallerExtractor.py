import re
from collections import deque
from typing import Iterable, List, Mapping, Tuple

from FunctionBodyExtractor import (
    extract_inner_body,
    get_function_body,
    iter_function_definitions,
    mask_comments_and_strings,
)

_NON_CALL_NAMES = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "else",
    "do",
    "try",
    "return",
    "sizeof",
}

_CALL_FINDER = re.compile(
    r"(?<![\w:])(?:[A-Za-z_]\w*::)*([A-Za-z_]\w*)\s*(?:<[^;{}()]*>)?\s*\(",
    flags=re.MULTILINE,
)


def _normalize_function_name(name: str) -> str:
    return str(name or "").strip().split("::")[-1]


def _candidate_pairs(
    interface_pairs: Iterable[Tuple[str, str]] | Iterable[Mapping[str, str]],
) -> List[dict]:
    pairs = []
    for item in interface_pairs:
        if isinstance(item, Mapping):
            interface_id = str(item.get("interface_id", "")).strip()
            function_name = str(item.get("function_name", "")).strip()
        else:
            interface_id = str(item[0]).strip()
            function_name = str(item[1]).strip()

        if not interface_id or not function_name:
            continue

        pairs.append(
            {
                "interface_id": interface_id,
                "function_name": function_name,
                "normalized_name": _normalize_function_name(function_name),
            }
        )

    return pairs


def build_caller_index(code_str: str) -> dict:
    definitions = []
    defined_names = set()
    for definition in iter_function_definitions(code_str):
        inner_body = extract_inner_body(definition.body)
        normalized = _normalize_function_name(definition.name)
        defined_names.add(normalized)
        definitions.append(
            {
                "name": definition.name,
                "normalized_name": normalized,
                "body": definition.body,
                "masked_inner_body": mask_comments_and_strings(inner_body),
            }
        )

    reverse_calls = {}
    body_by_name = {}

    for definition in definitions:
        caller = definition["normalized_name"]
        body_by_name.setdefault(caller, definition["body"])

        seen_callees = set()
        for match in _CALL_FINDER.finditer(definition["masked_inner_body"]):
            callee = _normalize_function_name(match.group(1))
            if not callee or callee in _NON_CALL_NAMES:
                continue
            if callee not in defined_names:
                continue
            if callee in seen_callees:
                continue
            seen_callees.add(callee)
            reverse_calls.setdefault(callee, []).append(caller)

    return {
        "definitions": definitions,
        "reverse_calls": reverse_calls,
        "body_by_name": body_by_name,
    }


def resolve_caller_function(
    code_str: str,
    target_function_name: str,
    interface_pairs: Iterable[Tuple[str, str]] | Iterable[Mapping[str, str]],
    class_name: str | None = None,
    body_expand_depth: int = 1,
    caller_index: dict | None = None,
    max_caller_depth: int = 6,
    max_nodes: int = 5000,
) -> dict:
    candidates = _candidate_pairs(interface_pairs)
    if not code_str or not target_function_name or not candidates:
        return {
            "caller_function_id": "",
            "caller_function_name": "",
            "caller_function_body": "",
        }

    interface_index = {}
    for pair in candidates:
        interface_index.setdefault(pair["normalized_name"], []).append(pair)

    index = caller_index or build_caller_index(code_str)
    reverse_calls = index.get("reverse_calls", {})
    body_by_name = index.get("body_by_name", {})

    queue = deque([(_normalize_function_name(target_function_name), 0)])
    visited = set()
    queued = {_normalize_function_name(target_function_name)}
    nodes = 0

    while queue:
        callee_name, depth = queue.popleft()
        queued.discard(callee_name)
        if callee_name in visited:
            continue
        visited.add(callee_name)

        nodes += 1
        if nodes > max_nodes:
            break

        for normalized_caller in reverse_calls.get(callee_name, []):
            caller_name = normalized_caller

            if normalized_caller in interface_index:
                pair = interface_index[normalized_caller][0]
                base_body = body_by_name.get(normalized_caller, "")
                if body_expand_depth <= 0:
                    expanded_body = base_body
                else:
                    expanded_body = (
                        get_function_body(code_str, pair["function_name"], class_name, body_expand_depth)
                        or get_function_body(code_str, caller_name, class_name, body_expand_depth)
                        or base_body
                    )

                return {
                    "caller_function_id": pair["interface_id"],
                    "caller_function_name": pair["function_name"],
                    "caller_function_body": expanded_body,
                }

            if (
                depth < max_caller_depth
                and normalized_caller not in visited
                and normalized_caller not in queued
            ):
                queue.append((normalized_caller, depth + 1))
                queued.add(normalized_caller)

    return {
        "caller_function_id": "",
        "caller_function_name": "",
        "caller_function_body": "",
    }
