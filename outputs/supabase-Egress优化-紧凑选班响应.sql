-- ============================================================
-- Supabase Egress 优化：选班写入 RPC 改为紧凑响应
--
-- 部署顺序：先发布已兼容紧凑响应的前端，再执行本脚本。
-- 作用：pick_set / pick_add / pick_remove / pick_add_cap 成功后不再
--       返回完整 picks 快照；同时确保过渡期 config.picks 镜像触发器已拆除。
--
-- 不改变：picks 行表权威来源、时段容量、咨询锁、失败原因。
-- 选班上限规则（本版同步）：取消每日上限（单日数量不限），改为每人每周合计不超过 56；
--                          管理员超额分配不受此限。
-- 可重复执行。
-- ============================================================

DO $$
BEGIN
  IF to_regclass('public.picks') IS NULL THEN
    RAISE EXCEPTION '缺少 public.picks 表，请先完成 picks 行表服务端化';
  END IF;
END $$;

-- 旧客户端兼容镜像会在每次 picks 变化时聚合并广播整块 JSON；新版已不读取它。
DROP TRIGGER IF EXISTS picks_sync_config ON public.picks;
DROP FUNCTION IF EXISTS public.sync_picks_to_config();

CREATE OR REPLACE FUNCTION public.pick_set(p_date text, p_mid text, p_sids jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE v_count int;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('pickday:' || p_date || ':' || p_mid));

  DELETE FROM public.picks WHERE date = p_date AND mid = p_mid;
  INSERT INTO public.picks(date, mid, sid)
    SELECT p_date, p_mid, (x.val)::text::int
      FROM jsonb_array_elements(p_sids) AS x(val)
    ON CONFLICT (date, mid, sid) DO NOTHING;

  DELETE FROM public.picks
   WHERE date < to_char(CURRENT_DATE - INTERVAL '60 days', 'YYYY-MM-DD');
  SELECT COUNT(*)::int INTO v_count FROM public.picks WHERE date = p_date AND mid = p_mid;

  RETURN jsonb_build_object('ok', true, 'count', v_count);
END; $$;

CREATE OR REPLACE FUNCTION public.pick_add(p_date text, p_mid text, p_sid int)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE v_inserted int := 0;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('pickday:' || p_date || ':' || p_mid));

  INSERT INTO public.picks(date, mid, sid) VALUES (p_date, p_mid, p_sid)
    ON CONFLICT (date, mid, sid) DO NOTHING;
  GET DIAGNOSTICS v_inserted = ROW_COUNT;

  DELETE FROM public.picks
   WHERE date < to_char(CURRENT_DATE - INTERVAL '60 days', 'YYYY-MM-DD');

  RETURN jsonb_build_object('ok', true, 'alreadyApplied', v_inserted = 0);
END; $$;

CREATE OR REPLACE FUNCTION public.pick_remove(p_date text, p_mid text, p_sid int)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE v_removed int := 0;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('pickday:' || p_date || ':' || p_mid));

  DELETE FROM public.picks WHERE date = p_date AND mid = p_mid AND sid = p_sid;
  GET DIAGNOSTICS v_removed = ROW_COUNT;

  RETURN jsonb_build_object('ok', true, 'alreadyApplied', v_removed = 0);
END; $$;

CREATE OR REPLACE FUNCTION public.pick_add_cap(p_date text, p_mid text, p_sid int, p_admin boolean)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  v_cap int := 0;
  v_count int := 0;
  v_w int := 6;
  v_dow int := 0;
  v_ws date;
  v_week int := 0;
  v_inserted int := 0;
BEGIN
  BEGIN
    SELECT COALESCE((data #>> ARRAY[p_date, p_sid::text])::int, 0)
      INTO v_cap FROM config WHERE id = 'slotcap';
  EXCEPTION WHEN OTHERS THEN
    v_cap := 0;
  END;
  IF v_cap IS NULL THEN v_cap := 0; END IF;

  -- 与转班/换班保持同一锁顺序：成员日锁 → 时段锁。
  PERFORM pg_advisory_xact_lock(hashtext('pickday:' || p_date || ':' || p_mid));
  PERFORM pg_advisory_xact_lock(hashtext('pickcap:' || p_date || ':' || p_sid::text));

  -- 重试幂等：班次已经存在时直接成功，不能误报 full/weekfull。
  IF EXISTS(SELECT 1 FROM public.picks WHERE date = p_date AND mid = p_mid AND sid = p_sid) THEN
    RETURN jsonb_build_object('ok', true, 'alreadyApplied', true);
  END IF;

  -- 每周上限（单日数量不限）：非管理员本周已选 + 本次 > 56 则拒绝；管理员超额分配不受限。
  IF NOT COALESCE(p_admin, false) THEN
    BEGIN
      SELECT COALESCE((data ->> 'weekStartDay')::int, 6) INTO v_w FROM config WHERE id = 'selcfg';
    EXCEPTION WHEN OTHERS THEN v_w := 6;
    END;
    IF v_w IS NULL THEN v_w := 6; END IF;
    v_dow := EXTRACT(DOW FROM p_date::date)::int;                 -- 0=周日..6=周六，与 JS getDay() 一致
    v_ws  := p_date::date - (((v_dow - v_w) % 7 + 7) % 7);
    SELECT COUNT(*)::int INTO v_week FROM public.picks
      WHERE mid = p_mid
        AND date >= to_char(v_ws, 'YYYY-MM-DD')
        AND date <= to_char(v_ws + 6, 'YYYY-MM-DD');
    IF v_week + 1 > 56 THEN
      RETURN jsonb_build_object('ok', false, 'reason', 'weekfull', 'count', v_week, 'max', 56);
    END IF;
  END IF;

  SELECT COUNT(*)::int INTO v_count FROM public.picks WHERE date = p_date AND sid = p_sid;
  IF v_cap > 0 AND v_count >= v_cap AND NOT COALESCE(p_admin, false) THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'full', 'count', v_count, 'cap', v_cap);
  END IF;

  INSERT INTO public.picks(date, mid, sid) VALUES (p_date, p_mid, p_sid)
    ON CONFLICT (date, mid, sid) DO NOTHING;
  GET DIAGNOSTICS v_inserted = ROW_COUNT;

  DELETE FROM public.picks
   WHERE date < to_char(CURRENT_DATE - INTERVAL '60 days', 'YYYY-MM-DD');

  RETURN jsonb_build_object(
    'ok', true,
    'alreadyApplied', v_inserted = 0,
    'count', v_count + v_inserted,
    'cap', v_cap
  );
END; $$;

DO $$
BEGIN
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_set(text,text,jsonb) TO anon, authenticated'; EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_add(text,text,int) TO anon, authenticated'; EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_remove(text,text,int) TO anon, authenticated'; EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_add_cap(text,text,int,boolean) TO anon, authenticated'; EXCEPTION WHEN OTHERS THEN NULL; END;
END $$;

SELECT
  'Egress 优化函数已创建' AS 结果,
  (SELECT count(*) FROM public.picks) AS 当前选班行数,
  (SELECT count(*) FROM pg_trigger WHERE tgname = 'picks_sync_config') AS 兼容镜像触发器数量;
