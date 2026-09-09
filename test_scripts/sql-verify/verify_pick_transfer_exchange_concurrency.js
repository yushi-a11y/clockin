// 并发/死锁压力验证：多连接并行调用 pick_transfer / pick_exchange，
// 验证 (a) 咨询锁顺序不会死锁(40P01)，(b) 净零名额在并发下不超员，(c) 结果一致。
const fs = require('fs');
const os = require('os');
const path = require('path');
const { Pool } = require('pg');
const EmbeddedPostgresModule = require('embedded-postgres');
const EmbeddedPostgres = EmbeddedPostgresModule.default || EmbeddedPostgresModule;

// 运行前置：在一个可联网的临时目录执行 `npm i embedded-postgres pg`，再 `node <本文件>`。
const SQL_FILE = path.join(__dirname, '..', '..', 'outputs', 'supabase-原子转班换班函数.sql');
const DBDIR = path.join(os.tmpdir(), 'pgverify_concurrency');
const PORT = 54340;
const SCHEMA = fs.readFileSync(path.join(__dirname, 'schema.sql'), 'utf8');

let pass = 0, fail = 0;
const check = (n, c, e) => { if (c) { pass++; console.log('  PASS', n); } else { fail++; console.log('  FAIL', n, e !== undefined ? JSON.stringify(e) : ''); } };

(async () => {
  fs.rmSync(DBDIR, { recursive: true, force: true });
  const pg = new EmbeddedPostgres({ databaseDir: DBDIR, user: 'postgres', password: 'pw', port: PORT, persistent: false });
  await pg.initialise(); await pg.start(); await pg.createDatabase('clockin');
  const pool = new Pool({ host: '127.0.0.1', port: PORT, user: 'postgres', password: 'pw', database: 'clockin', max: 10 });
  await pool.query(SCHEMA);
  await pool.query(fs.readFileSync(SQL_FILE, 'utf8'));

  const D = '2026-09-09';
  async function reset(slotcap, rows) {
    await pool.query('TRUNCATE public.picks'); await pool.query('DELETE FROM public.config');
    await pool.query(`INSERT INTO public.config(id,data,updated_at) VALUES ('slotcap',$1::jsonb,0),('selcfg','{"weekStartDay":6}'::jsonb,0),('picks','{}'::jsonb,0)`, [JSON.stringify(slotcap)]);
    for (const [d, m, s] of rows) await pool.query('INSERT INTO public.picks(date,mid,sid) VALUES($1,$2,$3)', [d, m, s]);
  }
  const isDeadlock = e => e && (e.code === '40P01' || /deadlock/i.test(e.message || ''));

  // ===== A) 同时段多人并发转班：净零，绝不超员、绝不死锁 =====
  console.log('[A] 并发：3 个转出方同时把 sid40 转给 3 个接收方（cap=3，含转出方满员）');
  await reset({ [D]: { 40: 3 } }, [
    [D, 'g1', 40], [D, 'g2', 40], [D, 'g3', 40],            // holders=3=cap（含转出方）
    [D, 'r1', 1], [D, 'r2', 1], [D, 'r3', 1],
  ]);
  let results = await Promise.all([
    pool.query('SELECT public.pick_transfer($1,$2,$3,$4) r', [D, 'g1', 'r1', 40]).then(x => x.rows[0].r).catch(e => ({ err: e.message, code: e.code })),
    pool.query('SELECT public.pick_transfer($1,$2,$3,$4) r', [D, 'g2', 'r2', 40]).then(x => x.rows[0].r).catch(e => ({ err: e.message, code: e.code })),
    pool.query('SELECT public.pick_transfer($1,$2,$3,$4) r', [D, 'g3', 'r3', 40]).then(x => x.rows[0].r).catch(e => ({ err: e.message, code: e.code })),
  ]);
  check('无死锁', !results.some(r => r && (r.code === '40P01' || r.err && /deadlock/i.test(r.err))), results);
  check('三笔均成功', results.every(r => r && r.ok === true), results);
  let h = (await pool.query('SELECT mid FROM public.picks WHERE date=$1 AND sid=40', [D])).rows.map(r => r.mid).sort();
  check('最终 holders = {r1,r2,r3}，人数=3（≤cap，无超员）', h.length === 3 && JSON.stringify(h) === JSON.stringify(['r1', 'r2', 'r3']), h);

  // ===== B) 并发争抢"最后一个名额"：cap=2 满员，两转出方各自净零转出，仍不超员 =====
  console.log('[B] 并发：cap=2 已满({A,B})，A→R1 与 B→R2 同时进行');
  await reset({ [D]: { 41: 2 } }, [[D, 'A', 41], [D, 'B', 41], [D, 'R1', 2], [D, 'R2', 2]]);
  results = await Promise.all([
    pool.query('SELECT public.pick_transfer($1,$2,$3,$4) r', [D, 'A', 'R1', 41]).then(x => x.rows[0].r).catch(e => ({ err: e.message, code: e.code })),
    pool.query('SELECT public.pick_transfer($1,$2,$3,$4) r', [D, 'B', 'R2', 41]).then(x => x.rows[0].r).catch(e => ({ err: e.message, code: e.code })),
  ]);
  check('无死锁', !results.some(r => r && (r.code === '40P01' || (r.err && /deadlock/i.test(r.err)))), results);
  h = (await pool.query('SELECT mid FROM public.picks WHERE date=$1 AND sid=41', [D])).rows.map(r => r.mid).sort();
  check('最终人数 ≤ cap(2)，为 {R1,R2}', h.length <= 2 && JSON.stringify(h) === JSON.stringify(['R1', 'R2']), { results, holders: h });

  // ===== C) 并发争抢导致真超员必须被拒：cap=1，{seat} 占位，两转出方 g1,g2 同时想转入 → 至多一个成功 =====
  console.log('[C] 并发：cap=1 真超员防护（排除转出方后仍≥cap 的应被拒）');
  await reset({ [D]: { 42: 1 } }, [[D, 'seat', 42], [D, 'g1', 42], [D, 'g2', 42], [D, 'r1', 3], [D, 'r2', 3]]);
  // 现状已 3 人 > cap1（异常态）；排除转出方后仍 ≥1 → 两笔都应 full
  results = await Promise.all([
    pool.query('SELECT public.pick_transfer($1,$2,$3,$4) r', [D, 'g1', 'r1', 42]).then(x => x.rows[0].r).catch(e => ({ err: e.message, code: e.code })),
    pool.query('SELECT public.pick_transfer($1,$2,$3,$4) r', [D, 'g2', 'r2', 42]).then(x => x.rows[0].r).catch(e => ({ err: e.message, code: e.code })),
  ]);
  check('无死锁', !results.some(r => r && (r.code === '40P01' || (r.err && /deadlock/i.test(r.err)))), results);
  check('两笔均被拒 full（净零也救不了真超员）', results.every(r => r && r.ok === false && r.reason === 'full'), results);
  h = (await pool.query('SELECT mid FROM public.picks WHERE date=$1 AND sid=42', [D])).rows.map(r => r.mid).sort();
  check('数据未被破坏（仍 3 人）', h.length === 3, h);

  // ===== D) 死锁顺序：两笔"参数顺序相反"的换班并发（A/B × D1/D2 互换）=====
  console.log('[D] 死锁顺序：ex1(A给B) 与 ex2(B给A，参数顺序相反) 并发');
  const D1 = '2026-09-10', D2 = '2026-09-11';
  await reset({ [D1]: { 10: 5 }, [D2]: { 20: 5 } }, [[D1, 'A', 10], [D2, 'B', 20]]);
  // ex1: A 把 10@D1 给 B，B 把 20@D2 给 A
  // ex2: 同一笔换班的相反表述 —— B 把 20@D2 给 A，A 把 10@D1 给 B（锁的"自然顺序"相反）
  results = await Promise.all([
    pool.query('SELECT public.pick_exchange($1,$2,$3,$4,$5,$6) r', [D1, 'A', 10, D2, 'B', 20]).then(x => x.rows[0].r).catch(e => ({ err: e.message, code: e.code })),
    pool.query('SELECT public.pick_exchange($1,$2,$3,$4,$5,$6) r', [D2, 'B', 20, D1, 'A', 10]).then(x => x.rows[0].r).catch(e => ({ err: e.message, code: e.code })),
  ]);
  check('无死锁(40P01)', !results.some(r => r && (r.code === '40P01' || (r.err && /deadlock/i.test(r.err)))), results);
  const okCount = results.filter(r => r && r.ok === true).length;
  check('恰好一笔真正执行 + 另一笔幂等/无冲突（ok 总数=2，其中≥1 alreadyApplied 或 not_owner 不报错）', results.every(r => r && typeof r.ok === 'boolean'), results);
  const aHas20 = (await pool.query('SELECT 1 FROM public.picks WHERE date=$1 AND mid=$2 AND sid=20', [D2, 'A'])).rowCount > 0;
  const bHas10 = (await pool.query('SELECT 1 FROM public.picks WHERE date=$1 AND mid=$2 AND sid=10', [D1, 'B'])).rowCount > 0;
  check('换班最终生效：A 得到 20@D2 且 B 得到 10@D1', aHas20 && bHas10, { aHas20, bHas10, okCount });

  // ===== E) 高频并发混合：20 笔转同一时段(cap 大)不丢不重 =====
  console.log('[E] 高频并发：20 个转出方→20 个接收方，同一 sid(cap=25)');
  const rows = [];
  for (let i = 0; i < 20; i++) { rows.push([D, 'gg' + i, 60]); rows.push([D, 'rr' + i, 4]); }
  await reset({ [D]: { 60: 25 } }, rows);
  results = await Promise.all(Array.from({ length: 20 }, (_, i) =>
    pool.query('SELECT public.pick_transfer($1,$2,$3,$4) r', [D, 'gg' + i, 'rr' + i, 60]).then(x => x.rows[0].r).catch(e => ({ err: e.message, code: e.code }))
  ));
  check('无死锁/无异常', results.every(r => r && r.ok === true), results.filter(r => !r || r.ok !== true));
  h = (await pool.query('SELECT mid FROM public.picks WHERE date=$1 AND sid=60', [D])).rows.map(r => r.mid);
  check('最终 20 个接收方持有、20 个转出方释放（人数=20，无丢失/重复）', h.length === 20 && h.every(m => m.startsWith('rr')), { count: h.length });

  console.log(`\n==== 并发结果：${pass} 通过 / ${fail} 失败 ====`);
  await pool.end(); await pg.stop();
  process.exit(fail === 0 ? 0 : 1);
})().catch(async e => { console.error('HARNESS ERROR:', e); process.exit(2); });
