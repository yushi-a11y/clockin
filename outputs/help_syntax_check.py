#!/usr/bin/env python3
"""检查帮助中心相关 JS 代码段落的括号/引号平衡（正确处理模板字符串 ${}）"""

from pathlib import Path

FILE = Path("/Users/lixiaotian/.qoderwork/workspace/mrssl6h69qlreqcf/index.html")

def check_balance(text, label=""):
    pairs = {"(": ")", "{": "}", "[": "]"}
    stack = []
    in_str = None
    escape = False
    tpl_interp_depth = 0  # 模板字符串 ${...} 的嵌套深度
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_str:
            if escape:
                escape = False
                i += 1
                continue
            if ch == "\\":
                escape = True
                i += 1
                continue
            if in_str == "`":
                if ch == "$" and i + 1 < n and text[i + 1] == "{":
                    tpl_interp_depth = 1
                    i += 2
                    continue
                if tpl_interp_depth > 0:
                    if ch == "{":
                        tpl_interp_depth += 1
                    elif ch == "}":
                        tpl_interp_depth -= 1
                    i += 1
                    continue
                if ch == "`":
                    in_str = None
            elif ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ('"', "'", "`"):
            in_str = ch
            i += 1
            continue
        if ch in pairs:
            stack.append(ch)
        elif ch in pairs.values():
            if not stack:
                ctx = text[max(0, i-60):i+60]
                return False, f"Unmatched closing '{ch}' at pos {i}\n  context: ...{ctx}..."
            last = stack.pop()
            if pairs[last] != ch:
                ctx = text[max(0, i-60):i+60]
                return False, f"Mismatched '{last}' closed with '{ch}' at pos {i}\n  context: ...{ctx}..."
        i += 1
    if in_str:
        return False, f"Unclosed string delimiter '{in_str}'"
    if stack:
        return False, f"Unclosed brackets: {stack}"
    return True, "ok"

def extract_section(content, start_marker, end_marker):
    start = content.find(start_marker)
    if start == -1:
        return None
    end = content.find(end_marker, start + len(start_marker))
    if end == -1:
        return None
    return content[start:end]

def main():
    content = FILE.read_text(encoding="utf-8")
    all_ok = True

    sections = {
        "帮助中心函数区块": (
            "// ===== 员工端：帮助中心（小二端自助答疑） =====",
            "async function submitLeave(isProxy){"
        ),
        "renderEmp 帮助分发": (
            "document.getElementById('tab-help').classList.toggle('active',empTab==='help');",
            "if(empTab==='help'){renderHelpView();return}"
        ),
        "setEmpTab 帮助重置": (
            "function setEmpTab(t){",
            "let myMonthOffset=0;"
        ),
    }

    for name, (start, end) in sections.items():
        sec = extract_section(content, start, end)
        if sec is None:
            print(f"[MISS] {name}: 无法定位边界")
            all_ok = False
            continue
        ok, msg = check_balance(sec, name)
        if ok:
            print(f"[PASS] {name} ({len(sec)} chars)")
        else:
            print(f"[FAIL] {name}: {msg}")
            all_ok = False

    return 0 if all_ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
