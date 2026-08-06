#!/usr/bin/env python3
"""验证 FAQ 字符分词匹配算法（复刻 index.html / dingtalk-faq 逻辑）"""

import re

FAQ_ENTRIES = [
    {"id": "punch-chain", "category": "punch", "title": "为什么点了一次上班卡，系统把下一个连续班次也打了？", "keywords": ["连班", "连续", "下一个班次", "一起打卡", "链", "共用"], "answer": "这是「连班链」机制。如果两个班次首尾相接（前班结束时间 = 后班开始时间），系统会合并为一条链，链中中间交接处只需打一次卡，不需要分别打下班卡和上班卡。"},
    {"id": "punch-window", "category": "punch", "title": "为什么打卡按钮是灰色的/点不了？", "keywords": ["打卡", "按钮", "灰色", "点不了", "不能打卡", "提前", "窗口"], "answer": "每个班次只能在管理后台配置的「容忍窗口」内打卡。提前到达或过了窗口期，按钮都会变灰。"},
    {"id": "pick-limit", "category": "pick", "title": "每天/每周最多能选几个班？", "keywords": ["上限", "最多", "7", "49", "每天", "每周", "限制"], "answer": "每人每天最多选 7 个时段，每周合计不超过 49 个时段。"},
    {"id": "makeup-how", "category": "makeup", "title": "怎么提交补卡？", "keywords": ["补卡", "提交", "缺卡", "申请"], "answer": "在「补卡」页选择缺卡日期、缺卡班次、实际打卡时间并填写原因后提交。"},
    {"id": "swap-expire", "category": "swap", "title": "换班请求多久不处理会过期？", "keywords": ["换班", "过期", "多久", "48", "小时"], "answer": "换班请求 48 小时未处理会自动过期。"},
    {"id": "leave-proxy", "category": "leave", "title": "店长可以帮我代提交请假/换班吗？", "keywords": ["代提交", "店长", "管理员", "请假", "换班"], "answer": "可以。店长/管理员可以在管理端替员工发起换班或请假。"},
    {"id": "rule-sync", "category": "rule", "title": "数据会实时同步吗？断网了怎么办？", "keywords": ["同步", "断网", "离线", "实时"], "answer": "系统使用 Supabase 作为后端，数据会实时同步。断网时页面右上角会显示「离线」，恢复网络后自动重连。"},
]

THRESHOLD = 0.25  # 与 index.html 一致；dingtalk-faq 使用 0.28

def tokenize_chars(s):
    if not s:
        return []
    return [c for c in re.sub(r"[^\u4e00-\u9fa5a-z0-9]", "", str(s).lower()) if c]

def score_faq_match(query, entry):
    if not query:
        return 0
    q = tokenize_chars(query)
    if not q:
        return 0
    text = (entry.get("title") or "") + " " + " ".join(entry.get("keywords") or []) + " " + (entry.get("answer") or "")
    pool = set(tokenize_chars(text))
    hits = sum(1 for c in q if c in pool)
    score = hits / len(q)
    for kw in entry.get("keywords") or []:
        if kw.lower() in query.lower():
            score += 0.35
    if entry.get("title") and entry["title"].lower() in query.lower():
        score += 0.5
    return score

def ranked_faq_results(query, category="all"):
    lst = FAQ_ENTRIES[:]
    if category and category != "all":
        lst = [e for e in lst if e["category"] == category]
    if not query or not query.strip():
        return [(e, 0) for e in lst]
    q = query.strip()
    ranked = [(e, score_faq_match(q, e)) for e in lst]
    ranked = [(e, s) for e, s in ranked if s > THRESHOLD]
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked

CASES = [
    ("每天最多选几个班", ["pick-limit"]),
    ("怎么补卡", ["makeup-how"]),
    ("换班多久过期", ["swap-expire"]),
    ("打卡按钮灰色", ["punch-window"]),
    ("连班链", ["punch-chain"]),
    ("店长代提交请假", ["leave-proxy"]),
    ("断网了怎么办", ["rule-sync"]),
    ("xxxxxx", []),  # 应无命中
]

def main():
    all_pass = True
    for query, expected_ids in CASES:
        results = ranked_faq_results(query)
        top_ids = [e["id"] for e, _ in results]
        ok = top_ids[:len(expected_ids)] == expected_ids
        if not ok:
            all_pass = False
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] 查询: {query!r}")
        print(f"       期望: {expected_ids}")
        print(f"       实际前3: {top_ids[:3]}")
        print(f"       分数: {[(e['id'], round(s, 2)) for e, s in results[:3]]}")
        print()
    return 0 if all_pass else 1

if __name__ == "__main__":
    raise SystemExit(main())
