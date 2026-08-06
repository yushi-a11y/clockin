#!/usr/bin/env python3
"""ClockIn v2026.08.07.17 离线打卡补同步队列测试（报告 A-3）：
阶段 A：Supabase CDN 被阻断（fbReady=false，真离线）→ 打卡应本地生效、
        标记 offline:true、员工端出现"离"标签、记录进入 copq6 队列
阶段 B：注入 window.supabase mock 模拟网络恢复 → flushOfflinePunches 应
         sanitize 掉 offline 字段（云端表无此列）、云端去重、清空队列、提示补同步成功
"""
import datetime as dt
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright, expect

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


async def shot(page, name):
    try:
        await page.screenshot(path=str(SHOTS / f'{name}.png'), full_page=True)
        log(f'screenshot: {name}')
    except Exception as e:
        log(f'screenshot failed for {name}: {e}')


async def wait_toast(page, text, timeout=10000):
    await page.wait_for_function(
        "() => { const t = document.getElementById('toast'); return !!t && t.textContent.includes('%s') }" % text,
        timeout=timeout)


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
        localStorage.removeItem('cb6');
        localStorage.removeItem('cb6exp');
        localStorage.removeItem('cb6auth');
        localStorage.removeItem('cb6authTs');
        localStorage.removeItem('cs6');
        localStorage.removeItem('cs6tk');
    }""")


async def login_member(page, mid):
    if not await page.evaluate('() => !!document.getElementById("memberSelect")'):
        await goto_robust(page)
    await page.wait_for_selector('#memberSelect option:not([value=""])', state='attached', timeout=25000)
    await page.select_option('#memberSelect', str(mid))
    await page.wait_for_selector('#pwdOverlay', state='visible', timeout=10000)
    await page.fill('#pwdInput', '123456')
    await page.click('#pwdOverlay .btn.p')
    await page.wait_for_function('() => !!selectedMember', timeout=15000)
    name = await page.evaluate('() => selectedMember.name')
    log(f'logged in as member {mid} ({name})')


async def seed_picks(page, date_str, mid, sids):
    await page.evaluate("""(args) => {
        const [ds, mid, sids] = args;
        if (!picks[ds]) picks[ds] = {};
        picks[ds][mid] = sids.slice();
        sv('cp6', picks);
    }""", [date_str, mid, sids])


async def test_offline_punch_queue(page):
    log('--- 阶段 A：离线打卡标记 + 入队 ---')
    real_now = dt.datetime.now()
    t_0902 = real_now.replace(hour=9, minute=2, second=0, microsecond=0)
    await page.clock.install(time=t_0902)
    await clear_state(page)

    fb = await page.evaluate('() => fbReady')
    assert fb is False, f'CDN 应被阻断从而 fbReady=false，实际 {fb}'
    log('fbReady=false（离线状态确认）')

    mid = 1
    today = await page.evaluate('() => tdStr()')
    await seed_picks(page, today, mid, [9])  # 09:00-10:00
    await login_member(page, mid)
    await page.evaluate('() => renderEmp()')

    btn = page.locator('.punch-btn:not(.off)')
    await expect(btn).to_contain_text('上班打卡', timeout=10000)
    await btn.click()
    await wait_toast(page, '打卡成功（离线）')
    log('离线打卡 toast 正确')

    checks = await page.evaluate("""() => {
        const d = tdStr();
        const rec = (state.punches[d] || []).find(p => p.sid === 9 && p.t === 's');
        const q = JSON.parse(localStorage.getItem('copq6') || '[]');
        return {
            recOffline: !!(rec && rec.offline),
            qLen: q.length,
            qOffline: q.length ? !!q[0].offline : false,
            qKeyOk: q.length ? (q[0].sid === 9 && q[0].t === 's' && q[0].mid === 1 && q[0].date === d) : false,
            tag: document.querySelectorAll('.off-tag').length
        };
    }""")
    assert checks['recOffline'], f'本地打卡记录应带 offline 标记: {checks}'
    assert checks['qLen'] == 1, f'copq6 队列应有 1 条: {checks}'
    assert checks['qOffline'], f'队列记录应保留 offline 标记: {checks}'
    assert checks['qKeyOk'], f'队列记录字段不完整: {checks}'
    assert checks['tag'] >= 1, f'员工端应显示"离"标签: {checks}'
    log('offline 标记 + 队列 + "离"标签 全部正确')
    await shot(page, 'opq_a_offline_punch')

    log('--- 阶段 B：模拟网络恢复，flush 补同步 ---')
    await page.evaluate("""() => {
        window.__opqInserts = [];
        window.__opqSelects = [];
        window.supabase = {
            createClient: () => ({
                from(table) {
                    return {
                        select(cols) {
                            const filters = {};
                            const chain = {
                                eq(c, v) { filters[c] = v; return chain; },
                                limit(n) {
                                    if (table === 'config') return Promise.resolve({ data: [{ id: '_probe' }], error: null });
                                    window.__opqSelects.push({ table, filters });
                                    return Promise.resolve({ data: [], error: null }); // 云端无同键记录
                                }
                            };
                            return chain;
                        },
                        insert(row) {
                            window.__opqInserts.push({ table, row });
                            return Promise.resolve({ data: [row], error: null });
                        }
                    };
                }
            })
        };
    }""")
    await page.evaluate('() => flushOfflinePunches()')
    await wait_toast(page, '已补同步')

    after = await page.evaluate("""() => {
        const q = JSON.parse(localStorage.getItem('copq6') || '[]');
        return { qLen: q.length, inserts: window.__opqInserts, selects: window.__opqSelects, fbReady: fbReady };
    }""")
    assert after['fbReady'] is True, f'ensureSupabaseReady 应懒重建客户端: {after}'
    assert after['qLen'] == 0, f'flush 后队列应清空: {after}'
    # 注意：flush 成功后 logEvent 还会向 logs 表写审计，这里只校验 punches 表的补写
    punch_inserts = [i for i in after['inserts'] if i['table'] == 'punches']
    assert len(punch_inserts) == 1, f'应恰好补写 1 条云端打卡: {after}'
    row = punch_inserts[0]['row']
    assert 'offline' not in row, f'云端写入必须剔除 offline 字段（表无此列）: {row}'
    assert row.get('sid') == 9 and row.get('t') == 's' and row.get('mid') == 1, f'补写记录字段错误: {row}'
    assert row.get('date') and row.get('time'), f'补写记录缺 date/time: {row}'
    assert len(after['selects']) == 1, f'补写前应先做云端去重查询: {after}'
    log('补同步成功：队列清空、payload 已 sanitize、去重查询已执行')
    await shot(page, 'opq_b_flushed')

    log('--- 阶段 C：幂等性——再次 flush 不应重复写入 ---')
    await page.evaluate("""() => {
        // 模拟云端已有该打卡（去重查询命中）
        window.__opqInserts = [];
        window.supabase.createClient = () => ({
            from(table) {
                return {
                    select(cols) {
                        const chain = {
                            eq(c, v) { return chain; },
                            limit(n) {
                                if (table === 'config') return Promise.resolve({ data: [{ id: '_probe' }], error: null });
                                return Promise.resolve({ data: [{ id: 999 }], error: null }); // 已存在
                            }
                        };
                        return chain;
                    },
                    insert(row) { window.__opqInserts.push({ table, row }); return Promise.resolve({ data: [row], error: null }); }
                };
            }
        });
        // 人为再塞一条同键记录进队列
        const d = tdStr();
        localStorage.setItem('copq6', JSON.stringify([{ sid: 9, t: 's', time: '09:02', ts: Date.now(), mid: 1, date: d, name: selectedMember.name, offline: true }]));
        // fbReady 已为 true，ensureSupabaseReady 不会重建，需显式替换活动客户端
        supa = window.supabase.createClient();
    }""")
    await page.evaluate('() => flushOfflinePunches(true)')
    after2 = await page.evaluate("""() => {
        const q = JSON.parse(localStorage.getItem('copq6') || '[]');
        return { qLen: q.length, inserts: window.__opqInserts };
    }""")
    assert after2['qLen'] == 0, f'云端已存在时应直接销账: {after2}'
    punch_inserts2 = [i for i in after2['inserts'] if i['table'] == 'punches']
    assert len(punch_inserts2) == 0, f'云端已存在时不得重复插入: {after2}'
    log('幂等性正确：云端已有同键记录时仅销账、不重复插入')

    log('OFFLINE_QUEUE TEST PASSED')


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        page.on('pageerror', lambda err: log(f'PAGE ERROR: {err}'))
        await block_external(page)
        try:
            await test_offline_punch_queue(page)
            log('ALL TESTS PASSED')
        except Exception as e:
            await shot(page, 'opq_99_error')
            log(f'TEST FAILED: {e}')
            raise
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(run())
