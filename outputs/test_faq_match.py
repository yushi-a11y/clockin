#!/usr/bin/env python3
# 模拟线上 help center 的 FAQ 匹配逻辑，验证搜索结果是否符合预期

import re
import sys


def tokenize_chars(s):
    if not s:
        return []
    return [c for c in re.sub(r'[^\u4e00-\u9fa5a-z0-9]', '', str(s).lower()) if c]


def score_faq_match(query, entry):
    if not query:
        return 0
    q = tokenize_chars(query)
    if not q:
        return 0
    text = (entry.get('title') or '') + ' ' + ' '.join(entry.get('keywords') or []) + ' ' + (entry.get('answer') or '')
    pool = set(tokenize_chars(text))
    hits = sum(1 for c in q if c in pool)
    score = hits / len(q)
    for kw in entry.get('keywords') or []:
        if query.lower() in kw.lower() or kw.lower() in query.lower():
            score += 0.35
    if query.lower() in (entry.get('title') or '').lower():
        score += 0.5
    return score


def ranked_faq_results(query, category, entries):
    result = entries[:]
    if category and category != 'all':
        result = [e for e in result if e.get('category') == category]
    if not query or not query.strip():
        return [{'entry': e, 'score': 0} for e in result]
    q = query.strip()
    ranked = [{'entry': e, 'score': score_faq_match(q, e)} for e in result]
    ranked = [x for x in ranked if x['score'] > 0.25]
    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked


FAQ_ENTRIES = [
    {'id': 'punch-window', 'category': 'punch', 'title': '为什么打卡按钮是灰色的/点不了？', 'keywords': ['打卡', '按钮', '灰色', '点不了', '不能打卡', '提前', '窗口'], 'answer': '每个班次只能在管理后台配置的「容忍窗口」内打卡。提前到达或过了窗口期，按钮都会变灰。请在自己的班次开始/结束前后规定时间内打卡。另外，只能对「今天」执行实际打卡，历史/未来日期仅用于预览。'},
    {'id': 'punch-remind', 'category': 'punch', 'title': '打卡提醒不弹出怎么办？', 'keywords': ['提醒', '通知', '不弹', '打卡提醒', '浏览器通知'], 'answer': '请先在浏览器地址栏左侧点击锁形/信息图标，允许本站发送通知；然后回到打卡页，打开「班次开始/结束前 5 分钟提醒我打卡」的开关。每个班次每天只会提醒一次。'},
    {'id': 'punch-history', 'category': 'punch', 'title': '可以补打今天之前的卡吗？', 'keywords': ['补卡', '昨天', '之前', '漏打', '历史'], 'answer': '不能直接在打卡页补打历史班次。如果已缺卡，请到「补卡」标签提交补卡申请，管理员审批通过后系统会自动写入一条打卡记录，缺卡状态会变为「已补」。'},
    {'id': 'pick-open', 'category': 'pick', 'title': '选班什么时候开放？', 'keywords': ['选班', '开放', '几点', '周五', '14:00', '开放时间'], 'answer': '默认每周五 14:00 开放下一周期的选班。管理员可在后台调整「开放星期」和「开放小时」。在开放前只能查看排班表，不能选择或修改。'},
    {'id': 'pick-lock', 'category': 'pick', 'title': '选班为什么被锁定/保存后改不了？', 'keywords': ['锁定', '保存', '改不了', '不能修改', '冻结'], 'answer': '原因通常有几种：1）管理员在后台锁定了选班；2）该天已经过去；3）你已经保存过该天的选班，保存后员工端自动锁定，只能换班或让管理员在后台修改。'},
    {'id': 'pick-limit', 'category': 'pick', 'title': '每天/每周最多能选几个班？', 'keywords': ['上限', '最多', '7', '49', '每天', '每周', '限制'], 'answer': '每人每天最多选 7 个时段，每周（按系统设置的周起始日计算）合计不超过 49 个时段。同一时段每人每天只能占 1 个。14:10 后的补位、换班、捡班同样受此限制。'},
    {'id': 'pick-freeze', 'category': 'pick', 'title': '每周五 14:05 和 14:10 会发生什么？', 'keywords': ['14:05', '14:10', '冻结', '清理', '补位'], 'answer': '每周五 14:05 系统会冻结全表并清理超额班次：如果某天选了超过 7 个班，超额部分会被清除。14:10 之后可以自由补位空余时段，但仍受每天 7 个、每周 49 个限制。'},
    {'id': 'pick-full', 'category': 'pick', 'title': '某个时段点不了/显示已满，为什么？', 'keywords': ['已满', '点不了', '时段', '满员', '人数上限'], 'answer': '管理员可能给该时段设置了人数上限，当已选人数达到上限后，其他员工就无法再选。你可以 14:10 后尝试捡班，或联系管理员调整上限。'},
    {'id': 'count-valid', 'category': 'count', 'title': '「有效合计」是怎么算的？', 'keywords': ['有效合计', '怎么算', '计算', '每日', '每周'], 'answer': '每日最多计 7 个有效班次，每周最多计 49 个有效班次。如果某天超过 7 个，只按 7 个计入；如果某周超过 49 个，只按 49 个计入。标红的单元格表示不足当周最低有效数。'},
    {'id': 'count-am-pm', 'category': 'count', 'title': '什么是早补和夜补？', 'keywords': ['早补', '夜补', '早晚补', '定义'], 'answer': '早补指选中特定早班时段（默认 07:00-08:00，时段 ID 7）的天数；夜补指选中特定夜班时段（默认次日 01:00-02:00，时段 ID 25）的天数。系统按实际选班数据自动统计，用于月度汇总。'},
    {'id': 'month-target', 'category': 'month', 'title': '月度页面的「达标」和「未达标」是什么意思？', 'keywords': ['达标', '未达标', '月度', '周有效', 'minValid'], 'answer': '当某周有效班次 ≥ 后台配置的「周最低有效」值（默认 30）时，显示为「达标」；否则显示「未达标」。这是判断本周出勤强度是否达标的依据。'},
    {'id': 'swap-how', 'category': 'swap', 'title': '怎么发起换班？', 'keywords': ['换班', '发起', '转让', '给别人'], 'answer': '进入「换班」标签，选择日期、要转出的班次、接收人，提交后对方会收到一条待确认请求。对方同意且双方都不超出每天 7 个/每周 49 个限制时，换班生效。'},
    {'id': 'swap-expire', 'category': 'swap', 'title': '换班请求多久不处理会过期？', 'keywords': ['换班', '过期', '多久', '48', '小时'], 'answer': '换班请求 48 小时未处理会自动过期。过期后班次仍归原持有人。'},
    {'id': 'swap-status', 'category': 'swap', 'title': '换班有哪些状态？', 'keywords': ['换班状态', 'pending', 'accepted', 'rejected', 'expired', 'proxy'], 'answer': '常见状态：pending（等待确认）、accepted（已同意）、rejected（已拒绝）、cancelled（已取消）、proxy_pending（代提交待本人确认）、expired（超过 48 小时未处理自动过期）、approved（管理员后台批准）。'},
    {'id': 'makeup-how', 'category': 'makeup', 'title': '怎么提交补卡？', 'keywords': ['补卡', '提交', '缺卡', '申请'], 'answer': '在「补卡」页选择缺卡日期、缺卡班次、实际打卡时间并填写原因后提交。只能对已经过去的班次发起补卡。提交后管理员会在「补卡审批」中处理，通过后缺卡状态变为「已补」。'},
    {'id': 'makeup-result', 'category': 'makeup', 'title': '补卡申请多久有结果？', 'keywords': ['补卡', '多久', '结果', '审批'], 'answer': '补卡需要管理员在管理端审批，没有固定时长。审批通过后员工端会实时更新，你可以在补卡页查看状态。'},
    {'id': 'leave-how', 'category': 'leave', 'title': '怎么请假？', 'keywords': ['请假', '提交', '申请'], 'answer': '在「请假」页选择请假日期、涉及班次、填写原因后提交。管理员审批通过后，该日相关班次显示为「已请假」，不计入有效出勤。'},
    {'id': 'leave-proxy', 'category': 'leave', 'title': '店长可以帮我代提交请假/换班吗？', 'keywords': ['代提交', '店长', '管理员', '请假', '换班'], 'answer': '可以。店长/管理员可以在管理端替员工发起换班或请假。代提交的申请仍需要走正常确认/审批流程（换班需本人确认，请假需管理员审批）。'},
    {'id': 'account-bind', 'category': 'account', 'title': '为什么每天要重新输密码/设备绑定会过期？', 'keywords': ['绑定', '过期', '密码', '每天', '设备'], 'answer': '为了账号安全，设备绑定默认在次日重置时间（默认 07:00）后自动过期，过期后需要重新输入密码验证。如果管理员执行了「强制下线」，绑定也会立即失效。'},
    {'id': 'account-pwd', 'category': 'account', 'title': '忘记密码/密码被锁怎么办？', 'keywords': ['密码', '忘记', '锁定', '输错', '5 次'], 'answer': '连续输错密码 5 次后账号会被锁定 30 秒。如果忘记密码，请联系管理员重置；重置后密码会恢复为默认初始密码 123456，登录后建议尽快修改。'},
    {'id': 'account-mobile', 'category': 'account', 'title': '为什么手机/平板打不开页面？', 'keywords': ['手机', '平板', '移动', '打不开', '电脑'], 'answer': '为了保证打卡和选班体验，系统禁止在手机、平板等移动设备/触屏小屏设备上访问。请使用电脑浏览器打开。'},
    {'id': 'rule-sync', 'category': 'rule', 'title': '数据会实时同步吗？断网了怎么办？', 'keywords': ['同步', '断网', '离线', '实时'], 'answer': '系统使用 Supabase 作为后端，数据会实时同步。断网时页面右上角会显示「离线」，恢复网络后自动重连。本地有缓存，刷新页面后会先从本地恢复，再与云端同步。'},
    {'id': 'rule-admin', 'category': 'rule', 'title': '管理端和小二端有什么区别？', 'keywords': ['管理端', '小二端', '后台', '员工端', '区别'], 'answer': '小二端（员工端）用于打卡、选班、申请换班/补卡/请假；管理端用于配置班次规则、审批补卡/请假、查看出勤概览和导出报表。只有管理员能登录管理端。'},
    {'id': 'punch-loc-when', 'category': 'punch', 'title': '打卡时会在哪些时候记录我的位置？', 'keywords': ['定位', '位置', '记录', '什么时候', '首卡', '末卡', '几次'], 'answer': '每天只记录两次：当天第一次打卡（上班卡）和最后一次打卡（下班卡）。除这两次外，工作期间、休息时、外出时都不会记录位置，系统也不会持续追踪你的行踪。'},
    {'id': 'punch-loc-slow', 'category': 'punch', 'title': '定位会不会很慢、影响打卡？', 'keywords': ['定位', '慢', '影响', '打卡', '超时', '等待'], 'answer': '不会。打卡时定位最多等待 2.5 秒，如果定位获取失败或超时会自动跳过，打卡照常成功，不会因此打不上卡。'},
    {'id': 'punch-loc-diff', 'category': 'punch', 'title': '首卡和末卡位置不一样会有问题吗？', 'keywords': ['首卡', '末卡', '位置', '不一样', '异地', '同地', '问题'], 'answer': '系统只负责如实记录两次位置并自动对比（同地/异地），结果仅管理员可见，用于考勤核对。上班和下班位置不同是正常情况，不会自动判定违规，最终以管理员核对为准。'},
    {'id': 'punch-loc-deny', 'category': 'punch', 'title': '不想给定位权限 / 拒绝定位会怎样？', 'keywords': ['定位', '权限', '拒绝', '未授权', '禁止', '不允许'], 'answer': '打卡本身不受影响，但该条记录会标记为「未授权」，管理员可在考勤表中看到提醒，你的页面也会持续显示红色提示直到重新授权。定位是公司考勤要求，请在浏览器弹窗时选择「允许」；如已拒绝，请到浏览器设置 → 网站设置 → 位置信息中重新允许本网站后刷新页面。'},
    {'id': 'punch-loc-fake', 'category': 'punch', 'title': '有人用虚拟定位 / 伪造 GPS 怎么办？', 'keywords': ['虚拟定位', '伪造', 'GPS', 'Fake GPS', '作弊', '虚假'], 'answer': '网页端无法识别员工电脑是否安装了虚拟定位或 Fake GPS 软件。浏览器只返回坐标本身，无法验证坐标的真实来源。系统能做的只是把定位精度、首末位置差异、异常距离等展示给管理员，由管理员结合考勤制度和实际情况判断。如果怀疑作弊，可按公司规定处理。'},
    {'id': 'punch-loc-map', 'category': 'punch', 'title': '为什么点开的地图不是员工实时位置？', 'keywords': ['地图', '实时', '链接', '位置', '打卡时', '现在'], 'answer': '地图链接打开的是这条打卡记录被记录时的位置（打卡瞬间的经纬度），不是实时追踪。系统只在首卡和末卡两个时刻各取一次位置，取完即停，不会持续定位。因此即使员工现在已经离开，地图显示的仍是当时的位置。'}
]


cases = [
    {'q': '每天最多选几个班', 'expect': '每天/每周最多能选几个班？'},
    {'q': '怎么补卡', 'expect': '怎么提交补卡？'},
    {'q': '换班过期', 'expect': '换班请求多久不处理会过期？'},
    {'q': 'zzz', 'expect': None},
    {'q': '手机打不开', 'expect': '为什么手机/平板打不开页面？'},
    {'q': '什么时候记录位置', 'expect': '打卡时会在哪些时候记录我的位置？'},
    {'q': '定位慢吗', 'expect': '定位会不会很慢、影响打卡？'},
    {'q': '首末位置不一样', 'expect': '首卡和末卡位置不一样会有问题吗？'},
    {'q': '拒绝定位权限', 'expect': '不想给定位权限 / 拒绝定位会怎样？'},
    {'q': '虚拟定位怎么办', 'expect': '有人用虚拟定位 / 伪造 GPS 怎么办？'},
    {'q': '地图为什么不是实时位置', 'expect': '为什么点开的地图不是员工实时位置？'},
]

pass_flag = True
for case in cases:
    results = ranked_faq_results(case['q'], 'all', FAQ_ENTRIES)
    top = results[0]['entry']['title'] if results else None
    ok = (case['expect'] is None and not results) or (top == case['expect'])
    status = '[PASS]' if ok else '[FAIL]'
    print(f"{status} \"{case['q']}\" → {top or '(no results)'}  expected: {case['expect'] or '(no results)'}")
    if not ok:
        pass_flag = False

sys.exit(0 if pass_flag else 1)
