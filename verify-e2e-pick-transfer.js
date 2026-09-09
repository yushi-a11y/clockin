// 线上端到端验证：pick_transfer / pick_exchange 是否已部署且行为正确。
// 设计原则（对生产零残留）：
//  - 阶段 A：只读探针。用"非变更"入参（from==to → invalid；不存在的转出方 → not_owner）
//    探测函数是否存在、anon 是否有执行权限、返回契约是否正确。不写任何数据。
//  - 阶段 B：仅当已部署才执行。在【远期哨兵日期 + 明显伪造的 mid】上复跑"9/9 那类"
//    满员含转出方场景，验证净零名额成功；随后在 finally 中彻底清理并还原 slotcap 与镜像，
//    最后断言零残留。全程先备份到 outputs/e2e-verify-backup-*.json。
const fs = require('fs');
const SUPABASE_URL = 'https://txtduqfhugjupxdoxdvp.supabase.co';
const SUPABASE_KEY = 'sb_publishable_EkzlCBH5DJu0OmFIUnGIZA_yiRPTvJA';
const headers = { apikey: SUPABASE_KEY, Authorization: `Bearer ${SUPABASE_KEY}` };

let pass = 0, fail = 0;
const check = (n, c, e) => { if (c) { pass++; console.log('  PASS', n); } else { fail++; console.log('  FAIL', n, e !== undefined ? JSON.stringify(e) : ''); } };

async function raw(pathname, options = {}) {
  const res = await fetch(SUPABASE_URL + '/rest/v1/' + pathname, { ...options, headers: { ...headers, ...(options.headers || {}) } });
  const text = await res.text();
  let body = null; try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  return { status: res.status, ok: res.ok, body };
}
async function rpc(fn, params) { return raw('rpc/' + fn, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(params) }); }
async function getConfig(id) { const r = await raw(`config?select=id,data&id=eq.${id}`); return (r.body && r.body[0] && r.body[0].data) || null; }
async function setConfig(id, data) { return raw('config', { method: 'POST', headers: { 'Content-Type': 'application/json', Prefer: 'return=minimal,resolution=merge-duplicates' }, body: JSON.stringify({ id, data, updated_at: Date.now() }) }); }
const isMissingFn = r => r.status === 404 || (r.body && typeof r.body === 'object' && /PGRST20[12]|Could not find the function|could not be found/i.test(JSON.stringify(r.body)));

// ---- 哨兵参数（远期日期 + 伪造 mid，绝不与真实员工/排班冲突）----
const SD = '2027-06-01';           // 远期日期，不受 60 天清理影响，也不参与任何真实考勤计算
const SSID = 987;                  // 哨兵时段
const GIVER = '__e2e_giver__', RECV = '__e2e_recv__';
const FILLERS = ['__e2e_f1__', '__e2e_f2__', '__e2e_f3__', '__e2e_f4__'];
const SENT_MIDS = [GIVER, RECV, ...FILLERS];

async function holders(date, sid) {
  const r = await raw(`picks?select=mid&date=eq.${date}&sid=eq.${sid}`);
  return (r.body || []).map(x => String(x.mid)).sort();
}
async function midHolds(date, mid, sid) {
  const r = await raw(`picks?select=sid&date=eq.${date}&mid=eq.${encodeURIComponent(mid)}&sid=eq.${sid}`);
  return (r.body || []).length > 0;
}
async function sentinelRows() {
  const r = await raw(`picks?select=date,mid,sid&date=eq.${SD}`);
  return (r.body || []).filter(x => SENT_MIDS.includes(String(x.mid)));
}
// 用 pick_set 设置某哨兵 mid 当天的班次（[] 即清空 = 删除其哨兵行）
async function setSentinel(mid, sids) { return rpc('pick_set', { p_date: SD, p_mid: mid, p_sids: sids }); }
async function resyncMirror() { const snap = await rpc('picks_snapshot', {}); if (snap.ok && snap.body && snap.body.data) await setConfig('picks', snap.body.data); }

(async () => {
  console.log('=== 阶段 A：只读探针（检测部署 + 权限 + 返回契约，不写数据）===');
  const tInv = await rpc('pick_transfer', { p_date: '2000-01-01', p_from_mid: '__x__', p_to_mid: '__x__', p_sid: 1 });
  const transferDeployed = !isMissingFn(tInv);
  if (!transferDeployed) console.log('  pick_transfer 探针响应：', tInv.status, JSON.stringify(tInv.body).slice(0, 200));
  check('pick_transfer 已部署且 anon 可执行', transferDeployed, { status: tInv.status, body: tInv.body });
  if (transferDeployed) check('pick_transfer from==to 返回 invalid（非变更探针）', tInv.body && tInv.body.ok === false && tInv.body.reason === 'invalid', tInv.body);

  const tOwner = await rpc('pick_transfer', { p_date: SD, p_from_mid: '__nobody__', p_to_mid: '__nobody2__', p_sid: SSID });
  if (transferDeployed) check('pick_transfer 转出方不持有返回 not_owner（非变更探针）', tOwner.body && tOwner.body.ok === false && tOwner.body.reason === 'not_owner', tOwner.body);

  const eInv = await rpc('pick_exchange', { p_give_date: '2000-01-01', p_giver_mid: '__x__', p_give_sid: 1, p_take_date: '2000-01-02', p_receiver_mid: '__x__', p_take_sid: 2 });
  const exchangeDeployed = !isMissingFn(eInv);
  if (!exchangeDeployed) console.log('  pick_exchange 探针响应：', eInv.status, JSON.stringify(eInv.body).slice(0, 200));
  check('pick_exchange 已部署且 anon 可执行', exchangeDeployed, { status: eInv.status, body: eInv.body });
  if (exchangeDeployed) check('pick_exchange giver==receiver 返回 invalid（非变更探针）', eInv.body && eInv.body.ok === false && eInv.body.reason === 'invalid', eInv.body);

  if (!transferDeployed || !exchangeDeployed) {
    console.log('\n>>> 函数尚未部署（或 anon 无执行权限）。请在 Supabase SQL Editor 全选运行');
    console.log('>>> outputs/supabase-原子转班换班函数.sql 后再复跑本验证。阶段 B（写入型端到端）已跳过。');
    console.log(`\n==== 结果：${pass} 通过 / ${fail} 失败 ====`);
    process.exit(fail === 0 ? 0 : 1);
  }

  console.log('\n=== 阶段 B：隔离哨兵场景端到端（远期日期 + 伪造 mid，跑完彻底还原）===');
  const backup = { at: new Date().toISOString(), slotcap: await getConfig('slotcap'), picksMirror: await getConfig('picks') };
  const backupPath = 'outputs/e2e-verify-backup-' + Date.now() + '.json';
  fs.writeFileSync(backupPath, JSON.stringify(backup));
  console.log('  已备份 slotcap + picks 镜像到', backupPath);

  let phaseBStarted = false;
  try {
    // 预清理：确保没有历史哨兵残留
    for (const m of SENT_MIDS) await setSentinel(m, []);

    // 构造"满员含转出方"：holders(SSID) = {GIVER, f1..f4} = 5，cap 设为 5
    phaseBStarted = true;
    await setSentinel(GIVER, [SSID]);
    for (const f of FILLERS) await setSentinel(f, [SSID]);
    await setSentinel(RECV, [1]); // 接收方当天先有 1 个别的班次
    const sc = JSON.parse(JSON.stringify(backup.slotcap || {}));
    sc[SD] = { ...(sc[SD] || {}), [SSID]: 5 };
    await setConfig('slotcap', sc);

    const hBefore = await holders(SD, SSID);
    check('前置：时段 holders = 5（含转出方，正好满员）', hBefore.length === 5 && hBefore.includes(GIVER), hBefore);

    // 核心：净零转班应成功
    const tr = await rpc('pick_transfer', { p_date: SD, p_from_mid: GIVER, p_to_mid: RECV, p_sid: SSID });
    check('pick_transfer 返回 ok:true（净零，未被满员误拒）', tr.body && tr.body.ok === true, tr.body);
    check('转出方已释放哨兵时段', !(await midHolds(SD, GIVER, SSID)));
    check('接收方已获得哨兵时段', await midHolds(SD, RECV, SSID));
    const hAfter = await holders(SD, SSID);
    check('时段人数仍为 5（净零，未超上限）', hAfter.length === 5, hAfter);
    check('holders 中转出方被接收方替换', !hAfter.includes(GIVER) && hAfter.includes(RECV), hAfter);
    check('返回体带最新 data 整块', tr.body && tr.body.data && Array.isArray(tr.body.data[SD] && tr.body.data[SD][RECV]) && tr.body.data[SD][RECV].includes(SSID), tr.body && tr.body.data && tr.body.data[SD]);

    // 幂等：重复接受
    const tr2 = await rpc('pick_transfer', { p_date: SD, p_from_mid: GIVER, p_to_mid: RECV, p_sid: SSID });
    check('重复转班幂等 alreadyApplied:true', tr2.body && tr2.body.ok === true && tr2.body.alreadyApplied === true, tr2.body);

    // 双向换班：GIVER 把 SSID2 给 RECV，RECV 把 1 给 GIVER（跨"日期"用同一天不同时段简化）
    const SSID2 = 988;
    await setSentinel(GIVER, [SSID2]);        // GIVER 持有 SSID2
    // RECV 当前持有 [1, SSID]；让 RECV 持有 1（已在）
    const ex = await rpc('pick_exchange', { p_give_date: SD, p_giver_mid: GIVER, p_give_sid: SSID2, p_take_date: SD, p_receiver_mid: RECV, p_take_sid: 1 });
    check('pick_exchange 返回 ok:true', ex.body && ex.body.ok === true, ex.body);
    check('换班后 GIVER 得到 1、失去 SSID2', (await midHolds(SD, GIVER, 1)) && !(await midHolds(SD, GIVER, SSID2)));
    check('换班后 RECV 得到 SSID2、失去 1', (await midHolds(SD, RECV, SSID2)) && !(await midHolds(SD, RECV, 1)));
  } catch (e) {
    console.error('  阶段 B 异常：', e.message);
    fail++;
  } finally {
    console.log('  --- 清理与还原 ---');
    try { for (const m of SENT_MIDS) await setSentinel(m, []); } catch (e) { console.error('  清理哨兵行失败：', e.message); }
    try { await setConfig('slotcap', backup.slotcap || {}); } catch (e) { console.error('  还原 slotcap 失败：', e.message); }
    try { await resyncMirror(); } catch (e) { console.error('  重同步镜像失败：', e.message); }

    // 零残留断言
    const residueRows = await sentinelRows();
    check('清理后 picks 无任何哨兵行残留', residueRows.length === 0, residueRows);
    const scNow = await getConfig('slotcap');
    check('slotcap 已还原（无哨兵日期键）', !scNow || scNow[SD] === undefined, scNow && scNow[SD]);
    const mirrorNow = await getConfig('picks');
    const mirrorSentinel = mirrorNow && mirrorNow[SD] ? Object.keys(mirrorNow[SD]).filter(k => SENT_MIDS.includes(k)) : [];
    check('config 镜像无哨兵残留', mirrorSentinel.length === 0, mirrorSentinel);
    // 与备份对比：slotcap 完全一致
    check('slotcap 与备份逐字节一致', JSON.stringify(scNow) === JSON.stringify(backup.slotcap || {}) || (scNow === null && backup.slotcap === null), { now: scNow && Object.keys(scNow).length, bak: backup.slotcap && Object.keys(backup.slotcap).length });
  }

  console.log(`\n==== 结果：${pass} 通过 / ${fail} 失败 ====`);
  process.exit(fail === 0 ? 0 : 1);
})().catch(e => { console.error('FATAL', e); process.exit(2); });
