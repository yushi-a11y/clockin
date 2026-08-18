import asyncio
from playwright.async_api import async_playwright

async def test_resolve_punch_action():
    """Directly test resolvePunchAction logic with mocked data"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        
        url = "http://127.0.0.1:9876/index.html"
        print(f"Opening {url}...")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Test resolvePunchAction with various scenarios
        test_results = await page.evaluate("""
            () => {
                const results = [];
                
                // Helper: create mock shift
                const mkShift = (id, name, start, end, tolerance=5) => ({id, name, start, end, tolerance, cross: end <= start});
                
                // Helper: create mock instance
                const mkInst = (sh, sd) => ({sh, sd});
                
                // Helper: create mock punch
                const mkPunch = (sid, t, time, sd) => ({sid, t, time, sd, mid: 999, date: sd, name: 'test'});
                
                // Scenario 1: Two consecutive shifts, handover punch missing for BOTH
                // 15:00-16:00 (chain first) has start punch, no end punch
                // 16:00-17:00 (chain last) has end punch, no start punch
                {
                    const sh1 = mkShift(100, '15:00-16:00', '15:00', '16:00');
                    const sh2 = mkShift(101, '16:00-17:00', '16:00', '17:00');
                    const sd = tdStr();
                    const items = [mkInst(sh1, sd), mkInst(sh2, sd)];
                    const punches = [
                        mkPunch(100, 's', '15:00', sd),  // start of first
                        mkPunch(101, 'e', '17:00', sd),  // end of second
                    ];
                    const punchesOf = () => punches;
                    
                    // Mock serverDate to be at 16:00 (handover time)
                    const mockNow = new Date();
                    mockNow.setHours(16, 0, 0, 0);
                    const origServerDate = serverDate;
                    serverDate = () => mockNow;
                    
                    const action = resolvePunchAction(items, sd, punchesOf, mockNow);
                    serverDate = origServerDate;
                    
                    results.push({
                        scenario: 'Both handover punches missing at 16:00',
                        action: action ? {label: action.label, hint: action.hint, shared: !!action.shared} : null
                    });
                }
                
                // Scenario 2: Only end of first missing (start of second exists)
                {
                    const sh1 = mkShift(100, '15:00-16:00', '15:00', '16:00');
                    const sh2 = mkShift(101, '16:00-17:00', '16:00', '17:00');
                    const sd = tdStr();
                    const items = [mkInst(sh1, sd), mkInst(sh2, sd)];
                    const punches = [
                        mkPunch(100, 's', '15:00', sd),  // start of first
                        mkPunch(101, 's', '16:00', sd),  // start of second (already punched)
                        mkPunch(101, 'e', '17:00', sd),  // end of second
                    ];
                    const punchesOf = () => punches;
                    
                    const mockNow = new Date();
                    mockNow.setHours(16, 0, 0, 0);
                    const origServerDate = serverDate;
                    serverDate = () => mockNow;
                    
                    const action = resolvePunchAction(items, sd, punchesOf, mockNow);
                    serverDate = origServerDate;
                    
                    results.push({
                        scenario: 'Only end of first missing (second fully punched)',
                        action: action ? {label: action.label, hint: action.hint, shared: !!action.shared} : null
                    });
                }
                
                // Scenario 3: Only start of second missing (end of first exists)
                {
                    const sh1 = mkShift(100, '15:00-16:00', '15:00', '16:00');
                    const sh2 = mkShift(101, '16:00-17:00', '16:00', '17:00');
                    const sd = tdStr();
                    const items = [mkInst(sh1, sd), mkInst(sh2, sd)];
                    const punches = [
                        mkPunch(100, 's', '15:00', sd),  // start of first
                        mkPunch(100, 'e', '16:00', sd),  // end of first (already punched)
                        mkPunch(101, 'e', '17:00', sd),  // end of second
                    ];
                    const punchesOf = () => punches;
                    
                    const mockNow = new Date();
                    mockNow.setHours(16, 0, 0, 0);
                    const origServerDate = serverDate;
                    serverDate = () => mockNow;
                    
                    const action = resolvePunchAction(items, sd, punchesOf, mockNow);
                    serverDate = origServerDate;
                    
                    results.push({
                        scenario: 'Only start of second missing (first fully punched)',
                        action: action ? {label: action.label, hint: action.hint, shared: !!action.shared} : null
                    });
                }
                
                // Scenario 4: Grace period - past handover time, both missing
                {
                    const sh1 = mkShift(100, '15:00-16:00', '15:00', '16:00');
                    const sh2 = mkShift(101, '16:00-17:00', '16:00', '17:00');
                    const sd = tdStr();
                    const items = [mkInst(sh1, sd), mkInst(sh2, sd)];
                    const punches = [
                        mkPunch(100, 's', '15:00', sd),  // start of first
                        mkPunch(101, 'e', '17:00', sd),  // end of second
                    ];
                    const punchesOf = () => punches;
                    
                    const mockNow = new Date();
                    mockNow.setHours(16, 25, 0, 0);  // 25 min past handover
                    const origServerDate = serverDate;
                    serverDate = () => mockNow;
                    
                    const action = resolvePunchAction(items, sd, punchesOf, mockNow);
                    serverDate = origServerDate;
                    
                    results.push({
                        scenario: 'Grace period 16:25 - both handover punches missing',
                        action: action ? {label: action.label, hint: action.hint, shared: !!action.shared} : null
                    });
                }
                
                return results;
            }
        """)
        
        print("\\n=== resolvePunchAction Test Results ===")
        for r in test_results:
            print(f"\\nScenario: {r['scenario']}")
            if r['action']:
                print(f"  → Action: {r['action']['label']}")
                print(f"    Hint: {r['action']['hint']}")
                print(f"    Shared: {r['action']['shared']}")
            else:
                print(f"  → No action returned (null)")
        
        await browser.close()

asyncio.run(test_resolve_punch_action())
