#!/usr/bin/env python3
"""Diagnose employee swap UI for member 9 in online mode (read-only)."""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

BASE_URL = 'http://127.0.0.1:9876/index.html'


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        logs = []
        page.on('console', lambda msg: logs.append(f'{msg.type}: {msg.text}'))
        page.on('pageerror', lambda err: logs.append(f'pageerror: {err}'))

        await page.goto(BASE_URL, wait_until='domcontentloaded')
        await page.evaluate("""() => {
            localStorage.removeItem('cb6');
            localStorage.removeItem('cb6exp');
            localStorage.removeItem('cb6auth');
            localStorage.removeItem('cb6authTs');
        }""")
        await page.reload(wait_until='domcontentloaded')
        await page.wait_for_selector('#memberSelect', state='visible', timeout=15000)
        await page.select_option('#memberSelect', '9')
        await page.wait_for_selector('#pwdOverlay', state='visible', timeout=5000)
        await page.fill('#pwdInput', '123456')
        await page.click('#pwdOverlay button:has-text("验证")')
        await page.wait_for_selector('#empTabs', state='visible', timeout=10000)
        await page.click('#tab-swap')
        await page.wait_for_timeout(800)
        # 展开单向换班日期下拉，查看可用时段
        one_way_date = page.locator('.swap-card:has-text("发起换班") select.swap-sel').first
        if await one_way_date.count():
            await one_way_date.select_option('2026-09-04')
            await page.wait_for_timeout(500)

        info = await page.evaluate("""() => {
            const selects = document.querySelectorAll('.swap-card select.swap-sel');
            const out = [];
            selects.forEach((s, i) => {
                out.push({
                    index: i,
                    label: s.previousElementSibling ? s.previousElementSibling.textContent : '',
                    options: Array.from(s.options).map(o => ({v: o.value, t: o.textContent}))
                });
            });
            return {
                fbReady: window.fbReady,
                toast: document.getElementById('toast') ? document.getElementById('toast').textContent : '',
                selects: out
            };
        }""")
        print('fbReady:', info['fbReady'])
        print('toast:', info['toast'])
        for s in info['selects']:
            print(f"select[{s['index']}] options: {s['options'][:20]}")
        print('--- console logs ---')
        for l in logs[-30:]:
            print(l)
        await browser.close()


if __name__ == '__main__':
    asyncio.run(run())
