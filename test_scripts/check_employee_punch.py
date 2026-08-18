import asyncio
from playwright.async_api import async_playwright

async def check_employee_punch():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Open the deployed site
        url = "https://yushi1.pages.dev"
        print(f"Opening {url}...")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Take screenshot of initial page
        await page.screenshot(path="/Users/lixiaotian/.qoderwork/workspace/mrssl6h69qlreqcf/outputs/check_initial.png")
        print("Initial page screenshot saved")
        
        # Check if we need to select employee
        # Look for the member select dropdown
        select = page.locator("#memberSelect")
        if await select.count() > 0:
            # Check available options
            options = await page.locator("#memberSelect option").all_text_contents()
            print(f"Available options: {options}")
            
            # Try to select employee 3060017 (member_id=3) using JavaScript
            await page.evaluate("""
                const select = document.getElementById('memberSelect');
                select.value = '3';
                select.dispatchEvent(new Event('change', { bubbles: true }));
            """)
            print("Selected employee 3060017 via JavaScript")
            await page.wait_for_timeout(3000)
            
            # Check if password prompt appeared
            login_overlay = page.locator("#loginOverlay")
            if await login_overlay.count() > 0:
                style = await login_overlay.get_attribute("style")
                if style and "display: none" not in style and "display:none" not in style:
                    print("Password prompt appeared, entering default password via JS...")
                    await page.evaluate("""
                        document.getElementById('loginInput').value = '123456';
                        document.getElementById('loginInput').dispatchEvent(new Event('input', { bubbles: true }));
                    """)
                    await page.locator("button:has-text('登录')").click(force=True)
                    await page.wait_for_timeout(3000)
                    print("Login submitted")
            
            # Take screenshot after login attempt
            await page.screenshot(path="/Users/lixiaotian/.qoderwork/workspace/mrssl6h69qlreqcf/outputs/check_after_login.png")
            print("After login screenshot saved")
        
        # Navigate to 8/3 (Monday) - need to click "上一天" multiple times
        # Today is 8/10, so we need to go back 7 days
        prev_btn = page.locator("button:has-text('‹ 上一天')")
        if await prev_btn.count() > 0:
            for i in range(7):
                await prev_btn.click()
                await page.wait_for_timeout(1000)
            print("Navigated to 8/3")
        
        # Take screenshot of 8/3 punch page
        await page.screenshot(path="/Users/lixiaotian/.qoderwork/workspace/mrssl6h69qlreqcf/outputs/check_8_3.png")
        print("8/3 punch page screenshot saved")
        
        # Get page content for analysis
        content = await page.content()
        
        # Check for punch status
        # Look for shift cards
        shift_cards = page.locator(".pc")
        count = await shift_cards.count()
        print(f"Found {count} shift cards")
        
        for i in range(count):
            card = shift_cards.nth(i)
            text = await card.text_content()
            print(f"Shift {i+1}: {text.strip()}")
        
        await browser.close()

asyncio.run(check_employee_punch())
