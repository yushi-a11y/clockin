#!/usr/bin/env python3
"""首卡定位功能测试。

功能定义：员工每天第一次打卡时附加当前位置（lat,lng,acc），
由「总开关 + 成员灰度开关」两层控制；定位获取永不阻塞打卡。

场景：
0. 纯逻辑单元检查：locEnabledFor / isFirstPunchOfDay / parseLoc / _opqSanitize
A. 授权定位 + 开关全开 → 首卡带 loc，坐标与授权坐标一致
B. 同日第二次打卡 → 不带 loc（首卡语义）
C. 成员灰度关闭 → 打卡不带 loc，员工页无定位提示
D. 总开关关闭 → 打卡不带 loc
E. 未授权定位（拒绝权限） → 打卡照常成功、不带 loc、不报错
"""
import asyncio
import datetime as dt
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = 'http://127.0.0.1:9876/index.html'
SHOTS = ROOT / 'test_outputs'
SHOTS.mkdir(exist_ok=True)

SID = 7          # 07:00-08:00 班次（容差 5 分钟）
GEO_LAT = 31.2304
GEO_LNG = 121.4737

TODAY = dt.date.today().isoformat()


def log(msg):
    print(f'[TEST] {msg}', flush=True)


async def take_screenshot(page, name):
    try:
        await page.screenshot(path=str(SHOTS / f'{name}.png'), full_page=False)
    except Exception as e:
        log(f'screenshot failed: {e}')


async def login_member(page, mid=1, pwd='123456'):
    await page.goto(BASE_URL, wait_until='domcontentloaded', timeout=20000)
    await page.wait_for_selector('#memberSelect', state='visible', timeout=15000)
    await page.evaluate("""() => {
        localStorage.removeItem('cb6');
        localStorage.removeItem('cb6exp');
        localStorage.removeItem('cb6auth');
        localStorage.removeItem('cb6authTs');
    }""")
    await page.reload()
    await page.wait_for_selector('#memberSelect', state='visible', timeout=15000)
    await page.select_option('#memberSelect', str(mid))
    await page.wait_for_selector('#pwdOverlay', state='visible', timeout=5000)
    await page.fill('#pwdInput', pwd)
    await page.click('#pwdOverlay button:has-text("验证")')
    await page.wait_for_selector('#empTabs', state='visible', timeout=8000)
    log(f'member {mid} logged in')


async def setup_scenario(page, loc_cfg, fake_hour, fake_minute, mid=1):
    """写入 locCfg / picks / 空 punches，拨好伪造时间，清掉限流与离线队列。"""
    await page.evaluate("""(args) => {
        const {locCfgVal, fakeHour, fakeMinute, mid} = args;
        locCfg = locCfgVal; sv('cloccfg6', locCfg);
        state = { punches: {}, shifts: DEF_SHIFTS };
        sv('cv6', state);
        const newPicks = {};
        newPicks[args.today] = {};
        newPicks[args.today][String(mid)] = [args.sid];
        picks = newPicks; sv('cp6', picks);
        fbPunches = [];
        localStorage.removeItem('copq6');
        try { delete _rateLimits['sens_punch_' + mid]; } catch (e) {}
        _locCache = null; _locPrefetching = false;
        // 阻止 syncServerTime 覆盖我们伪造的 skew（利用其 60s 缓存分支）
        _serverSyncedAt = Date.now();
        const target = new Date();
        target.setHours(fakeHour, fakeMinute, 0, 0);
        _serverSkew = target.getTime() - Date.now();
    }""", {'locCfgVal': loc_cfg, 'fakeHour': fake_hour, 'fakeMinute': fake_minute,
           'mid': mid, 'today': TODAY, 'sid': SID})
    # 渲染员工页：若开关生效会显示透明告知并触发静默预取
    await page.evaluate("async () => { await renderEmp(); }")
    await page.wait_for_timeout(400)


async def do_punch(page):
    await page.evaluate("async () => { await doPunch(); }")
    await page.wait_for_timeout(300)


async def day_punches(page):
    return await page.evaluate("(d) => state.punches[d] || []", TODAY)


async def main():
    failures = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # ====== Context A：授权定位 ======
        ctx_ok = await browser.new_context(
            permissions=['geolocation'],
            geolocation={'latitude': GEO_LAT, 'longitude': GEO_LNG, 'accuracy': 10})
        page = await ctx_ok.new_page()
        await page.route('**/*', lambda r: r.continue_()
                         if r.request.url.startswith('http://127.0.0.1:9876/')
                         else r.abort())
        await login_member(page, 1)

        # ---------- 场景 0：纯逻辑单元检查 ----------
        unit = await page.evaluate("""() => {
            const out = {};
            locCfg = {on: true, members: {1: true}};
            out.en_m1 = locEnabledFor(1);
            out.en_m2 = locEnabledFor(2);
            locCfg = {on: false, members: {1: true}};
            out.en_master_off = locEnabledFor(1);
            locCfg = {on: true, members: {}};
            out.en_member_off = locEnabledFor(1);
            // parseLoc
            out.pv = parseLoc({loc: '31.2304,121.4737,15'});
            out.pi_bad = parseLoc({loc: '999,121.4737,15'});
            out.pi_none = parseLoc({});
            out.pi_garbage = parseLoc({loc: 'abc'});
            // _opqSanitize 保留 loc
            const s = _opqSanitize({sid: 7, t: 's', time: '07:02', ts: 1, mid: 1,
                                      date: '2026-01-01', name: 'x', loc: '1,2,3', offline: true, sd: 'y'});
            out.san_loc = s.loc; out.san_offline = s.offline; out.san_sd = s.sd;
            // isFirstPunchOfDay
            state = { punches: {'2026-01-01': [{mid: 1, sid: 7, t: 's'}]}, shifts: DEF_SHIFTS };
            out.first_empty = isFirstPunchOfDay(2, '2026-01-01');
            out.first_taken = isFirstPunchOfDay(1, '2026-01-01');
            return out;
        }""")
        checks0 = [
            (unit.get('en_m1') is True, 'locEnabledFor 双开→true'),
            (unit.get('en_m2') is False, 'locEnabledFor 成员未开→false'),
            (unit.get('en_master_off') is False, 'locEnabledFor 总开关关→false'),
            (unit.get('en_member_off') is False, 'locEnabledFor 成员开关关→false'),
            (bool(unit.get('pv')) and abs(unit['pv']['lat'] - GEO_LAT) < 1e-4
             and unit['pv']['acc'] == 15, 'parseLoc 正常解析'),
            (unit.get('pi_bad') is None, 'parseLoc 非法纬度→null'),
            (unit.get('pi_none') is None, 'parseLoc 缺失→null'),
            (unit.get('pi_garbage') is None, 'parseLoc 垃圾串→null'),
            (unit.get('san_loc') == '1,2,3', '_opqSanitize 保留 loc'),
            (unit.get('san_offline') is None and unit.get('san_sd') is None,
             '_opqSanitize 仍剔除 offline/sd'),
            (unit.get('first_empty') is True, 'isFirstPunchOfDay 他人未打→true'),
            (unit.get('first_taken') is False, 'isFirstPunchOfDay 本人已打→false'),
        ]
        for ok, desc in checks0:
            if ok:
                log(f'PASS 0: {desc}')
            else:
                failures.append(f'0({desc})')
                log(f'FAIL 0: {desc} → {unit}')

        # ---------- 场景 A：开关全开 + 已授权 → 首卡带 loc ----------
        await setup_scenario(page, {'on': True, 'members': {'1': True}}, 7, 2)
        notice = await page.evaluate(
            "() => document.getElementById('empContent').textContent.includes('每天第一次打卡时会记录当前位置')")
        if notice:
            log('PASS A1: 开关开启时员工页显示定位透明告知')
        else:
            failures.append('A1(notice)')
            log('FAIL A1: 未显示定位透明告知')
            await take_screenshot(page, 'loc_fail_A1')
        await do_punch(page)
        recs = await day_punches(page)
        first = next((r for r in recs if r.get('t') == 's'), None)
        if first and isinstance(first.get('loc'), str) \
                and first['loc'].startswith(f'{GEO_LAT},{GEO_LNG}'):
            log(f'PASS A2: 首卡带定位 loc={first["loc"]}')
        else:
            failures.append('A2(first-loc)')
            log(f'FAIL A2: 首卡未带正确定位 recs={recs}')
            await take_screenshot(page, 'loc_fail_A2')

        # ---------- 场景 B：同日第二次打卡不带 loc ----------
        await page.evaluate("""() => {
            _serverSyncedAt = Date.now();
            const target = new Date(); target.setHours(7, 58, 0, 0);
            _serverSkew = target.getTime() - Date.now();
            try { delete _rateLimits['sens_punch_1']; } catch (e) {}
        }""")
        await do_punch(page)
        recs = await day_punches(page)
        end_rec = next((r for r in recs if r.get('t') == 'e'), None)
        loc_count = sum(1 for r in recs if r.get('loc'))
        if end_rec and 'loc' not in end_rec and loc_count == 1:
            log('PASS B: 同日第二张卡不带定位（全日仅首卡 1 条 loc）')
        else:
            failures.append('B(second-no-loc)')
            log(f'FAIL B: 第二张卡定位状态异常 recs={recs}')
            await take_screenshot(page, 'loc_fail_B')

        # ---------- 场景 C：成员灰度关闭 → 不带 loc、无告知 ----------
        await setup_scenario(page, {'on': True, 'members': {}}, 7, 2)
        notice = await page.evaluate(
            "() => document.getElementById('empContent').textContent.includes('每天第一次打卡时会记录当前位置')")
        await do_punch(page)
        recs = await day_punches(page)
        if not notice and recs and all('loc' not in r for r in recs):
            log('PASS C: 成员灰度关闭时无定位且无告知')
        else:
            failures.append('C(member-off)')
            log(f'FAIL C: notice={notice} recs={recs}')
            await take_screenshot(page, 'loc_fail_C')

        # ---------- 场景 D：总开关关闭 → 不带 loc ----------
        await setup_scenario(page, {'on': False, 'members': {'1': True}}, 7, 2)
        await do_punch(page)
        recs = await day_punches(page)
        if recs and all('loc' not in r for r in recs):
            log('PASS D: 总开关关闭时无定位')
        else:
            failures.append('D(master-off)')
            log(f'FAIL D: recs={recs}')
            await take_screenshot(page, 'loc_fail_D')

        await ctx_ok.close()

        # ====== 场景 E：拒绝定位授权 → 打卡照常成功、不带 loc ======
        ctx_deny = await browser.new_context()  # 不授权 geolocation → 请求被拒绝
        page2 = await ctx_deny.new_page()
        await page2.route('**/*', lambda r: r.continue_()
                          if r.request.url.startswith('http://127.0.0.1:9876/')
                          else r.abort())
        await login_member(page2, 1)
        await setup_scenario(page2, {'on': True, 'members': {'1': True}}, 7, 2)
        page_errors = []
        page2.on('pageerror', lambda e: page_errors.append(str(e)))
        await do_punch(page2)
        recs = await day_punches(page2)
        punched = bool(recs) and any(r.get('t') == 's' for r in recs)
        no_loc = recs and all('loc' not in r for r in recs)
        if punched and no_loc and not page_errors:
            log('PASS E: 拒绝授权时打卡成功、无定位、无 JS 错误')
        else:
            failures.append('E(denied)')
            log(f'FAIL E: punched={punched} recs={recs} errors={page_errors}')
            await take_screenshot(page2, 'loc_fail_E')
        await ctx_deny.close()

        await browser.close()

    if failures:
        log(f'LOC TESTS FAILED: {failures}')
        raise SystemExit(1)
    log('ALL LOC TESTS PASSED')


if __name__ == '__main__':
    asyncio.run(main())
