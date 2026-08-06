#!/usr/bin/env python3
"""ClockIn v2026.08.05.5 自动化测试：绩效导入 + 单一时段人数配置 + 单格编辑."""
import asyncio
import os
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = 'http://127.0.0.1:8765/index.html'
ADMIN_PWD = 'admin123'
SCREENSHOTS = ROOT / 'test_outputs'
SCREENSHOTS.mkdir(exist_ok=True)

CSV_FILE = ROOT / 'test_assets' / 'perf_ranking.csv'
PNG_FILE = ROOT / 'test_assets' / 'perf_ranking.png'


def log(msg):
    print(f'[TEST] {msg}', flush=True)


async def take_screenshot(page, name):
    path = SCREENSHOTS / f'{name}.png'
    try:
        await page.screenshot(path=str(path), full_page=True)
        log(f'screenshot saved: {path}')
    except Exception as e:
        log(f'full-page screenshot failed for {name}: {e}; trying viewport')
        try:
            await page.screenshot(path=str(path), full_page=False)
            log(f'screenshot saved: {path}')
        except Exception as e2:
            log(f'viewport screenshot also failed for {name}: {e2}')
    return path


async def setup_route_blocking(page):
    """拦截易挂起的外部资源：Google Fonts、Supabase；保留 xlsx/tesseract 给 OCR/CSV 测试用."""
    blocked_hosts = {'fonts.googleapis.com', 'fonts.gstatic.com'}

    async def handle_route(route):
        url = route.request.url
        if any(h in url for h in blocked_hosts) or 'supabase' in url:
            await route.abort()
        else:
            await route.continue_()

    await page.route('**/*', handle_route)


async def goto_local(page, url=BASE_URL, tries=3):
    for i in range(tries):
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=20000)
            return
        except Exception as e:
            if i == tries - 1:
                raise
            log(f'goto_local retry {i + 1}: {e}')


async def login_admin(page):
    # Start fresh to avoid leftover admin session
    await goto_local(page)
    await page.evaluate("""() => {
        localStorage.clear();
        sessionStorage.clear();
    }""")
    await goto_local(page, f'{BASE_URL}#clockin-admin')
    await page.wait_for_selector('#loginOverlay.show', state='visible', timeout=10000)
    await page.fill('#loginInput', ADMIN_PWD)
    await page.click('#loginOverlay .login-btn')
    # Wait for admin page to become active
    await expect(page.locator('#pg-admin')).to_have_class(re.compile(r'active'))
    log('admin logged in')


async def navigate_to_performance(page):
    # Click the sidebar menu item that switches to performance panel
    await page.locator('.sb li:has-text("绩效录入") a').click()
    await expect(page.locator('#ap-performance')).to_have_class(re.compile(r'active'))
    log('navigated to performance admin')


async def test_csv_import(page):
    log('--- CSV import test ---')
    await page.set_input_files('#perfImportFile', str(CSV_FILE))
    await page.click('button:has-text("开始导入")')
    # Wait for result
    await page.wait_for_selector('#perfImportResult:has-text("已导入")', timeout=10000)
    result_text = await page.inner_text('#perfImportResult')
    log(f'CSV import result: {result_text}')

    # Verify table shows decimal formatting for imported scores <=1
    # Rows: 133122 1.00, 3051105 0.95, 3060017 0.88, 3065861 0.82, 3072437 0.79
    await take_screenshot(page, '01_csv_import_result')
    for name, score in [('133122', '1.00'), ('3051105', '0.95'), ('3060017', '0.88')]:
        cell = page.locator('#performanceAdminList td', has_text=re.compile(f'^{re.escape(name)}$')).locator('..').locator('td').nth(7)
        await expect(cell).to_have_text(score)
        log(f'{name} score displayed as {score}')

    # Verify raw storage in localStorage
    raw = await page.evaluate("""() => {
        const arr = JSON.parse(localStorage.getItem('cperf6') || '[]');
        return arr.filter(p => p.month && p.name === '133122')[0];
    }""")
    assert raw is not None, '133122 performance record not found in localStorage'
    assert float(raw['score']) == 1.0, f'Expected raw score 1.0, got {raw["score"]}'
    log(f'localStorage raw score for 133122 = {raw["score"]} (correct)')


async def test_png_ocr_import(page):
    log('--- PNG OCR import test ---')
    # Clear previous import result
    await page.evaluate("""() => { document.getElementById('perfImportResult').innerHTML = ''; }""")
    await page.set_input_files('#perfImportFile', str(PNG_FILE))
    await page.click('button:has-text("开始导入")')

    # Wait for OCR recognition to finish; Tesseract loading + recognition may take 15-60s
    log('waiting for OCR preview...')
    confirm_btn = page.locator('#perfImportConfirmBtn')
    await expect(confirm_btn).to_be_visible(timeout=300000)
    await expect(confirm_btn).to_be_enabled(timeout=300000)

    preview_text = await page.inner_text('#perfImportResult')
    log(f'OCR preview: {preview_text[:500]}')
    await take_screenshot(page, '02_ocr_preview')

    # Confirm import
    await confirm_btn.click()
    await page.wait_for_selector('#perfImportResult:has-text("已导入")', timeout=10000)
    result_text = await page.inner_text('#perfImportResult')
    log(f'OCR import result: {result_text}')
    await take_screenshot(page, '03_ocr_import_result')

    # Confirm button should be hidden after import
    await expect(confirm_btn).to_be_hidden()


async def test_single_slot_capacity(page):
    log('--- Single-slot capacity test ---')
    # Go to admin selection management -> capacity tab
    await page.locator('.sb li:has-text("选班管理") a').click()
    await expect(page.locator('#ap-selection')).to_have_class(re.compile(r'active'))
    await page.locator('#ast-cap').click()
    await expect(page.locator('#capBatchBar')).to_be_visible()
    log('capacity tab visible')

    # Populate single-slot dropdown (should already be populated by renderSelection)
    option_count = await page.locator('#capSingleSlot option').count()
    assert option_count > 1, f'Expected more than 1 option, got {option_count}'

    # Choose a slot, e.g. 07:00-08:00 (id=7) and set to 3
    await page.select_option('#capSingleSlot', '7')
    await page.fill('#capSingleVal', '3')
    await page.click('button:has-text("应用到本周") >> nth=1')

    # Wait for toast and grid re-render
    await page.wait_for_timeout(500)
    await take_screenshot(page, '04_single_slot_cap_set')

    # Verify localStorage slotCap has 3 for each day of current week for sid=7
    # Use the app's own week calculation to avoid mismatched week-start assumptions
    week_days = await page.evaluate("""() => {
      const curWs = weekStartOf(new Date());
      const ws = addDays(curWs, adminSelWeekOffset * 7);
      return weekDaysArr(ws).map(d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`);
    }""")
    slot_cap = await page.evaluate("""() => JSON.parse(localStorage.getItem('csc6') || '{}')""")
    for d in week_days:
        assert str(slot_cap.get(d, {}).get('7')) == '3', f'Expected cap 3 for {d}/07:00, got {slot_cap.get(d, {})}'
    log('single-slot cap set to 3 for whole week')

    # Clear single-slot cap
    await page.click('button:has-text("清空(不限)") >> nth=1')
    await page.wait_for_timeout(500)
    slot_cap = await page.evaluate("""() => JSON.parse(localStorage.getItem('csc6') || '{}')""")
    for d in week_days:
        assert slot_cap.get(d, {}).get('7') in (None, 0), f'Expected cap cleared for {d}/07:00, got {slot_cap.get(d, {})}'
    log('single-slot cap cleared for whole week')
    await take_screenshot(page, '05_single_slot_cap_cleared')

    # Per-cell edit: edit only the first day of current week for sid=7 to 2
    log('--- Per-cell capacity edit test ---')
    target_day = week_days[0]
    other_days = week_days[1:]
    input_selector = f'input[onchange="onCapInput(\'{target_day}\',7,this.value)"]'
    await page.fill(input_selector, '2')
    await page.press(input_selector, 'Enter')
    await page.wait_for_timeout(500)
    await take_screenshot(page, '06_per_cell_cap_set')

    slot_cap = await page.evaluate("""() => JSON.parse(localStorage.getItem('csc6') || '{}')""")
    assert str(slot_cap.get(target_day, {}).get('7')) == '2', f'Expected cap 2 for {target_day}/07:00, got {slot_cap.get(target_day, {})}'
    for d in other_days:
        assert slot_cap.get(d, {}).get('7') in (None, 0), f'Expected no cap for {d}/07:00 after per-cell edit, got {slot_cap.get(d, {})}'
    log(f'per-cell cap set to 2 only for {target_day}')

    # Clear the per-cell value
    await page.fill(input_selector, '')
    await page.press(input_selector, 'Enter')
    await page.wait_for_timeout(500)
    slot_cap = await page.evaluate("""() => JSON.parse(localStorage.getItem('csc6') || '{}')""")
    assert slot_cap.get(target_day, {}).get('7') in (None, 0), f'Expected cap cleared for {target_day}/07:00, got {slot_cap.get(target_day, {})}'
    log('per-cell cap cleared')
    await take_screenshot(page, '07_per_cell_cap_cleared')


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        await setup_route_blocking(page)
        try:
            await login_admin(page)
            await navigate_to_performance(page)
            await test_csv_import(page)
            await test_png_ocr_import(page)
            await test_single_slot_capacity(page)
            log('ALL TESTS PASSED')
        except Exception as e:
            await take_screenshot(page, '99_error')
            log(f'TEST FAILED: {e}')
            raise
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(run())
