// Supabase 数据迁移脚本：孟买(旧) → 新加坡(新)
// 用法：OLD_URL=... OLD_KEY=... NEW_URL=... NEW_KEY=... node migrate-supabase.mjs
// 通过 REST API 全量搬运 5 张表，保留 id，重置自增序列，并核对条数。

const OLD_URL = process.env.OLD_URL;
const OLD_KEY = process.env.OLD_KEY; // 旧项目 service_role key
const NEW_URL = process.env.NEW_URL;
const NEW_KEY = process.env.NEW_KEY; // 新项目 service_role key

if (!OLD_URL || !OLD_KEY || !NEW_URL || !NEW_KEY) {
  console.error('缺少环境变量：需要 OLD_URL OLD_KEY NEW_URL NEW_KEY');
  process.exit(1);
}

const TABLES = ['config', 'picks', 'punches', 'claims', 'logs'];
const PAGE = 1000;

async function fetchAll(table) {
  const rows = [];
  let offset = 0;
  while (true) {
    const res = await fetch(
      `${OLD_URL}/rest/v1/${table}?select=*&order=id.asc.nullsfirst&offset=${offset}&limit=${PAGE}`,
      { headers: { apikey: OLD_KEY, Authorization: `Bearer ${OLD_KEY}` } }
    );
    if (!res.ok) {
      // 有的表没有 id 列（如 picks），改用不带 order 的分页
      const res2 = await fetch(
        `${OLD_URL}/rest/v1/${table}?select=*&offset=${offset}&limit=${PAGE}`,
        { headers: { apikey: OLD_KEY, Authorization: `Bearer ${OLD_KEY}` } }
      );
      if (!res2.ok) throw new Error(`读取 ${table} 失败: ${res2.status} ${await res2.text()}`);
      const batch = await res2.json();
      rows.push(...batch);
      if (batch.length < PAGE) break;
      offset += PAGE;
      continue;
    }
    const batch = await res.json();
    rows.push(...batch);
    if (batch.length < PAGE) break;
    offset += PAGE;
  }
  return rows;
}

async function insertAll(table, rows) {
  if (!rows.length) return 0;
  let inserted = 0;
  for (let i = 0; i < rows.length; i += PAGE) {
    const chunk = rows.slice(i, i + PAGE);
    const res = await fetch(`${NEW_URL}/rest/v1/${table}`, {
      method: 'POST',
      headers: {
        apikey: NEW_KEY,
        Authorization: `Bearer ${NEW_KEY}`,
        'Content-Type': 'application/json',
        Prefer: 'resolution=merge-duplicates',
      },
      body: JSON.stringify(chunk),
    });
    if (!res.ok) throw new Error(`写入 ${table} 失败: ${res.status} ${await res.text()}`);
    inserted += chunk.length;
  }
  return inserted;
}

async function resetSequence(table) {
  // 通过 RPC 重置自增序列（punches / logs 是 bigserial）
  const sql = `SELECT setval(pg_get_serial_sequence('${table}','id'), COALESCE((SELECT MAX(id) FROM ${table}),1));`;
  const res = await fetch(`${NEW_URL}/rest/v1/rpc/exec_sql`, {
    method: 'POST',
    headers: { apikey: NEW_KEY, Authorization: `Bearer ${NEW_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: sql }),
  });
  // exec_sql 可能不存在（需要预建），失败则记录，稍后在 SQL 编辑器手动重置
  if (!res.ok) {
    console.log(`  ⚠️ ${table} 序列自动重置不可用，稍后需在 SQL 编辑器手动执行：`);
    console.log(`     SELECT setval(pg_get_serial_sequence('${table}','id'), (SELECT MAX(id) FROM ${table}));`);
  } else {
    console.log(`  ✓ ${table} 自增序列已重置`);
  }
}

async function countRows(url, key, table) {
  const res = await fetch(`${url}/rest/v1/${table}?select=*`, {
    headers: { apikey: key, Authorization: `Bearer ${key}`, Prefer: 'count=exact', Range: '0-0' },
  });
  const range = res.headers.get('content-range') || '';
  const m = range.match(/\/(\d+)/);
  return m ? parseInt(m[1], 10) : -1;
}

(async () => {
  console.log('=== 开始迁移：孟买 → 新加坡 ===\n');
  const summary = [];
  for (const t of TABLES) {
    console.log(`▶ ${t}`);
    const rows = await fetchAll(t);
    console.log(`  旧库读取 ${rows.length} 行`);
    const inserted = await insertAll(t, rows);
    console.log(`  新库写入 ${inserted} 行`);
    if (t === 'punches' || t === 'logs') await resetSequence(t);
    summary.push({ table: t, old: rows.length, new: inserted });
    console.log('');
  }

  console.log('=== 条数核对 ===');
  let allOk = true;
  for (const s of summary) {
    const newCount = await countRows(NEW_URL, NEW_KEY, s.table);
    const ok = newCount === s.old;
    if (!ok) allOk = false;
    console.log(`${ok ? '✓' : '✗'} ${s.table}: 旧库 ${s.old} → 新库 ${newCount}`);
  }
  console.log(allOk ? '\n✅ 迁移完成，所有表条数一致' : '\n⚠️ 有表条数不一致，请检查');
})().catch((e) => {
  console.error('迁移出错:', e.message);
  process.exit(1);
});
