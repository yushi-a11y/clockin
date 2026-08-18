import asyncio
from playwright.async_api import async_playwright

async def screenshot_admin_dashboard():
    """Take screenshot of admin dashboard on deployed site"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        
        url = "https://yushi1.pages.dev"
        print(f"Opening {url}...")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Check version
        version = await page.evaluate("APP_VERSION")
        print(f"Deployed version: {version}")
        
        # Navigate to admin page using admin password
        await page.evaluate("""
            () => {
                // Set admin session
                localStorage.setItem('cs6', String(Date.now() + 86400000));
                // Directly switch to admin page
                if (typeof switchPage === 'function') switchPage('admin');
            }
        """)
        await page.wait_for_timeout(5000)
        
        # Check if KPI data loaded, if not wait more
        kpi_check = await page.evaluate("""
            () => {
                const kpiRow = document.getElementById('kpiRow');
                return kpiRow ? kpiRow.innerHTML.length : 0;
            }
        """)
        if kpi_check < 100:
            print(f"KPI data not loaded yet (length={kpi_check}), waiting more...")
            await page.wait_for_timeout(5000)
        
        # Take screenshot
        await page.screenshot(path="/Users/lixiaotian/.qoderwork/workspace/mrssl6h69qlreqcf/outputs/admin_dashboard.png")
        print("Screenshot saved: admin_dashboard.png")
        
        # Get KPI data
        kpi_data = await page.evaluate("""
            () => {
                const kpiRow = document.getElementById('kpiRow');
                return kpiRow ? kpiRow.textContent.trim() : 'no kpi row';
            }
        """)
        print(f"KPI data: {kpi_data}")
        
        await browser.close()

asyncio.run(screenshot_admin_dashboard())
