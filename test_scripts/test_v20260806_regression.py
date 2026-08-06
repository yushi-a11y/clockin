#!/usr/bin/env python3
"""ClockIn v2026.08.05.15 全功能回归测试：
覆盖员工登录、正常打卡、迟到检测、缺卡显示、补卡申请/审批、请假申请/审批、绩效录入。
测试在本地隔离环境运行，不依赖外部 CDN/Supabase。
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
    blocked_hosts = {'fonts.googleapis.com', 'fonts.gstatic.com'}

    async def handle_route(route):
        url = route.request.url
        if any(h in url for h in blocked_hosts) or 'supabase' in url:
            await route.abort()
        else:
            await route.continue_()

    await page.route('**/*', handle_route)


async def shot(page, name):
    try:
        await page.screenshot(path=str(SHOTS / f'{name}.png'), full_page=True)
        log(f'screenshot: {name}')
    except Exception as e:
        log(f'screenshot failed for {name}: {e}')
        try:
            await page.screenshot(path=str(SHOTS / f'{name}.png'))
            log(f'screenshot viewport fallback: {name}')
        except Exception as e2:
            log(f'screenshot fallback failed: {e2}')


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


async def clear_state(page):
    await goto_robust(page)
    await page.evaluate("""() => {
        localStorage.clear();
        state = { punches: {}, shifts: DEF_SHIFTS };
        picks = {};
        makeups = [];
        leaves = [];
        performances = [];
        TEAM = JSON.parse(JSON.stringify(DEF_TEAM));
        selectedMember = null;
        sv('cv6', state);
        sv('cp6', picks);
        sv('cmkup6', makeups);
        sv('cleave6', leaves);
        sv('cperf6', performances);
        sv('ct6', TEAM);
        localStorage.removeItem('cb6');
        localStorage.removeItem('cb6exp');
        localStorage.removeItem('cb6auth');
        localStorage.removeItem('cb6authTs');
        localStorage.removeItem('cs6');
        localStorage.removeItem('cs6tk');
    }""")


async def login_member(page, mid):
    # 假设页面已由 clear_state 或前置步骤加载；必要时刷新而不是重新导航，避免二次 goto 偶发挂起
    if not await page.evaluate('() => !!document.getElementById("memberSelect")'):
        await goto_robust(page)
    await page.wait_for_selector('#memberSelect option:not([value=""])', state='attached', timeout=25000)
    await page.select_option('#memberSelect', str(mid))
    await page.wait_for_selector('#pwdOverlay', state='visible', timeout=10000)
    await page.fill('#pwdInput', '123456')
    await page.click('#pwdOverlay .btn.p')
    await page.wait_for_function('() => !!selectedMember', timeout=15000)
    name = await page.evaluate('() => selectedMember.name')
    log(f'logged in as member {mid} ({name})')


async def login_admin(page):
    # 员工视角下"管理后台"按钮隐藏，直接调用内部函数打开登录弹窗
    await page.evaluate('() => _openAdminLogin()')
    await page.wait_for_selector('#loginOverlay.show', state='visible', timeout=10000)
    await page.fill('#loginInput', 'admin123')
    await page.click('#loginOverlay .login-btn')
    await page.wait_for_function("""() => {
        const exp = localStorage.getItem('cs6');
        return !!exp && +exp > Date.now();
    }""", timeout=10000)
    log('logged in as admin')


async def set_mock_clock(page, t):
    await page.clock.install(time=t)
    log(f'clock installed at {t.isoformat()}')


async def seed_picks(page, date_str, mid, sids):
    await page.evaluate("""(args) => {
        const [ds, mid, sids] = args;
        if (!picks[ds]) picks[ds] = {};
        picks[ds][mid] = sids.slice();
        sv('cp6', picks);
    }""", [date_str, mid, sids])


async def today_str(page):
    return await page.evaluate('() => tdStr()')


async def test_normal_and_late_punch(page):
    log('--- 正常打卡 + 迟到检测测试 ---')
    real_now = dt.datetime.now()
    t_0902 = real_now.replace(hour=9, minute=2, second=0, microsecond=0)
    await set_mock_clock(page, t_0902)
    await clear_state(page)
    mid = 1
    today = await today_str(page)
    await seed_picks(page, today, mid, [9, 12])  # 09:00-10:00, 12:00-13:00（不连班）
    await login_member(page, mid)
    await page.evaluate('() => renderEmp()')

    # 上班打卡按钮应为第一个班次 09:00-10:00
    btn = page.locator('.punch-btn:not(.off)')
    await expect(btn).to_contain_text('上班打卡', timeout=10000)
    await shot(page, 'reg_a_start_btn')
    await btn.click()
    await wait_toast(page, '打卡成功')
    log('09:02 上班打卡成功')

    # 验证状态：上班卡已打，下班卡未打
    st = await page.evaluate("""() => {
        const sh = state.shifts.find(s => s.id === 9);
        const ps = getAllPunchesForMember(selectedMember.id, tdStr());
        return ss(sh, ps, tdStr(), tdStr());
    }""")
    assert st['sp'], f'上班卡记录不存在: {st}'
    assert not st['ep'], f'下班卡不应存在: {st}'
    assert st['ss'] in ('ok', 'late'), f'上班状态异常: {st}'
    log('09:00 班次上班卡状态正确')

    # 下班打卡：10:02 完成 09:00-10:00 班次
    await page.clock.install(time=real_now.replace(hour=10, minute=2, second=0, microsecond=0))
    await page.evaluate('() => renderEmp()')
    btn = page.locator('.punch-btn:not(.off)')
    await expect(btn).to_contain_text('下班打卡', timeout=10000)
    await shot(page, 'reg_b_end_btn')
    await btn.click()
    await wait_toast(page, '打卡成功')

    st = await page.evaluate("""() => {
        const sh = state.shifts.find(s => s.id === 9);
        const ps = getAllPunchesForMember(selectedMember.id, tdStr());
        return ss(sh, ps, tdStr(), tdStr());
    }""")
    assert st['ov'] == 'ok', f'下班打卡后状态应为 ok，实际 {st}'
    log('09:00-10:00 班次完成')

    # 迟到检测：对 12:00-13:00 班次直接注入一条 12:10 的上班卡（超出 5 分钟容忍）
    await page.evaluate("""() => {
        const d = tdStr();
        if (!state.punches[d]) state.punches[d] = [];
        state.punches[d].push({ sid: 12, t: 's', time: '12:10', ts: Date.now(), mid: selectedMember.id, date: d, name: selectedMember.name });
        sv('cv6', state);
    }""")
    await page.clock.install(time=real_now.replace(hour=12, minute=15, second=0, microsecond=0))
    await page.evaluate('() => renderEmp()')
    st = await page.evaluate("""() => {
        const sh = state.shifts.find(s => s.id === 12);
        const ps = getAllPunchesForMember(selectedMember.id, tdStr());
        return ss(sh, ps, tdStr(), tdStr());
    }""")
    assert st['ss'] == 'late', f'12:10 上班卡应判定为迟到，实际 {st}'
    assert st['ov'] == 'warn', f'整体状态应为 warn，实际 {st}'
    log('迟到检测正确')
    await shot(page, 'reg_c_late_status')

    # 完成 12:00-13:00 迟到班次的下班卡
    await page.clock.install(time=real_now.replace(hour=13, minute=2, second=0, microsecond=0))
    await page.evaluate('() => renderEmp()')
    btn = page.locator('.punch-btn:not(.off)')
    await expect(btn).to_contain_text('下班打卡', timeout=10000)
    await btn.click()
    await wait_toast(page, '打卡成功')
    st = await page.evaluate("""() => {
        const sh = state.shifts.find(s => s.id === 12);
        const ps = getAllPunchesForMember(selectedMember.id, tdStr());
        return ss(sh, ps, tdStr(), tdStr());
    }""")
    assert st['ss'] == 'late' and st['es'] == 'ok', f'迟到班次下班卡后状态异常: {st}'
    assert st['ov'] == 'warn', f'迟到但下班正常应整体 warn，实际 {st}'
    log('12:00-13:00 迟到班次完成，整体状态为 warn')


async def test_makeup_flow(page):
    log('--- 补卡申请 + 管理员审批测试 ---')
    real_now = dt.datetime.now()
    t_1200 = real_now.replace(hour=12, minute=0, second=0, microsecond=0)
    await set_mock_clock(page, t_1200)
    await clear_state(page)
    mid = 1
    today = await today_str(page)
    yesterday = (dt.date.fromisoformat(today) - dt.timedelta(days=1)).isoformat()
    await seed_picks(page, yesterday, mid, [11])  # 昨日 11:00-12:00 缺卡
    await login_member(page, mid)

    # 进入补卡标签
    await page.click('#tab-makeup')
    await page.wait_for_timeout(300)
    await shot(page, 'reg_d_makeup_form')

    # 选择日期
    await page.select_option('#empContent .swap-sel:nth-of-type(1)', yesterday)
    await page.wait_for_timeout(300)
    # 选择班次
    await page.select_option('#empContent .swap-sel:nth-of-type(2)', '11')
    await page.wait_for_timeout(300)
    # 填写时间
    time_input = page.locator('#empContent input[type="time"]')
    await time_input.fill('11:05')
    # 提交
    await page.click('#empContent .btn.p')
    await wait_toast(page, '补卡申请已提交')
    log('补卡申请提交成功')

    # 验证 makeups 记录
    makeup = await page.evaluate("""() => {
        return JSON.parse(localStorage.getItem('cmkup6') || '[]').find(m => m.mid === selectedMember.id && m.sid === 11);
    }""")
    assert makeup, 'localStorage 中未找到补卡记录'
    assert makeup['status'] == 'pending'
    log(f'补卡记录 pending: {makeup["id"]}')

    # 管理员登录并审批
    await login_admin(page)
    await page.evaluate('() => switchPanel("makeup")')
    await page.wait_for_selector('#makeupAdminList table', state='visible', timeout=10000)
    await shot(page, 'reg_e_makeup_admin')

    # 通过第一个待审批。注意：筛选 Tab “已通过”也包含子串“通过”，
    # 必须将选择器限定在 table 内，否则会误点筛选 Tab
    await page.click('#makeupAdminList table button:has-text("通过")')
    # 等待审批完成：toast 含“已批准”（在线/离线两种文案均覆盖）
    await wait_toast(page, '已批准')
    await page.wait_for_function("""() => {
        const arr = JSON.parse(localStorage.getItem('cmkup6') || '[]');
        return arr.some(m => m.mid === 1 && m.sid === 11 && m.status === 'accepted');
    }""", timeout=10000)

    # 验证 punches 中已写入补卡记录
    rec = await page.evaluate("""() => {
        const d = JSON.parse(localStorage.getItem('cmkup6') || '[]').find(m => m.mid === 1 && m.sid === 11);
        const pd = d ? (d.punchDate || d.date) : '';
        return { pd, recs: (state.punches[pd] || []).filter(p => p.sid === 11 && p.mid === 1) };
    }""")
    if not rec['recs']:
        diag = await page.evaluate("""() => ({
            toast: (document.getElementById('toast') || {}).textContent || '',
            status: (JSON.parse(localStorage.getItem('cmkup6') || '[]').find(m => m.mid === 1 && m.sid === 11) || {}).status,
            punchKeys: Object.keys(state.punches)
        })""")
        log(f'补卡写入诊断: {diag}')
    assert rec['recs'], f'补卡批准后 punches 中未写入记录: {rec}'
    assert any(r.get('makeup') for r in rec['recs']), '补卡记录未标记 makeup=true'
    log('补卡审批通过且打卡记录已写入')

    # 回到员工端查看状态
    await page.evaluate('() => switchPage("emp")')
    await page.click('#tab-makeup')
    await page.wait_for_timeout(300)
    await shot(page, 'reg_f_makeup_accepted')
    status_text = await page.inner_text('#empContent')
    assert '已通过' in status_text, '员工端未显示补卡已通过'


async def test_leave_flow(page):
    log('--- 请假申请 + 管理员审批测试 ---')
    real_now = dt.datetime.now()
    t_1200 = real_now.replace(hour=12, minute=0, second=0, microsecond=0)
    await set_mock_clock(page, t_1200)
    await clear_state(page)
    mid = 1
    today = await today_str(page)
    tomorrow = (dt.date.fromisoformat(today) + dt.timedelta(days=1)).isoformat()
    await seed_picks(page, tomorrow, mid, [9, 10])  # 明天 09:00-10:00, 10:00-11:00
    await login_member(page, mid)

    await page.click('#tab-leave')
    await page.wait_for_timeout(300)
    await shot(page, 'reg_g_leave_form')

    await page.select_option('#empContent .swap-sel:nth-of-type(1)', tomorrow)
    await page.fill('#empContent textarea', '家中有事')
    await page.click('#empContent .btn.p')
    await wait_toast(page, '请假申请已提交')
    log('请假申请提交成功')

    leave = await page.evaluate("""() => {
        return JSON.parse(localStorage.getItem('cleave6') || '[]').find(l => l.mid === selectedMember.id && l.date === '%s');
    }""" % tomorrow)
    assert leave, 'localStorage 中未找到请假记录'
    assert leave['status'] == 'pending'

    # 管理员审批
    await login_admin(page)
    await page.evaluate('() => switchPanel("leave")')
    await page.wait_for_selector('#leaveAdminList table', state='visible', timeout=10000)
    await shot(page, 'reg_h_leave_admin')

    # 同上：筛选 Tab “已批准”包含子串“批准”，需限定在 table 内
    await page.click('#leaveAdminList table button:has-text("批准")')
    await wait_toast(page, '已批准请假')

    # 验证 picks 中已移除
    removed = await page.evaluate("""() => {
        const d = '%s';
        const arr = (picks[d] || {})[1] || [];
        return arr.length === 0;
    }""" % tomorrow)
    assert removed, '请假批准后班次未移除'
    log('请假审批通过且班次已移除')


async def test_performance_crud(page):
    log('--- 绩效录入 + 员工查看测试 ---')
    real_now = dt.datetime.now()
    t_1200 = real_now.replace(hour=12, minute=0, second=0, microsecond=0)
    await set_mock_clock(page, t_1200)
    await clear_state(page)
    await login_admin(page)

    await page.evaluate('() => switchPanel("performance")')
    await page.wait_for_selector('#performanceFormBox', state='visible', timeout=10000)

    month = real_now.strftime('%Y-%m')
    # 直接通过内部函数填充表单（perfForm 初始 month 为空，必须走 setPerfMonth 才能通过保存校验）
    await page.evaluate("""(month) => {
        setPerfMonth(month);
        setPerfMid('1');
        setPerfField('workDays', '22');
        setPerfField('workHours', '160');
        setPerfField('score', '95');
    }""", month)
    # 表单内有两个 .btn.p（开始导入/保存），精确点"保存"
    await page.click('#performanceFormBox button:has-text("保存")')
    await wait_toast(page, '绩效记录已保存')
    log('绩效记录保存成功')

    # 员工端查看
    await page.evaluate('() => switchPage("emp")')
    await page.wait_for_selector('#memberSelect option:not([value=""])', state='attached', timeout=25000)
    await login_member(page, 1)
    await page.click('#tab-performance')
    await page.wait_for_timeout(300)
    await shot(page, 'reg_i_performance_view')
    perf_text = await page.inner_text('#empContent')
    assert '95' in perf_text, '员工端未显示绩效评分 95'
    log('员工端绩效查看正确')


async def run_test(browser, name, test_fn):
    context = await browser.new_context()
    page = await context.new_page()
    page.on('pageerror', lambda err: log(f'{name} PAGEERROR: {err}'))
    await block_external(page)
    page.on('dialog', lambda dialog: asyncio.create_task(dialog.accept()))
    try:
        await test_fn(page)
        log(f'{name} PASSED')
    except Exception as e:
        await shot(page, f'99_{name.lower()}_error')
        log(f'{name} FAILED: {e}')
        raise
    finally:
        await context.close()


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            await run_test(browser, 'NORMAL_LATE_PUNCH', test_normal_and_late_punch)
            await run_test(browser, 'MAKEUP_FLOW', test_makeup_flow)
            await run_test(browser, 'LEAVE_FLOW', test_leave_flow)
            await run_test(browser, 'PERFORMANCE_CRUD', test_performance_crud)
            log('ALL REGRESSION TESTS PASSED')
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(run())
