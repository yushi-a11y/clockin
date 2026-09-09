// 只读诊断：2026-09-09 8191272 → 8027356 换班接受失败原因核查
const SUPABASE_URL = 'https://txtduqfhugjupxdoxdvp.supabase.co';
const SUPABASE_KEY = 'sb_publishable_EkzlCBH5DJu0OmFIUnGIZA_yiRPTvJA';
const H = { apikey: SUPABASE_KEY, Authorization: `Bearer ${SUPABASE_KEY}` };
const DATE = '2026-09-09';

async function get(pathname) {
  const res = await fetch(SUPABASE_URL + pathname, { headers: H });
  if (!res.ok) throw new Error(pathname + ' -> ' + res.status + ' ' + (await res.text()));
  return res.json();
}

(async () => {
  const cfg = await get('/rest/v1/config?select=id,data,updated_at&id=in.("swaps","team","slotcap","selcfg")');
  const byId = {};
  for (const row of cfg) byId[row.id] = row.data;
  const team = byId.team || [];
  const idOf = name => {
    const m = team.find(x => String(x.name) === String(name) || String(x.id) === String(name));
    return m ? String(m.id) : null;
  };
  const fromMid = idOf('8191272'), toMid = idOf('8027356');
  console.log('team ids:', { from: '8191272->' + fromMid, to: '8027356->' + toMid });

  const swaps = (byId.swaps || []).filter(s => s.date === DATE && (s.fromName === '8191272' || s.fromId === fromMid));
  console.log('pending/related swaps on', DATE, 'from 8191272:');
  for (const s of swaps) console.log(JSON.stringify({ id: s.id, sid: s.sid, from: s.fromId + '/' + s.fromName, to: s.toId + '/' + s.toName, status: s.status, ts: s.ts, decidedTs: s.decidedTs, exchange: s.exchange || null }));

  // picks 行表（当天）
  const rows = await get(`/rest/v1/picks?select=date,mid,sid&date=eq.${DATE}&order=mid`);
  const day = {};
  for (const r of rows) { (day[String(r.mid)] = day[String(r.mid)] || []).push(Number(r.sid)); }
  console.log('picks rows', DATE, ':');
  for (const mid of Object.keys(day).sort((a, b) => +a - +b)) console.log('  mid', mid, '->', day[mid].sort((a, b) => a - b).join(','));

  for (const s of swaps) {
    const sid = Number(s.sid);
    const holders = Object.keys(day).filter(mid => day[mid].includes(sid));
    console.log(`swap ${s.id}: sid=${sid} status=${s.status} holders(${holders.length})=[${holders.join(',')}] cap=${(byId.slotcap || {})[DATE] ? ((byId.slotcap[DATE] || {})[sid] || 0) : 0}`);
    console.log(`  giver ${s.fromId} holds sid? ${day[String(s.fromId)] ? day[String(s.fromId)].includes(sid) : false}; receiver ${s.toId} day count=${(day[String(s.toId)] || []).length} holds? ${day[String(s.toId)] ? day[String(s.toId)].includes(sid) : false}`);
  }
  console.log('slotcap', DATE, ':', JSON.stringify((byId.slotcap || {})[DATE] || {}));
})().catch(e => { console.error('DIAG ERROR', e); process.exit(1); });
