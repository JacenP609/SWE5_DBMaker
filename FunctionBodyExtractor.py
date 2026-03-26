import re
from dataclasses import dataclass
from typing import List, Optional


_CONTROL_HEADS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "else",
    "do",
    "try",
}

_BLOCK_HEADS = {
    "class",
    "struct",
    "namespace",
    "enum",
    "union",
}

_BAD_PREFIX_HEADS = _CONTROL_HEADS | _BLOCK_HEADS | {
    "public",
    "private",
    "protected",
    "case",
    "default",
}

_NAME_PATTERN = re.compile(
    r"(?P<name>(?:~?[A-Za-z_]\w*|operator\s*[^\s(]+)"
    r"(?:\s*::\s*(?:~?[A-Za-z_]\w*|operator\s*[^\s(]+))*)\s*$"
)

_CALL_PREFIX = re.compile(r"^[\w\s:<>,*&~\[\].#]+$")


@dataclass
class FunctionDefinition:
    name: str
    qualified_name: str
    body: str
    start: int
    end: int


def mask_comments_and_strings(code_str: str) -> str:
    out = []
    i = 0
    state = "code"

    while i < len(code_str):
        ch = code_str[i]
        nxt = code_str[i + 1] if i + 1 < len(code_str) else ""

        if state == "code":
            if ch == "/" and nxt == "/":
                out.extend((" ", " "))
                i += 2
                state = "line_comment"
                continue
            if ch == "/" and nxt == "*":
                out.extend((" ", " "))
                i += 2
                state = "block_comment"
                continue
            if ch == '"':
                out.append(ch)
                i += 1
                state = "double_quote"
                continue
            if ch == "'":
                out.append(ch)
                i += 1
                state = "single_quote"
                continue

            out.append(ch)
            i += 1
            continue

        if state == "line_comment":
            if ch == "\n":
                out.append("\n")
                state = "code"
            else:
                out.append(" ")
            i += 1
            continue

        if state == "block_comment":
            if ch == "*" and nxt == "/":
                out.extend((" ", " "))
                i += 2
                state = "code"
            else:
                out.append("\n" if ch == "\n" else " ")
                i += 1
            continue

        if state == "double_quote":
            if ch == "\\" and nxt:
                out.extend((" ", " "))
                i += 2
            elif ch == '"':
                out.append(ch)
                i += 1
                state = "code"
            else:
                out.append("\n" if ch == "\n" else " ")
                i += 1
            continue

        if state == "single_quote":
            if ch == "\\" and nxt:
                out.extend((" ", " "))
                i += 2
            elif ch == "'":
                out.append(ch)
                i += 1
                state = "code"
            else:
                out.append("\n" if ch == "\n" else " ")
                i += 1
            continue

    return "".join(out)


def _find_matching_brace(masked_code: str, open_index: int) -> int:
    depth = 0
    for idx in range(open_index, len(masked_code)):
        ch = masked_code[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return idx
    return -1


def _find_matching_open_paren(masked_code: str, close_index: int) -> int:
    depth = 0
    for idx in range(close_index, -1, -1):
        ch = masked_code[idx]
        if ch == ")":
            depth += 1
        elif ch == "(":
            depth -= 1
            if depth == 0:
                return idx
    return -1


def _looks_like_signature_prefix(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False

    if stripped.endswith(":") and "::" not in stripped:
        return False

    head = stripped.split()[0]
    if head in _BAD_PREFIX_HEADS:
        return False

    if any(ch in stripped for ch in "{};="):
        return False

    if stripped.startswith("[[") or stripped.startswith("__attribute__"):
        return True

    if stripped.startswith("template"):
        return True

    return bool(_CALL_PREFIX.match(stripped))


def _locate_signature_start(code_str: str, search_start: int, name_index: int) -> int:
    start = code_str.rfind("\n", search_start, name_index) + 1

    while start > search_start:
        prev_end = start - 1
        prev_start = code_str.rfind("\n", search_start, prev_end) + 1
        prev_line = code_str[prev_start:prev_end]

        if not _looks_like_signature_prefix(prev_line):
            break

        start = prev_start

    return start


def _parse_definition_at(code_str: str, masked_code: str, brace_index: int) -> Optional[FunctionDefinition]:
    search_start = max(
        masked_code.rfind(";", 0, brace_index),
        masked_code.rfind("{", 0, brace_index),
        masked_code.rfind("}", 0, brace_index),
    ) + 1

    close_paren = masked_code.rfind(")", search_start, brace_index)
    if close_paren == -1:
        return None

    open_paren = _find_matching_open_paren(masked_code, close_paren)
    if open_paren == -1 or open_paren < search_start:
        return None

    between = masked_code[close_paren + 1:brace_index]
    if ";" in between:
        return None

    before_paren = code_str[search_start:open_paren].strip()
    if not before_paren:
        return None

    name_match = _NAME_PATTERN.search(before_paren)
    if not name_match:
        return None

    qualified_name = re.sub(r"\s+", "", name_match.group("name"))
    simple_name = qualified_name.split("::")[-1]
    if simple_name in _CONTROL_HEADS or simple_name in _BLOCK_HEADS:
        return None

    signature_start = _locate_signature_start(code_str, search_start, open_paren)
    signature_head = code_str[signature_start:open_paren].strip()
    if not signature_head:
        return None

    signature_head_token = signature_head.split()[0]
    if signature_head_token in _BAD_PREFIX_HEADS:
        return None

    end_index = _find_matching_brace(masked_code, brace_index)
    if end_index == -1:
        return None

    body = code_str[signature_start:end_index + 1]
    return FunctionDefinition(
        name=simple_name,
        qualified_name=qualified_name,
        body=body,
        start=signature_start,
        end=end_index + 1,
    )


def iter_function_definitions(code_str: str) -> List[FunctionDefinition]:
    masked_code = mask_comments_and_strings(code_str)
    found = []
    seen = set()

    for idx, ch in enumerate(masked_code):
        if ch != "{":
            continue

        definition = _parse_definition_at(code_str, masked_code, idx)
        if not definition:
            continue

        key = (definition.start, definition.end)
        if key in seen:
            continue

        seen.add(key)
        found.append(definition)

    return found


def extract_inner_body(function_body: str) -> str:
    open_brace = function_body.find("{")
    close_brace = function_body.rfind("}")
    if open_brace == -1 or close_brace == -1 or open_brace >= close_brace:
        return function_body.strip()
    return function_body[open_brace + 1:close_brace].strip()


def extract_function_body(code_str: str, function_name: str, class_name: Optional[str] = None) -> str:
    target_simple = str(function_name or "").strip().split("::")[-1]
    target_qualified = re.sub(r"\s+", "", str(function_name or "").strip())
    preferred_class = re.sub(r"\s+", "", str(class_name or "").strip())

    best_body = ""
    best_score = -1

    for definition in iter_function_definitions(code_str):
        score = -1

        if definition.qualified_name == target_qualified:
            score = 10
        elif definition.name == target_simple:
            score = 4
            if preferred_class:
                if definition.qualified_name == f"{preferred_class}::{target_simple}":
                    score = 12
                elif definition.qualified_name.endswith(f"::{target_simple}"):
                    score = 8
                elif "::" not in definition.qualified_name:
                    score = 6

        if score > best_score:
            best_body = definition.body
            best_score = score

    return best_body


def expand_one_level(function_body: str, code_str: str, class_name: Optional[str]) -> str:
    def extract_body_only(func_name: str) -> str:
        full_body = extract_function_body(code_str, func_name, class_name)
        return extract_inner_body(full_body)

    def infer_current_function_name() -> str:
        header = function_body.split("{", 1)[0]
        match = re.search(r"([A-Za-z_]\w*)\s*\(", header)
        return match.group(1) if match else ""

    current_function_name = infer_current_function_name()
    normalized_class = re.sub(r"\s+", "", str(class_name or "").strip())

    local_candidate_names = set()
    for definition in iter_function_definitions(code_str):
        if normalized_class:
            if definition.qualified_name == f"{normalized_class}::{definition.name}":
                local_candidate_names.add(definition.name)
        else:
            local_candidate_names.add(definition.name)

    def is_expandable_name(func_name: str) -> bool:
        if func_name in _BAD_PREFIX_HEADS:
            return False
        if current_function_name and func_name == current_function_name:
            return False
        if local_candidate_names and func_name not in local_candidate_names:
            return False
        return True

    standalone_call = re.compile(
        r"^(\s*)([A-Za-z_]\w*)\s*\((.*)\)\s*;\s*$"
    )
    inline_call = re.compile(
        r"(?<![\w:.>])([A-Za-z_]\w*)\s*\(.*?\)"
    )

    lines = function_body.splitlines()
    updated = []
    indent_unit = "    "
    inside_body = False

    for line in lines:
        if not inside_body:
            updated.append(line)
            if "{" in line:
                inside_body = True
            continue

        standalone = standalone_call.match(line)
        if standalone:
            indent = standalone.group(1)
            private_name = standalone.group(2)
            if not is_expandable_name(private_name):
                updated.append(line)
                continue
            body = extract_body_only(private_name)
            if body:
                expanded = "\n".join(f"{indent}{indent_unit}{part}" for part in body.splitlines())
                updated.extend([f"{indent}[", expanded, f"{indent}]"])
            else:
                updated.append(line)
            continue

        def inline_replace(match: re.Match[str]) -> str:
            private_name = match.group(1)
            if not is_expandable_name(private_name):
                return match.group(0)
            body = extract_body_only(private_name)
            if not body:
                return match.group(0)

            base_indent = line[:len(line) - len(line.lstrip())]
            expanded = "\n".join(f"{base_indent}{indent_unit}{part}" for part in body.splitlines())
            return f"\n{base_indent}[\n{expanded}\n{base_indent}]\n{base_indent}"

        updated.append(re.sub(inline_call, inline_replace, line))

    return "\n".join(updated)


def get_function_body(
    code_str: str,
    function_name: str,
    class_name: Optional[str] = None,
    max_depth: int = 5,
) -> str:
    base = extract_function_body(code_str, function_name, class_name)
    if not base:
        return ""

    current = base
    for _ in range(max_depth):
        expanded = expand_one_level(current, code_str, class_name)
        if expanded == current:
            break
        current = expanded

    return current
