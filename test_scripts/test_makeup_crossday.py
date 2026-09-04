#!/usr/bin/env python3
"""验证问题2：8/7 0点上班缺卡补卡全流程。

场景（承接用户真实经历）：
- 8/6 晚 22-23 / 23-0 上班卡正常，但 23-0 的下班卡因旧 bug 没打上（缺 e）。
- 8/7 0-1 / 1-2 的上班卡也因此没打上（缺 s）。
- 员工在补卡界面应能分别看到：昨日跨天 23-0 下班缺卡、0-1 上班缺卡、1-2 上班缺卡。
- 申请 0-1 上班补卡 → 管理员批准 → 应写入 (sid24, s, date=8/7, sd=8/7)，
  并按连班交接同步补上 (sid23, e, date=8/7, sd=8/6)。
- 批准后：员工端 23-0 昨日跨天卡消失（已收尾）、0-1 显示上班已打；
  补卡界面不允许对同一实例二次申请。
"""
import datetime as dt
import asyncio
from playwright.async_api import async_playwright

BASE_URL = 'http://127.0.0.1:9876/index.html'
SIDS = [24, 25, 11, 12, 13, 22, 23]
MID = 1


def log(m):
    print(m, flush=True)


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await (await b.new_context()).new_page()
        page.on('pageerror', lambda e: log(f'[pageerror] {e}'))

        async def block_external(route):
            if route.request.url.startswith('http://127.0.0.1:9876/'):
                await route.continue_()
            else:
                await route.abort()
        await page.route('**/*', block_external)
        await page.clock.install(time=dt.datetime(2026, 8, 7, 9, 0))
        await page.goto(BASE_URL, wait_until='domcontentloaded', timeout=20000)
        await page.evaluate("""(a)=>{
            const [sids,mid]=a;
            localStorage.clear();
            state={punches:{},shifts:DEF_SHIFTS};
            picks={};
            ['2026-08-06','2026-08-07'].forEach(d=>{picks[d]={};picks[d][mid]=sids.slice()});
            // 8/6 晚：22-23 完整、23-0 只有上班卡（下班卡被旧 bug 吞了）
            state.punches['2026-08-06']=[
                {sid:22,t:'s',time:'22:00',ts:0,mid,date:'2026-08-06',name:'x'},
                {sid:22,t:'e',time:'23:00',ts:0,mid,date:'2026-08-06',name:'x'},
                {sid:23,t:'s',time:'23:00',ts:0,mid,date:'2026-08-06',name:'x',sd:'2026-08-06'}
            ];
            makeups=[];leaves=[];performances=[];
            TEAM=JSON.parse(JSON.stringify(DEF_TEAM)); selectedMember=null;
            sv('cv6',state);sv('cp6',picks);sv('cmkup6',makeups);sv('cleave6',leaves);
            sv('cperf6',performances);sv('ct6',TEAM);
        }""", [SIDS, MID])
        # login
        await page.evaluate("() => {['cb6','cb6exp','cb6auth','cb6authTs'].forEach(k=>localStorage.removeItem(k));}")
        await page.evaluate('() => renderEmp()')
        await page.wait_for_selector('#memberSelect option:not([value=""])', state='attached', timeout=25000)
        await page.select_option('#memberSelect', str(MID))
        await page.wait_for_selector('#pwdOverlay', state='visible', timeout=10000)
        await page.fill('#pwdInput', '123456')
        await page.click('#pwdOverlay .btn.p')
        await page.wait_for_function('() => !!selectedMember', timeout=15000)

        # ---- 1) 补卡界面：选 8/7，列出可选缺卡班次 ----
        await page.evaluate("() => setEmpTab('makeup')")
        await page.wait_for_timeout(200)
        await page.evaluate("() => setMakeupDate('2026-08-07')")
        await page.wait_for_timeout(200)
        opts = await page.evaluate("""() => Array.from(document.querySelectorAll('#empContent select'))
            .map(s=>Array.from(s.options).map(o=>o.value+'|'+o.textContent.trim()))""")
        log('---- 补卡班次选项（8/7 视图）----')
        for group in opts:
            for o in group:
                log('   ' + o)
        flat = [o for g in opts for o in g]
        assert any(v.startswith('23_2026-08-06') for v in flat), '缺少昨日跨天 23-0 下班缺卡选项'
        assert any(v.startswith('24_2026-08-07') for v in flat), '缺少 0-1 上班缺卡选项'
        assert any(v.startswith('25_2026-08-07') for v in flat), '缺少 1-2 上班缺卡选项'
        log('✓ 选项完整：昨日跨天 23-0 / 0-1 / 1-2 缺卡均可申请')

        # ---- 2) 申请 0-1 上班补卡 ----
        await page.evaluate("() => setMakeupSid('24_2026-08-07')")
        await page.wait_for_timeout(150)
        await page.evaluate("() => setMakeupTime('00:05')")
        await page.evaluate("() => setMakeupReason('当时没有打卡按钮')")
        await page.evaluate('() => submitMakeup()')
        await page.wait_for_timeout(300)
        mk = await page.evaluate('() => makeups')
        assert len(mk) == 1, f'补卡申请数应为1，实际 {len(mk)}'
        m = mk[0]
        log(f'✓ 已提交补卡申请: date(pickDate)={m["date"]} punchDate={m["punchDate"]} sid={m["sid"]} t={m["t"]} time={m["time"]}')
        assert m['date'] == '2026-08-07', '补卡申请的选班日期应为 8/7（问题2核心：不能再错位到次日）'
        assert m['punchDate'] == '2026-08-07', '打卡落账日期应为 8/7'
        assert m['t'] == 's'

        # ---- 3) 重复申请防护：同一实例不应再出现在可选列表 ----
        await page.evaluate("() => setEmpTab('makeup')")
        await page.wait_for_timeout(150)
        await page.evaluate("() => setMakeupDate('2026-08-07')")
        await page.wait_for_timeout(150)
        opts2 = await page.evaluate("""() => {
            const sels=Array.from(document.querySelectorAll('#empContent select'));
            return sels.length>1?Array.from(sels[1].options).map(o=>o.value):[];
        }""")
        log('  待审批后剩余可选班次: ' + (', '.join(opts2) if opts2 else '(空)'))
        assert '24_2026-08-07' not in opts2, '问题2：已申请的实例仍能二次申请！'
        log('✓ 0-1 已不可二次申请（pending 去重生效）')

        # ---- 4) 管理员批准 ----
        await page.evaluate("() => {localStorage.setItem('cs6', String(Date.now()+86400000)); window.confirm=()=>true;}")
        await page.evaluate('() => acceptMakeup(makeups[0].id)')
        await page.wait_for_timeout(500)
        recs = await page.evaluate("""()=>{const o=[];Object.keys(state.punches).sort().forEach(d=>
            (state.punches[d]||[]).forEach(p=>o.push({d,sid:p.sid,t:p.t,time:p.time,sd:p.sd||'-'})));return o}""")
        log('---- 批准后打卡记录 ----')
        for r in recs:
            log(f'   {r["d"]} sid={r["sid"]} {r["t"]} @{r["time"]} sd={r["sd"]}')
        st = await page.evaluate("() => makeups[0].status")
        assert st == 'accepted', f'补卡状态应为 accepted，实际 {st}'
        assert any(r['d'] == '2026-08-07' and r['sid'] == 24 and r['t'] == 's' and r['sd'] == '2026-08-07' for r in recs), \
            '缺少 0-1 上班补卡记录（sd=8/7）'
        assert any(r['d'] == '2026-08-07' and r['sid'] == 23 and r['t'] == 'e' and r['sd'] == '2026-08-06' for r in recs), \
            '缺少连班交接同步补卡：23-0(昨日实例) 下班记录（sd=8/6）'
        log('✓ 批准写入正确：0-1 上班(sd=8/7) + 23-0 昨日实例下班(sd=8/6) 交接同步')

        # ---- 5) 员工端状态：23-0 已收尾不再挂"昨日跨天"，0-1 上班已打 ----
        await page.evaluate("() => setEmpTab('punch')")
        await page.wait_for_timeout(300)
        cards = await page.evaluate("""()=>Array.from(document.querySelectorAll('.pc')).map(c=>({
            name:(c.querySelector('.pc-range')||{}).textContent?.replace(/\\s+/g,' ').trim()||'',
            status:(c.querySelector('.pc-status')||{}).textContent?.trim()||'',
            marks:Array.from(c.querySelectorAll('.pc-chk')).map(x=>x.textContent.trim()).join('')}))""")
        for c in cards:
            log(f'   {c["name"]:<28} [{c["marks"]}] {c["status"]}')
        assert not any('待收尾' in c['name'] for c in cards), '问题2：批准后昨日跨天 23-0 仍未收尾'
        c01 = next(c for c in cards if c['name'].startswith('00:00-01:00'))
        assert c01['marks'].startswith('✓'), f'问题2：0-1 上班补卡后仍未显示上班已打: {c01}'
        log('✓ 员工端显示正确：昨日跨天已收尾，0-1 上班卡可见')

        # ---- 6) 补卡界面复核：0-1 上班不再缺卡（只剩下班缺卡），23-0 不再出现 ----
        await page.evaluate("() => setEmpTab('makeup')")
        await page.wait_for_timeout(150)
        await page.evaluate("() => setMakeupDate('2026-08-07')")
        await page.wait_for_timeout(150)
        opts3 = await page.evaluate("""() => {
            const sels=Array.from(document.querySelectorAll('#empContent select'));
            return sels.length>1?Array.from(sels[1].options).map(o=>o.value+'|'+o.textContent.trim()):[];
        }""")
        log('---- 批准后补卡选项 ----')
        for o in opts3:
            log('   ' + o)
        assert not any(v.startswith('23_2026-08-06') for v in opts3), '23-0 昨日实例已补齐，不应再出现'
        o24 = [v for v in opts3 if v.startswith('24_2026-08-07')]
        assert len(o24) == 1 and '下班缺卡' in o24[0], f'0-1 应只剩下班缺卡: {o24}'
        log('✓ 补卡界面复核通过：23-0 消失，0-1 只剩下班缺卡')

        log('\n===== 问题2 全流程验证通过 =====')
        await b.close()


asyncio.run(main())
