-- ============================================================
--  选班数据服务端化改造：config 单行 JSON → 独立 picks 表
--  目标：一人一天一班次 = 一行。不同人的操作不碰同一行，
--       从结构上杜绝并发覆盖；满员用事务级咨询锁原子卡死。
--
--  ⚠️ 重要：请用 Cmd+A（全选）后再点 Run / 运行！
--  本脚本在 Supabase SQL 编辑器以 postgres 身份运行（可绕过 RLS 迁移数据）。
--  幂等：可安全重复执行。
--
--  执行顺序：先跑本脚本 → 再部署新前端 → 全员刷新。
-- ============================================================

-- ===== 第1步：建 picks 表 + 索引 =====
CREATE TABLE IF NOT EXISTS public.picks (
  date text NOT NULL,
  mid  text NOT NULL,
  sid  int  NOT NULL,
  created_at timestamptz DEFAULT now(),
  PRIMARY KEY (date, mid, sid)
);
CREATE INDEX IF NOT EXISTS idx_picks_date_sid ON public.picks (date, sid);
CREATE INDEX IF NOT EXISTS idx_picks_date     ON public.picks (date);

-- ===== 第2步：RLS 策略（可读/可增/可删；逻辑由函数控制）=====
ALTER TABLE public.picks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS picks_sel ON public.picks;
DROP POLICY IF EXISTS picks_ins ON public.picks;
DROP POLICY IF EXISTS picks_del ON public.picks;
CREATE POLICY picks_sel ON public.picks FOR SELECT USING (true);
CREATE POLICY picks_ins ON public.picks FOR INSERT WITH CHECK (true);
CREATE POLICY picks_del ON public.picks FOR DELETE USING (true);

-- ===== 第3步：把 config 里旧的整块 picks 迁移成行（已有数据不丢）=====
INSERT INTO public.picks (date, mid, sid)
SELECT d.key AS date, m.key AS mid, (s.val)::text::int AS sid
FROM config c,
     LATERAL jsonb_each(c.data)        AS d(key, value),
     LATERAL jsonb_each(d.value)       AS m(key, value),
     LATERAL jsonb_array_elements(m.value) AS s(val)
WHERE c.id = 'picks'
ON CONFLICT (date, mid, sid) DO NOTHING;

-- ===== 第4步：函数 =====

-- 4.1 全量快照（前端拉取用，返回 {data:<整块>, updated_at:<毫秒>}，与旧结构兼容）
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

-- 4.2 某时段已选人数（满员实时校验用，可排除某人）
CREATE OR REPLACE FUNCTION public.picks_count(p_date text, p_sid int, p_except_mid text DEFAULT NULL)
RETURNS int LANGUAGE sql STABLE AS $$
  SELECT COUNT(*)::int FROM public.picks
   WHERE date = p_date AND sid = p_sid
     AND (p_except_mid IS NULL OR mid <> p_except_mid);
$$;

-- 4.3 增量加一个班次（返回最新整块）
CREATE OR REPLACE FUNCTION public.pick_add(p_date text, p_mid text, p_sid int)
RETURNS jsonb LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO public.picks(date, mid, sid) VALUES (p_date, p_mid, p_sid)
    ON CONFLICT (date, mid, sid) DO NOTHING;
  DELETE FROM public.picks WHERE date < to_char(CURRENT_DATE - INTERVAL '60 days', 'YYYY-MM-DD');
  RETURN (public.picks_snapshot()) -> 'data';
END; $$;

-- 4.4 增量删一个班次（返回最新整块）
CREATE OR REPLACE FUNCTION public.pick_remove(p_date text, p_mid text, p_sid int)
RETURNS jsonb LANGUAGE plpgsql AS $$
BEGIN
  DELETE FROM public.picks WHERE date = p_date AND mid = p_mid AND sid = p_sid;
  RETURN (public.picks_snapshot()) -> 'data';
END; $$;

-- 4.5 整体设置某人某天班次（管理员整格编辑/一键清空用，返回最新整块）
CREATE OR REPLACE FUNCTION public.pick_set(p_date text, p_mid text, p_sids jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $$
BEGIN
  DELETE FROM public.picks WHERE date = p_date AND mid = p_mid;
  INSERT INTO public.picks(date, mid, sid)
    SELECT p_date, p_mid, (x.val)::text::int
      FROM jsonb_array_elements(p_sids) AS x(val)
  ON CONFLICT (date, mid, sid) DO NOTHING;
  DELETE FROM public.picks WHERE date < to_char(CURRENT_DATE - INTERVAL '60 days', 'YYYY-MM-DD');
  RETURN (public.picks_snapshot()) -> 'data';
END; $$;

-- 4.6 满员原子校验 + 加班（咨询锁只锁"同一时段"，不同时段互不阻塞）
CREATE OR REPLACE FUNCTION public.pick_add_cap(p_date text, p_mid text, p_sid int, p_admin boolean)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE v_cap int := 0; v_count int;
BEGIN
  BEGIN
    SELECT COALESCE((data #>> ARRAY[p_date, p_sid::text])::int, 0) INTO v_cap
      FROM config WHERE id = 'slotcap';
  EXCEPTION WHEN OTHERS THEN v_cap := 0;
  END;
  IF v_cap IS NULL THEN v_cap := 0; END IF;

  -- 事务级咨询锁：仅序列化"同一日期同一时段"的满员校验，杜绝并发超员
  PERFORM pg_advisory_xact_lock(hashtext('pickcap:' || p_date || ':' || p_sid::text));

  SELECT COUNT(*)::int INTO v_count FROM public.picks WHERE date = p_date AND sid = p_sid;
  IF v_cap > 0 AND v_count >= v_cap AND NOT p_admin THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'full', 'count', v_count, 'cap', v_cap);
  END IF;

  INSERT INTO public.picks(date, mid, sid) VALUES (p_date, p_mid, p_sid)
    ON CONFLICT (date, mid, sid) DO NOTHING;
  DELETE FROM public.picks WHERE date < to_char(CURRENT_DATE - INTERVAL '60 days', 'YYYY-MM-DD');

  RETURN jsonb_build_object('ok', true, 'picks', (public.picks_snapshot()) -> 'data', 'count', v_count + 1, 'cap', v_cap);
END; $$;

-- ===== 第4.7步：过渡期同步触发器 =====
-- 选班表一变，就把 config 里旧的整块 picks 同步刷新，
-- 保证"还没刷新到新版前端"的客户端读旧块也不会错乱。
-- 待全员升级到新版前端后，可执行文末注释的语句拆掉它以获得极致并发性能。
CREATE OR REPLACE FUNCTION public.sync_picks_to_config() RETURNS trigger AS $$
BEGIN
  UPDATE config
     SET data = (public.picks_snapshot()) -> 'data',
         updated_at = (EXTRACT(epoch FROM now()) * 1000)::bigint
   WHERE id = 'picks';
  RETURN NULL;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS picks_sync_config ON public.picks;
CREATE TRIGGER picks_sync_config
  AFTER INSERT OR DELETE ON public.picks
  FOR EACH STATEMENT EXECUTE FUNCTION public.sync_picks_to_config();

-- ===== 第5步：授权（容错）=====
DO $$
BEGIN
  BEGIN EXECUTE 'GRANT SELECT, INSERT, DELETE ON public.picks TO anon';          EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT SELECT, INSERT, DELETE ON public.picks TO authenticated'; EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.picks_snapshot() TO anon, authenticated';        EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.picks_count(text,int,text) TO anon, authenticated'; EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_add(text,text,int) TO anon, authenticated';    EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_remove(text,text,int) TO anon, authenticated'; EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_set(text,text,jsonb) TO anon, authenticated';  EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_add_cap(text,text,int,boolean) TO anon, authenticated'; EXCEPTION WHEN OTHERS THEN NULL; END;
END $$;

-- ===== 第6步：自检 =====
DO $$
DECLARE n_tbl int; n_fn int; n_rows int;
BEGIN
  SELECT count(*) INTO n_tbl FROM information_schema.tables WHERE table_schema='public' AND table_name='picks';
  SELECT count(*) INTO n_fn FROM pg_proc p JOIN pg_namespace ns ON ns.oid=p.pronamespace
    WHERE ns.nspname='public' AND p.proname IN ('picks_snapshot','picks_count','pick_add','pick_remove','pick_set','pick_add_cap');
  SELECT count(*) INTO n_rows FROM public.picks;
  IF n_tbl < 1 THEN RAISE EXCEPTION '自检失败：picks 表未创建'; END IF;
  IF n_fn < 6 THEN RAISE EXCEPTION '自检失败：函数不全（%/6），请确认已全选脚本运行', n_fn; END IF;
END $$;

SELECT '服务端化完成' AS 结果,
       (SELECT count(*) FROM public.picks) AS 已迁移选班条数;

-- ============================================================
-- 【可选·日后优化】待确认全员都已刷新到新版前端后，
-- 可单独执行下面两句拆掉过渡触发器，彻底消除 config 行锁，获得极致并发：
--   DROP TRIGGER IF EXISTS picks_sync_config ON public.picks;
--   DROP FUNCTION IF EXISTS public.sync_picks_to_config();
-- （不拆也完全正确，只是写入时会多一次对 config 旧块的同步。）
-- ============================================================
