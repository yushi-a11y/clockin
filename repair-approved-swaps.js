const fs = require('fs');
const path = require('path');

const SUPABASE_URL = 'https://txtduqfhugjupxdoxdvp.supabase.co';
const SUPABASE_KEY = 'sb_publishable_EkzlCBH5DJu0OmFIUnGIZA_yiRPTvJA';
const REPAIR_FROM = '2026-09-02';
const headers = { apikey: SUPABASE_KEY, Authorization: `Bearer ${SUPABASE_KEY}` };

async function request(pathname, options = {}) {
  const response = await fetch(`${SUPABASE_URL}/rest/v1/${pathname}`, {
    ...options,
    headers: { ...headers, ...(options.headers || {}) },
    signal: AbortSignal.timeout(30000)
  });
  const text = await response.text();
  if (!response.ok) throw new Error(`${pathname}: HTTP ${response.status} ${text}`);
  return text ? JSON.parse(text) : null;
}

async function fetchAllPickRows() {
  const rows = [];
  for (let from = 0; ; from += 1000) {
    const page = await request('picks?select=date,mid,sid&order=date.asc,mid.asc,sid.asc', {
      headers: { Range: `${from}-${from + 999}` }
    });
    rows.push(...page);
    if (page.length < 1000) return rows;
  }
}

function normalize(items) {
  return [...new Set((items || []).map(Number).filter(Number.isFinite))].sort((a, b) => a - b);
}

function rowsToPicks(rows) {
  const result = {};
  for (const row of rows) {
    if (!result[row.date]) result[row.date] = {};
    const mid = String(row.mid);
    if (!result[row.date][mid]) result[row.date][mid] = [];
    result[row.date][mid].push(Number(row.sid));
  }
  for (const day of Object.values(result)) {
    for (const mid of Object.keys(day)) day[mid] = normalize(day[mid]);
  }
  return result;
}

function normalizedSignature(picks) {
  const normalized = {};
  for (const date of Object.keys(picks || {}).sort()) {
    normalized[date] = {};
    for (const mid of Object.keys(picks[date] || {}).sort((a, b) => Number(a) - Number(b))) {
      normalized[date][mid] = normalize(picks[date][mid]);
    }
  }
  return JSON.stringify(normalized);
}

function move(picks, date, fromMid, toMid, sid) {
  sid = Number(sid);
  fromMid = String(fromMid);
  toMid = String(toMid);
  if (!date || !Number.isFinite(sid) || fromMid === toMid) return;
  if (!picks[date]) picks[date] = {};
  picks[date][fromMid] = normalize((picks[date][fromMid] || []).filter(value => Number(value) !== sid));
  picks[date][toMid] = normalize([...(picks[date][toMid] || []), sid]);
}

function buildEvents(config, team) {
  const memberId = ref => String((team || []).find(member =>
    String(member.id) === String(ref) || String(member.name) === String(ref)
  )?.id ?? ref);
  const events = [];
  for (const record of config.swaps || []) {
    if (record?.status !== 'accepted') continue;
    if (record.date < REPAIR_FROM && (!record.exchange || record.exchange.takeDate < REPAIR_FROM)) continue;
    events.push({ type: record.exchange ? 'old_exchange' : 'old_transfer', at: Number(record.decidedTs || record.ts) || 0, record });
  }
  for (const record of config.swap_requests || []) {
    if (record?.status !== 'approved' || record.date < REPAIR_FROM) continue;
    events.push({ type: record.type === 'transfer' ? 'new_transfer' : 'new_exchange', at: Number(record.decidedTs || record.ts) || 0, record });
  }
  events.sort((a, b) => a.at - b.at || String(a.record.id).localeCompare(String(b.record.id)));
  return { events, memberId };
}

function replay(source, events, memberId) {
  const result = JSON.parse(JSON.stringify(source));
  for (const event of events) {
    const record = event.record;
    if (event.type === 'old_transfer') {
      move(result, record.date, memberId(record.fromId), memberId(record.toId), record.sid);
    } else if (event.type === 'old_exchange') {
      move(result, record.date, memberId(record.fromId), memberId(record.toId), record.sid);
      move(result, record.exchange.takeDate, memberId(record.toId), memberId(record.fromId), record.exchange.takeSid);
    } else if (event.type === 'new_transfer') {
      move(result, record.date, memberId(record.requester_mid), memberId(record.partner_mid), record.original_shift_id);
    } else {
      move(result, record.date, memberId(record.requester_mid), memberId(record.partner_mid), record.original_shift_id);
      move(result, record.date, memberId(record.partner_mid), memberId(record.requester_mid), record.new_shift_id);
    }
  }
  return result;
}

function changedCells(before, after) {
  const changes = [];
  const dates = new Set([...Object.keys(before || {}), ...Object.keys(after || {})]);
  for (const date of [...dates].sort()) {
    const mids = new Set([...Object.keys(before[date] || {}), ...Object.keys(after[date] || {})]);
    for (const mid of [...mids].sort((a, b) => Number(a) - Number(b))) {
      const oldSids = normalize(before[date]?.[mid]);
      const newSids = normalize(after[date]?.[mid]);
      if (JSON.stringify(oldSids) !== JSON.stringify(newSids)) changes.push({ date, mid, before: oldSids, after: newSids });
    }
  }
  return changes;
}

async function setCell(date, mid, sids) {
  const result = await request('rpc/pick_set', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ p_date: date, p_mid: String(mid), p_sids: normalize(sids) })
  });
  if (!result || typeof result !== 'object') throw new Error(`pick_set returned invalid result for ${date}/${mid}`);
}

async function setConfigMirror(picks) {
  await request('config', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Prefer: 'return=minimal,resolution=merge-duplicates'
    },
    body: JSON.stringify({ id: 'picks', data: picks, updated_at: Date.now() })
  });
}

async function loadProduction() {
  const [configRows, pickRows] = await Promise.all([
    request('config?select=id,data,updated_at&id=in.(picks,swaps,swap_requests,team)'),
    fetchAllPickRows()
  ]);
  return {
    configRows,
    config: Object.fromEntries(configRows.map(row => [row.id, row.data])),
    pickRows,
    picks: rowsToPicks(pickRows)
  };
}

async function main() {
  const initial = await loadProduction();
  const { events, memberId } = buildEvents(initial.config, initial.config.team || []);
  const target = replay(initial.picks, events, memberId);
  const replayAgain = replay(target, events, memberId);
  if (normalizedSignature(target) !== normalizedSignature(replayAgain)) throw new Error('Swap replay is not idempotent; aborting before write');

  const changes = changedCells(initial.picks, target);
  const invalid = changes.filter(change => change.after.length > 7);
  if (invalid.length) throw new Error(`Repair would exceed daily limit in ${invalid.length} cells; aborting before write`);

  const backupPath = path.join(__dirname, 'outputs', 'swap-repair-backup-2026-09-09-attempt2.json');
  if (fs.existsSync(backupPath)) throw new Error(`Backup already exists: ${backupPath}`);
  fs.writeFileSync(backupPath, JSON.stringify({
    createdAt: new Date().toISOString(),
    repairFrom: REPAIR_FROM,
    configRows: initial.configRows,
    pickRows: initial.pickRows,
    events,
    plannedChanges: changes
  }, null, 2));
  console.log(`Backup written: ${backupPath}`);
  console.log(`Approved/accepted events: ${events.length}; cells to repair: ${changes.length}`);

  const freshness = await fetchAllPickRows();
  if (normalizedSignature(rowsToPicks(freshness)) !== normalizedSignature(initial.picks)) {
    throw new Error('Production picks changed after backup; aborting before write');
  }

  const applied = [];
  try {
    for (const change of changes) {
      await setCell(change.date, change.mid, change.after);
      applied.push(change);
    }
    // 当前线上未部署行表→config 镜像触发器；行表全部成功后再一次性刷新兼容镜像。
    await setConfigMirror(target);

    const verified = await loadProduction();
    const remainingTargetDiff = changedCells(verified.picks, target);
    const mirrorDiff = changedCells(verified.picks, verified.config.picks || {});
    if (remainingTargetDiff.length || mirrorDiff.length) {
      throw new Error(`Verification failed: targetDiff=${remainingTargetDiff.length}, mirrorDiff=${mirrorDiff.length}`);
    }

    const resultPath = path.join(__dirname, 'outputs', 'swap-repair-result-2026-09-09.json');
    fs.writeFileSync(resultPath, JSON.stringify({
      completedAt: new Date().toISOString(),
      repairedCells: changes.length,
      replayedEvents: events.length,
      rowCount: verified.pickRows.length,
      rowConfigDivergence: mirrorDiff.length,
      changes
    }, null, 2));
    console.log(`Repair verified: ${changes.length} cells updated; row/config divergence is 0`);
    console.log(`Result written: ${resultPath}`);
  } catch (error) {
    console.error(`Repair failed after ${applied.length} writes; rolling back changed cells and config mirror...`);
    let rollbackFailures = 0;
    for (const change of applied.reverse()) {
      try { await setCell(change.date, change.mid, change.before); }
      catch (rollbackError) { rollbackFailures++; console.error(`Rollback failed for ${change.date}/${change.mid}:`, rollbackError.message); }
    }
    try { await setConfigMirror(initial.config.picks || {}); }
    catch (rollbackError) { rollbackFailures++; console.error('Config mirror rollback failed:', rollbackError.message); }
    if (rollbackFailures) throw new Error(`${error.message}; rollback failures=${rollbackFailures}`);
    throw new Error(`${error.message}; applied writes and config mirror rolled back`);
  }
}

main().catch(error => {
  console.error(error.stack || error.message);
  process.exit(1);
});
