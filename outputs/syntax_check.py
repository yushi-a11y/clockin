#!/usr/bin/env python3
"""对 index.html 做基础语法检查：HTML 标签平衡 + JS 词法/语法检查。

JS 部分先用 esprima 做真实解析；因为 esprima 4.0 不支持可选链 `?.`，
会在保留字符串/注释/正则/模板字面量的前提下把代码中的 `?.` 替换为空格再解析。
同时保留一个简单的括号平衡检查作为兜底。
"""

from html.parser import HTMLParser
import re
from pathlib import Path

try:
    import esprima
except ImportError:
    esprima = None

FILE = Path("/Users/lixiaotian/.qoderwork/workspace/mrssl6h69qlreqcf/index.html")


class SimpleHTMLChecker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.errors = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        void = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                "link", "meta", "param", "source", "track", "wbr"}
        if tag not in void:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        void = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                "link", "meta", "param", "source", "track", "wbr"}
        if tag in void:
            return
        if not self.stack:
            self.errors.append(f"Unexpected closing </{tag}>")
            return
        if self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.errors.append(f"Mismatched tag: expected </{self.stack[-1]}> but got </{tag}>")


def strip_code_qdot(text):
    """把代码里的 ?. 替换为普通访问，但保留字符串/注释/正则/模板字面量内部。

    用递归处理模板字面量 ${...} 插值，使插值内部的可选链也能被正确替换。
    """
    out = []
    i = 0
    n = len(text)

    def read_string(delim):
        """读取字符串或模板字面量。对模板字面量，其插值内部会被递归处理。"""
        nonlocal i
        out.append(delim)
        i += 1
        while i < n:
            ch = text[i]
            if ch == '\\':
                out.append(ch)
                i += 1
                if i < n:
                    out.append(text[i])
                    i += 1
                continue
            if ch == delim:
                out.append(ch)
                i += 1
                return
            if delim == '`' and ch == '$' and i + 1 < n and text[i + 1] == '{':
                out.append('${')
                i += 2
                # 递归处理插值表达式，直到匹配的 }
                process_until('}')
                if i < n and text[i] == '}':
                    out.append('}')
                    i += 1
                continue
            out.append(ch)
            i += 1
        # 未闭合也直接返回

    def read_regex():
        """读取一个字面正则表达式（从 / 开始，假设已确认是正则上下文）。"""
        nonlocal i
        start = i
        i += 1
        while i < n and text[i] != '/':
            if text[i] == '\\':
                i += 2
                continue
            i += 1
        i += 1
        while i < n and text[i] in 'gimsuy':
            i += 1
        out.append(text[start:i])

    def read_line_comment():
        """读取行注释。"""
        nonlocal i
        nl = text.find('\n', i)
        if nl == -1:
            out.append(text[i:])
            i = n
        else:
            out.append(text[i:nl])
            i = nl

    def read_block_comment():
        """读取块注释。"""
        nonlocal i
        end = text.find('*/', i + 2)
        if end == -1:
            out.append(text[i:])
            i = n
        else:
            out.append(text[i:end + 2])
            i = end + 2

    def process_until(stop_char):
        """处理代码直到遇到 stop_char（作为顶层结束符）。"""
        nonlocal i
        while i < n:
            ch = text[i]
            if stop_char is not None and ch == stop_char:
                return
            if ch in ('"', "'", '`'):
                read_string(ch)
                continue
            if ch == '/' and i + 1 < n:
                if text[i + 1] == '/':
                    read_line_comment()
                    continue
                if text[i + 1] == '*':
                    read_block_comment()
                    continue
                # 简单识别字面正则：前面是常见可接正则的运算符/括号/等号
                if i > 0 and text[i - 1] in '=,(;:[{!&|~\n\t ':
                    read_regex()
                    continue
            # 可选链 ?. / ?.[ / ?.( 对 esprima 4.0 不友好；语法检查阶段降级为普通访问
            if ch == '?' and i + 1 < n and text[i + 1] == '.':
                if i + 2 < n and text[i + 2] in '([':
                    out.append(text[i + 2])  # 去掉 ?. 只保留 [ 或 (
                    i += 3
                else:
                    out.append('.')  # ?.prop -> .prop
                    i += 2
                continue
            out.append(ch)
            i += 1

    process_until(None)
    return ''.join(out)


def check_brace_balance(text, label=""):
    """检查 ()/[]/{} 平衡。跳过字符串、注释、正则、模板字面量文本，
    但统计模板插值 ${...} 内部的括号。"""
    pairs = {"(": ")", "{": "}", "[": "]"}
    stack = []
    i = 0
    n = len(text)

    def skip_string(delim):
        nonlocal i
        i += 1
        while i < n:
            ch = text[i]
            if ch == '\\':
                i += 2
                continue
            if ch == delim:
                i += 1
                return
            if delim == '`' and ch == '$' and i + 1 < n and text[i + 1] == '{':
                # 进入模板插值：${ 计入一个左花括号
                stack.append('{')
                i += 2
                balance_until('}')
                if i < n and text[i] == '}':
                    # 匹配刚才压入的 {
                    if stack and stack[-1] == '{':
                        stack.pop()
                    else:
                        return False
                    i += 1
                continue
            i += 1
        return True

    def balance_until(stop_char):
        """在模板插值或普通代码中统计括号，直到 stop_char。"""
        nonlocal i
        while i < n:
            ch = text[i]
            if stop_char is not None and ch == stop_char:
                return True
            if ch in ('"', "'", '`'):
                ok = skip_string(ch)
                if not ok:
                    return False
                continue
            if ch == '/' and i + 1 < n:
                if text[i + 1] == '/':
                    i = text.find('\n', i)
                    if i == -1:
                        return True
                    i += 1
                    continue
                if text[i + 1] == '*':
                    end = text.find('*/', i + 2)
                    i = end + 2 if end != -1 else n
                    continue
                # 简单识别字面正则
                if i > 0 and text[i - 1] in '=,(;:[{!&|~\n\t ':
                    i += 1
                    while i < n and text[i] != '/':
                        if text[i] == '\\':
                            i += 2
                            continue
                        i += 1
                    i += 1
                    while i < n and text[i] in 'gimsuy':
                        i += 1
                    continue
            if ch in pairs:
                stack.append(ch)
            elif ch in pairs.values():
                if not stack:
                    ctx = text[max(0, i - 40):i + 40]
                    return False
                last = stack.pop()
                if pairs[last] != ch:
                    ctx = text[max(0, i - 40):i + 40]
                    return False
            i += 1
        return True

    ok = balance_until(None)
    if not ok:
        ctx = text[max(0, i - 40):i + 40]
        return False, f"Brace mismatch near pos {i}\n  context: ...{ctx}..."
    if stack:
        return False, f"Unclosed brackets: {stack}"
    return True, "ok"


def main():
    content = FILE.read_text(encoding="utf-8")

    checker = SimpleHTMLChecker()
    checker.feed(content)

    print("=" * 50)
    print("HTML tag balance check")
    print("=" * 50)
    if checker.errors:
        print("FAIL")
        for e in checker.errors[:20]:
            print("  -", e)
    elif checker.stack:
        print("FAIL: unclosed tags:", checker.stack)
    else:
        print("PASS: tag stack is clean")

    scripts = re.findall(r"<script[^>]*>(.*?)</script>", content, re.DOTALL | re.IGNORECASE)
    print("\n" + "=" * 50)
    print(f"JS syntax check ({len(scripts)} script block(s))")
    print("=" * 50)

    js_ok = True
    for idx, script in enumerate(scripts, 1):
        # 1) esprima parse（真实 JS 语法检查，最权威）
        esprima_ok = False
        esprima_msg = "esprima not installed"
        if esprima is not None:
            try:
                stripped = strip_code_qdot(script)
                esprima.parseScript(stripped, {"tolerant": True, "jsx": False})
                esprima_ok = True
                esprima_msg = "esprima parse ok"
            except Exception as e:
                esprima_msg = f"esprima: {type(e).__name__}: {e}"

        # 2) brace balance sanity check（模板字面量 HTML 会导致误报，仅作辅助）
        bal_ok, bal_msg = check_brace_balance(script, label=f"block {idx}")

        if esprima_ok:
            status = "PASS"
            notes = f"{esprima_msg}"
            if not bal_ok:
                notes += f" (brace balance warning: {bal_msg})"
            print(f"{status} block {idx} ({notes})")
        else:
            js_ok = False
            print(f"FAIL block {idx}")
            print(f"  - {esprima_msg}")
            if not bal_ok:
                print(f"  - brace balance: {bal_msg}")

    return 0 if (not checker.errors and not checker.stack and js_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
