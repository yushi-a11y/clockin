#!/usr/bin/env python3
"""验证「同一 sid 连续两天排班时，跨天班次的下班卡串味」假设。

前置：8/5 的 23-0 下班卡落在 8/6 00:00（真实打卡或补卡审批都会写成 date=8/6）。
预期看到：8/6 的 23-0 班次凭空继承了这条下班卡 → 打完上班卡后直接"已完成"，
         23:59 没有下班按钮，且 8/6 的下班卡永远补不上。
"""
import datetime as dt
import asyncio
from playwright.async_api import async_playwright

BASE_URL = 'http://127.0.0.1:8765/index.html'
SIDS = [24, 25, 11, 12, 13, 22, 23]
DATES = ['2026-08-05', '2026-08-06', '2026-08-07', '2026-08-08']
MID = 1


def log(m):
    print(m, flush=True)


async def block_external(page):
    async def handle(route):
        u = route.request.url
        if 'fonts.g' in u or 'supabase' in u:
            await route.abort()
        else:
            await route.continue_()
    await page.route('**/*', handle)


async def do_login(page):
    await page.evaluate("""() => {
        ['cb6','cb6exp','cb6auth','cb6authTs'].forEach(k=>localStorage.removeItem(k));
        selectedMember=null; claims={};
    }""")
    await page.evaluate('() => renderEmp()')
    await page.wait_for_selector('#memberSelect option:not([value=""])', state='attached', timeout=25000)
    await page.select_option('#memberSelect', str(MID))
    await page.wait_for_selector('#pwdOverlay', state='visible', timeout=10000)
    await page.fill('#pwdInput', '123456')
    await page.click('#pwdOverlay .btn.p')
    await page.wait_for_function('() => !!selectedMember', timeout=15000)


async def snap(page):
    return await page.evaluate("""() => {
        const btn=document.querySelector('.punch-btn');
        const cards=Array.from(document.querySelectorAll('.pc')).map(c=>({
            name:(c.querySelector('.pc-range')||{}).textContent?.trim()||'',
            status:(c.querySelector('.pc-status')||{}).textContent?.trim()||'',
            marks:Array.from(c.querySelectorAll('.pc-chk')).map(x=>x.textContent.trim()).join('')
        }));
        return {td:tdStr(),
                btnText:btn?btn.textContent.replace(/\\s+/g,' ').trim():'(no button)',
                btnOff:btn?(btn.disabled||btn.classList.contains('off')):null, cards};
    }""")


async def moment(page, when, label, presses=3):
    await page.clock.set_fixed_time(when)
    if not await page.evaluate('() => !!selectedMember'):
        await do_login(page)
    await page.evaluate('() => renderEmp()')
    await page.wait_for_timeout(220)
    info = await snap(page)
    log(f'\n=== {label}  td={info["td"]} ===')
    log(f'  按钮: off={info["btnOff"]} | {info["btnText"]}')
    for c in info['cards']:
        log(f'    {c["name"]:<16} [{c["marks"]}] {c["status"]}')
    cur, n = when, 0
    while n < presses:
        info = await snap(page)
        if info['btnOff'] or '打卡' not in info['btnText']:
            break
        txt = info['btnText']
        await page.click('.punch-btn')
        await page.wait_for_timeout(400)
        n += 1
        a = await snap(page)
        log(f'  >>> 点击#{n}「{txt}」→ off={a["btnOff"]} | {a["btnText"]}')
        for c in a['cards']:
            log(f'      {c["name"]:<16} [{c["marks"]}] {c["status"]}')
        cur += dt.timedelta(seconds=8)
        await page.clock.set_fixed_time(cur)
        await page.evaluate('() => renderEmp()')
        await page.wait_for_timeout(180)


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await (await b.new_context()).new_page()
        page.on('pageerror', lambda e: log(f'[pageerror] {e}'))
        await page.clock.install(time=dt.datetime(2026, 8, 6, 21, 50))
        await block_external(page)
        await page.goto(BASE_URL, wait_until='domcontentloaded', timeout=20000)
        await page.evaluate("""(a)=>{
            const [dates,sids,mid]=a;
            localStorage.clear();
            state={punches:{},shifts:DEF_SHIFTS};
            picks={}; dates.forEach(d=>{picks[d]={};picks[d][mid]=sids.slice()});
            // 8/5 的 23-0：上班卡落 8/5 23:00，下班卡落 8/6 00:00（跨天必然如此）
            state.punches['2026-08-05']=[{sid:23,t:'s',time:'23:00',ts:0,mid,date:'2026-08-05',name:'x'}];
            state.punches['2026-08-06']=[{sid:23,t:'e',time:'00:00',ts:0,mid,date:'2026-08-06',name:'x'}];
            makeups=[];leaves=[];performances=[];
            TEAM=JSON.parse(JSON.stringify(DEF_TEAM)); selectedMember=null;
            sv('cv6',state);sv('cp6',picks);sv('cmkup6',makeups);sv('cleave6',leaves);
            sv('cperf6',performances);sv('ct6',TEAM);
        }""", [DATES, SIDS, MID])
        await do_login(page)

        T = dt.datetime
        for when, label in [
            (T(2026, 8, 6, 14, 0), '8/6 14:00 白天回看（★用户问题5 的现象）'),
            (T(2026, 8, 6, 22, 0), '8/6 22:00 上班 22-23'),
            (T(2026, 8, 6, 23, 0), '8/6 23:00 ★用户问题1'),
            (T(2026, 8, 6, 23, 30), '8/6 23:30'),
            (T(2026, 8, 6, 23, 59), '8/6 23:59 ★用户问题1（下班按钮）'),
            (T(2026, 8, 7, 0, 0), '8/7 00:00 ★用户问题2/3'),
        ]:
            await moment(page, when, label)

        log('\n---- 记录 ----')
        for r in await page.evaluate("""()=>{const o=[];Object.keys(state.punches).sort().forEach(d=>
            (state.punches[d]||[]).forEach(p=>o.push(`${d} sid=${p.sid} ${p.t} @${p.time}`)));return o}"""):
            log('  ' + r)
        await b.close()


asyncio.run(main())
