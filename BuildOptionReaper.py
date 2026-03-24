import json
import os
import re

# build_options.json
_BUILD_OPTION_JSON = os.path.join(os.path.dirname(__file__), "build_options.json")

# 모듈 로드 시 딱 한 번 읽어둠
try:
    with open(_BUILD_OPTION_JSON, "r", encoding="utf-8") as f:
        _BUILD_OPTIONS = json.load(f)
except Exception as e:
    print(f"[ERROR] 빌드 옵션 JSON 로딩 실패: {e}")
    _BUILD_OPTIONS = {}

# 디렉티브 패턴 (대소문자 무시, 공백 및 괄호 허용)
_if_pattern    = re.compile(r"(?i)^#\s*if\b")
_elif_pattern  = re.compile(r"(?i)^#\s*elif\b")
_else_pattern  = re.compile(r"(?i)^#\s*else\b")
_endif_pattern = re.compile(r"(?i)^#\s*endif\b")

def filter_code_by_build_options(code: str) -> str:
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
            if re.match(r"^0($|\s)", cond):
                stack.append({"skip": True,  "taken": False})
            else:
                keep = _evaluate_logic(cond)
                stack.append({"skip": not keep, "taken": keep})
            continue

        # 6) #elif 처리
        if _elif_pattern.match(stripped) and stack:
            prev = stack.pop()
            if not prev["taken"]:
                cond = re.sub(r"(?i)^#\s*elif\b", "", stripped).strip("() ").strip()
                if re.match(r"^0($|\s)", cond):
                    new = {"skip": True,  "taken": False}
                else:
                    keep = _evaluate_logic(cond)
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

def _eval_simple(cond: str) -> bool:
    cond = cond.strip()

    if cond.startswith('!'):
        inner = cond[1:].strip("() ").strip()
        return not _eval_simple(inner)

    cond = cond.strip("() ")

    m = re.match(r"^([A-Z0-9_]+)\s*(==|!=|>=|<=|>|<)\s*([A-Z0-9_]+|\d+)$", cond)
    if m:
        key, op, val_token = m.groups()
        actual = _BUILD_OPTIONS.get(key, 0)
        compare = int(val_token) if val_token.isdigit() else _BUILD_OPTIONS.get(val_token, 0)
        if op == "==": return actual == compare
        if op == "!=": return actual != compare
        if op == ">":  return actual > compare
        if op == "<":  return actual < compare
        if op == ">=": return actual >= compare
        if op == "<=": return actual <= compare
        return False
    if re.match(r"^[A-Z0-9_]+$", cond):
        return _BUILD_OPTIONS.get(cond, 0) != 0
    return False


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
