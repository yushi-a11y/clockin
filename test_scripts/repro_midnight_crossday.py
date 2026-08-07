#!/usr/bin/env python3
"""复现跨天班次（23-0 / 0-1）打卡按钮消失问题。
场景：员工在 D 选了 23:00-00:00（id=23，跨天），在 D+1 选了 00:00-01:00（id=24）。
在 D 23:00、D 23:30、D+1 00:00、D+1 00:30 四个时刻抓取：
  - 顶部打卡按钮的文本/disabled 状态
  - 我的班次卡片及状态文字
  - 控制台 [诊断 23-0] 日志
"""
import datetime as dt
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = 'http://127.0.0.1:8765/index.html'
SHOTS = ROOT / 'test_outputs'
SHOTS.mkdir(exist_ok=True)


def log(msg):
    print(f'[REPRO] {msg}', flush=True)


async def block_external(page):
    blocked = {'fonts.googleapis.com', 'fonts.gstatic.com'}

    async def handle(route):
        url = route.request.url
        if any(h in url for h in blocked) or 'supabase' in url:
            await route.abort()
        else:
            await route.continue_()

    await page.route('**/*', handle)


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
        makeups = []; leaves = []; performances = [];
        TEAM = JSON.parse(JSON.stringify(DEF_TEAM));
        selectedMember = null;
        sv('cv6', state); sv('cp6', picks); sv('cmkup6', makeups);
        sv('cleave6', leaves); sv('cperf6', performances); sv('ct6', TEAM);
        localStorage.removeItem('cb6'); localStorage.removeItem('cb6exp');
        localStorage.removeItem('cb6auth'); localStorage.removeItem('cb6authTs');
    }""")


async def login_member(page, mid):
    if not await page.evaluate('() => !!document.getElementById("memberSelect")'):
        await goto_robust(page)
    await page.wait_for_selector('#memberSelect option:not([value=""])', state='attached', timeout=25000)
    await page.select_option('#memberSelect', str(mid))
    await page.wait_for_selector('#pwdOverlay', state='visible', timeout=10000)
    await page.fill('#pwdInput', '123456')
    await page.click('#pwdOverlay .btn.p')
    await page.wait_for_function('() => !!selectedMember', timeout=15000)
    log(f'logged in as member {mid}')


async def seed_picks(page, date_str, mid, sids):
    await page.evaluate("""(a) => {
        const [ds, mid, sids] = a;
        if (!picks[ds]) picks[ds] = {};
        picks[ds][mid] = sids.slice();
        sv('cp6', picks);
    }""", [date_str, mid, sids])


async def snapshot(page, label):
    info = await page.evaluate("""() => {
        const btn = document.querySelector('.punch-btn');
        const cards = Array.from(document.querySelectorAll('.pc')).map(c => {
            const r = c.querySelector('.pc-range'); const s = c.querySelector('.pc-status');
            return (r ? r.textContent.trim() : '') + ' => ' + (s ? s.textContent.trim() : '');
        });
        return {
            td: tdStr(),
            nowLocal: new Date().toString().slice(0, 24),
            btnText: btn ? btn.textContent.replace(/\\s+/g, ' ').trim() : '(none)',
            btnDisabled: btn ? btn.disabled || btn.classList.contains('off') : null,
            cards
        };
    }""")
    log(f'--- {label} ---')
    log(f'  td={info["td"]}  local={info["nowLocal"]}')
    log(f'  button: disabled={info["btnDisabled"]}  text="{info["btnText"]}"')
    for c in info['cards']:
        log(f'  card: {c}')
    try:
        await page.screenshot(path=str(SHOTS / f'midnight_{label}.png'), full_page=True)
    except Exception:
        pass
    return info


async def set_time(page, t):
    await page.clock.install(time=t)
    await page.evaluate('() => renderEmp()')
    await page.wait_for_timeout(400)


async def run_scenario(name, mid, day_picks, next_picks):
    log(f'======== scenario: {name} ========')
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        page.on('console', lambda m: log(f'  [console:{m.type}] {m.text}') if '诊断' in m.text or 'diag' in m.text.lower() else None)
        page.on('pageerror', lambda e: log(f'  [pageerror] {e}'))
        await block_external(page)
        base = dt.datetime(2026, 8, 6, 22, 50, 0)
        await page.clock.install(time=base)
        await clear_state(page)
        d = '2026-08-06'
        dnext = '2026-08-07'
        if day_picks is not None:
            await seed_picks(page, d, mid, day_picks)
        if next_picks is not None:
            await seed_picks(page, dnext, mid, next_picks)
        await login_member(page, mid)
        # 23:00 on D
        await set_time(page, dt.datetime(2026, 8, 6, 23, 0, 0))
        await snapshot(page, f'{name}_D_2300')
        # 23:03 on D (inside tolerance)
        await set_time(page, dt.datetime(2026, 8, 6, 23, 3, 0))
        await snapshot(page, f'{name}_D_2303')
        # 00:00 on D+1
        await set_time(page, dt.datetime(2026, 8, 7, 0, 0, 0))
        await snapshot(page, f'{name}_D1_0000')
        # 00:03 on D+1
        await set_time(page, dt.datetime(2026, 8, 7, 0, 3, 0))
        await snapshot(page, f'{name}_D1_0003')
        await browser.close()


async def main():
    # 场景1：D 只选 23（23-0），D+1 只选 24（0-1）
    await run_scenario('only23_then_24', mid=1, day_picks=[23], next_picks=[24])
    # 场景2：D 选 22+23（连班跨午夜），D+1 选 24
    await run_scenario('chain223_then_24', mid=1, day_picks=[22, 23], next_picks=[24])
    # 场景3：不手动选班，用成员默认 shiftIds（含 23/24 的成员）
    await run_scenario('default_shiftids', mid=12, day_picks=None, next_picks=None)
    log('DONE')


if __name__ == '__main__':
    asyncio.run(main())
