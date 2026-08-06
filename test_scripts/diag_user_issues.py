#!/usr/bin/env python3
"""诊断用户报告的两个问题：
1. 今天 23-0 还没上班但显示已打卡
2. 8.3 完整打卡但现在显示缺卡，补卡里也没有 8.3
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = 'http://127.0.0.1:8765/index.html'
SHOTS = ROOT / 'test_outputs'
SHOTS.mkdir(exist_ok=True)


async def block_external(page):
    async def _abort(route):
        await route.abort()
    for pat in ('**/fonts.googleapis.com/**', '**/fonts.gstatic.com/**', '**/*.supabase.co/**'):
        await page.route(pat, _abort)


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        await block_external(page)

        await page.goto(BASE_URL, wait_until='domcontentloaded')
        await page.wait_for_selector('#memberSelect option:not([value=""])', state='attached', timeout=25000)

        # 选第一个成员
        mid = await page.evaluate('() => TEAM[0].id')
        await page.select_option('#memberSelect', str(mid))
        await page.wait_for_selector('#pwdOverlay', state='visible', timeout=10000)
        await page.fill('#pwdInput', '123456')
        await page.click('#pwdOverlay .btn.p')
        await page.wait_for_function('() => !!selectedMember', timeout=15000)

        today = await page.evaluate('() => tdStr()')
        print(f'=== 今天日期: {today} ===')

        # 1. 检查 23-0 班次的状态
        diag_23 = await page.evaluate("""() => {
            const mid = selectedMember.id;
            const today = tdStr();
            const yesterday = ymd(addDays(parseYmd(today), -1));

            // 检查 picks：今天和昨天有没有选 23 号班次
            const todayPicks = (picks[today] && picks[today][mid]) || [];
            const yesterdayPicks = (picks[yesterday] && picks[yesterday][mid]) || [];

            // 检查 punches：今天和昨天的打卡记录
            const todayPunches = (state.punches[today] || []).filter(p => p.mid === mid);
            const yesterdayPunches = (state.punches[yesterday] || []).filter(p => p.mid === mid);
            const tomorrow = ymd(addDays(parseYmd(today), 1));
            const tomorrowPunches = (state.punches[tomorrow] || []).filter(p => p.mid === mid);

            // 用 getAllPunchesForMember 查今天和昨天的
            const todayAll = getAllPunchesForMember(mid, today);
            const yesterdayAll = getAllPunchesForMember(mid, yesterday);

            // 23-0 shift
            const sh23 = state.shifts.find(s => s.id === 23);

            // 用 ss() 检查状态
            const stToday = ss(sh23, todayAll, today, today);
            const stYesterday = ss(sh23, yesterdayAll, yesterday, yesterday);

            // isPrevDayChainShift 检查
            const isPrev = isPrevDayChainShift(23, today, mid);

            // punchesFor 会返回哪个？
            const isPrevChain = isToday => isToday && isPrevDayChainShift(23, tdStr(), mid);

            return {
                today, yesterday,
                todayPicks23: todayPicks.includes(23),
                yesterdayPicks23: yesterdayPicks.includes(23),
                isPrevDayChainShift: isPrev,
                todayPunches23: todayPunches.filter(p => p.sid === 23).map(p => ({t: p.t, time: p.time, date: p.date})),
                yesterdayPunches23: yesterdayPunches.filter(p => p.sid === 23).map(p => ({t: p.t, time: p.time, date: p.date})),
                tomorrowPunches23: tomorrowPunches.filter(p => p.sid === 23).map(p => ({t: p.t, time: p.time, date: p.date})),
                todayAll23: todayAll.filter(p => p.sid === 23).map(p => ({t: p.t, time: p.time, date: p.date})),
                yesterdayAll23: yesterdayAll.filter(p => p.sid === 23).map(p => ({t: p.t, time: p.time, date: p.date})),
                ssToday: stToday,
                ssYesterday: stYesterday,
                allPickDates: Object.keys(picks).filter(d => picks[d] && picks[d][mid] && picks[d][mid].includes(23)),
                allPunchDates23: Object.keys(state.punches).filter(d => (state.punches[d]||[]).some(p => p.sid === 23 && p.mid === mid)),
            };
        }""")
        print(f'\n=== 23-0 班次诊断 ===')
        for k, v in diag_23.items():
            print(f'  {k}: {v}')

        # 2. 检查 8/3 的状态
        diag_83 = await page.evaluate("""() => {
            const mid = selectedMember.id;
            const d83 = '2026-08-03';

            // picks for 8/3
            const picks83 = (picks[d83] && picks[d83][mid]) || [];

            // punches for 8/3
            const punches83 = (state.punches[d83] || []).filter(p => p.mid === mid);

            // getAllPunchesForMember for 8/3 (includes 8/4)
            const all83 = getAllPunchesForMember(mid, d83);

            // 8/2 picks (for cross-day from 8/2)
            const d82 = '2026-08-02';
            const picks82 = (picks[d82] && picks[d82][mid]) || [];
            const punches82 = (state.punches[d82] || []).filter(p => p.mid === mid);

            // Check each shift's status on 8/3
            const shiftStatuses = {};
            state.shifts.filter(s => s.enabled).forEach(sh => {
                const inPicks83 = picks83.includes(sh.id);
                const inPicks82 = picks82.includes(sh.id);
                const punches = all83.filter(p => p.sid === sh.id);
                const st = ss(sh, all83, d83, d83);
                if (inPicks83 || inPicks82) {
                    shiftStatuses[sh.name] = {
                        inPicks83, inPicks82,
                        punches: punches.map(p => ({t: p.t, time: p.time, date: p.date})),
                        ss: st.ss, es: st.es, ov: st.ov
                    };
                }
            });

            // All dates with picks for this member
            const allPickDates = Object.keys(picks).filter(d => picks[d] && picks[d][mid] && picks[d][mid].length);

            // All dates with punches for this member
            const allPunchDates = Object.keys(state.punches).filter(d => (state.punches[d]||[]).some(p => p.mid === mid));

            return {
                d83,
                picks83,
                punches83: punches83.map(p => ({sid: p.sid, t: p.t, time: p.time})),
                all83: all83.map(p => ({sid: p.sid, t: p.t, time: p.time, date: p.date})),
                picks82,
                punches82: punches82.map(p => ({sid: p.sid, t: p.t, time: p.time})),
                shiftStatuses,
                allPickDates,
                allPunchDates,
            };
        }""")
        print(f'\n=== 8/3 诊断 ===')
        for k, v in diag_83.items():
            print(f'  {k}: {v}')

        # 截图
        await page.screenshot(path=str(SHOTS / 'diag_current_state.png'), full_page=True)
        print(f'\n截图已保存: {SHOTS / "diag_current_state.png"}')

        await browser.close()


if __name__ == '__main__':
    asyncio.run(run())
