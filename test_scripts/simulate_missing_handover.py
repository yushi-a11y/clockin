import asyncio
from playwright.async_api import async_playwright

async def simulate_missing_handover():
    """Simulate the bug scenario: chain where handover punch is missing"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        
        url = "http://127.0.0.1:9876/index.html"
        print(f"Opening {url}...")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Select member 7 (8027356) who has 14:00-15:00, 15:00-16:00, 16:00-17:00
        # This matches the user's screenshot scenario
        target_id = 7
        target_name = '8027356'
        
        # Set up binding and force-select
        await page.evaluate(f"""
            () => {{
                const tomorrow = new Date();
                tomorrow.setDate(tomorrow.getDate() + 1);
                tomorrow.setHours(7, 0, 0, 0);
                localStorage.setItem('cb6', '{target_id}');
                localStorage.setItem('cb6exp', tomorrow.toISOString());
                localStorage.setItem('cb6auth', '1');
                localStorage.setItem('cb6authTs', Date.now().toString());
                
                if (typeof claims !== 'undefined') claims[{target_id}] = null;
                
                const member = TEAM.find(m => m.id === {target_id});
                if (member) {{
                    selectedMember = member;
                    if (typeof renderEmp === 'function') renderEmp();
                }}
            }}
        """)
        await page.wait_for_timeout(3000)
        
        # Now simulate the bug: manually inject punches that create the "missing handover" state
        # Member 7 has shifts: 14:00-15:00 (id=14), 15:00-16:00 (id=15), 16:00-17:00 (id=16)
        # Simulate: punched start of 14:00-15:00, punched end of 16:00-17:00, 
        # but NO handover punch at 15:00 or 16:00
        # This creates: 14-15 has start✓ end✗, 15-16 has start✗ end✗, 16-17 has start✗ end✓
        today = await page.evaluate("tdStr()")
        print(f"Today: {today}")
        
        await page.evaluate(f"""
            () => {{
                const td = '{today}';
                // Add a start punch for shift 14 (14:00-15:00) at 14:00
                const p1 = {{sid: 14, t: 's', time: '14:00', ts: new Date().getTime(), mid: {target_id}, date: td, name: '{target_name}', sd: td}};
                // Add an end punch for shift 16 (16:00-17:00) at 17:00
                const p2 = {{sid: 16, t: 'e', time: '17:00', ts: new Date().getTime(), mid: {target_id}, date: td, name: '{target_name}', sd: td}};
                
                // Inject into state
                if (!state.punches[td]) state.punches[td] = [];
                state.punches[td].push(p1, p2);
                
                // Also add to fbPunches
                fbPunches.push(p1, p2);
                
                // Re-render
                if (typeof renderEmp === 'function') renderEmp();
            }}
        """)
        await page.wait_for_timeout(3000)
        
        # Take screenshot of the simulated bug scenario
        await page.screenshot(path="/Users/lixiaotian/.qoderwork/workspace/mrssl6h69qlreqcf/outputs/simulate_missing_handover.png")
        print("Screenshot saved: simulate_missing_handover.png")
        
        # Get shift card details
        cards = await page.evaluate("""
            () => {
                const items = document.querySelectorAll('.pc');
                return Array.from(items).map(el => el.textContent.trim());
            }
        """)
        print(f"Shift cards found: {len(cards)}")
        for i, card in enumerate(cards):
            print(f"  Card {i+1}: {card}")
        
        # Get punch button
        btn_text = await page.evaluate("""
            () => {
                const btn = document.querySelector('.punch-btn');
                return btn ? btn.textContent.trim() : 'no punch button';
            }
        """)
        print(f"Punch button: {btn_text}")
        
        # Get status bar
        status = await page.evaluate("""
            () => {
                const sbar = document.querySelector('.sbar');
                return sbar ? sbar.textContent.trim() : 'no status bar';
            }
        """)
        print(f"Status bar: {status}")
        
        await browser.close()

asyncio.run(simulate_missing_handover())
