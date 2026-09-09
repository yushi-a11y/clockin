// 在真实 Postgres 上验证 pick_transfer / pick_exchange。
// 搭建与线上一致的最小 schema（config + picks 行表 + picks_snapshot），
// 原样加载 outputs/supabase-原子转班换班函数.sql，跑用例电池。
const fs = require('fs');
const os = require('os');
const path = require('path');
const EmbeddedPostgresModule = require('embedded-postgres');
const EmbeddedPostgres = EmbeddedPostgresModule.default || EmbeddedPostgresModule;

// 运行前置：在一个可联网的临时目录执行 `npm i embedded-postgres pg`，再 `node <本文件>`。
// 它会拉起真实 Postgres，原样加载 outputs/supabase-原子转班换班函数.sql 并跑用例电池。
const SQL_FILE = path.join(__dirname, '..', '..', 'outputs', 'supabase-原子转班换班函数.sql');
const DBDIR = path.join(os.tmpdir(), 'pgverify_correctness');
const PORT = 54339;

const SCHEMA = `
CREATE TABLE IF NOT EXISTS public.config (id text PRIMARY KEY, data jsonb, updated_at bigint);
CREATE TABLE IF NOT EXISTS public.picks (
  date text NOT NULL, mid text NOT NULL, sid int NOT NULL,
  created_at timestamptz DEFAULT now(), PRIMARY KEY (date, mid, sid)
);
CREATE INDEX IF NOT EXISTS idx_picks_date_sid ON public.picks (date, sid);
CREATE OR REPLACE FUNCTION public.picks_snapshot()
RETURNS jsonb LANGUAGE sql STABLE AS $$
  SELECT jsonb_build_object(
    'data', COALESCE((
      SELECT jsonb_object_agg(p_date, members)
      FROM (
        SELECT date AS p_date, jsonb_object_agg(mid, sids) AS members
        FROM (
          SELECT date, mid, jsonb_agg(sid ORDER BY sid) AS sids
          FROM public.picks GROUP BY date, mid
        ) dm GROUP BY date
      ) d
    ), '{}'::jsonb),
    'updated_at', (EXTRACT(epoch FROM now()) * 1000)::bigint
  );
$$;
`;

let pass = 0, fail = 0;
function check(name, cond, extra) {
  if (cond) { pass++; console.log('  PASS', name); }
  else { fail++; console.log('  FAIL', name, extra !== undefined ? JSON.stringify(extra) : ''); }
}

(async () => {
  fs.rmSync(DBDIR, { recursive: true, force: true });
  const pg = new EmbeddedPostgres({ databaseDir: DBDIR, user: 'postgres', password: 'pw', port: PORT, persistent: false });
  await pg.initialise();
  await pg.start();
  await pg.createDatabase('clockin');
  const client = pg.getPgClient('clockin');
  await client.connect();
  const q = (sql, params) => client.query(sql, params);

  // 建 schema + 加载被测函数（原样执行整个 SQL 文件，含 DO 授权块与自检）
  await q(SCHEMA);
  const fnSql = fs.readFileSync(SQL_FILE, 'utf8');
  await q(fnSql);
  console.log('SQL 文件加载成功（CREATE FUNCTION + 授权 + 自检均无语法/语义错误）\n');

  const D = '2026-09-09';
  async function reset(slotcap, selcfg, rows) {
    await q('TRUNCATE public.picks');
    await q('DELETE FROM public.config');
    await q(`INSERT INTO public.config(id,data,updated_at) VALUES ('slotcap',$1::jsonb,0),('selcfg',$2::jsonb,0),('picks','{}'::jsonb,0)`,
      [JSON.stringify(slotcap), JSON.stringify(selcfg)]);
    for (const [date, mid, sid] of rows) await q('INSERT INTO public.picks(date,mid,sid) VALUES($1,$2,$3)', [date, mid, sid]);
  }
  const holds = async (date, mid, sid) => (await q('SELECT 1 FROM public.picks WHERE date=$1 AND mid=$2 AND sid=$3', [date, String(mid), sid])).rowCount > 0;
  const holders = async (date, sid) => (await q('SELECT mid FROM public.picks WHERE date=$1 AND sid=$2 ORDER BY mid', [date, sid])).rows.map(r => r.mid);
  const dayCount = async (date, mid) => (await q('SELECT count(*)::int c FROM public.picks WHERE date=$1 AND mid=$2', [date, String(mid)])).rows[0].c;
  const transfer = (date, from, to, sid) => q('SELECT public.pick_transfer($1,$2,$3,$4) r', [date, String(from), String(to), sid]).then(x => x.rows[0].r);
  const exchange = (gd, gm, gs, td, rm, ts) => q('SELECT public.pick_exchange($1,$2,$3,$4,$5,$6) r', [gd, String(gm), gs, td, String(rm), ts]).then(x => x.rows[0].r);

  // ===== 用例 1：线上复现场景 —— 含转出方正好满员(cap 5/5)，净零应成功 =====
  console.log('[1] 满员含转出方的转班应成功（净零名额）');
  await reset({ [D]: { 22: 5 } }, { weekStartDay: 6 }, [
    [D, '5', 22], [D, '9', 22], [D, '10', 22], [D, '13', 22], [D, '14', 22], // holders(22)=5, cap5
    [D, '7', 7], [D, '7', 17], [D, '7', 21],                                 // 接收方 mid7 现有 3 个
    [D, '10', 12], [D, '10', 13],
  ]);
  let r = await transfer(D, '10', '7', 22);
  check('返回 ok:true', r.ok === true, r);
  check('alreadyApplied=false', r.alreadyApplied === false, r);
  check('转出方 mid10 已释放 sid22', !(await holds(D, '10', 22)));
  check('接收方 mid7 已获得 sid22', await holds(D, '7', 22));
  check('时段人数仍为 5（净零，未超上限）', (await holders(D, 22)).length === 5, await holders(D, 22));
  check('holders 变为集合 {5,7,9,13,14}', JSON.stringify((await holders(D, 22)).map(Number).sort((a,b)=>a-b)) === JSON.stringify([5,7,9,13,14]), await holders(D, 22));
  check('返回 data 为最新整块', r.data && Array.isArray(r.data[D]['7']) && r.data[D]['7'].includes(22), r.data && r.data[D]);
  const mirror = (await q("SELECT data FROM public.config WHERE id='picks'")).rows[0].data;
  check('config 兼容镜像已同步(mid7 含 22, mid10 不含)', Array.isArray(mirror[D]['7']) && mirror[D]['7'].includes(22) && !mirror[D]['10'].includes(22), mirror[D]);

  // ===== 用例 2：幂等 —— 重复接受同一转班 =====
  console.log('[2] 重复转班应幂等（alreadyApplied）');
  r = await transfer(D, '10', '7', 22); // 此时 mid10 已无、mid7 已有
  check('第二次返回 ok:true 且 alreadyApplied:true', r.ok === true && r.alreadyApplied === true, r);
  check('未产生重复行(mid7 只有一个 22)', (await q("SELECT count(*)::int c FROM public.picks WHERE date=$1 AND mid='7' AND sid=22", [D])).rows[0].c === 1);

  // ===== 用例 3：转出方不持有 → not_owner =====
  console.log('[3] 转出方不持有该班次 → not_owner');
  await reset({ [D]: { 22: 5 } }, { weekStartDay: 6 }, [[D, '7', 7]]);
  r = await transfer(D, '10', '7', 22);
  check('not_owner', r.ok === false && r.reason === 'not_owner', r);
  check('未写入任何 22', (await holders(D, 22)).length === 0);

  // ===== 用例 4：接收方已持有 → duplicate =====
  console.log('[4] 双方都持有同一班次 → duplicate');
  await reset({ [D]: { 22: 5 } }, { weekStartDay: 6 }, [[D, '10', 22], [D, '7', 22]]);
  r = await transfer(D, '10', '7', 22);
  check('duplicate', r.ok === false && r.reason === 'duplicate', r);
  check('转出方仍持有(未被误删)', await holds(D, '10', 22));

  // ===== 用例 5：接收方当天已满 7 → dayfull =====
  console.log('[5] 接收方当天已达 7 个 → dayfull');
  await reset({ [D]: { 22: 9 } }, { weekStartDay: 6 }, [
    [D, '10', 22],
    [D, '7', 1], [D, '7', 2], [D, '7', 3], [D, '7', 4], [D, '7', 5], [D, '7', 6], [D, '7', 8],
  ]);
  r = await transfer(D, '10', '7', 22);
  check('dayfull', r.ok === false && r.reason === 'dayfull', r);
  check('转出方未被删除(原子拒绝)', await holds(D, '10', 22));

  // ===== 用例 6：真超员（排除转出方后仍 ≥ cap）→ full =====
  console.log('[6] 排除转出方后仍满员 → full（真超员）');
  await reset({ [D]: { 30: 2 } }, { weekStartDay: 6 }, [[D, 'a', 30], [D, 'b', 30], [D, 'c', 30]]); // 已 3 人，cap 2（异常态）
  r = await transfer(D, 'a', 'd', 30);
  check('full', r.ok === false && r.reason === 'full', r);
  check('未改动数据', (await holders(D, 30)).length === 3);

  // ===== 用例 7：同 mid 转给自己 → invalid =====
  console.log('[7] from==to → invalid');
  await reset({ [D]: { 22: 5 } }, { weekStartDay: 6 }, [[D, '10', 22]]);
  r = await transfer(D, '10', '10', 22);
  check('invalid', r.ok === false && r.reason === 'invalid', r);

  // ===== 用例 8：双向换班（跨日期）正常 =====
  console.log('[8] 双向换班跨日期正常互换');
  const D1 = '2026-09-10', D2 = '2026-09-11';
  await reset({ [D1]: { 10: 5 }, [D2]: { 20: 5 } }, { weekStartDay: 6 }, [
    [D1, 'G', 10], [D2, 'R', 20], [D1, 'G', 11],
  ]);
  r = await exchange(D1, 'G', 10, D2, 'R', 20);
  check('ok:true', r.ok === true, r);
  check('G 不再持有 10@D1', !(await holds(D1, 'G', 10)));
  check('G 获得 20@D2', await holds(D2, 'G', 20));
  check('R 不再持有 20@D2', !(await holds(D2, 'R', 20)));
  check('R 获得 10@D1', await holds(D1, 'R', 10));
  check('G 保留其它班次 11@D1', await holds(D1, 'G', 11));

  // ===== 用例 9：双向换班幂等 =====
  console.log('[9] 重复换班应幂等（alreadyApplied）');
  r = await exchange(D1, 'G', 10, D2, 'R', 20);
  check('alreadyApplied:true', r.ok === true && r.alreadyApplied === true, r);

  // ===== 用例 10：换班 not_owner / duplicate =====
  console.log('[10] 换班 not_owner 与 duplicate');
  await reset({ [D1]: { 10: 5 }, [D2]: { 20: 5 } }, { weekStartDay: 6 }, [[D2, 'R', 20]]);
  r = await exchange(D1, 'G', 10, D2, 'R', 20); // G 不持有 10@D1
  check('not_owner', r.ok === false && r.reason === 'not_owner', r);
  await reset({ [D1]: { 10: 5 }, [D2]: { 20: 5 } }, { weekStartDay: 6 }, [[D1, 'G', 10], [D2, 'R', 20], [D1, 'R', 10]]);
  r = await exchange(D1, 'G', 10, D2, 'R', 20); // R 已持有 10@D1
  check('duplicate', r.ok === false && r.reason === 'duplicate', r);
  check('未改动(G 仍持 10@D1)', await holds(D1, 'G', 10));

  // ===== 用例 11：换班净零名额（含转出方满员）应成功 =====
  console.log('[11] 换班净零名额（时段含转出方正好满员）应成功');
  await reset({ [D1]: { 10: 2 }, [D2]: { 20: 2 } }, { weekStartDay: 6 }, [
    [D1, 'G', 10], [D1, 'X', 10],   // 10@D1 holders={G,X}=2, cap2（含转出方 G 满员）
    [D2, 'R', 20], [D2, 'Y', 20],   // 20@D2 holders={R,Y}=2, cap2（含转出方 R 满员）
  ]);
  r = await exchange(D1, 'G', 10, D2, 'R', 20);
  check('ok:true（净零，两个时段都不误判满员）', r.ok === true, r);
  check('10@D1 holders 变 {R,X}', JSON.stringify(await holders(D1, 10)) === JSON.stringify(['R', 'X']), await holders(D1, 10));
  check('20@D2 holders 变 {G,Y}', JSON.stringify(await holders(D2, 20)) === JSON.stringify(['G', 'Y']), await holders(D2, 20));

  // ===== 用例 12：换班真超员 → full =====
  console.log('[12] 换班排除转出方后仍满员 → full');
  await reset({ [D1]: { 10: 1 }, [D2]: { 20: 5 } }, { weekStartDay: 6 }, [
    [D1, 'G', 10], [D1, 'X', 10],   // 10@D1 cap1 但已有 {G,X}=2（异常），排除 G 后 {X}=1>=1 → full
    [D2, 'R', 20],
  ]);
  r = await exchange(D1, 'G', 10, D2, 'R', 20);
  check('full', r.ok === false && r.reason === 'full', r);
  check('未改动(G 仍持 10@D1)', await holds(D1, 'G', 10));

  // ===== 用例 13：换班 dayfull =====
  console.log('[13] 换班接收侧当天已满 → dayfull');
  await reset({ [D1]: { 10: 9 }, [D2]: { 20: 9 } }, { weekStartDay: 6 }, [
    [D1, 'G', 10], [D2, 'R', 20],
    [D1, 'R', 1], [D1, 'R', 2], [D1, 'R', 3], [D1, 'R', 4], [D1, 'R', 5], [D1, 'R', 6], [D1, 'R', 7], // R 在 D1 已 7 个
  ]);
  r = await exchange(D1, 'G', 10, D2, 'R', 20); // R 将在 D1 获得 10 → 超 7
  check('dayfull', r.ok === false && r.reason === 'dayfull', r);
  check('原子拒绝(G 仍持 10@D1, R 仍持 20@D2)', (await holds(D1, 'G', 10)) && (await holds(D2, 'R', 20)));

  console.log(`\n==== 结果：${pass} 通过 / ${fail} 失败 ====`);
  await client.end();
  await pg.stop();
  process.exit(fail === 0 ? 0 : 1);
})().catch(async e => { console.error('HARNESS ERROR:', e); process.exit(2); });
