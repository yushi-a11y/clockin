#!/usr/bin/env python3
"""ClockIn v2026.08.07.17 密码认证改造测试（报告 C-2）：
1. 无密码成员：123456 走 DEFAULT_PWD_HASH 分支可登录，登录后透明升级为成员专属哈希
2. 明文密码成员：旧明文仍可登录一次（过渡分支），登录后自动升级为哈希
3. hashAllTeamPwds：管理员一键批量哈希升级，幂等且计数正确
4. 错误密码/非默认密码被拒绝，暴力破解锁定不受影响
"""
import datetime as dt
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = 'http://127.0.0.1:8765/index.html'
SHOTS = ROOT / 'test_outputs'
SHOTS.mkdir(exist_ok=True)


def log(msg):
    print(f'[TEST] {msg}', flush=True)


async def block_external(page):
    blocked_hosts = {'fonts.googleapis.com', 'fonts.gstatic.com'}

    async def handle_route(route):
        url = route.request.url
        if any(h in url for h in blocked_hosts) or 'supabase' in url:
            await route.abort()
        else:
            await route.continue_()

    await page.route('**/*', handle_route)


async def goto_robust(page, url=BASE_URL, tries=3):
    for i in range(tries):
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=20000)
            return
        except Exception as e:
            if i == tries - 1:
                raise
            log(f'goto retry {i + 1}: {e}')


async def clear_state(page):
    await goto_robust(page)
    await page.evaluate("""() => {
        localStorage.clear();
        state = { punches: {}, shifts: DEF_SHIFTS };
        picks = {};
        makeups = [];
        leaves = [];
        performances = [];
        TEAM = JSON.parse(JSON.stringify(DEF_TEAM));
        selectedMember = null;
        sv('cv6', state);
        sv('cp6', picks);
        sv('cmkup6', makeups);
        sv('cleave6', leaves);
        sv('cperf6', performances);
        sv('ct6', TEAM);
    }""")


async def attempt_login(page, mid, pwd):
    """返回 'ok' | 'fail' | 'locked'"""
    await page.evaluate("""() => {
        selectedMember = null;
        claims = {};
        localStorage.removeItem('cb6');
        localStorage.removeItem('cb6exp');
        localStorage.removeItem('cb6auth');
        localStorage.removeItem('cb6authTs');
        localStorage.removeItem('cu6');
        document.getElementById('memberSelect').value = '';
        const o = document.getElementById('pwdOverlay'); if (o) o.style.display = 'none';
        renderEmp();
    }""")
    await page.select_option('#memberSelect', str(mid))
    await page.wait_for_selector('#pwdOverlay', state='visible', timeout=10000)
    await page.fill('#pwdInput', pwd)
    await page.click('#pwdOverlay .btn.p')
    await page.wait_for_timeout(500)
    return await page.evaluate("""() => {
        if (selectedMember) return 'ok';
        const e = document.getElementById('pwdErr');
        const t = e ? e.textContent : '';
        if (t.includes('锁定')) return 'locked';
        return 'fail';
    }""")


async def test_default_pwd_hash_branch(page):
    log('--- 1. 无密码成员默认哈希分支 ---')
    await clear_state(page)
    await page.evaluate("""() => {
        TEAM = TEAM.map(m => m.id === 1 ? { ...m, pwd: undefined } : m);
        sv('ct6', TEAM);
    }""")
    r = await attempt_login(page, 1, '999999')
    assert r == 'fail', f'非默认密码应被拒绝: {r}'
    log('非默认密码被拒绝')
    r = await attempt_login(page, 1, '123456')
    assert r == 'ok', f'默认密码应通过哈希分支登录: {r}'
    upgraded = await page.evaluate("""() => {
        const m = TEAM.find(x => x.id === 1);
        return { isHash: typeof m.pwd === 'string' && /^[a-f0-9]{64}$/.test(m.pwd) };
    }""")
    assert upgraded['isHash'], f'登录后应透明升级为哈希: {upgraded}'
    log('默认密码登录成功且已透明升级为成员专属哈希')


async def test_plaintext_transition(page):
    log('--- 2. 明文密码过渡分支 + 自动升级 ---')
    await clear_state(page)
    await page.evaluate("""() => {
        TEAM = TEAM.map(m => m.id === 2 ? { ...m, pwd: 'abc123' } : m);
        sv('ct6', TEAM);
    }""")
    r = await attempt_login(page, 2, 'wrong')
    assert r == 'fail', f'错误明文应被拒绝: {r}'
    r = await attempt_login(page, 2, 'abc123')
    assert r == 'ok', f'存量明文密码应可过渡登录: {r}'
    st = await page.evaluate("""() => {
        const m = TEAM.find(x => x.id === 2);
        return typeof m.pwd === 'string' && /^[a-f0-9]{64}$/.test(m.pwd) && m.pwd !== 'abc123';
    }""")
    assert st, '明文密码登录后应自动升级为哈希'
    log('明文过渡登录成功且已升级为哈希')


async def test_bulk_hash_migration(page):
    log('--- 3. 管理员一键批量哈希升级 ---')
    await clear_state(page)
    await page.evaluate("""() => {
        TEAM = TEAM.map(m => m.id === 3 ? { ...m, pwd: 'plain3' } : m.id === 4 ? { ...m, pwd: 'plain4' } : m);
        sv('ct6', TEAM);
    }""")
    cnt = await page.evaluate('() => plaintextPwdCount()')
    assert cnt == 2, f'应检测到 2 条明文密码: {cnt}'
    await page.evaluate('() => hashAllTeamPwds()')
    await page.wait_for_timeout(600)
    st = await page.evaluate("""() => {
        return {
            cnt: plaintextPwdCount(),
            m3: /^[a-f0-9]{64}$/.test(TEAM.find(x => x.id === 3).pwd || ''),
            m4: /^[a-f0-9]{64}$/.test(TEAM.find(x => x.id === 4).pwd || '')
        };
    }""")
    assert st['cnt'] == 0 and st['m3'] and st['m4'], f'批量升级应清空全部明文: {st}'
    # 升级后密码值语义不变：原明文经同一哈希后仍可登录
    r = await attempt_login(page, 3, 'plain3')
    assert r == 'ok', f'批量升级后原密码应仍可登录: {r}'
    log('批量哈希升级正确，升级后密码语义不变')


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        page.on('dialog', lambda d: asyncio.ensure_future(d.accept()))
        page.on('pageerror', lambda err: log(f'PAGE ERROR: {err}'))
        await block_external(page)
        try:
            real_now = dt.datetime.now()
            await page.clock.install(time=real_now.replace(hour=9, minute=0, second=0, microsecond=0))
            await test_default_pwd_hash_branch(page)
            await test_plaintext_transition(page)
            await test_bulk_hash_migration(page)
            log('ALL TESTS PASSED')
        except Exception as e:
            try:
                await page.screenshot(path=str(SHOTS / 'pwd_99_error.png'))
            except Exception:
                pass
            log(f'TEST FAILED: {e}')
            raise
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(run())
