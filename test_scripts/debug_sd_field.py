import asyncio
from playwright.async_api import async_playwright

async def debug_sd_field():
    """Check if punches have sd field"""
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
                const memberId = 8598314;
                const shiftId = 7;  // 07:00-08:00
                
                // Get all punches from state
                const allLocalPunches = [];
                Object.keys(state.punches).forEach(date => {
                    state.punches[date].forEach(p => {
                        if (p.mid === memberId) allLocalPunches.push({...p, date});
                    });
                });
                
                // Get fbPunches
                const allFbPunches = fbPunches.filter(p => p.mid === memberId);
                
                // Get the shift
                const sh = state.shifts.find(s => s.id === shiftId);
                
                // Check isPunchOfInstance for each punch
                const punchChecks = allLocalPunches.filter(p => p.sid === shiftId).map(p => ({
                    t: p.t,
                    time: p.time,
                    date: p.date,
                    sd: p.sd,
                    ts: p.ts,
                    isPunchOfInstance: isPunchOfInstance(p, sh, td),
                    hasSd: !!p.sd
                }));
                
                return {
                    localPunchesCount: allLocalPunches.length,
                    fbPunchesCount: allFbPunches.length,
                    punchChecks,
                    shift: sh ? {id: sh.id, name: sh.name, start: sh.start, end: sh.end} : null
                };
            }
        """)
        
        print(f"\n=== Debug SD Field for 8598314 - {result['shift']['name']} ===")
        print(f"Local punches: {result['localPunchesCount']}, FB punches: {result['fbPunchesCount']}")
        print(f"\nPunch checks for shift {result['shift']['id']}:")
        for p in result['punchChecks']:
            print(f"  t={p['t']}, time={p['time']}, date={p['date']}, sd={p['sd']}, hasSd={p['hasSd']}, isPunchOfInstance={p['isPunchOfInstance']}")
        
        await browser.close()

asyncio.run(debug_sd_field())
