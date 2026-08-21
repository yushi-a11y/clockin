#!/usr/bin/env python3
"""ClockIn 双向换班功能聚焦测试."""
import asyncio
import re
from datetime import datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = 'http://127.0.0.1:9876/index.html'
SCREENSHOTS = ROOT / 'test_outputs'
SCREENSHOTS.mkdir(exist_ok=True)


def log(msg):
    print(f'[TEST] {msg}', flush=True)


async def take_screenshot(page, name):
    path = SCREENSHOTS / f'{name}.png'
    try:
        await page.screenshot(path=str(path), full_page=False)
        log(f'screenshot saved: {path}')
    except Exception as e:
        log(f'screenshot failed for {name}: {e}')
    return path


def future_dates():
    today = datetime.now()
    d1 = (today + timedelta(days=1)).strftime('%Y-%m-%d')
    d2 = (today + timedelta(days=2)).strftime('%Y-%m-%d')
    return d1, d2


async def setup_picks(page):
    """在 localStorage 中直接写入测试所需的选班数据."""
    d1, d2 = future_dates()
    # 成员 1 (id=1) 在 d1 有 sid=7 的班；成员 2 (id=2) 在 d2 有 sid=8 的班
    picks = {
        d1: {'1': [7]},
        d2: {'2': [8]},
    }
    await page.goto(BASE_URL, wait_until='domcontentloaded')
    await page.evaluate("""(picks) => {
        localStorage.clear();
        localStorage.setItem('cp6', JSON.stringify(picks));
        localStorage.setItem('ct6_v', '2');
    }""", picks)
    log(f'setup picks: {d1}/m1/s7, {d2}/m2/s8')


async def login_member(page, mid, pwd='123456'):
    """从员工页选择成员并输入密码."""
    await page.goto(BASE_URL, wait_until='domcontentloaded')
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
    await take_screenshot(page, 'swap_m1_before')

    # Fill exchange form step by step (selects appear dynamically based on previous choice)
    swap_card = page.locator('.swap-card:has-text("发起双向换班")')

    async def select_in_card(label_or_index, value):
        sel = swap_card.locator('select.swap-sel').nth(label_or_index)
        await expect(sel).to_be_visible(timeout=5000)
        await sel.select_option(value)
        await page.wait_for_timeout(250)

    await select_in_card(0, d1)   # give date
    await select_in_card(1, '7')  # give sid
    await select_in_card(2, '2')  # to member id=2
    await select_in_card(3, d2)   # take date
    await select_in_card(4, '8')  # take sid

    await take_screenshot(page, 'swap_m1_filled')

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
    await take_screenshot(page, 'swap_m1_sent')

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
    await take_screenshot(page, 'swap_m2_inbox')

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
    await take_screenshot(page, 'swap_m2_accepted')

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
        # 外部 CDN（字体、Supabase、Tesseract、xlsx）在部分网络下加载缓慢，测试只依赖本地资源
        await page.route('**/*', lambda route: route.continue_()
                        if route.request.url.startswith('http://127.0.0.1:9876/')
                        else route.abort())
        try:
            await setup_picks(page)
            await test_two_way_swap(page)
            log('ALL SWAP TESTS PASSED')
        except Exception as e:
            await take_screenshot(page, '99_swap_error')
            log(f'SWAP TEST FAILED: {e}')
            raise
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(run())
