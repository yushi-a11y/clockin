#!/usr/bin/env python3
"""ClockIn v2026.08.05.12 自动化测试：
1. 跨天班次（23:00-00:00）：昨晚选班并上班打卡，凌晨 0 点后下班打卡按钮应正常出现并可打卡（Playwright 时钟模拟）
2. 绩效自动计算：出勤天数/工时/迟到/缺卡(补卡批准后扣减)/请假天数(仅统计已批准)
"""
import datetime as dt
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = 'http://127.0.0.1:8765/index.html'
SHOTS = ROOT / 'test_outputs'
SHOTS.mkdir(exist_ok=True)


def log(msg):
    print(f'[TEST] {msg}', flush=True)


async def block_external(page):
    async def _abort(route):
        await route.abort()
    for pat in ('**/fonts.googleapis.com/**', '**/fonts.gstatic.com/**', '**/*.supabase.co/**'):
        await page.route(pat, _abort)


async def shot(page, name):
    await page.screenshot(path=str(SHOTS / f'{name}.png'), full_page=True)
    log(f'screenshot: {name}')


async def wait_toast(page, text, timeout=10000):
    await page.wait_for_function(
        "() => { const t = document.getElementById('toast'); return !!t && t.textContent.includes('%s') }" % text,
        timeout=timeout)


async def goto_robust(page, url=BASE_URL, tries=3):
    for i in range(tries):
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=20000)
            return
        except Exception as e:
            if i == tries - 1:
                raise
            log(f'goto retry {i + 1}: {e}')


async def login_first_member(page):
    await goto_robust(page)
    await page.wait_for_selector('#memberSelect option:not([value=""])', state='attached', timeout=25000)
    mid = await page.evaluate('() => TEAM[0].id')
    await page.select_option('#memberSelect', str(mid))
    await page.wait_for_selector('#pwdOverlay', state='visible', timeout=10000)
    await page.fill('#pwdInput', '123456')
    await page.click('#pwdOverlay .btn.p')
    await page.wait_for_function('() => !!selectedMember', timeout=15000)
    log(f'logged in as member id={mid}')
    return mid


async def test_crossday_shift(page):
    log('--- 跨天班次 23:00-00:00 下班打卡测试 ---')
    # 阶段1：模拟昨天 23:02 —— 选班 23:00-00:00 并上班打卡
    real_now = dt.datetime.now()
    yesterday = real_now - dt.timedelta(days=1)
    t_2302 = yesterday.replace(hour=23, minute=2, second=0, microsecond=0)
    await page.clock.install(time=t_2302)
    log(f'clock installed at mocked {t_2302.isoformat()}')

    mid = await login_first_member(page)

    # 给该成员今天(模拟时间里的"今天"=实际的昨天)选 23:00-00:00 班次
    await page.evaluate("""() => {
        const d = tdStr();
        if (!picks[d]) picks[d] = {};
        picks[d][selectedMember.id] = [23];
        sv('cp6', picks);
    }""")
    await page.evaluate('() => renderEmp()')

    btn = page.locator('.punch-btn:not(.off)')
    await expect(btn).to_contain_text('上班打卡', timeout=10000)
    await shot(page, '12a_crossday_start_btn')
    await btn.click()
    await wait_toast(page, '打卡成功')
    start_rec = await page.evaluate("""() => {
        const d = tdStr();
        return (state.punches[d] || []).find(p => p.sid === 23 && p.t === 's') || null;
    }""")
    assert start_rec, '上班打卡记录未找到'
    pick_date = start_rec['date']
    log(f'上班打卡成功：{pick_date} {start_rec["time"]}')

    # 阶段2：快进 60 分钟 → 次日 00:02，验证下班打卡按钮出现
    await page.clock.fast_forward(60 * 60 * 1000)
    await page.evaluate('() => renderEmp()')
    today_mock = await page.evaluate('() => tdStr()')
    assert today_mock != pick_date, f'快进后日期未变化: {today_mock}'
    log(f'clock advanced to {today_mock} (after midnight)')

    # 回归核心：昨天 23-0 跨天班必须出现在"我的班次"，且下班打卡按钮可用
    shift_card = page.locator('#empContent .pc', has_text='23:00-00:00')
    await expect(shift_card).to_be_visible(timeout=8000)
    log('跨天班次卡片出现在今日视图')

    btn = page.locator('.punch-btn:not(.off)')
    await expect(btn).to_contain_text('下班打卡', timeout=8000)
    await shot(page, '12b_crossday_end_btn')
    log('下班打卡按钮正常显示（修复生效）')

    # 清除上一阶段残留的 toast 文本，避免误判
    await page.evaluate("() => { const t = document.getElementById('toast'); if (t) t.textContent = ''; }")
    await btn.click()
    try:
        await wait_toast(page, '打卡成功', timeout=8000)
    except Exception:
        toast_txt = await page.evaluate("() => (document.getElementById('toast') || {}).textContent || ''")
        log(f'未等到打卡成功 toast，当前 toast 文本: {toast_txt!r}')
        raise
    end_rec = await page.evaluate("""() => {
        const d = tdStr();
        return (state.punches[d] || []).find(p => p.sid === 23 && p.t === 'e') || null;
    }""")
    if not end_rec:
        diag = await page.evaluate("""() => ({
            today: tdStr(),
            keys: Object.keys(state.punches),
            recs: Object.keys(state.punches).map(k => [k, (state.punches[k] || []).map(p => p.sid + '_' + p.t + '@' + p.date)]),
            toast: (document.getElementById('toast') || {}).textContent || ''
        })""")
        log(f'诊断信息: {diag}')
    assert end_rec, '下班打卡记录未找到'
    assert end_rec['date'] == today_mock, f'下班卡日期应为 {today_mock}，实际 {end_rec["date"]}'
    log(f'下班打卡成功：{end_rec["date"]} {end_rec["time"]}')

    # 打完卡后：跨天班已完成，按钮应回到无班次状态
    await expect(page.locator('.punch-btn.off')).to_be_visible(timeout=8000)

    # 历史日期(昨天)视角下，该班次应判定为完成(ok)，而非缺卡
    st = await page.evaluate("""() => {
        const prev = ymd(addDays(parseYmd(tdStr()), -1));
        const sh = state.shifts.find(s => s.id === 23);
        const ps = getAllPunchesForMember(selectedMember.id, prev);
        return ss(sh, ps, prev, prev);
    }""")
    assert st['ov'] == 'ok', f'历史视角跨天班次状态应为 ok，实际 {st}'
    log('历史视角下跨天班次状态 = ok（不再误判缺卡）')

    both = await page.evaluate("""() => {
        const prev = ymd(addDays(parseYmd(tdStr()), -1));
        const ps = getAllPunchesForMember(selectedMember.id, prev);
        return { s: !!ps.find(p => p.sid === 23 && p.t === 's'),
                 e: !!ps.find(p => p.sid === 23 && p.t === 'e') };
    }""")
    assert both['s'] and both['e'], f'跨天查询应同时包含 D 与 D+1 的打卡: {both}'
    log('getAllPunchesForMember 正确合并了 D+1 的下班卡')
    return mid


async def test_stale_chain_fallback(page, mid):
    log('--- 过期连班链回退测试（12-13/13-14 链末班窗口已过，18-19 仍在窗口内）---')
    # 把时间拨到今天 18:02
    real_now = dt.datetime.now()
    t_1802 = real_now.replace(hour=18, minute=2, second=0, microsecond=0)
    await page.clock.install(time=t_1802)
    log(f'clock installed at mocked {t_1802.isoformat()}')

    # 重新登录（时钟已变，绑定可能过期）
    await goto_robust(page)
    await page.wait_for_selector('#memberSelect option:not([value=""])', state='attached', timeout=25000)
    await page.select_option('#memberSelect', str(mid))
    await page.wait_for_selector('#pwdOverlay', state='visible', timeout=10000)
    await page.fill('#pwdInput', '123456')
    await page.click('#pwdOverlay .btn.p')
    await page.wait_for_function('() => !!selectedMember', timeout=15000)

    today = await page.evaluate('() => tdStr()')
    # 构造选班：12-13 + 13-14（链A）+ 18-19 + 19-20（链B）
    setup = await page.evaluate("""() => {
        const mid = selectedMember.id;
        const name = selectedMember.name;
        const d = tdStr();
        // 清空今日选班和打卡，避免前序测试干扰
        picks[d] = { [mid]: [12, 13, 18, 19] };
        sv('cp6', picks);
        state.punches = {};
        sv('cv6', state);
        // 链A：12-13 上班 + 连班交接（12-13 下班 + 13-14 上班共用），但 13-14 下班未打
        const now = Date.now();
        const recs = [
            { sid: 12, t: 's', time: '12:00', ts: now, mid, date: d, name },
            { sid: 12, t: 'e', time: '13:00', ts: now, mid, date: d, name },  // 链交接：12-13 下班
            { sid: 13, t: 's', time: '13:00', ts: now, mid, date: d, name },  // 链交接：13-14 上班
            // 13-14 的下班卡故意不打 → 链A 末班窗口已过
        ];
        upd(s => { const p = { ...s.punches }; p[d] = recs; return { ...s, punches: p }; });
        return { d, recs: recs.length };
    }""")
    log(f'测试数据准备：today={setup["d"]}, 预置 {setup["recs"]} 条打卡记录')

    await page.evaluate('() => renderEmp()')

    # 核心断言：18-19 的上班打卡按钮必须出现（而不是"暂无可打卡时段"）
    btn = page.locator('.punch-btn:not(.off)')
    await expect(btn).to_contain_text('上班打卡', timeout=8000)
    btn_text = await btn.text_content()
    log(f'打卡按钮文本: {btn_text!r}')
    assert '18:00' in btn_text or '18' in btn_text, f'按钮应指向 18-19 班次，实际: {btn_text}'
    await shot(page, '12d_stale_chain_fallback')

    # 点击打卡，验证 18-19 上班卡成功写入
    await page.evaluate("() => { const t = document.getElementById('toast'); if (t) t.textContent = ''; }")
    await btn.click()
    await wait_toast(page, '打卡成功', timeout=8000)
    punch_ok = await page.evaluate("""() => {
        const d = tdStr();
        return !!(state.punches[d] || []).find(p => p.sid === 18 && p.t === 's');
    }""")
    assert punch_ok, '18-19 上班打卡记录未写入'
    log('18-19 上班打卡成功（过期链未阻塞后续班次）')


async def test_performance_metrics(page, mid):
    log('--- 绩效自动计算测试（请假天数 + 补卡扣减缺卡）---')
    # 独立 context 运行时先完成登录（原先依赖前序测试的登录态）
    if not await page.evaluate('() => !!document.getElementById("memberSelect")'):
        await login_first_member(page)
    elif not await page.evaluate('() => !!window.selectedMember'):
        await login_first_member(page)
    month_str = await page.evaluate('() => tdStr().slice(0, 7)')

    # 清理前序测试留下的数据，避免干扰
    await page.evaluate("""() => {
        const today = tdStr();
        // 清除今日选班和打卡
        if (picks[today]) delete picks[today];
        sv('cp6', picks);
        state.punches = {};
        sv('cv6', state);
        // 重置请假和补卡
        leaves.length = 0;
        svLeaves();
        makeups.length = 0;
        svMakeups();
        // 清除绩效记录
        performances.length = 0;
        sv('cperf6', performances);
    }""")
    log('已清理前序测试数据')

    # 构造跨天班次场景（昨天 23-00，上下班卡都打了）+ 4 号 10:00 班次
    setup = await page.evaluate("""(monthStr) => {
        const mid = selectedMember.id;
        const name = selectedMember.name;
        const today = tdStr();
        const yesterday = ymd(addDays(parseYmd(today), -1));
        // 昨天选 23-00 跨天班，上下班卡都打（昨天上班，今天下班）
        if (!picks[yesterday]) picks[yesterday] = {};
        picks[yesterday][mid] = [23];
        sv('cp6', picks);
        const now = Date.now();
        // 昨天 23:02 上班卡
        const startRec = { sid: 23, t: 's', time: '23:02', ts: now - 3600000, mid, date: yesterday, name };
        // 今天 00:02 下班卡
        const endRec = { sid: 23, t: 'e', time: '00:02', ts: now, mid, date: today, name };
        upd(s => { const p = { ...s.punches }; p[yesterday] = [startRec]; p[today] = [endRec]; return { ...s, punches: p }; });
        // 4 号选 10:00-11:00，只打上班卡且迟到 12 分钟
        const d2 = monthStr + '-04';
        if (!picks[d2]) picks[d2] = {};
        picks[d2][mid] = [10];
        sv('cp6', picks);
        const rec = { sid: 10, t: 's', time: '10:12', ts: Date.now(), mid, date: d2, name };
        upd(s => { const p = { ...s.punches }; p[d2] = [...(p[d2] || []), rec]; return { ...s, punches: p }; });
        // 请假：1 条已批准 + 1 条待审批（只应统计已批准）
        leaves.push({ id: 'lv_t1', mid, name, date: monthStr + '-04', sids: [10], reason: 'test', status: 'approved', ts: Date.now(), decidedTs: Date.now(), decidedBy: '管理员' });
        leaves.push({ id: 'lv_t2', mid, name, date: monthStr + '-05', sids: [], reason: 'test-pending', status: 'pending', ts: Date.now(), decidedTs: 0, decidedBy: '' });
        svLeaves();
        return { mid, name, yesterday, today };
    }""", month_str)
    log(f'测试数据准备完成：member={setup["mid"]}, month={month_str}, yesterday={setup["yesterday"]}')

    # 阶段A：补卡批准前 —— 8/4 班次已请假批准，不应计缺卡；10点班仅有上班卡且迟到
    m1 = await page.evaluate("""(monthStr) => calcMonthMetrics(selectedMember.id, monthStr)""", month_str)
    log(f'补卡前指标: {m1}')
    assert m1['workDays'] == 2, f'出勤天数应为 2（跨天班 + 10点班），实际 {m1["workDays"]}'
    assert float(m1['workHours']) == 2.0, f'工时应为 2.0，实际 {m1["workHours"]}'
    assert m1['lateCount'] == 1, f'迟到次数应为 1，实际 {m1["lateCount"]}'
    assert m1['missCount'] == 0, f'已请假批准的班次不应计缺卡，实际 {m1["missCount"]}'
    assert m1['leaveDays'] == 1, f'请假天数应为 1（仅已批准），实际 {m1["leaveDays"]}'

    # 阶段B：补卡批准（status=accepted）后 —— 缺卡应自动扣减为 0
    await page.evaluate("""(monthStr) => {
        const mid = selectedMember.id;
        const name = selectedMember.name;
        makeups.push({ id: 'mk_t1', mid, name, date: monthStr + '-04', punchDate: monthStr + '-04',
                       sid: 10, sname: '10:00-11:00', time: '11:00', t: 'e', reason: 'test',
                       status: 'accepted', ts: Date.now(), decidedTs: Date.now(), decidedBy: '管理员' });
        svMakeups();
    }""", month_str)
    m2 = await page.evaluate("""(monthStr) => calcMonthMetrics(selectedMember.id, monthStr)""", month_str)
    log(f'补卡批准后指标: {m2}')
    assert m2['missCount'] == 0, f'补卡批准后缺卡次数应为 0，实际 {m2["missCount"]}'
    assert m2['workDays'] == 2 and float(m2['workHours']) == 2.0, '补卡不应影响出勤/工时'

    # 阶段C：驳回状态的补卡不应扣减 —— 再造一个缺卡班次，配 rejected 补卡
    await page.evaluate("""(monthStr) => {
        const mid = selectedMember.id;
        const name = selectedMember.name;
        const d3 = monthStr + '-03';
        if (!picks[d3]) picks[d3] = {};
        picks[d3][mid] = [11];
        sv('cp6', picks);
        const rec = { sid: 11, t: 's', time: '11:00', ts: Date.now(), mid, date: d3, name };
        upd(s => { const p = { ...s.punches }; p[d3] = [...(p[d3] || []), rec]; return { ...s, punches: p }; });
        makeups.push({ id: 'mk_t2', mid, name, date: d3, punchDate: d3,
                       sid: 11, sname: '11:00-12:00', time: '12:00', t: 'e', reason: 'test',
                       status: 'rejected', ts: Date.now(), decidedTs: Date.now(), decidedBy: '管理员' });
        svMakeups();
    }""", month_str)
    m3 = await page.evaluate("""(monthStr) => calcMonthMetrics(selectedMember.id, monthStr)""", month_str)
    log(f'驳回补卡场景指标: {m3}')
    assert m3['missCount'] == 1, f'被驳回的补卡不应扣减缺卡，实际 {m3["missCount"]}'
    assert m3['workDays'] == 3, f'出勤天数应为 3，实际 {m3["workDays"]}'

    # 阶段D：员工端绩效页 UI 展示自动指标
    await page.evaluate("""(monthStr) => {
        performances.push({ id: 'perf_t1', month: monthStr, mid: selectedMember.id, name: selectedMember.name,
                            score: '0.95', remark: '', ts: Date.now(), updatedBy: 'test' });
        sv('cperf6', performances);
        empTab = 'performance';
    }""", month_str)
    await page.evaluate('() => renderEmp()')
    cells = await page.evaluate("""() => {
        const grid = document.querySelector('#empContent .chart-card div[style*="grid"]');
        if (!grid) return null;
        return [...grid.children].map(c => [c.children[1].textContent.trim(), c.children[0].textContent.trim()]);
    }""")
    assert cells, '绩效页未渲染指标卡片'
    shown = dict(cells)
    log(f'绩效页展示: {shown}')
    assert shown.get('出勤天数') == '3', f'UI 出勤天数应为 3，实际 {shown.get("出勤天数")}'
    assert shown.get('缺卡次数') == '1', f'UI 缺卡次数应为 1，实际 {shown.get("缺卡次数")}'
    assert shown.get('请假天数') == '1', f'UI 请假天数应为 1，实际 {shown.get("请假天数")}'
    await shot(page, '12c_performance_auto_metrics')
    log('员工端绩效页自动指标展示正确')


async def run_sub(browser, fn, *args):
    """每个子测试使用独立 context，规避同 context 二次导航偶发挂起"""
    context = await browser.new_context()
    page = await context.new_page()
    await block_external(page)
    try:
        return await fn(page, *args)
    finally:
        await context.close()


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            mid = await run_sub(browser, test_crossday_shift)
            await run_sub(browser, test_stale_chain_fallback, mid)
            await run_sub(browser, test_performance_metrics, mid)
            log('ALL TESTS PASSED')
        except Exception as e:
            log(f'TEST FAILED: {e}')
            raise
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(run())
