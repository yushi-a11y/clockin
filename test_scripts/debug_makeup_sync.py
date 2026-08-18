"""
排查补卡通过后员工端仍显示缺卡的根因
追踪完整链路：补卡申请 → 审批 → punch 写入 → 员工端渲染 → instPunch 匹配
"""
import asyncio, json, os, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE = 'http://127.0.0.1:18925/index.html'

def abort_extra(page):
    page.route('**/*.{woff,woff2,ttf,eot,svg,png,jpg,jpeg,gif,webp,ico}', lambda r: r.abort())
    page.route('**/supabase.co/**', lambda r: r.abort())
    page.route('**/cdn.jsdelivr.net/**', lambda r: r.abort())

async def main():
    pw = await async_playwright().start()
    page = await pw.chromium.launch_persistent_context(
        user_data_dir='/tmp/clockin_debug_makeup',
        headless=True,
        args=['--no-sandbox', '--disable-dev-shm-usage']
    )
    p = page.pages[0] if page.pages else await page.new_page()
    abort_extra(p)
    await p.goto(BASE)
    await p.wait_for_selector('#memberSelect', timeout=8000)
    clock = datetime(2026, 8, 7, 12, 0, 0)
    await p.clock.install(time=clock)
    await p.clock.set_fixed_time(clock)
    print(f'[TEST] clock installed at {clock.isoformat()}')

    # 1) 清理前序数据
    await p.evaluate("""() => { localStorage.clear(); }""")
    await p.reload()
    await p.wait_for_selector('#memberSelect', timeout=8000)

    # 2) 以 member 1 登录
    await p.select_option('#memberSelect', '1')
    await p.wait_for_timeout(500)
    pwd_input = await p.query_selector('#pwdInput')
    if pwd_input:
        await pwd_input.fill('123456')
        await p.click('#pwdSubmit')
        await p.wait_for_timeout(1000)
    print('[TEST] logged in as member 1')

    # 3) 选班：选 09:00-10:00 (sid=9) 和 10:00-11:00 (sid=10)
    await p.click('#tab-pick')
    await p.wait_for_timeout(500)
    await p.evaluate("""() => {
        const picks = {};
        const td = new Date().toISOString().slice(0,10);
        picks[td] = {1: [9, 10]};
        localStorage.setItem('cp6', JSON.stringify(picks));
        if (window.picks) window.picks = picks;
    }""")
    await p.click('#tab-punch')
    await p.wait_for_timeout(500)
    print('[TEST] shifts selected: 09-10 (sid=9), 10-11 (sid=10)')

    # 4) 检查当前 punches 状态
    punches_state = await p.evaluate("""() => {
        return JSON.stringify(window.state?.punches || {});
    }""")
    print(f'[TEST] state.punches: {punches_state[:500]}')

    # 5) 模拟管理员审批补卡 - 创建补卡记录并审批
    result = await p.evaluate("""() => {
        const td = '2026-08-07';
        
        // 创建补卡记录
        const makeup = {
            id: 'test_makeup_1',
            mid: 1,
            name: '133122',
            sid: 9,
            t: 'e',
            date: td,
            time: '10:05',
            reason: '忘记打卡',
            status: 'pending',
            ts: Date.now(),
            punchDate: td
        };
        const makeups = JSON.parse(localStorage.getItem('cmkup6') || '[]');
        makeups.push(makeup);
        localStorage.setItem('cmkup6', JSON.stringify(makeups));
        
        // 模拟管理员登录
        localStorage.setItem('cs6', String(Date.now() + 7*864e5));
        localStorage.setItem('cs6tk', 'test_token.fp');
        
        // 执行 acceptMakeup 的核心逻辑
        const m = makeups[makeups.length - 1];
        const punchDate = m.punchDate || m.date;
        const sh = window.state.shifts.find(s => s.id === m.sid);
        const rec = {
            sid: m.sid,
            t: m.t,
            time: m.time,
            ts: new Date(punchDate + 'T' + m.time).getTime(),
            mid: m.mid,
            date: punchDate,
            name: m.name,
            makeup: true,
            sd: m.date
        };
        
        // 写入 state.punches
        const s = window.state;
        const p = {...s.punches};
        if (!p[rec.date]) p[rec.date] = [];
        p[rec.date] = [...p[rec.date], rec];
        window.state = {...s, punches: p};
        localStorage.setItem('cv6', JSON.stringify(window.state));
        
        // 写入 fbPunches
        if (!window.fbPunches) window.fbPunches = [];
        const key = `${rec.sid}_${rec.t}_${rec.mid}_${rec.date}_${rec.time}`;
        if (!window.fbPunches.some(x => `${x.sid}_${x.t}_${x.mid}_${x.date}_${x.time}` === key)) {
            window.fbPunches.push(rec);
        }
        
        m.status = 'accepted';
        m.decidedTs = Date.now();
        localStorage.setItem('cmkup6', JSON.stringify(makeups));
        
        return {
            success: true,
            rec: rec,
            punchesOnDate: (window.state.punches[punchDate] || []).length,
            fbPunchesCount: window.fbPunches.length
        };
    }""")
    print(f'[TEST] acceptMakeup result: {json.dumps(result, ensure_ascii=False)}')

    # 6) 渲染员工页面
    await p.evaluate("""() => {
        if (window.renderEmp) window.renderEmp();
    }""")
    await p.wait_for_timeout(1000)

    # 7) 检查渲染后的状态
    emp_content = await p.inner_text('#empContent')
    print(f'[TEST] empContent (first 1500 chars): {emp_content[:1500]}')

    # 8) 检查 getAllPunchesForMember 的结果
    punch_check = await p.evaluate("""() => {
        const td = '2026-08-07';
        const mid = 1;
        const punches = window.getAllPunchesForMember ? window.getAllPunchesForMember(mid, td) : [];
        return punches.map(p => ({
            sid: p.sid,
            t: p.t,
            date: p.date,
            time: p.time,
            sd: p.sd,
            makeup: p.makeup
        }));
    }""")
    print(f'[TEST] getAllPunchesForMember result: {json.dumps(punch_check, ensure_ascii=False)}')

    # 9) 检查 instPunch 对 sid=9 的匹配
    inst_check = await p.evaluate("""() => {
        const td = '2026-08-07';
        const mid = 1;
        const punches = window.getAllPunchesForMember ? window.getAllPunchesForMember(mid, td) : [];
        const sh = window.state.shifts.find(s => s.id === 9);
        if (!sh) return {error: 'shift 9 not found'};
        const ep = window.instPunch ? window.instPunch(punches, sh, td, 'e') : null;
        return {
            shift: sh.name,
            endPunch: ep ? {sid: ep.sid, t: ep.t, date: ep.date, time: ep.time, sd: ep.sd} : null
        };
    }""")
    print(f'[TEST] instPunch for sid=9 end: {json.dumps(inst_check, ensure_ascii=False)}')

    # 10) 检查 shift status
    status_check = await p.evaluate("""() => {
        const td = '2026-08-07';
        const mid = 1;
        const punches = window.getAllPunchesForMember ? window.getAllPunchesForMember(mid, td) : [];
        const sh = window.state.shifts.find(s => s.id === 9);
        if (!sh || !window.ss) return {error: 'shift or ss not found'};
        const st = window.ss(sh, punches, td);
        return {
            shift: sh.name,
            ov: st.ov,
            ss: st.ss,
            es: st.es,
            sp: st.sp ? {time: st.sp.time} : null,
            ep: st.ep ? {time: st.ep.time, sd: st.ep.sd} : null
        };
    }""")
    print(f'[TEST] shift status for sid=9: {json.dumps(status_check, ensure_ascii=False)}')

    await page.close()
    await pw.stop()
    print('\n[TEST] DEBUG COMPLETE')

if __name__ == '__main__':
    asyncio.run(main())
