#!/usr/bin/env python3
"""ClockIn v2026.08.05.8 自动化测试：绩效导入 + 截图 OCR + 单一时段/单格人数配置 + 双向换班."""
import asyncio
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = 'http://127.0.0.1:8765/index.html'
ADMIN_PWD = 'admin123'
SCREENSHOTS = ROOT / 'test_outputs'
SCREENSHOTS.mkdir(exist_ok=True)

CSV_FILE = ROOT / 'test_assets' / 'perf_ranking.csv'
PNG_FILE = ROOT / 'test_assets' / 'perf_ranking.png'
JULY_PNG_FILE = ROOT / 'test_assets' / 'perf_ranking_july.png'

EXPECTED_JULY = {
    '8593490': '1.00',
    '3065861': '0.80',
    '3072437': '1.00',
    '8027356': '0.95',
    '8091129': '1.00',
    '8191398': '1.00',
    '8596120': '0.90',
    '8593305': '1.00',
    '133122': '0.95',
    '3060017': '0.95',
    '3051105': '1.00',
    '8191272': '0.95',
    '8598314': '1.00',
    '8139540': '1.00',
    '8094271': '1.00',
    '8597644': '1.00',
    '8600441': '0.90',
}


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


async def goto_local(page, url=BASE_URL):
    await page.goto(url, wait_until='domcontentloaded')


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


async def test_july_screenshot_ocr_import(page):
    log('--- July screenshot OCR import test ---')
    await page.evaluate("""() => { document.getElementById('perfImportResult').innerHTML = ''; }""")
    # Use July 2025 to avoid overwriting current-month records from earlier tests
    await page.fill('#perfImportMonth', '2025-07')
    await page.set_input_files('#perfImportFile', str(JULY_PNG_FILE))
    await page.click('button:has-text("开始导入")')

    log('waiting for July OCR preview...')
    confirm_btn = page.locator('#perfImportConfirmBtn')
    await expect(confirm_btn).to_be_visible(timeout=300000)
    await expect(confirm_btn).to_be_enabled(timeout=300000)

    preview_text = await page.inner_text('#perfImportResult')
    log(f'July OCR preview: {preview_text[:500]}')
    await take_screenshot(page, '08_july_ocr_preview')

    # Parse preview table and verify decimal ranks, not member IDs
    rows = await page.locator('#perfImportResult .cnt-tbl tbody tr').all()
    assert rows, 'No preview rows rendered for July screenshot'
    found = {}
    bad_ranks = []
    for row in rows:
        cells = row.locator('td')
        name = await cells.nth(0).inner_text()
        rank = await cells.nth(1).inner_text()
        status = await cells.nth(2).inner_text()
        log(f'preview row: {name} -> {rank} ({status})')
        if name and rank:
            found[name] = rank
            if not re.match(r'^[0-9]+(?:\.[0-9]+)?$', rank):
                bad_ranks.append((name, rank))
            # The rank must not be the same as the member ID
            if rank == name:
                bad_ranks.append((name, rank))

    assert not bad_ranks, f'Invalid rank values detected: {bad_ranks}'
    assert len(found) >= 10, f'Expected at least 10 recognized rows, got {len(found)}'

    for name, expected_rank in EXPECTED_JULY.items():
        if name in found:
            assert found[name] == expected_rank, f'Expected {name} rank {expected_rank}, got {found[name]}'
    log(f'July OCR ranks are decimal and distinct from member IDs ({len(found)} rows)')

    # Confirm import
    await confirm_btn.click()
    await page.wait_for_selector('#perfImportResult:has-text("已导入")', timeout=10000)
    await take_screenshot(page, '09_july_ocr_import_result')
    await expect(confirm_btn).to_be_hidden()

    # Verify raw storage for one representative row
    raw = await page.evaluate("""() => {
        const arr = JSON.parse(localStorage.getItem('cperf6') || '[]');
        return arr.filter(p => p.month === '2025-07' && p.name === '8593490')[0];
    }""")
    assert raw is not None, '8593490 July record not found in localStorage'
    assert float(raw['score']) == 1.0, f'Expected raw score 1.0, got {raw["score"]}'
    log('July screenshot imported and stored correctly')


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


def future_dates():
    today = datetime.now()
    d1 = (today + timedelta(days=1)).strftime('%Y-%m-%d')
    d2 = (today + timedelta(days=2)).strftime('%Y-%m-%d')
    return d1, d2


async def setup_swap_picks(page):
    """在 localStorage 中直接写入测试所需的选班数据."""
    d1, d2 = future_dates()
    picks = {
        d1: {'1': [7]},
        d2: {'2': [8]},
    }
    await goto_local(page)
    await page.evaluate("""(picks) => {
        localStorage.clear();
        localStorage.setItem('cp6', JSON.stringify(picks));
        localStorage.setItem('ct6_v', '2');
    }""", picks)
    log(f'setup swap picks: {d1}/m1/s7, {d2}/m2/s8')


async def login_member(page, mid, pwd='123456'):
    """从员工页选择成员并输入密码."""
    await goto_local(page)
    await page.wait_for_selector('#memberSelect', state='visible', timeout=10000)
    # 清除旧绑定
    await page.evaluate("""() => {
        localStorage.removeItem('cb6');
        localStorage.removeItem('cb6exp');
        localStorage.removeItem('cb6auth');
        localStorage.removeItem('cb6authTs');
    }""")
    await page.reload()
    await page.wait_for_selector('#memberSelect', state='visible', timeout=10000)
    await page.select_option('#memberSelect', str(mid))
    await page.wait_for_selector('#pwdOverlay', state='visible', timeout=5000)
    await page.fill('#pwdInput', pwd)
    await page.click('#pwdOverlay button:has-text("验证")')
    # Wait for tabs to appear (successful login)
    await page.wait_for_selector('#empTabs', state='visible', timeout=5000)
    log(f'member {mid} logged in')


async def test_two_way_swap(page):
    log('--- Two-way shift exchange test ---')
    d1, d2 = future_dates()

    # Member 1 initiates exchange: give d1/sid=7, take d2/sid=8 from member 2
    await login_member(page, 1)
    await page.click('#tab-swap')
    await page.wait_for_timeout(300)
    await take_screenshot(page, '10_swap_m1_before')

    # Fill exchange form step by step (selects appear dynamically based on previous choice)
    swap_card = page.locator('.swap-card:has-text("发起双向换班")')

    async def select_in_card(idx, value):
        sel = swap_card.locator('select.swap-sel').nth(idx)
        await expect(sel).to_be_visible(timeout=5000)
        await sel.select_option(value)
        await page.wait_for_timeout(250)

    await select_in_card(0, d1)   # give date
    await select_in_card(1, '7')  # give sid
    await select_in_card(2, '2')  # to member id=2
    await select_in_card(3, d2)   # take date
    await select_in_card(4, '8')  # take sid

    await take_screenshot(page, '11_swap_m1_filled')

    # Click send button
    send_btn = swap_card.locator('button:has-text("发送双向换班请求")')
    await expect(send_btn).to_be_enabled(timeout=5000)
    await send_btn.click()

    # Wait for toast to reflect the send result (ignore stale login toast)
    await page.wait_for_function(
        """() => {
            const t = document.getElementById('toast');
            return t && t.classList.contains('show') && (t.textContent.includes('已发送') || t.textContent.includes('等待') || t.textContent.includes('请求已发送'));
        }""",
        timeout=5000
    )
    toast_text = await page.inner_text('#toast')
    log(f'toast: {toast_text}')
    assert '已发送' in toast_text or '等待' in toast_text, f'unexpected toast: {toast_text}'
    await take_screenshot(page, '12_swap_m1_sent')

    # Verify swap record in localStorage
    swaps = await page.evaluate("""() => JSON.parse(localStorage.getItem('cswap6') || '[]')""")
    assert len(swaps) == 1, f'expected 1 swap, got {len(swaps)}'
    s = swaps[0]
    assert s['status'] == 'pending'
    assert s['fromId'] == 1
    assert s['toId'] == 2
    assert s['date'] == d1
    assert s['sid'] == 7
    assert s['exchange']['takeDate'] == d2
    assert s['exchange']['takeSid'] == 8
    log('swap record verified')

    # Member 2 accepts the exchange
    await login_member(page, 2)
    await page.click('#tab-swap')
    await page.wait_for_timeout(300)
    await take_screenshot(page, '13_swap_m2_inbox')

    accept_btn = page.locator('.swap-req button:has-text("接受换班")')
    await expect(accept_btn).to_be_visible(timeout=5000)
    await accept_btn.click()

    await page.wait_for_function(
        """() => {
            const t = document.getElementById('toast');
            return t && t.classList.contains('show') && (t.textContent.includes('已接受') || t.textContent.includes('互换') || t.textContent.includes('已互换'));
        }""",
        timeout=5000
    )
    toast_text = await page.inner_text('#toast')
    log(f'accept toast: {toast_text}')
    assert '已接受' in toast_text or '互换' in toast_text, f'unexpected accept toast: {toast_text}'
    await take_screenshot(page, '14_swap_m2_accepted')

    # Verify picks swapped in localStorage
    picks = await page.evaluate("""() => JSON.parse(localStorage.getItem('cp6') || '{}')""")
    log(f'final picks: {picks}')
    assert picks.get(d1, {}).get('1') in ([], None), f'm1 should no longer have d1 shift: {picks}'
    assert picks.get(d2, {}).get('2') in ([], None), f'm2 should no longer have d2 shift: {picks}'
    assert 8 in picks.get(d2, {}).get('1', []), f'm1 should receive d2/s8: {picks}'
    assert 7 in picks.get(d1, {}).get('2', []), f'm2 should receive d1/s7: {picks}'
    log('picks swapped correctly')

    # Verify swap status accepted
    swaps = await page.evaluate("""() => JSON.parse(localStorage.getItem('cswap6') || '[]')""")
    assert swaps[0]['status'] == 'accepted', f'swap not accepted: {swaps[0]}'
    log('swap status accepted')


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
            await test_july_screenshot_ocr_import(page)
            await test_single_slot_capacity(page)

            # Run swap test in a fresh page to avoid admin localStorage pollution
            swap_page = await context.new_page()
            await setup_route_blocking(swap_page)
            await setup_swap_picks(swap_page)
            await test_two_way_swap(swap_page)

            log('ALL TESTS PASSED')
        except Exception as e:
            await take_screenshot(page, '99_error')
            log(f'TEST FAILED: {e}')
            raise
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(run())
