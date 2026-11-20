"""选班隔离回归：所有外部请求被拦截，不读写生产数据。"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'index.html').read_text()
URL = 'http://127.0.0.1:8765/index.html'
SETUP = """() => {
  TEAM=[{id:1,name:'测试员工甲',dept:'测试',shiftIds:[]},{id:2,name:'测试员工乙',dept:'测试',shiftIds:[]}];
  selectedMember=TEAM[0];empTab='pick';pickWeekOffset=0;picks={};slotCap={};pickDraft={};
  isLocalBindExpired=()=>false;isAdminNow=()=>false;isSelectionOpen=()=>true;
  selCfg.lock=false;fbReady=true;pickPendingOps.clear();pickWriteQueue.length=0;
  window.testDate=tdStr();window.calls=[];window.logs=[];window.pending=[];
  logEvent=(type,text)=>logs.push({type,text});
  window.queryResult={data:null,error:true};
  supa={
    rpc(fn,args){calls.push({fn,args});return new Promise(resolve=>pending.push(resolve))},
    from(){const q={select(){return q},eq(){return q},maybeSingle(){return Promise.resolve(queryResult)}};return q}
  };
  renderEmp();
  window.firstNode=document.querySelector(`[data-pick-day="${testDate}"] [data-pick-sid="7"]`);
  window.clickSlots=sids=>sids.forEach(s=>document.querySelector(`[data-pick-day="${testDate}"] [data-pick-sid="${s}"]`).click());
}"""


def main():
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        def new_page():
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=HTML)
                       if route.request.url == URL else route.abort())
            page.goto(URL, wait_until='domcontentloaded')
            page.wait_for_function("typeof renderPickView==='function'")
            page.evaluate(SETUP)
            return page, errors

        def release(page, response):
            page.evaluate('(response)=>pending.shift()(response)', response)

        def end(page, errors, name):
            assert not errors, f'{name}: {errors}'
            results.append(name)
            page.close()

        page, errors = new_page()
        instant = page.evaluate("""() => {
          const start=performance.now();clickSlots([7,8,9,10,11,12,13]);clickSlots([7,7]);
          return {duration:performance.now()-start,selected:pickSel(testDate).length,calls:calls.length,
            pending:pickPendingOps.size,stable:firstNode===document.querySelector(`[data-pick-day="${testDate}"] [data-pick-sid="7"]`)};
        }""")
        assert instant['selected'] == 7 and instant['calls'] == 1 and instant['pending'] == 7
        assert instant['stable'] and instant['duration'] < 250, instant
        page.evaluate("applyAuthoritativePicksSnapshot({data:{},updated_at:1});renderAll()")
        assert page.evaluate('pickSel(testDate).length') == 7
        assert page.evaluate('firstNode.isConnected')
        for index in range(7):
            page.wait_for_function(f'calls.length==={index + 1}')
            release(page, {'data': {'ok': True}, 'error': None})
        page.wait_for_function('!pickQueueRunning')
        assert page.evaluate('pickPendingOps.size') == 0
        assert page.evaluate('pickSel(testDate).length') == 7
        assert page.evaluate('logs.length') == 7
        page.screenshot(path=str(ROOT / 'test_outputs' / 'pick-queue-verified.png'), full_page=True)
        print('即时点击指标:', json.dumps(instant, ensure_ascii=False))
        end(page, errors, '慢网7连点全部受理、单格去重、DOM稳定、保存完毕')

        page, errors = new_page()
        realistic = page.evaluate("""() => {
          const slots=enabledShiftsSorted().map(s=>s.id);
          TEAM=Array.from({length:15},(_,i)=>({id:i+1,name:'测试员工'+i,dept:'测试',shiftIds:[]}));
          selectedMember=TEAM[0];
          for(let i=1;i<=64;i++){
            const ds=ymd(addDays(new Date(),-i));
            picks[ds]={};TEAM.forEach(m=>picks[ds][String(m.id)]=slots.slice(0,9));
          }
          // 本周数据清空，避免历史负载干扰56上限测试。
          weekDaysArr(weekStartOf(new Date())).forEach(d=>delete picks[ymd(d)]);
          renderEmp();const start=performance.now();clickSlots([7,8,9,10,11,12,13]);
          return {duration:performance.now()-start,selected:pickSel(testDate).length};
        }""")
        assert realistic['selected'] == 7 and realistic['duration'] < 250, realistic
        for index in range(7):
            page.wait_for_function(f'calls.length==={index + 1}')
            release(page, {'data': {'ok': True}, 'error': None})
        page.wait_for_function('!pickQueueRunning')
        print('15人64天负载点击指标:', json.dumps(realistic, ensure_ascii=False))
        end(page, errors, '15人64天历史负载下7连点即时受理')

        page, errors = new_page()
        page.evaluate('clickSlots([7,8,9])')
        release(page, {'data': {'ok': False, 'reason': 'full', 'count': 2, 'cap': 2}, 'error': None})
        page.wait_for_function('calls.length===2')
        release(page, {'data': {'ok': True}, 'error': None})
        page.wait_for_function('calls.length===3')
        release(page, {'data': {'ok': True}, 'error': None})
        page.wait_for_function('!pickQueueRunning')
        assert page.evaluate('pickSel(testDate)') == [8, 9]
        end(page, errors, '满员只回滚被拒绝的格子，不丢其他点击')

        page, errors = new_page()
        page.evaluate('clickSlots([7,8])')
        release(page, {'data': None, 'error': {'message': 'connection unavailable'}})
        page.wait_for_function('calls.length===2')
        release(page, {'data': {'ok': True}, 'error': None})
        page.wait_for_function('!pickQueueRunning')
        assert page.evaluate("pickPendingOps.get(pickOpKey(testDate,1,7)).status") == 'uncertain'
        assert page.locator('.slot.uncertain').count() == 1
        assert page.evaluate('logs.length') == 1
        page.evaluate('clickSlots([7])')
        page.wait_for_function('calls.length===3')
        release(page, {'data': {'ok': True}, 'error': None})
        page.wait_for_function('!pickQueueRunning')
        assert page.evaluate('pickPendingOps.size') == 0
        assert page.evaluate('pickSel(testDate)') == [7, 8]
        end(page, errors, '断网不假报成功，其他班次继续，单格点击重试')

        page, errors = new_page()
        page.evaluate('queryResult={data:{sid:7},error:null};clickSlots([7])')
        release(page, {'data': None, 'error': {'message': 'connection unavailable'}})
        page.wait_for_function('!pickQueueRunning')
        assert page.evaluate('pickPendingOps.size') == 0
        assert page.evaluate('calls.length') == 1
        end(page, errors, '回执丢失用行表确认，不重复写入')

        page, errors = new_page()
        page.evaluate('clickSlots([7,8]);selectedMember=TEAM[1];renderEmp()')
        release(page, {'data': {'ok': True}, 'error': None})
        page.wait_for_function('!pickQueueRunning')
        assert page.evaluate('calls.length') == 1
        assert page.evaluate('(picks[testDate]||{})["1"]') == [7]
        assert page.evaluate('(picks[testDate]||{})["2"]||[]') == []
        end(page, errors, '切换账号后未提交队列取消，不写入新账号')

        page, errors = new_page()
        page.evaluate("""() => {
          window.resolveSnapshot=null;
          fetchAuthoritativePicksSnapshot=()=>new Promise(r=>resolveSnapshot=r);
          window.snapshotJob=pullPicksSnapshotOnly();clickSlots([7]);
        }""")
        release(page, {'data': {'ok': True}, 'error': None})
        page.wait_for_function('!pickQueueRunning')
        page.evaluate('resolveSnapshot({data:{},updated_at:1})')
        assert page.evaluate('snapshotJob') is False
        assert page.evaluate('pickSel(testDate)') == [7]
        end(page, errors, '晚到旧快照不能覆盖刚保存的班次')

        page, errors = new_page()
        page.evaluate("""() => {
          const days=weekDaysArr(weekStartOf(new Date())).map(ymd).filter(d=>d!==testDate);
          const slots=enabledShiftsSorted().map(s=>s.id);
          let n=55;
          days.forEach(d=>{const arr=slots.slice(0,Math.min(n,slots.length));setMemberPick(d,1,arr);n-=arr.length});
          clickSlots([7,8]);
        }""")
        assert page.evaluate('pickPendingOps.size') == 1
        assert page.evaluate('draftWeekTotalExcept(testDate)+pickSel(testDate).length') == 56
        release(page, {'data': {'ok': True}, 'error': None})
        page.wait_for_function('!pickQueueRunning')
        page.evaluate('selCfg.lock=true;clickSlots([9])')
        assert page.evaluate('calls.length') == 1
        end(page, errors, '每周56和选班锁定规则不变')

        page, errors = new_page()
        page.evaluate("""() => {
          isAdminNow=()=>true;setMemberPick(testDate,1,[7]);renderPickView();clickSlots([7,8]);
          applyAuthoritativePicksSnapshot({data:{[testDate]:{'1':[7]}},updated_at:1});renderEmp();
        }""")
        assert page.evaluate('pickSel(testDate)') == [8]
        release(page, {'data': {'ok': True}, 'error': None})
        page.wait_for_function('calls.length===2')
        release(page, {'data': {'ok': True}, 'error': None})
        page.wait_for_function('!pickQueueRunning')
        assert page.evaluate('pickSel(testDate)') == [8]
        end(page, errors, '管理员取消与新增排队互不覆盖')

        page, errors = new_page()
        page.evaluate('clickSlots([7,8]);selCfg.lock=true')
        release(page, {'data': {'ok': True}, 'error': None})
        page.wait_for_function('!pickQueueRunning')
        assert page.evaluate('calls.length') == 1
        assert page.evaluate('pickSel(testDate)') == [7]
        assert page.evaluate('pickPendingOps.size') == 0
        end(page, errors, '排队期间管理员锁定选班，未提交操作恢复')

        page, errors = new_page()
        page.evaluate('clickSlots([7,8])')
        page.evaluate("""applyPicksDelta([{eventType:'DELETE',old:{date:testDate,mid:'1',sid:8}}]);renderEmp()""")
        assert page.evaluate('pickSel(testDate)') == [7, 8]
        release(page, {'data': {'picks': {page.evaluate('testDate'): {'1': [7]}}}, 'error': None})
        page.wait_for_function('calls.length===2')
        assert page.evaluate('pickSel(testDate)') == [7, 8]
        release(page, {'data': {'picks': {page.evaluate('testDate'): {'1': [7, 8]}}}, 'error': None})
        page.wait_for_function('!pickQueueRunning')
        assert page.evaluate('pickSel(testDate)') == [7, 8]
        end(page, errors, '实时差量与旧版完整RPC回执保留后续待保存操作')

        page, errors = new_page()
        missing = {'data': None, 'error': {'code': 'PGRST202', 'message': 'function missing'}}
        page.evaluate('clickSlots([7,8])')
        release(page, missing)
        page.wait_for_function('calls.length===2')
        release(page, missing)
        page.wait_for_function('calls.length===3')
        assert page.evaluate('calls[2].fn') == 'pick_set'
        assert page.evaluate('calls[2].args.p_sids') == [7]
        page.evaluate('selectedMember=TEAM[1];renderEmp()')
        release(page, {'data': {'ok': True}, 'error': None})
        page.wait_for_function('!pickQueueRunning')
        assert page.evaluate('calls.length') == 3
        assert page.evaluate('(picks[testDate]||{})["1"]') == [7]
        end(page, errors, '旧pick_set回退只提交当前格，不夹带其他待保存点击')

        page, errors = new_page()
        page.evaluate('clickSlots([7]);selectedMember=null')
        release(page, {'data': None, 'error': {'message': 'transaction conflict'}})
        page.wait_for_function('!pickQueueRunning')
        assert page.evaluate('calls.length') == 1
        end(page, errors, '退出账号后内部重试不再发送写请求')

        page, errors = new_page()
        page.evaluate('isAdminNow=()=>true;renderPickView();clickSlots([7]);isAdminNow=()=>false')
        release(page, {'data': None, 'error': {'message': 'transaction conflict'}})
        page.wait_for_function('!pickQueueRunning')
        assert page.evaluate('calls.length') == 1
        end(page, errors, '管理员权限失效后内部重试不再使用特权')

        page, errors = new_page()
        page.evaluate("""() => {
          window.resolveAudit=null;_lastIntegrityAuditAt=0;
          fetchAuthoritativePicksSnapshot=()=>new Promise(r=>resolveAudit=r);
          window.auditJob=auditPicksIntegrity();clickSlots([7]);
        }""")
        release(page, {'data': {'ok': True}, 'error': None})
        page.wait_for_function('!pickQueueRunning')
        page.evaluate('resolveAudit({data:{[testDate]:{"1":[]}},updated_at:1})')
        page.evaluate('auditJob')
        assert page.evaluate('pickSel(testDate)') == [7]
        end(page, errors, '晚到完整性审计不清除刚确认选班')

        page, errors = new_page()
        page.evaluate("""() => {
          window.forceFetchStarted=false;window.resolveForce=null;
          window.fetch=()=>{forceFetchStarted=true;return new Promise(r=>resolveForce=r)};
          window.forceJob=forceSyncFromSupabase();
        }""")
        page.wait_for_function('forceFetchStarted')
        page.evaluate('clickSlots([7])')
        release(page, {'data': {'ok': True}, 'error': None})
        page.wait_for_function('!pickQueueRunning')
        page.evaluate('resolveForce({ok:true,status:200,json:async()=>({data:{[testDate]:{"1":[]}},updated_at:1})})')
        assert page.evaluate('forceJob') is False
        assert page.evaluate('pickSel(testDate)') == [7]
        end(page, errors, '晚到强制同步不清除刚确认选班')

        page, errors = new_page()
        page.evaluate("""() => {
          const nativeTimer=window.setTimeout;
          window.setTimeout=(fn,ms,...args)=>nativeTimer(fn,ms===8000?20:(ms>=100&&ms<2000?1:ms),...args);
          window.fallbackAborts=0;
          supa.rpc=(fn,args)=>{
            calls.push({fn,args});
            if(fn!=='pick_set')return Promise.resolve({error:{code:'PGRST202',message:'function missing'}});
            return {abortSignal(signal){signal.addEventListener('abort',()=>fallbackAborts++);return new Promise(()=>{})}};
          };
          clickSlots([7,8]);
        }""")
        page.wait_for_function('!pickQueueRunning')
        assert page.evaluate('fallbackAborts') == 10
        assert page.evaluate('[...pickPendingOps.values()].every(op=>op.status==="uncertain")')
        end(page, errors, '旧接口fallback超时仍能结束队列，不永久悬挂')

        page, errors = new_page()
        page.evaluate("""() => {
          const nativeTimer=window.setTimeout;
          window.setTimeout=(fn,ms,...args)=>nativeTimer(fn,ms===8000?20:ms,...args);
          window.aborted=false;
          supa.rpc=()=>({abortSignal(signal){signal.addEventListener('abort',()=>aborted=true);return new Promise(()=>{})}});
        }""")
        timeout = page.evaluate("requestPickRpc('pick_add_cap',{})")
        assert timeout.get('error') and page.evaluate('aborted')
        end(page, errors, '请求超时实际中止连接')
        browser.close()
    print(f'隔离选班回归通过：{len(results)} 个场景')
    for name in results:
        print(name)


if __name__ == '__main__':
    main()
