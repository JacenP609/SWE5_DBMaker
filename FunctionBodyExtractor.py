import re


def extract_function_body(code_str, function_name, class_name):
    """
    code_str(빌드 옵션 필터링까지 완료된 전체 코드 텍스트)에서
    특정 Class::Function 의 function body 를 추출한다.
    """
    content = code_str

    def _join_return_type(src: str) -> str:
        lines = src.splitlines()
        if len(lines) >= 2 and "::" in lines[1] and "(" in lines[1] and "(" not in lines[0]:
            lines[0] = lines[0].rstrip() + " " + lines[1].lstrip()
            del lines[1]
        return "\n".join(lines)

    def _maybe_extend_return_line(content: str, sig_start: int) -> int:
        line_start = content.rfind('\n', 0, sig_start) + 1
        prev_end = line_start - 1
        if prev_end <= 0:
            return line_start

        prev_start = content.rfind('\n', 0, prev_end) + 1
        s = content[prev_start:prev_end].strip()
        if not s:
            return line_start

        if any(c in s for c in "(){};=#"):
            return line_start
        if ":" in s and "::" not in s:
            return line_start

        bad_heads = {
            "template", "class", "struct", "enum", "union",
            "using", "typedef", "case", "default",
            "public", "private", "protected"
        }
        head = s.split()[0]
        if head in bad_heads:
            return line_start

        typeish = r'^[A-Za-z_]\w*(?:::[A-Za-z_]\w*)?(?:<[^<>{}]*>)?\s*[\*&\s]*(?:const|volatile)?\s*$'
        if re.match(typeish, s):
            return prev_start

        return line_start

    # class::func → func 단독 순으로 검색
    for target in (f"{class_name}::{function_name}", function_name):
        pat = rf"^[^\n]*\b{re.escape(target)}\s*\([^)]*\)\s*\{{"
        m = re.search(pat, content, flags=re.MULTILINE)
        if not m:
            continue

        sig_start = m.start()
        start = _maybe_extend_return_line(content, sig_start)

        brace = 0
        for i in range(start, len(content)):
            ch = content[i]
            if ch == "{":
                brace += 1
            elif ch == "}":
                brace -= 1
                if brace == 0:
                    body = _join_return_type(content[start:i + 1])
                    return body

    return ""


def expand_one_level(function_body, code_str, class_name):
    """
    _privXXXX() 한 단계 확장.
    재귀 호출 시 동일 code_str 을 사용한다.
    """
    def extract_body_only(fname: str) -> str:
        full = extract_function_body(code_str, fname, class_name)
        if not full:
            return ""
        s = full.find("{")
        e = full.rfind("}")
        if s != -1 and e != -1 and s < e:
            return full[s+1:e].strip()
        return full.strip()

    lines = function_body.splitlines()
    updated = []
    indent_unit = "    "
    inside = False

    for line in lines:
        if not inside:
            updated.append(line)
            if "{" in line:
                inside = True
            continue

        m = re.match(r'^(\s*)(_\w+)\s*\(.*?\)\s*;\s*$', line)
        if m:
            indent = m.group(1)
            fname = m.group(2)
            body = extract_body_only(fname)
            if body:
                body_ind = "\n".join(indent + indent_unit + l for l in body.splitlines())
                updated.extend([f"{indent}[", f"{body_ind}", f"{indent}]"])
            else:
                updated.append(line)
            continue

        def inline_replace(m2):
            fname = m2.group(1)
            body = extract_body_only(fname)
            if not body:
                return m2.group(0)
            lead = line[:len(line) - len(line.lstrip())]
            body_fmt = "\n".join(lead + indent_unit + s for s in body.splitlines())
            return f"\n{lead}[\n{body_fmt}\n{lead}]\n{lead}"

        updated.append(re.sub(r'\b(_\w+)\s*\(.*?\)', inline_replace, line))

    return "\n".join(updated)


def get_function_body(code_str, function_name, class_name, max_depth=3):

    base = extract_function_body(code_str, function_name, class_name)
    if not base:
        return ""

    curr = base
    for _ in range(max_depth):
        nxt = expand_one_level(curr, code_str, class_name)
        if nxt == curr:
            break
        curr = nxt

    return curr
