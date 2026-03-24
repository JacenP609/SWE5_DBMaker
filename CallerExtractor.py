import re
from collections import deque
from typing import Iterable, List, Mapping, Tuple

from FunctionBodyExtractor import (
    extract_inner_body,
    get_function_body,
    iter_function_definitions,
    mask_comments_and_strings,
)


def _normalize_function_name(name: str) -> str:
    return str(name or "").strip().split("::")[-1]


def _build_call_pattern(callee_name: str) -> re.Pattern[str]:
    bare_name = re.escape(_normalize_function_name(callee_name))
    return re.compile(
        rf"(?<![\w:])(?:[A-Za-z_]\w*::)*{bare_name}\s*(?:<[^;{{}}()]*>)?\s*\(",
        flags=re.MULTILINE,
    )


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


def resolve_caller_function(
    code_str: str,
    target_function_name: str,
    interface_pairs: Iterable[Tuple[str, str]] | Iterable[Mapping[str, str]],
    class_name: str | None = None,
    max_depth: int = 8,
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

    definitions = []
    for definition in iter_function_definitions(code_str):
        inner_body = extract_inner_body(definition.body)
        definitions.append(
            {
                "name": definition.name,
                "body": definition.body,
                "masked_inner_body": mask_comments_and_strings(inner_body),
            }
        )

    queue = deque([_normalize_function_name(target_function_name)])
    visited = set()

    while queue:
        callee_name = queue.popleft()
        if callee_name in visited:
            continue
        visited.add(callee_name)

        pattern = _build_call_pattern(callee_name)

        for definition in definitions:
            if not pattern.search(definition["masked_inner_body"]):
                continue

            caller_name = definition["name"]
            normalized_caller = _normalize_function_name(caller_name)

            if normalized_caller in interface_index:
                pair = interface_index[normalized_caller][0]
                expanded_body = (
                    get_function_body(code_str, pair["function_name"], class_name, max_depth)
                    or get_function_body(code_str, caller_name, class_name, max_depth)
                    or definition["body"]
                )

                return {
                    "caller_function_id": pair["interface_id"],
                    "caller_function_name": pair["function_name"],
                    "caller_function_body": expanded_body,
                }

            queue.append(normalized_caller)

    return {
        "caller_function_id": "",
        "caller_function_name": "",
        "caller_function_body": "",
    }
