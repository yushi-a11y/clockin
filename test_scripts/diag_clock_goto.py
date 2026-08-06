#!/usr/bin/env python3
"""诊断：clock.install 之后的首次 goto 挂起问题"""
import asyncio, datetime as dt
from playwright.async_api import async_playwright

BASE_URL = 'http://127.0.0.1:8765/index.html'


async def block_external(page):
    blocked_hosts = {'fonts.googleapis.com', 'fonts.gstatic.com'}

    async def handle_route(route):
        url = route.request.url
        if any(h in url for h in blocked_hosts) or 'supabase' in url:
            await route.abort()
        else:
            await route.continue_()

    await page.route('**/*', handle_route)


async def probe(page, label):
    try:
        ready = await page.evaluate('() => document.readyState', timeout=5000)
    except Exception as e:
        ready = f'evaluate failed: {e}'
    print(f'[{label}] readyState={ready}', flush=True)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # 场景1：不装时钟直接 goto
        ctx1 = await browser.new_context()
        pg1 = await ctx1.new_page()
        await block_external(pg1)
        try:
            await pg1.goto(BASE_URL, wait_until='domcontentloaded', timeout=20000)
            print('[no-clock] goto OK', flush=True)
        except Exception as e:
            print(f'[no-clock] goto FAILED: {e}', flush=True)
        await probe(pg1, 'no-clock')
        await ctx1.close()

        # 场景2：先 clock.install 再 goto
        ctx2 = await browser.new_context()
        pg2 = await ctx2.new_page()
        await block_external(pg2)
        t = dt.datetime.now().replace(hour=9, minute=2, second=0, microsecond=0)
        await pg2.clock.install(time=t)
        try:
            await pg2.goto(BASE_URL, wait_until='domcontentloaded', timeout=20000)
            print('[clock-first] goto OK', flush=True)
        except Exception as e:
            print(f'[clock-first] goto FAILED: {e}', flush=True)
        await probe(pg2, 'clock-first')
        await ctx2.close()

        # 场景3：先 goto，再 clock.install，再 reload
        ctx3 = await browser.new_context()
        pg3 = await ctx3.new_page()
        await block_external(pg3)
        await pg3.goto(BASE_URL, wait_until='domcontentloaded', timeout=20000)
        t = dt.datetime.now().replace(hour=9, minute=2, second=0, microsecond=0)
        await pg3.clock.install(time=t)
        try:
            await pg3.reload(wait_until='domcontentloaded', timeout=20000)
            print('[goto-then-clock-reload] reload OK', flush=True)
        except Exception as e:
            print(f'[goto-then-clock-reload] reload FAILED: {e}', flush=True)
        await probe(pg3, 'goto-then-clock-reload')
        await ctx3.close()

        await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
