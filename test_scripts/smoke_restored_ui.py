from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8765/index.html"
SCREENSHOT = Path("test_outputs/restored-ui-smoke.png")
SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.goto(URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)

    feedback = page.get_by_role("button", name="反馈")
    assert feedback.is_visible(), "顶部反馈入口不可见"
    feedback.click()
    assert page.get_by_text("问题诊断", exact=True).is_visible(), "反馈诊断面板未打开"
    page.get_by_text("诊断结果", exact=True).wait_for(state="visible", timeout=30000)

    checks = page.evaluate("""() => ({
      feedback: typeof openFeedbackPanel === 'function',
      exchange: typeof initiateExchange === 'function' && typeof acceptExchange === 'function',
      performance: typeof renderPerformanceView === 'function',
      dailyUnlimited: dayValid(9) === 9,
      weeklyLimit: MAX_PER_WEEK === 56,
      earlyPunch: PUNCH_EARLY_MIN === 2
    })""")
    failed = [name for name, passed in checks.items() if not passed]
    assert not failed, f"功能运行时检查失败: {failed}"
    assert not page_errors, f"页面脚本异常: {page_errors}"

    page.screenshot(path=str(SCREENSHOT), full_page=True)
    browser.close()
    print(f"浏览器冒烟通过：{checks}；截图 {SCREENSHOT}")
