-- ============================================================
--  新加坡项目（御史）一键建表脚本
--  与旧孟买项目结构完全一致：表 / 索引 / RLS / 函数 / 触发器
--  注意：不含已拆除的过渡触发器 picks_sync_config
--
--  ⚠️ Cmd+A 全选后，在新项目（txtduqfhugjupxdoxdvp）的 SQL 编辑器运行
--  幂等：可安全重复执行
-- ============================================================

-- ===== 1. 建表 =====
CREATE TABLE IF NOT EXISTS public.config (
  id         text PRIMARY KEY,
  data       jsonb,
  updated_at bigint
);

CREATE TABLE IF NOT EXISTS public.punches (
  id     bigserial PRIMARY KEY,
  sid    integer,
  t      text,
  time   text,
  ts     bigint,
  mid    integer,
  date   text,
  name   text,
  makeup boolean
);

CREATE TABLE IF NOT EXISTS public.claims (
  id         text PRIMARY KEY,
  fp         text,
  by_name    text,
  expires_at bigint,
  updated_at bigint
);

CREATE TABLE IF NOT EXISTS public.logs (
  id         bigserial PRIMARY KEY,
  ts         bigint,
  account    text,
  role       text,
  action     text,
  detail     text,
  created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.picks (
  date text NOT NULL,
  mid  text NOT NULL,
  sid  int  NOT NULL,
  created_at timestamptz DEFAULT now(),
  PRIMARY KEY (date, mid, sid)
);
CREATE INDEX IF NOT EXISTS idx_picks_date_sid ON public.picks (date, sid);
CREATE INDEX IF NOT EXISTS idx_picks_date     ON public.picks (date);

-- ===== 2. 开启 RLS（含 FORCE）=====
ALTER TABLE public.config  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.punches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.claims  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.logs    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.picks   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.config  FORCE ROW LEVEL SECURITY;
ALTER TABLE public.punches FORCE ROW LEVEL SECURITY;
ALTER TABLE public.claims  FORCE ROW LEVEL SECURITY;
ALTER TABLE public.logs    FORCE ROW LEVEL SECURITY;

-- ===== 3. RLS 策略（与旧库一致）=====
DROP POLICY IF EXISTS config_select_all ON public.config;
DROP POLICY IF EXISTS config_insert     ON public.config;
DROP POLICY IF EXISTS config_update     ON public.config;
CREATE POLICY config_select_all ON public.config FOR SELECT USING (true);
CREATE POLICY config_insert ON public.config FOR INSERT
  WITH CHECK (pg_column_size(data::text) < 500000);
CREATE POLICY config_update ON public.config FOR UPDATE
  USING (pg_column_size(data::text) < 500000)
  WITH CHECK (pg_column_size(data::text) < 500000);

DROP POLICY IF EXISTS punches_select_all       ON public.punches;
DROP POLICY IF EXISTS punches_insert_validated ON public.punches;
CREATE POLICY punches_select_all ON public.punches FOR SELECT USING (true);
CREATE POLICY punches_insert_validated ON public.punches FOR INSERT
  WITH CHECK (
    date ~ '^\d{4}-\d{2}-\d{2}$'
    AND time ~ '^\d{2}:\d{2}$'
    AND date::date >= CURRENT_DATE - INTERVAL '7 days'
    AND date::date <= CURRENT_DATE + INTERVAL '1 day'
  );

DROP POLICY IF EXISTS claims_select_all ON public.claims;
DROP POLICY IF EXISTS claims_insert     ON public.claims;
DROP POLICY IF EXISTS claims_update     ON public.claims;
DROP POLICY IF EXISTS claims_delete     ON public.claims;
CREATE POLICY claims_select_all ON public.claims FOR SELECT USING (true);
CREATE POLICY claims_insert ON public.claims FOR INSERT WITH CHECK (true);
CREATE POLICY claims_update ON public.claims FOR UPDATE USING (true) WITH CHECK (true);
CREATE POLICY claims_delete ON public.claims FOR DELETE USING (true);

DROP POLICY IF EXISTS logs_select_all ON public.logs;
DROP POLICY IF EXISTS logs_insert_all ON public.logs;
CREATE POLICY logs_select_all ON public.logs FOR SELECT USING (true);
CREATE POLICY logs_insert_all ON public.logs FOR INSERT WITH CHECK (true);

DROP POLICY IF EXISTS picks_sel ON public.picks;
DROP POLICY IF EXISTS picks_ins ON public.picks;
DROP POLICY IF EXISTS picks_del ON public.picks;
CREATE POLICY picks_sel ON public.picks FOR SELECT USING (true);
CREATE POLICY picks_ins ON public.picks FOR INSERT WITH CHECK (true);
CREATE POLICY picks_del ON public.picks FOR DELETE USING (true);

-- ===== 4. 防篡改触发器（日志/打卡不可改删）=====
CREATE OR REPLACE FUNCTION public.prevent_logs_update() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'Logs are immutable'; END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS no_update_logs ON public.logs;
CREATE TRIGGER no_update_logs BEFORE UPDATE ON public.logs
  FOR EACH ROW EXECUTE FUNCTION public.prevent_logs_update();

CREATE OR REPLACE FUNCTION public.prevent_punches_mutation() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'Data is immutable'; END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS no_update_punches ON public.punches;
CREATE TRIGGER no_update_punches BEFORE UPDATE ON public.punches
  FOR EACH ROW EXECUTE FUNCTION public.prevent_punches_mutation();
DROP TRIGGER IF EXISTS no_delete_punches ON public.punches;
CREATE TRIGGER no_delete_punches BEFORE DELETE ON public.punches
  FOR EACH ROW EXECUTE FUNCTION public.prevent_punches_mutation();

-- ===== 5. 选班函数（表驱动 + 咨询锁满员 + 自动清理）=====
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

CREATE OR REPLACE FUNCTION public.picks_count(p_date text, p_sid int, p_except_mid text DEFAULT NULL)
RETURNS int LANGUAGE sql STABLE AS $$
  SELECT COUNT(*)::int FROM public.picks
   WHERE date = p_date AND sid = p_sid
     AND (p_except_mid IS NULL OR mid <> p_except_mid);
$$;

CREATE OR REPLACE FUNCTION public.pick_add(p_date text, p_mid text, p_sid int)
RETURNS jsonb LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO public.picks(date, mid, sid) VALUES (p_date, p_mid, p_sid)
    ON CONFLICT (date, mid, sid) DO NOTHING;
  DELETE FROM public.picks WHERE date < to_char(CURRENT_DATE - INTERVAL '60 days', 'YYYY-MM-DD');
  RETURN (public.picks_snapshot()) -> 'data';
END; $$;

CREATE OR REPLACE FUNCTION public.pick_remove(p_date text, p_mid text, p_sid int)
RETURNS jsonb LANGUAGE plpgsql AS $$
BEGIN
  DELETE FROM public.picks WHERE date = p_date AND mid = p_mid AND sid = p_sid;
  RETURN (public.picks_snapshot()) -> 'data';
END; $$;

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

-- ===== 6. 授权（容错）=====
DO $$
BEGIN
  BEGIN EXECUTE 'GRANT SELECT, INSERT, UPDATE ON public.config TO anon, authenticated';  EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT SELECT, INSERT ON public.punches TO anon, authenticated';          EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.claims TO anon, authenticated'; EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT SELECT, INSERT ON public.logs TO anon, authenticated';             EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT SELECT, INSERT, DELETE ON public.picks TO anon, authenticated';    EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated'; EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.picks_snapshot() TO anon, authenticated';        EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.picks_count(text,int,text) TO anon, authenticated'; EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_add(text,text,int) TO anon, authenticated';    EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_remove(text,text,int) TO anon, authenticated'; EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_set(text,text,jsonb) TO anon, authenticated';  EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_add_cap(text,text,int,boolean) TO anon, authenticated'; EXCEPTION WHEN OTHERS THEN NULL; END;
END $$;

-- ===== 7. 自检 =====
DO $$
DECLARE n_tbl int; n_fn int;
BEGIN
  SELECT count(*) INTO n_tbl FROM information_schema.tables
    WHERE table_schema='public' AND table_name IN ('config','punches','claims','logs','picks');
  SELECT count(*) INTO n_fn FROM pg_proc p JOIN pg_namespace ns ON ns.oid=p.pronamespace
    WHERE ns.nspname='public' AND p.proname IN ('picks_snapshot','picks_count','pick_add','pick_remove','pick_set','pick_add_cap');
  IF n_tbl < 5 THEN RAISE EXCEPTION '自检失败：表不全（%/5）', n_tbl; END IF;
  IF n_fn < 6 THEN RAISE EXCEPTION '自检失败：函数不全（%/6）', n_fn; END IF;
END $$;

SELECT '新项目建表完成：5 张表 + RLS + 6 个选班函数 + 防篡改触发器' AS 结果;
