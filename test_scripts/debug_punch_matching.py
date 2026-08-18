import asyncio
from playwright.async_api import async_playwright

async def debug_punch_matching():
    """Debug why punches exist but aren't matched to shifts"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        
        url = "http://127.0.0.1:9876/index.html"
        print(f"Opening {url}...")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        result = await page.evaluate("""
            () => {
                const td = '2026-08-13';
                const memberId = 8598314;  // First abnormal case
                const shiftId = 7;  // 07:00-08:00
                
                // Get all punches for this member on this date
                const mp = getAllPunchesForMember(memberId, td);
                
                // Get punches for D-1, D, D+1
                const prevDate = ymd(addDays(parseYmd(td), -1));
                const nextDate = ymd(addDays(parseYmd(td), 1));
                
                const punchesD = (state.punches[td] || []).filter(p => p.mid === memberId);
                const punchesPrev = (state.punches[prevDate] || []).filter(p => p.mid === memberId);
                const punchesNext = (state.punches[nextDate] || []).filter(p => p.mid === memberId);
                
                const fbPunchesForMember = fbPunches.filter(p => p.mid === memberId && (p.date === td || p.date === prevDate || p.date === nextDate));
                
                // Get the shift
                const sh = state.shifts.find(s => s.id === shiftId);
                
                // Check each punch
                const punchDetails = mp.filter(p => p.sid === shiftId).map(p => ({
                    t: p.t,
                    time: p.time,
                    date: p.date,
                    sd: p.sd,
                    ts: p.ts,
                    isPunchOfInstance: isPunchOfInstance(p, sh, td)
                }));
                
                // Check ss() result
                const st = ss(sh, mp, td);
                
                return {
                    memberId,
                    shift: sh.name,
                    shiftId,
                    td,
                    prevDate,
                    nextDate,
                    punchesD: punchesD.map(p => ({sid: p.sid, t: p.t, time: p.time, date: p.date, sd: p.sd})),
                    punchesPrev: punchesPrev.map(p => ({sid: p.sid, t: p.t, time: p.time, date: p.date, sd: p.sd})),
                    punchesNext: punchesNext.map(p => ({sid: p.sid, t: p.t, time: p.time, date: p.date, sd: p.sd})),
                    fbPunchesForMember: fbPunchesForMember.map(p => ({sid: p.sid, t: p.t, time: p.time, date: p.date, sd: p.sd})),
                    allPunches: mp.map(p => ({sid: p.sid, t: p.t, time: p.time, date: p.date, sd: p.sd})),
                    punchDetails,
                    ssResult: {
                        sp: st.sp,
                        ep: st.ep,
                        ss: st.ss,
                        es: st.es,
                        ov: st.ov
                    }
                };
            }
        """)
        
        print(f"\n=== Debug Punch Matching for {result['memberId']} - {result['shift']} ===")
        print(f"Date: {result['td']}, Prev: {result['prevDate']}, Next: {result['nextDate']}")
        print(f"\nPunches on D ({result['td']}):")
        for p in result['punchesD']:
            print(f"  sid={p['sid']}, t={p['t']}, time={p['time']}, date={p['date']}, sd={p['sd']}")
        print(f"\nPunches on D-1 ({result['prevDate']}):")
        for p in result['punchesPrev']:
            print(f"  sid={p['sid']}, t={p['t']}, time={p['time']}, date={p['date']}, sd={p['sd']}")
        print(f"\nPunches on D+1 ({result['nextDate']}):")
        for p in result['punchesNext']:
            print(f"  sid={p['sid']}, t={p['t']}, time={p['time']}, date={p['date']}, sd={p['sd']}")
        print(f"\nAll punches from getAllPunchesForMember:")
        for p in result['allPunches']:
            print(f"  sid={p['sid']}, t={p['t']}, time={p['time']}, date={p['date']}, sd={p['sd']}")
        print(f"\nPunch details for shift {result['shiftId']}:")
        for p in result['punchDetails']:
            print(f"  t={p['t']}, time={p['time']}, date={p['date']}, sd={p['sd']}, isPunchOfInstance={p['isPunchOfInstance']}")
        print(f"\nss() result: sp={result['ssResult']['sp']}, ep={result['ssResult']['ep']}, ss={result['ssResult']['ss']}, es={result['ssResult']['es']}, ov={result['ssResult']['ov']}")
        
        await browser.close()

asyncio.run(debug_punch_matching())
