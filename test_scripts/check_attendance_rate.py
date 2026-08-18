import asyncio
from playwright.async_api import async_playwright

async def check_attendance_rate():
    """Check if attendance rate calculation is correct for 2026-08-13"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        
        url = "http://127.0.0.1:9876/index.html"
        print(f"Opening {url}...")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Check attendance calculation for 2026-08-13
        result = await page.evaluate("""
            () => {
                const td = '2026-08-13';
                const en = state.shifts.filter(s => s.enabled);
                
                // Replicate admin KPI calculation
                let norm = 0, total = 0;
                const details = [];
                
                en.forEach(sh => {
                    const count = slotCount(td, sh.id);
                    if (count === 0) return;
                    
                    TEAM.forEach(m => {
                        if (!(memberShifts(m, td).includes(sh.id))) return;
                        const mp = getAllPunchesForMember(m.id, td);
                        const st = ss(sh, mp, td);
                        
                        const hasStart = !!st.sp;
                        const hasEnd = !!st.ep;
                        const isNormal = hasStart && hasEnd;
                        
                        if (isNormal) norm++;
                        
                        details.push({
                            member: m.name,
                            memberId: m.id,
                            shift: sh.name,
                            shiftId: sh.id,
                            hasStart,
                            hasEnd,
                            isNormal,
                            punches: mp.filter(p => p.sid === sh.id).map(p => ({t: p.t, time: p.time}))
                        });
                    });
                    
                    total += count;
                });
                
                const anom = total - norm;
                const rate = total ? ((norm / total) * 100).toFixed(1) : '0';
                
                // Find abnormal cases
                const abnormal = details.filter(d => !d.isNormal);
                
                return {
                    total,
                    norm,
                    anom,
                    rate: rate + '%',
                    abnormalCount: abnormal.length,
                    abnormal: abnormal.slice(0, 10),  // First 10 abnormal cases
                    totalDetails: details.length
                };
            }
        """)
        
        print(f"\n=== Attendance Rate Check for 2026-08-13 ===")
        print(f"Total expected (应到): {result['total']}")
        print(f"Normal (正常): {result['norm']}")
        print(f"Abnormal (异常): {result['anom']}")
        print(f"Attendance rate: {result['rate']}")
        print(f"\nTotal detail records: {result['totalDetails']}")
        print(f"Abnormal cases found: {result['abnormalCount']}")
        
        if len(result['abnormal']) > 0:
            print(f"\nFirst 10 abnormal cases:")
            for d in result['abnormal'][:10]:
                print(f"  {d['member']} - {d['shift']}: start={d['hasStart']}, end={d['hasEnd']}, punches={d['punches']}")
        else:
            print(f"\nNo abnormal cases found - all scheduled members have both punches!")
        
        await browser.close()

asyncio.run(check_attendance_rate())
