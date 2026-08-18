import asyncio
from playwright.async_api import async_playwright

async def check_attendance_for_dates():
    """Check attendance rate calculation for different date ranges"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        
        url = "https://yushi1.pages.dev"
        print(f"Opening {url}...")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Set admin session
        await page.evaluate("""
            () => {
                localStorage.setItem('cs6', String(Date.now() + 86400000));
                if (typeof switchPage === 'function') switchPage('admin');
            }
        """)
        await page.wait_for_timeout(3000)
        
        # Check attendance for multiple dates using kpiShiftDay
        dates_to_check = [
            (0, '今天'),
            (-1, '昨天'),
            (-2, '前天'),
            (-4, '4天前'),
            (-7, '7天前'),
        ]
        
        results = []
        for offset, label in dates_to_check:
            # Navigate to the date using kpiShiftDay
            await page.evaluate(f"""
                () => {{
                    kpiDayOffset = {offset};
                    if (typeof renderAdmin === 'function') renderAdmin();
                }}
            """)
            await page.wait_for_timeout(2000)
            
            # Get KPI data
            kpi_data = await page.evaluate("""
                () => {
                    const kpiRow = document.getElementById('kpiRow');
                    if (!kpiRow) return null;
                    
                    const kpis = kpiRow.querySelectorAll('.kpi');
                    if (kpis.length < 4) return null;
                    
                    // Get the actual date from the date button
                    const dateBtn = document.getElementById('dateBtn');
                    const actualDate = dateBtn ? dateBtn.textContent : 'unknown';
                    
                    return {
                        date: actualDate,
                        total: kpis[0].querySelector('.kpi-v').textContent,
                        normal: kpis[1].querySelector('.kpi-v').textContent,
                        rate: kpis[2].querySelector('.kpi-v').textContent,
                        abnormal: kpis[3].querySelector('.kpi-v').textContent
                    };
                }
            """)
            
            if kpi_data:
                results.append(kpi_data)
                print(f"{label} ({kpi_data['date']}): 应到={kpi_data['total']}, 正常={kpi_data['normal']}, 出勤率={kpi_data['rate']}, 异常={kpi_data['abnormal']}")
            else:
                print(f"{label}: 无法获取数据")
        
        # Take screenshot
        await page.screenshot(path="/Users/lixiaotian/.qoderwork/workspace/mrssl6h69qlreqcf/outputs/attendance_multi_date.png")
        print("\nScreenshot saved: attendance_multi_date.png")
        
        await browser.close()
        return results

asyncio.run(check_attendance_for_dates())
