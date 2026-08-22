#!/usr/bin/env python3
"""验证打卡提醒在「同一班次连续两天排班」时被错误抑制的问题。

背景（用户真实反馈）：开启了"班次开始/结束前 5 分钟提醒我打卡"，但不提醒。
疑似原因：checkReminders 用 `p.sid===sh.id && p.t==='s'/'e'` 裸匹配打卡，
而 getAllPunchesForMember 会合并 D-1/D/D+1 三天的打卡记录。
同一班次昨天也排了且已打卡时，昨天的卡会把今天的提醒误判为"已打过"而吞掉。
正确做法应使用班次实例匹配 instPunch(list, sh, sd, t)。

场景：
A. sid23(23:00-00:00,跨天) 昨天+今天都排了，昨天实例已完成打卡。
   模拟现在=今天 22:57（开始前3分钟）→ 应提醒"即将开始上班"。
B. 对照组：sid23 只有今天排、无任何打卡，22:57 → 应提醒（验证提醒机制本身可用）。
C. 今天实例已打上班卡，昨天实例已完成；模拟现在=今天 23:57（结束前3分钟）
   → 应提醒"即将下班"。
D. 反例：今天实例两张卡都打了 → 22:57 不应有任何提醒。
"""
import asyncio
import datetime as dt
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = 'http://127.0.0.1:9876/index.html'
SHOTS = ROOT / 'test_outputs'
SHOTS.mkdir(exist_ok=True)

SID = 23  # 23:00-00:00 跨天班次


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


async def setup_scenario(page, picks_by_day, punches_by_day, fake_hour, fake_minute):
    """写入 picks / punches，开启提醒，并把服务器时间拨到 fake_hour:fake_minute。"""
    await page.evaluate("""(args) => {
        const {newPicks, newPunches, fakeHour, fakeMinute} = args;
        // 清理旧提醒日志，保证断言干净
        localStorage.removeItem('clockin_reminder_log');
        localStorage.setItem('clockin_reminder', '1');
        state = { punches: newPunches, shifts: DEF_SHIFTS };
        sv('cv6', state);
        picks = newPicks;
        sv('cp6', picks);
        fbPunches = [];
        // 阻止 syncServerTime 覆盖我们伪造的 skew（利用其 60s 缓存分支）
        _serverSyncedAt = Date.now();
        const target = new Date();
        target.setHours(fakeHour, fakeMinute, 0, 0);
        _serverSkew = target.getTime() - Date.now();
        stopReminderTimer();  // 手动驱动 checkReminders，避免 60s 定时器干扰
    }""", {'newPicks': picks_by_day, 'newPunches': punches_by_day,
           'fakeHour': fake_hour, 'fakeMinute': fake_minute})


async def run_check(page):
    await page.evaluate("async () => { await checkReminders(); }")
    return await page.evaluate(
        "() => JSON.parse(localStorage.getItem('clockin_reminder_log')||'{}')")


def dstr(offset):
    return (dt.date.today() + dt.timedelta(days=offset)).isoformat()


def ts_of(date_str, hh, mm):
    d = dt.date.fromisoformat(date_str)
    return int(dt.datetime(d.year, d.month, d.day, hh, mm).timestamp() * 1000)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await (await browser.new_context()).new_page()
        # 只允许本地资源，避免外部 CDN 拖慢测试
        await page.route('**/*', lambda r: r.continue_()
                         if r.request.url.startswith('http://127.0.0.1:9876/')
                         else r.abort())
        await login_member(page)

        yest, today = dstr(-1), dstr(0)
        failures = []

        # ---------- 场景 B（对照组）：仅今天排班、无打卡 → 开始提醒应触发 ----------
        await setup_scenario(page, {today: {'1': [SID]}}, {}, 22, 57)
        logreminded = await run_check(page)
        key = f'{today}_{SID}_s'
        if key in logreminded:
            log('PASS B: 无连续排班时开始提醒正常触发')
        else:
            failures.append('B')
            log(f'FAIL B: 对照组开始提醒未触发 log={logreminded}')
            await take_screenshot(page, 'reminder_fail_B')

        # ---------- 场景 A（核心回归）：昨天同班次已打卡 → 今天开始提醒仍应触发 ----------
        picks = {yest: {'1': [SID]}, today: {'1': [SID]}}
        punches = {
            yest: [{'sid': SID, 't': 's', 'time': '23:00', 'ts': ts_of(yest, 23, 0),
                    'mid': 1, 'date': yest, 'name': '133122', 'sd': yest}],
            today: [{'sid': SID, 't': 'e', 'time': '00:00', 'ts': ts_of(today, 0, 0),
                     'mid': 1, 'date': today, 'name': '133122', 'sd': yest}],
        }
        await setup_scenario(page, picks, punches, 22, 57)
        logreminded = await run_check(page)
        if key in logreminded:
            log('PASS A: 连续两天排同一班次，今天的开始提醒不再被昨天的卡抑制')
        else:
            failures.append('A')
            log(f'FAIL A: 今天的开始提醒被昨天同班次打卡错误抑制 log={logreminded}')
            await take_screenshot(page, 'reminder_fail_A')

        # ---------- 场景 C：结束提醒同样不应被昨天的下班卡抑制 ----------
        punches[today].append({'sid': SID, 't': 's', 'time': '23:00',
                                 'ts': ts_of(today, 23, 0), 'mid': 1,
                                 'date': today, 'name': '133122', 'sd': today})
        await setup_scenario(page, picks, punches, 23, 57)
        logreminded = await run_check(page)
        ekey = f'{today}_{SID}_e'
        if ekey in logreminded:
            log('PASS C: 连续两天排同一班次，今天的结束提醒不再被昨天的卡抑制')
        else:
            failures.append('C')
            log(f'FAIL C: 今天的结束提醒被昨天同班次打卡错误抑制 log={logreminded}')
            await take_screenshot(page, 'reminder_fail_C')

        # ---------- 场景 D（反例）：今天两张卡都打了 → 不应提醒 ----------
        punches[today].append({'sid': SID, 't': 'e', 'time': '00:00',
                                 'ts': ts_of(dstr(1), 0, 0), 'mid': 1,
                                 'date': dstr(1), 'name': '133122', 'sd': today})
        await setup_scenario(page, picks, punches, 22, 57)
        logreminded = await run_check(page)
        if not logreminded:
            log('PASS D: 已全部打卡时无误报提醒')
        else:
            failures.append('D')
            log(f'FAIL D: 已打卡仍误报提醒 log={logreminded}')
            await take_screenshot(page, 'reminder_fail_D')

        await browser.close()
        if failures:
            log(f'REMINDER TESTS FAILED: {failures}')
            raise SystemExit(1)
        log('ALL REMINDER TESTS PASSED')


if __name__ == '__main__':
    asyncio.run(main())
