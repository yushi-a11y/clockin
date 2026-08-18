import asyncio
from playwright.async_api import async_playwright

async def check_shift_source():
    """Check where the 23:00-00:00 shift comes from for member 133122"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        
        url = "http://127.0.0.1:9876/index.html"
        print(f"Opening {url}...")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Check shift data for member 1 (133122)
        result = await page.evaluate("""
            () => {
                const today = tdStr();
                const yesterday = ymd(addDays(parseYmd(today), -1));
                const memberId = 14;  // 8597644
                
                // Get today's picks
                const todayPicks = (picks[today] && picks[today][memberId]) || [];
                const yesterdayPicks = (picks[yesterday] && picks[yesterday][memberId]) || [];
                
                // Get shift details
                const todayShifts = todayPicks.map(sid => {
                    const sh = state.shifts.find(s => s.id === sid);
                    return sh ? {id: sh.id, name: sh.name, start: sh.start, end: sh.end, cross: sh.cross} : null;
                }).filter(Boolean);
                
                const yesterdayShifts = yesterdayPicks.map(sid => {
                    const sh = state.shifts.find(s => s.id === sid);
                    return sh ? {id: sh.id, name: sh.name, start: sh.start, end: sh.end, cross: sh.cross} : null;
                }).filter(Boolean);
                
                // Check which shifts are cross-midnight
                const crossMidnightToday = todayShifts.filter(s => s.cross || s.end <= s.start);
                const crossMidnightYesterday = yesterdayShifts.filter(s => s.cross || s.end <= s.start);
                
                // Find 23:00-00:00 shift
                const shift23 = todayShifts.find(s => s.start === '23:00' && s.end === '00:00');
                const shift23Yesterday = yesterdayShifts.find(s => s.start === '23:00' && s.end === '00:00');
                
                return {
                    today,
                    yesterday,
                    todayPicks,
                    yesterdayPicks,
                    todayShifts,
                    yesterdayShifts,
                    crossMidnightToday,
                    crossMidnightYesterday,
                    shift23Today: shift23,
                    shift23Yesterday: shift23Yesterday
                };
            }
        """)
        
        print(f"Today: {result['today']}")
        print(f"Yesterday: {result['yesterday']}")
        print(f"\nToday's picks (shift IDs): {result['todayPicks']}")
        print(f"Yesterday's picks (shift IDs): {result['yesterdayPicks']}")
        print(f"\nToday's shifts:")
        for s in result['todayShifts']:
            print(f"  {s['name']} (cross={s['cross']})")
        print(f"\nYesterday's shifts:")
        for s in result['yesterdayShifts']:
            print(f"  {s['name']} (cross={s['cross']})")
        print(f"\n23:00-00:00 in today's picks: {result['shift23Today']}")
        print(f"23:00-00:00 in yesterday's picks: {result['shift23Yesterday']}")
        
        await browser.close()

asyncio.run(check_shift_source())
