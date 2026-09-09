// 一次性线上修复：员工 8027356(mid 7) 接受 8191272(mid 10) 的 2026-09-09 sid22 转班
// 因旧版组合降级"先加后删"在满员时段被 pick_add_cap 误拒（cap 5/5 含转出方）。
// 本脚本按"接受"意图直接落库：行表 pick_set 双方 + swaps 状态置 accepted + 刷新兼容镜像。
// 只写这一笔；带备份、写后校验、失败回滚。
const SUPABASE_URL = 'https://txtduqfhugjupxdoxdvp.supabase.co';
const SUPABASE_KEY = 'sb_publishable_EkzlCBH5DJu0OmFIUnGIZA_yiRPTvJA';
const headers = { apikey: SUPABASE_KEY, Authorization: `Bearer ${SUPABASE_KEY}` };

const SWAP_ID = 'sw1788926677015_mfrb';
const DATE = '2026-09-09';
const FROM_MID = '10';
const TO_MID = '7';
const SID = 22;

async function request(pathname, options = {}) {
  const res = await fetch(SUPABASE_URL + '/' + pathname, { ...options, headers: { ...headers, ...(options.headers || {}) } });
  const text = await res.text();
  if (!res.ok) throw new Error(`${pathname} -> ${res.status} ${text.slice(0, 300)}`);
  return text ? JSON.parse(text) : null;
}
const normalize = arr => [...new Set((arr || []).map(Number).filter(Number.isFinite))].sort((a, b) => a - b);

async function loadDay() {
  const rows = await request(`rest/v1/picks?select=date,mid,sid&date=eq.${DATE}`);
  const day = {};
  for (const r of rows) (day[String(r.mid)] = day[String(r.mid)] || []).push(Number(r.sid));
  for (const k of Object.keys(day)) day[k] = normalize(day[k]);
  return day;
}
async function loadSwapsAndMirror() {
  const cfg = await request(`rest/v1/config?select=id,data,updated_at&id=in.("swaps","picks")`);
  const out = { swaps: [], mirror: {} };
  for (const row of cfg) { if (row.id === 'swaps') out.swaps = row.data || []; if (row.id === 'picks') out.mirror = row.data || {}; }
  return out;
}
async function setCell(mid, sids) {
  const result = await request('rest/v1/rpc/pick_set', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ p_date: DATE, p_mid: String(mid), p_sids: normalize(sids) }) });
  if (!result || typeof result !== 'object') throw new Error(`pick_set invalid result for ${mid}`);
}
async function setConfigMirror(picksMap) {
  await request('rest/v1/config', { method: 'POST', headers: { 'Content-Type': 'application/json', Prefer: 'return=minimal,resolution=merge-duplicates' }, body: JSON.stringify({ id: 'picks', data: picksMap, updated_at: Date.now() }) });
}
async function setSwaps(list) {
  await request('rest/v1/config', { method: 'POST', headers: { 'Content-Type': 'application/json', Prefer: 'return=minimal,resolution=merge-duplicates' }, body: JSON.stringify({ id: 'swaps', data: list, updated_at: Date.now() }) });
}

(async () => {
  const day = await loadDay();
  const { swaps, mirror } = await loadSwapsAndMirror();
  const rec = swaps.find(s => s.id === SWAP_ID);
  if (!rec) throw new Error('swap record not found: ' + SWAP_ID);
  if (rec.status !== 'pending') throw new Error('swap not pending: ' + rec.status);
  if (Number(rec.sid) !== SID || rec.date !== DATE || String(rec.fromId) !== FROM_MID || String(rec.toId) !== TO_MID) throw new Error('swap fields mismatch: ' + JSON.stringify(rec));
  const fromArr = day[FROM_MID] || [], toArr = day[TO_MID] || [];
  if (!fromArr.includes(SID)) throw new Error('giver does not hold sid');
  if (toArr.includes(SID)) throw new Error('receiver already holds sid');
  if (toArr.length + 1 > 7) throw new Error('receiver day full');
  const holders = Object.keys(day).filter(mid => day[mid].includes(SID));
  const cap = 5; // 线上 slotcap[2026-09-09][22]
  if (holders.length > cap) throw new Error('slot over cap before transfer');
  const newFrom = fromArr.filter(x => x !== SID), newTo = normalize([...toArr, SID]);
  console.log('plan:', { from: { before: fromArr, after: newFrom }, to: { before: toArr, after: newTo }, holdersBefore: holders.length, cap });

  const origRec = JSON.parse(JSON.stringify(rec));
  const backup = { at: new Date().toISOString(), day, swaps: origRec, mirrorCellFrom: (mirror[DATE] || {})[FROM_MID], mirrorCellTo: (mirror[DATE] || {})[TO_MID] };
  require('fs').writeFileSync('outputs/fix-pending-swap-0909-backup.json', JSON.stringify(backup, null, 2));

  const applied = [];
  try {
    await setCell(FROM_MID, newFrom); applied.push([FROM_MID, fromArr]);
    await setCell(TO_MID, newTo); applied.push([TO_MID, toArr]);

    rec.status = 'accepted'; rec.decidedTs = Date.now();
    await setSwaps(swaps);

    const mirrorNext = JSON.parse(JSON.stringify(mirror));
    if (!mirrorNext[DATE]) mirrorNext[DATE] = {};
    mirrorNext[DATE][FROM_MID] = newFrom; mirrorNext[DATE][TO_MID] = newTo;
    await setConfigMirror(mirrorNext);

    const verified = await loadDay();
    const okFrom = JSON.stringify(verified[FROM_MID] || []) === JSON.stringify(newFrom);
    const okTo = JSON.stringify(verified[TO_MID] || []) === JSON.stringify(newTo);
    const vcfg = await loadSwapsAndMirror();
    const okSwap = (vcfg.swaps.find(s => s.id === SWAP_ID) || {}).status === 'accepted';
    const okMirror = JSON.stringify((vcfg.mirror[DATE] || {})[FROM_MID] || []) === JSON.stringify(newFrom) && JSON.stringify((vcfg.mirror[DATE] || {})[TO_MID] || []) === JSON.stringify(newTo);
    if (!okFrom || !okTo || !okSwap || !okMirror) throw new Error(`verify failed from=${okFrom} to=${okTo} swap=${okSwap} mirror=${okMirror}`);
    console.log('OK: transfer applied, swap accepted, mirror synced', { verifiedFrom: verified[FROM_MID], verifiedTo: verified[TO_MID] });
  } catch (e) {
    console.error('FAILED:', e.message, '- rolling back', applied.length, 'cells');
    for (const [mid, before] of applied.reverse()) { try { await setCell(mid, before); } catch (re) { console.error('rollback cell failed', mid, re.message); } }
    try { await setSwaps(swaps.map(s => s.id === SWAP_ID ? backup.swaps : s)); } catch (re) { console.error('rollback swaps failed', re.message); }
    try { await setConfigMirror(mirror); } catch (re) { console.error('rollback mirror failed', re.message); }
    process.exit(1);
  }
})().catch(e => { console.error('FATAL', e); process.exit(1); });
