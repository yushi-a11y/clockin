import asyncio
from playwright.async_api import async_playwright

async def verify_consecutive_shift_fix():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        
        # Use local server
        url = "http://127.0.0.1:9876/index.html"
        print(f"Opening {url}...")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Select employee via JavaScript - find unclaimed member with consecutive shifts
        print("Selecting employee...")
        result = await page.evaluate("""
            () => {
                const today = new Date();
                const ymd = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
                
                const members = TEAM.map(m => {
                    const sids = (picks[ymd] && picks[ymd][m.id]) || [];
                    const shifts = sids.map(sid => state.shifts.find(s => s.id === sid)).filter(Boolean);
                    const claimed = fbReady && claims[m.id] && claims[m.id].fp !== (typeof devFp === 'function' ? devFp() : 'unknown');
                    return { id: m.id, name: m.name, shiftCount: shifts.length, claimed, shifts: shifts.map(s => ({id: s.id, name: s.name, start: s.start, end: s.end})) };
                });
                
                // Find unclaimed members with 2+ shifts (potential consecutive)
                const unclaimedMulti = members.filter(m => !m.claimed && m.shiftCount >= 2);
                // Also find members with exactly 2 consecutive shifts (like user's 15-16, 16-17 scenario)
                const consecutivePairs = unclaimedMulti.filter(m => {
                    for (let i = 0; i < m.shifts.length - 1; i++) {
                        if (m.shifts[i].end === m.shifts[i+1].start) return true;
                    }
                    return false;
                });
                
                return { 
                    today: ymd, 
                    members: members.map(m => ({id: m.id, name: m.name, count: m.shiftCount, claimed: m.claimed})), 
                    unclaimedMulti,
                    consecutivePairs
                };
            }
        """)
        print(f"Today: {result['today']}")
        print(f"All members claim status:")
        for m in result['members']:
            print(f"  {m['id']}: {m['name']} - shifts={m['count']}, claimed={m['claimed']}")
        print(f"Unclaimed with 2+ shifts: {[(m['id'], m['name']) for m in result['unclaimedMulti']]}")
        print(f"With consecutive pairs: {[(m['id'], m['name']) for m in result['consecutivePairs']]}")
        
        # Strategy: try to select ANY member with consecutive shifts, even if claimed
        # We'll use JS to force the selection and bypass device binding
        target_id = None
        target_name = ''
        if result['consecutivePairs']:
            target_id = result['consecutivePairs'][0]['id']
            target_name = result['consecutivePairs'][0]['name']
            print(f"Target: member {target_id} ({target_name}) with consecutive shifts")
        elif result['unclaimedMulti']:
            target_id = result['unclaimedMulti'][0]['id']
            target_name = result['unclaimedMulti'][0]['name']
            print(f"Target: member {target_id} ({target_name}) with multiple shifts")
        else:
            # Find any member with consecutive shifts regardless of claim status
            all_with_consecutive = [m for m in result['members'] if m['count'] >= 2]
            if all_with_consecutive:
                target_id = all_with_consecutive[0]['id']
                target_name = all_with_consecutive[0]['name']
                print(f"Target: member {target_id} ({target_name}) - will try force-select")
            else:
                print("ERROR: No members with multiple shifts available")
                await browser.close()
                return
        
        # Force-select member: set up valid binding, mock claims, then set selectedMember
        print(f"Force-selecting member {target_id}...")
        await page.evaluate(f"""
            () => {{
                // Set up valid device binding (not expired)
                const tomorrow = new Date();
                tomorrow.setDate(tomorrow.getDate() + 1);
                tomorrow.setHours(7, 0, 0, 0);
                localStorage.setItem('cb6', '{target_id}');
                localStorage.setItem('cb6exp', tomorrow.toISOString());
                localStorage.setItem('cb6auth', '1');
                localStorage.setItem('cb6authTs', Date.now().toString());
                
                // Mock claims to show this member as unclaimed by others
                if (typeof claims !== 'undefined') {{
                    claims[{target_id}] = null;
                }}
                
                // Set selectedMember
                const member = TEAM.find(m => m.id === {target_id});
                if (member) {{
                    selectedMember = member;
                    // Trigger render
                    if (typeof renderEmp === 'function') renderEmp();
                }}
            }}
        """)
        await page.wait_for_timeout(3000)
        
        # Check for password prompt - look for various login UI elements
        login_visible = await page.evaluate("""
            () => {
                // Check for login overlay
                const overlay = document.getElementById('loginOverlay');
                if (overlay) {
                    const style = overlay.getAttribute('style') || '';
                    const isVisible = style.indexOf('display: none') === -1 && 
                                     style.indexOf('display:none') === -1 && 
                                     overlay.offsetParent !== null;
                    if (isVisible) return 'overlay';
                }
                // Check for login input directly
                const loginInput = document.getElementById('loginInput');
                if (loginInput && loginInput.offsetParent !== null) return 'input';
                return null;
            }
        """)
        
        if login_visible:
            print(f"Login UI detected: {login_visible}")
            await page.evaluate("""
                () => {
                    const input = document.getElementById('loginInput');
                    if (input) {
                        input.value = '123456';
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                }
            """)
            await page.wait_for_timeout(500)
            # Try multiple login button selectors
            login_btn = page.locator("button:has-text('登录')").first
            if await login_btn.count() > 0:
                await login_btn.click(force=True)
                await page.wait_for_timeout(3000)
                print("Login submitted")
            else:
                print("Login button not found, trying Enter key")
                await page.keyboard.press('Enter')
                await page.wait_for_timeout(3000)
        else:
            print("No login prompt detected")
        
        # Take screenshot of the punch view
        await page.screenshot(path="/Users/lixiaotian/.qoderwork/workspace/mrssl6h69qlreqcf/outputs/verify_consecutive_today.png")
        print("Screenshot saved: verify_consecutive_today.png")
        
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
        
        # Also get the punch button state
        btn_text = await page.evaluate("""
            () => {
                const btn = document.querySelector('.punch-btn');
                return btn ? btn.textContent.trim() : 'no punch button';
            }
        """)
        print(f"Punch button: {btn_text}")
        
        # Get status bar info
        status = await page.evaluate("""
            () => {
                const sbar = document.querySelector('.sbar');
                return sbar ? sbar.textContent.trim() : 'no status bar';
            }
        """)
        print(f"Status bar: {status}")
        
        await browser.close()

asyncio.run(verify_consecutive_shift_fix())
