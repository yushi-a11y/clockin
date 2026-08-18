import asyncio
from playwright.async_api import async_playwright

async def test_4_shift_chain():
    """Test resolvePunchAction with a 4-shift chain"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        
        url = "http://127.0.0.1:9876/index.html"
        print(f"Opening {url}...")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        test_results = await page.evaluate("""
            () => {
                const results = [];
                const mkShift = (id, name, start, end, tolerance=5) => ({id, name, start, end, tolerance, cross: end <= start});
                const mkInst = (sh, sd) => ({sh, sd});
                const mkPunch = (sid, t, time, sd) => ({sid, t, time, sd, mid: 999, date: sd, name: 'test'});
                
                // Scenario: 4-shift chain 14:00-15:00 → 15:00-16:00 → 16:00-17:00 → 17:00-18:00
                // First two shifts done, need handover between shift 2 and 3
                {
                    const sh1 = mkShift(100, '14:00-15:00', '14:00', '15:00');
                    const sh2 = mkShift(101, '15:00-16:00', '15:00', '16:00');
                    const sh3 = mkShift(102, '16:00-17:00', '16:00', '17:00');
                    const sh4 = mkShift(103, '17:00-18:00', '17:00', '18:00');
                    const sd = tdStr();
                    const items = [mkInst(sh1, sd), mkInst(sh2, sd), mkInst(sh3, sd), mkInst(sh4, sd)];
                    const punches = [
                        mkPunch(100, 's', '14:00', sd),  // start of shift 1
                        mkPunch(100, 'e', '15:00', sd),  // end of shift 1 (handover)
                        mkPunch(101, 's', '15:00', sd),  // start of shift 2 (handover)
                        mkPunch(101, 'e', '16:00', sd),  // end of shift 2 (handover)
                        // shift 3 and 4 have no punches yet
                    ];
                    const punchesOf = () => punches;
                    
                    const mockNow = new Date();
                    mockNow.setHours(16, 0, 0, 0);
                    const origServerDate = serverDate;
                    serverDate = () => mockNow;
                    
                    const action = resolvePunchAction(items, sd, punchesOf, mockNow);
                    serverDate = origServerDate;
                    
                    results.push({
                        scenario: '4-shift chain: shifts 1-2 done, need handover 2→3 at 16:00',
                        action: action ? {label: action.label, hint: action.hint, shared: !!action.shared} : null
                    });
                }
                
                // Scenario: 4-shift chain, first shift needs start punch
                {
                    const sh1 = mkShift(100, '14:00-15:00', '14:00', '15:00');
                    const sh2 = mkShift(101, '15:00-16:00', '15:00', '16:00');
                    const sh3 = mkShift(102, '16:00-17:00', '16:00', '17:00');
                    const sh4 = mkShift(103, '17:00-18:00', '17:00', '18:00');
                    const sd = tdStr();
                    const items = [mkInst(sh1, sd), mkInst(sh2, sd), mkInst(sh3, sd), mkInst(sh4, sd)];
                    const punches = [];  // no punches at all
                    const punchesOf = () => punches;
                    
                    const mockNow = new Date();
                    mockNow.setHours(14, 0, 0, 0);
                    const origServerDate = serverDate;
                    serverDate = () => mockNow;
                    
                    const action = resolvePunchAction(items, sd, punchesOf, mockNow);
                    serverDate = origServerDate;
                    
                    results.push({
                        scenario: '4-shift chain: no punches, at 14:00 (first shift start)',
                        action: action ? {label: action.label, hint: action.hint, shared: !!action.shared} : null
                    });
                }
                
                // Scenario: 4-shift chain, middle handover missing
                {
                    const sh1 = mkShift(100, '14:00-15:00', '14:00', '15:00');
                    const sh2 = mkShift(101, '15:00-16:00', '15:00', '16:00');
                    const sh3 = mkShift(102, '16:00-17:00', '16:00', '17:00');
                    const sh4 = mkShift(103, '17:00-18:00', '17:00', '18:00');
                    const sd = tdStr();
                    const items = [mkInst(sh1, sd), mkInst(sh2, sd), mkInst(sh3, sd), mkInst(sh4, sd)];
                    const punches = [
                        mkPunch(100, 's', '14:00', sd),  // start of shift 1
                        mkPunch(100, 'e', '15:00', sd),  // end of shift 1
                        mkPunch(101, 's', '15:00', sd),  // start of shift 2
                        // shift 2 end and shift 3 start missing (handover at 16:00)
                        mkPunch(103, 'e', '18:00', sd),  // end of shift 4
                    ];
                    const punchesOf = () => punches;
                    
                    const mockNow = new Date();
                    mockNow.setHours(16, 0, 0, 0);
                    const origServerDate = serverDate;
                    serverDate = () => mockNow;
                    
                    const action = resolvePunchAction(items, sd, punchesOf, mockNow);
                    serverDate = origServerDate;
                    
                    results.push({
                        scenario: '4-shift chain: handover 2→3 missing at 16:00',
                        action: action ? {label: action.label, hint: action.hint, shared: !!action.shared} : null
                    });
                }
                
                return results;
            }
        """)
        
        print("\n=== 4-Shift Chain Test Results ===")
        for r in test_results:
            print(f"\nScenario: {r['scenario']}")
            if r['action']:
                print(f"  → Action: {r['action']['label']}")
                print(f"    Hint: {r['action']['hint']}")
                print(f"    Shared: {r['action']['shared']}")
            else:
                print(f"  → No action returned (null)")
        
        await browser.close()

asyncio.run(test_4_shift_chain())
