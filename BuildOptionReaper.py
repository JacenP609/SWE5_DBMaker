import json
import os
import re

# build_options.json
_BUILD_OPTION_JSON = os.path.join(os.path.dirname(__file__), "build_options.json")

# 모듈 로드 시 딱 한 번 읽어둠
try:
    with open(_BUILD_OPTION_JSON, "r", encoding="utf-8") as f:
        _raw_options = json.load(f)
        _BUILD_OPTIONS = {str(key).upper(): value for key, value in _raw_options.items()}
except Exception as e:
    print(f"[ERROR] 빌드 옵션 JSON 로딩 실패: {e}")
    _BUILD_OPTIONS = {}

# 디렉티브 패턴 (대소문자 무시, 공백 및 괄호 허용)
_if_pattern    = re.compile(r"(?i)^#\s*if\b")
_elif_pattern  = re.compile(r"(?i)^#\s*elif\b")
_else_pattern  = re.compile(r"(?i)^#\s*else\b")
_endif_pattern = re.compile(r"(?i)^#\s*endif\b")
_SPECIAL_ALWAYS_IF_OPTIONS = {"OP_BL_CODE"}


def _contains_special_always_if_option(cond: str) -> bool:
    tokens = set(re.findall(r"[A-Z][A-Z0-9_]*", cond.upper()))
    return any(option in tokens for option in _SPECIAL_ALWAYS_IF_OPTIONS)


def is_special_option_for_else_resolve(option: str) -> bool:
    return str(option or "").upper() in _SPECIAL_ALWAYS_IF_OPTIONS


def _evaluate_if_condition(cond: str, prefer_special_if: bool = True) -> bool:
    if re.match(r"^0($|\s)", cond):
        return False
    if prefer_special_if and _contains_special_always_if_option(cond):
        return True
    return _evaluate_logic(cond)

def filter_code_by_build_options(code: str, prefer_special_if: bool = True) -> str:
    # 0) /*…*/ 블록 주석 제거 (멀티라인 포함)
    code = re.sub(r"/\*[\s\S]*?\*/", "", code)

    lines = code.splitlines()
    output = []
    stack = []  # 각 레벨: {skip: bool, taken: bool}

    for raw in lines:
        # 스트립하면 보기 안좋으니까 공백 추가
        if raw.strip() == "":
            output.append("")
            continue

        # 2) // 주석 제거 (inline)
        line = re.sub(r"//.*", "", raw)

        # 3) 주석만 남은 경우(또는 공백만 남은 경우) 스킵
        if line.strip() == "":
            continue

        stripped = line.strip()

        # 4) static_assert 라인 제거
        if stripped.startswith("static_assert"):
            continue

        # 5) #if 처리
        if _if_pattern.match(stripped):
            cond = re.sub(r"(?i)^#\s*if\b", "", stripped).strip("() ").strip()
            keep = _evaluate_if_condition(cond, prefer_special_if=prefer_special_if)
            stack.append({"skip": not keep, "taken": keep})
            continue

        # 6) #elif 처리
        if _elif_pattern.match(stripped) and stack:
            prev = stack.pop()
            if not prev["taken"]:
                cond = re.sub(r"(?i)^#\s*elif\b", "", stripped).strip("() ").strip()
                keep = _evaluate_if_condition(cond, prefer_special_if=prefer_special_if)
                new = {"skip": not keep, "taken": keep}
            else:
                new = {"skip": True, "taken": True}
            stack.append(new)
            continue

        # 7) #else 처리
        if _else_pattern.match(stripped) and stack:
            prev = stack.pop()
            new = {"skip": prev["taken"], "taken": True}
            stack.append(new)
            continue

        # 8) #endif 처리
        if _endif_pattern.match(stripped):
            if stack:
                stack.pop()
            continue

        # 9) 실제 코드 출력: 현재 스택이 비어있거나 skip=False 일 때만
        if not any(level["skip"] for level in stack):
            output.append(line)

    return "\n".join(output)


def _evaluate_logic(expr: str) -> bool:
    or_parts = re.split(r"\|\||\s+or\s+", expr, flags=re.IGNORECASE)
    for part in or_parts:
        and_parts = re.split(r"&&|\s+and\s+", part, flags=re.IGNORECASE)
        if all(_eval_simple(p.strip()) for p in and_parts):
            return True
    return False


def _resolve_option_value(token: str) -> int:
    return int(_BUILD_OPTIONS.get(str(token or "").upper(), 0))


def _eval_simple(cond: str) -> bool:
    cond = cond.strip()

    if cond.startswith('!'):
        inner = cond[1:].strip("() ").strip()
        return not _eval_simple(inner)

    cond = cond.strip("() ")

    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(==|!=|>=|<=|>|<)\s*([A-Za-z_][A-Za-z0-9_]*|\d+)$", cond)
    if m:
        key, op, val_token = m.groups()
        actual = _resolve_option_value(key)
        compare = int(val_token) if val_token.isdigit() else _resolve_option_value(val_token)
        if op == "==": return actual == compare
        if op == "!=": return actual != compare
        if op == ">":  return actual > compare
        if op == "<":  return actual < compare
        if op == ">=": return actual >= compare
        if op == "<=": return actual <= compare
        return False
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", cond):
        return _resolve_option_value(cond) != 0
    return False


def diagnose_call_reap_out(code: str, function_name: str, prefer_special_if: bool = True) -> dict:
    code = re.sub(r"/\*[\s\S]*?\*/", "", code)
    lines = code.splitlines()
    target = re.escape(str(function_name or "").strip().split("::")[-1])
    call_pattern = re.compile(rf"(?<![\w:])(?:[A-Za-z_]\w*::)*{target}\s*(?:<[^;{{}}()]*>)?\s*\(")

    stack = []
    reaped = False
    conditions = []

    for raw in lines:
        line = re.sub(r"//.*", "", raw)
        stripped = line.strip()
        if not stripped:
            continue

        if _if_pattern.match(stripped):
            cond = re.sub(r"(?i)^#\s*if\b", "", stripped).strip("() ").strip()
            keep = _evaluate_if_condition(cond, prefer_special_if=prefer_special_if)
            stack.append({"skip": not keep, "taken": keep, "condition": cond})
            continue

        if _elif_pattern.match(stripped) and stack:
            prev = stack.pop()
            cond = re.sub(r"(?i)^#\s*elif\b", "", stripped).strip("() ").strip()
            if not prev["taken"]:
                keep = _evaluate_if_condition(cond, prefer_special_if=prefer_special_if)
                stack.append({"skip": not keep, "taken": keep, "condition": cond})
            else:
                stack.append({"skip": True, "taken": True, "condition": cond})
            continue

        if _else_pattern.match(stripped) and stack:
            prev = stack.pop()
            stack.append(
                {
                    "skip": prev["taken"],
                    "taken": True,
                    "condition": f"else({prev.get('condition', '')})",
                }
            )
            continue

        if _endif_pattern.match(stripped):
            if stack:
                stack.pop()
            continue

        if call_pattern.search(line) and any(level["skip"] for level in stack):
            reaped = True
            for level in stack:
                if level["skip"] and level.get("condition"):
                    cond = level["condition"]
                    if cond not in conditions:
                        conditions.append(cond)

    options = []
    for cond in conditions:
        for token in re.findall(r"[A-Z][A-Z0-9_]{2,}", cond.upper()):
            if token in {"IF", "ELIF", "IFDEF", "IFNDEF", "ELSE"}:
                continue
            if token not in options:
                options.append(token)

    return {"reaped": reaped, "conditions": conditions[:5], "options": options[:8]}


# Test 용 코드로 실제로 불리지 않는다.
def test_filter_sample_file():
    header_path = "C:\\path\\blabla.cpp"
    filename = os.path.basename(header_path)
    name, ext = os.path.splitext(filename)

    output_filename = f"{name}.filtered{ext}"
    output_path = os.path.join(os.getcwd(), output_filename)

    with open(header_path, "r", encoding="utf-8", errors="ignore") as f:
        raw_code = f.read()

    filtered_code = filter_code_by_build_options(raw_code)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(filtered_code)

    print(f"✅ 필터링 완료: {output_path}")
