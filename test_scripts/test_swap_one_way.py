#!/usr/bin/env python3
"""ClockIn 单向换班功能聚焦测试（离线模式，不触碰生产数据）."""
import asyncio
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


def future_date(days=7):
    return (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')


async def setup_picks(page):
    """在 localStorage 中写入测试所需的选班与团队数据."""
    d1 = future_date(7)
    # 成员 9 (8191272) 在 d1 有 sid=23 的班；成员 5 (3072437) 无班
    picks = {d1: {'9': [23], '5': []}}
    await page.goto(BASE_URL, wait_until='domcontentloaded')
    await page.evaluate("""(picks) => {
        localStorage.clear();
        localStorage.setItem('cp6', JSON.stringify(picks));
        localStorage.setItem('ct6_v', '2');
    }""", picks)
    log(f'setup picks: {d1}/m9/s23 -> m5')


async def login_member(page, mid, pwd='123456'):
    """选择成员并输入密码；保留 cp6/cswap6 等测试数据."""
    await page.goto(BASE_URL, wait_until='domcontentloaded')
    await page.wait_for_selector('#memberSelect', state='visible', timeout=10000)
    # 只清除设备绑定相关键，保留选班/换班/团队数据
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
    await page.wait_for_selector('#empTabs', state='visible', timeout=5000)
    log(f'member {mid} logged in')


async def test_one_way_swap(page):
    log('--- One-way shift transfer test ---')
    d1 = future_date(7)

    # Member 9 initiates transfer of sid=23 to member 5
    await login_member(page, 9)
    await page.click('#tab-swap')
    await page.wait_for_timeout(300)
    await take_screenshot(page, 'oneway_m9_before')

    swap_card = page.locator('.swap-card:has-text("发起换班")')

    async def select_in_card(label_or_index, value):
        sel = swap_card.locator('select.swap-sel').nth(label_or_index)
        await expect(sel).to_be_visible(timeout=5000)
        await sel.select_option(value)
        await page.wait_for_timeout(250)

    await select_in_card(0, d1)   # date
    await select_in_card(1, '23')  # sid
    await select_in_card(2, '5')  # to member id=5

    await take_screenshot(page, 'oneway_m9_filled')

    send_btn = swap_card.locator('button:has-text("发送换班请求")')
    await expect(send_btn).to_be_enabled(timeout=5000)
    await send_btn.click()

    await page.wait_for_function(
        """() => {
            const t = document.getElementById('toast');
            return t && t.classList.contains('show') && (t.textContent.includes('已发送') || t.textContent.includes('等待'));
        }""",
        timeout=5000
    )
    toast_text = await page.inner_text('#toast')
    log(f'toast: {toast_text}')
    assert '已发送' in toast_text or '等待' in toast_text, f'unexpected toast: {toast_text}'
    await take_screenshot(page, 'oneway_m9_sent')

    swaps = await page.evaluate("""() => JSON.parse(localStorage.getItem('cswap6') || '[]')""")
    assert len(swaps) == 1, f'expected 1 swap, got {len(swaps)}'
    s = swaps[0]
    assert s['status'] == 'pending'
    assert str(s['fromId']) == '9'
    assert str(s['toId']) == '5'
    assert s['date'] == d1
    assert s['sid'] == 23
    log('swap record verified')

    # Member 5 accepts
    await login_member(page, 5)
    await page.click('#tab-swap')
    await page.wait_for_timeout(300)
    await take_screenshot(page, 'oneway_m5_inbox')

    accept_btn = page.locator('.swap-req button:has-text("接受")')
    await expect(accept_btn).to_be_visible(timeout=5000)
    await accept_btn.click()

    await page.wait_for_function(
        """() => {
            const t = document.getElementById('toast');
            return t && t.classList.contains('show') && (t.textContent.includes('已接受') || t.textContent.includes('已转到'));
        }""",
        timeout=5000
    )
    toast_text = await page.inner_text('#toast')
    log(f'accept toast: {toast_text}')
    assert '已接受' in toast_text, f'unexpected accept toast: {toast_text}'
    await take_screenshot(page, 'oneway_m5_accepted')

    picks = await page.evaluate("""() => JSON.parse(localStorage.getItem('cp6') || '{}')""")
    log(f'final picks: {picks}')
    assert picks.get(d1, {}).get('9') in ([], None), f'm9 should no longer have d1 shift: {picks}'
    assert 23 in picks.get(d1, {}).get('5', []), f'm5 should receive d1/s23: {picks}'
    log('picks transferred correctly')

    swaps = await page.evaluate("""() => JSON.parse(localStorage.getItem('cswap6') || '[]')""")
    assert swaps[0]['status'] == 'accepted', f'swap not accepted: {swaps[0]}'
    log('swap status accepted')


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        # 阻断所有外部请求，强制离线模式，避免触碰生产 Firestore
        await page.route('**/*', lambda route: route.continue_()
                        if route.request.url.startswith('http://127.0.0.1:9876/')
                        else route.abort())
        try:
            await setup_picks(page)
            await test_one_way_swap(page)
            log('ALL ONE-WAY SWAP TESTS PASSED')
        except Exception as e:
            await take_screenshot(page, '99_oneway_error')
            log(f'ONE-WAY SWAP TEST FAILED: {e}')
            raise
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(run())
