#!/usr/bin/env python3
"""调试：8/6 23:59 打完 23-0 下班卡后，各实例的匹配细节。"""
import datetime as dt
import asyncio
from playwright.async_api import async_playwright

BASE_URL = 'http://127.0.0.1:8765/index.html'
SIDS = [24, 25, 11, 12, 13, 22, 23]
MID = 1


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await (await b.new_context()).new_page()
        page.on('pageerror', lambda e: print('[pageerror]', e, flush=True))

        async def block_external(route):
            u = route.request.url
            if 'fonts.g' in u or 'supabase' in u:
                await route.abort()
            else:
                await route.continue_()
        await page.route('**/*', block_external)
        await page.clock.install(time=dt.datetime(2026, 8, 6, 23, 58))
        await page.goto(BASE_URL, wait_until='domcontentloaded', timeout=20000)
        await page.evaluate("""(a)=>{
            const [sids,mid]=a;
            localStorage.clear();
            state={punches:{},shifts:DEF_SHIFTS};
            picks={};
            ['2026-08-05','2026-08-06'].forEach(d=>{picks[d]={};picks[d][mid]=sids.slice()});
            state.punches['2026-08-05']=[{sid:23,t:'s',time:'23:00',ts:0,mid,date:'2026-08-05',name:'x'}];
            state.punches['2026-08-06']=[
                {sid:23,t:'e',time:'00:00',ts:0,mid,date:'2026-08-06',name:'x'},
                {sid:22,t:'s',time:'22:00',ts:0,mid,date:'2026-08-06',name:'x'},
                {sid:22,t:'e',time:'23:00',ts:0,mid,date:'2026-08-06',name:'x'},
                {sid:23,t:'s',time:'23:00',ts:0,mid,date:'2026-08-06',name:'x',sd:'2026-08-06'},
                {sid:23,t:'e',time:'23:59',ts:0,mid,date:'2026-08-06',name:'x',sd:'2026-08-06'},
                {sid:24,t:'s',time:'00:00',ts:0,mid,date:'2026-08-06',name:'x',sd:'2026-08-06'}
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

        info = await page.evaluate("""() => {
            const mid=selectedMember.id, viewDate='2026-08-06', prevDate='2026-08-05';
            const punches=getAllPunchesForMember(mid,viewDate);
            const prevPunches=getAllPunchesForMember(mid,prevDate);
            const items=buildDayInstances(selectedMember,viewDate,true,prevPunches);
            const punchesOf=(it)=>it.sd===viewDate?punches:prevPunches;
            const out={
                mergedView: punches.map(p=>`${p.sid}${p.t}@${p.time} d=${p.date} sd=${p.sd||'-'}`),
                mergedPrev: prevPunches.map(p=>`${p.sid}${p.t}@${p.time} d=${p.date} sd=${p.sd||'-'}`),
                rawLocal86: (state.punches['2026-08-06']||[]).map(p=>`${p.sid}${p.t}@${p.time} sd=${p.sd||'-'}`),
                items: items.map(it=>({name:it.sh.name,sd:it.sd,prev:it.prev})),
                detail: items.map(it=>{
                    const st=ss(it.sh,punchesOf(it),viewDate,it.sd);
                    return {name:it.sh.name,sd:it.sd,ov:st.ov,ss:st.ss,es:st.es,
                            sp:st.sp?`${st.sp.time} sd=${st.sp.sd||'-'}`:null,
                            ep:st.ep?`${st.ep.time} sd=${st.ep.sd||'-'}`:null};
                })
            };
            return out;
        }""")
        import json
        print(json.dumps(info, ensure_ascii=False, indent=1))
        await b.close()


asyncio.run(main())
