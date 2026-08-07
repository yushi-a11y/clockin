#!/usr/bin/env python3
"""高保真复现用户上报的跨天问题（连续多天同排班）。

用户当日班次：0-1(24) 1-2(25) 11-12(11) 12-13(12) 13-14(13) 22-23(22) 23-0(23)
连续四天同样排班（8/5 ~ 8/8）。

两个变体：
  A) 23-0 的下班卡在 23:58 打（记录落在当天）
  B) 23-0 的下班卡在 00:00 打（记录落在次日）—— 怀疑这是"污染次日同 id 班次"的根因
"""
import datetime as dt
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE_URL = 'http://127.0.0.1:8765/index.html'
SIDS = [24, 25, 11, 12, 13, 22, 23]
DATES = ['2026-08-05', '2026-08-06', '2026-08-07', '2026-08-08']
MID = 1


def log(msg):
    print(msg, flush=True)


async def block_external(page):
    async def handle(route):
        url = route.request.url
        if 'fonts.googleapis.com' in url or 'fonts.gstatic.com' in url or 'supabase' in url:
            await route.abort()
        else:
            await route.continue_()
    await page.route('**/*', handle)


async def goto_robust(page, tries=3):
    for i in range(tries):
        try:
            await page.goto(BASE_URL, wait_until='domcontentloaded', timeout=20000)
            return
        except Exception as e:
            if i == tries - 1:
                raise
            log(f'goto retry {i+1}: {e}')


async def do_login(page):
    await page.evaluate("""() => {
        ['cb6','cb6exp','cb6auth','cb6authTs'].forEach(k => localStorage.removeItem(k));
        selectedMember = null; claims = {};
    }""")
    await page.evaluate('() => renderEmp()')
    await page.wait_for_selector('#memberSelect option:not([value=""])', state='attached', timeout=25000)
    await page.select_option('#memberSelect', str(MID))
    await page.wait_for_selector('#pwdOverlay', state='visible', timeout=10000)
    await page.fill('#pwdInput', '123456')
    await page.click('#pwdOverlay .btn.p')
    await page.wait_for_function('() => !!selectedMember', timeout=15000)


async def setup(page):
    await goto_robust(page)
    await page.evaluate("""(a) => {
        const [dates, sids, mid] = a;
        localStorage.clear();
        state = { punches: {}, shifts: DEF_SHIFTS };
        picks = {};
        dates.forEach(d => { picks[d] = {}; picks[d][mid] = sids.slice(); });
        makeups = []; leaves = []; performances = [];
        TEAM = JSON.parse(JSON.stringify(DEF_TEAM));
        selectedMember = null;
        sv('cv6', state); sv('cp6', picks); sv('cmkup6', makeups);
        sv('cleave6', leaves); sv('cperf6', performances); sv('ct6', TEAM);
    }""", [DATES, SIDS, MID])
    await do_login(page)


async def ensure_login(page):
    ok = await page.evaluate('() => !!selectedMember')
    if not ok:
        await do_login(page)


async def render(page):
    await page.evaluate('() => renderEmp()')
    await page.wait_for_timeout(220)


async def snap(page):
    return await page.evaluate("""() => {
        const btn = document.querySelector('.punch-btn');
        const cards = Array.from(document.querySelectorAll('.pc')).map(c => {
            const r = c.querySelector('.pc-range');
            const s = c.querySelector('.pc-status');
            const chks = Array.from(c.querySelectorAll('.pc-chk')).map(x => x.textContent.trim());
            return {
                name: r ? r.textContent.trim() : '',
                status: s ? s.textContent.trim() : '',
                marks: chks.join('')
            };
        });
        return {
            td: tdStr(),
            btnText: btn ? btn.textContent.replace(/\\s+/g, ' ').trim() : '(no button)',
            btnOff: btn ? (btn.disabled || btn.classList.contains('off')) : None_,
            cards
        };
    }""".replace('None_', 'null'))


async def all_punches(page):
    return await page.evaluate("""() => {
        const out = [];
        Object.keys(state.punches).sort().forEach(d => {
            (state.punches[d] || []).forEach(p => out.push(`${d} sid=${p.sid} ${p.t} @${p.time}`));
        });
        return out;
    }""")


async def moment(page, when, label, click=True, presses=3):
    await page.clock.set_fixed_time(when)
    await ensure_login(page)
    await render(page)
    info = await snap(page)
    log(f'\n=== {label}  td={info["td"]} ===')
    log(f'  按钮: off={info["btnOff"]} | {info["btnText"]}')
    for c in info['cards']:
        log(f'    {c["name"]:<16} [{c["marks"]}] {c["status"]}')
    if not click:
        return info
    n = 0
    cur = when
    while n < presses:
        info = await snap(page)
        if info['btnOff'] or '打卡' not in info['btnText']:
            break
        txt = info['btnText']
        await page.click('.punch-btn')
        await page.wait_for_timeout(450)
        n += 1
        after = await snap(page)
        log(f'  >>> 点击#{n}「{txt}」→ 按钮: off={after["btnOff"]} | {after["btnText"]}')
        for c in after['cards']:
            log(f'      {c["name"]:<16} [{c["marks"]}] {c["status"]}')
        cur = cur + dt.timedelta(seconds=8)
        await page.clock.set_fixed_time(cur)
        await render(page)
    return info


def build_timeline(end23_at):
    T = dt.datetime
    tl = [
        (T(2026, 8, 5, 22, 0), '8/5 22:00 上班(22-23)', True),
        (T(2026, 8, 5, 23, 0), '8/5 23:00 交接 22-23下班/23-0上班', True),
    ]
    if end23_at == '2358':
        tl.append((T(2026, 8, 5, 23, 58), '8/5 23:58 打 23-0 下班', True))
    tl += [
        (T(2026, 8, 6, 0, 0), '8/6 00:00（若上面没打，这里应能补打 23-0 下班 + 打 0-1 上班）', True),
        (T(2026, 8, 6, 0, 2), '8/6 00:02 回看', True),
        (T(2026, 8, 6, 1, 0), '8/6 01:00 交接', True),
        (T(2026, 8, 6, 2, 0), '8/6 02:00 1-2 下班', True),
        (T(2026, 8, 6, 11, 0), '8/6 11:00 上班(11-12)', True),
        (T(2026, 8, 6, 12, 0), '8/6 12:00 交接', True),
        (T(2026, 8, 6, 13, 0), '8/6 13:00 12-13下班 + 13-14上班', True),
        (T(2026, 8, 6, 14, 0), '8/6 14:00 13-14下班 ★问题5', True),
        (T(2026, 8, 6, 22, 0), '8/6 22:00 上班(22-23) ★问题5', True),
        (T(2026, 8, 6, 23, 0), '8/6 23:00 ★问题1', True),
        (T(2026, 8, 6, 23, 59), '8/6 23:59 ★问题1', True),
        (T(2026, 8, 7, 0, 0), '8/7 00:00 ★问题2/3', True),
        (T(2026, 8, 7, 0, 2), '8/7 00:02', True),
        (T(2026, 8, 7, 1, 0), '8/7 01:00 ★问题4', True),
        (T(2026, 8, 7, 2, 0), '8/7 02:00 ★问题4', True),
        (T(2026, 8, 7, 8, 0), '8/7 08:00 白天回看', False),
    ]
    return tl


async def run(variant):
    log('\n' + '#' * 70)
    log(f'# 变体 {variant}: 8/5 的 23-0 下班卡在 ' + ('23:58' if variant == 'A' else '00:00') + ' 打')
    log('#' * 70)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        page.on('pageerror', lambda e: log(f'  [pageerror] {e}'))
        await page.clock.install(time=dt.datetime(2026, 8, 5, 21, 50))
        await block_external(page)
        await setup(page)
        for when, label, click in build_timeline('2358' if variant == 'A' else '0000'):
            await moment(page, when, label, click=click)
        log('\n---------------- 本地打卡记录 ----------------')
        for r in await all_punches(page):
            log('  ' + r)
        await browser.close()


async def main():
    which = sys.argv[1] if len(sys.argv) > 1 else 'B'
    for v in (['A', 'B'] if which == 'all' else [which]):
        await run(v)


if __name__ == '__main__':
    asyncio.run(main())
