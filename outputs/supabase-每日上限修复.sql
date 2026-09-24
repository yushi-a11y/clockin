-- ============================================================
-- 新加坡项目（御史）· 选班上限规则调整：取消每日上限，改每周 56
-- 背景：业务规则调整——不再限制每人每天最多 7 个时段，改为
--       "每人整周合计不超过 56 个"（与前端 MAX_PER_WEEK=56 一致）。
-- 修复：在服务器端同一事务内加"每周上限"硬校验，并对管理员放行
--       （管理员可超额分配，不受每周限制）；同时加"成员-日"级咨询锁。
-- 执行位置：Supabase Dashboard（御史项目）→ SQL Editor → Run
-- 注意：若已部署「supabase-Egress优化-紧凑选班响应.sql」，那份也会
--       CREATE OR REPLACE pick_add_cap；两者以最后执行者为准，规则一致
--       （无每日上限 / 每周 56 / 管理员豁免），仅响应体是否回传完整快照不同。
-- 幂等：可重复执行。
-- ============================================================

CREATE OR REPLACE FUNCTION public.pick_add_cap(p_date text, p_mid text, p_sid int, p_admin boolean)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE v_cap int := 0; v_count int; v_w int := 6; v_dow int := 0; v_ws date; v_week int := 0;
BEGIN
  -- 读取该日期该时段的容量配置
  BEGIN
    SELECT COALESCE((data #>> ARRAY[p_date, p_sid::text])::int, 0) INTO v_cap
      FROM config WHERE id = 'slotcap';
  EXCEPTION WHEN OTHERS THEN v_cap := 0;
  END;
  IF v_cap IS NULL THEN v_cap := 0; END IF;

  -- 锁顺序固定：先"成员-日"锁，再"时段"锁（全局一致顺序，避免死锁）
  -- 成员-日锁：把同一人同一天的所有选班串行化
  PERFORM pg_advisory_xact_lock(hashtext('pickday:' || p_date || ':' || p_mid));
  -- 时段锁：把同一时段（跨成员）的容量校验串行化
  PERFORM pg_advisory_xact_lock(hashtext('pickcap:' || p_date || ':' || p_sid::text));

  -- 幂等：班次已存在直接成功，避免重试误报
  IF EXISTS(SELECT 1 FROM public.picks WHERE date = p_date AND mid = p_mid AND sid = p_sid) THEN
    RETURN jsonb_build_object('ok', true, 'picks', (public.picks_snapshot()) -> 'data', 'count', 0);
  END IF;

  -- [规则调整] 每周上限：单日数量不限，整周合计（含本次）> 56 → 拒绝。
  -- 注意：56 需与前端 MAX_PER_WEEK 一致；管理员可超额分配，跳过每周与时段容量限制。
  IF NOT COALESCE(p_admin, false) THEN
    BEGIN
      SELECT COALESCE((data ->> 'weekStartDay')::int, 6) INTO v_w FROM config WHERE id = 'selcfg';
    EXCEPTION WHEN OTHERS THEN v_w := 6;
    END;
    IF v_w IS NULL THEN v_w := 6; END IF;
    v_dow := EXTRACT(DOW FROM p_date::date)::int;
    v_ws  := p_date::date - (((v_dow - v_w) % 7 + 7) % 7);
    SELECT COUNT(*)::int INTO v_week FROM public.picks
      WHERE mid = p_mid
        AND date >= to_char(v_ws, 'YYYY-MM-DD')
        AND date <= to_char(v_ws + 6, 'YYYY-MM-DD');
    IF v_week + 1 > 56 THEN
      RETURN jsonb_build_object('ok', false, 'reason', 'weekfull', 'count', v_week, 'max', 56);
    END IF;
  END IF;

  -- 时段容量校验（管理员可超额）
  SELECT COUNT(*)::int INTO v_count FROM public.picks WHERE date = p_date AND sid = p_sid;
  IF v_cap > 0 AND v_count >= v_cap AND NOT COALESCE(p_admin, false) THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'full', 'count', v_count, 'cap', v_cap);
  END IF;

  INSERT INTO public.picks(date, mid, sid) VALUES (p_date, p_mid, p_sid)
    ON CONFLICT (date, mid, sid) DO NOTHING;

  DELETE FROM public.picks WHERE date < to_char(CURRENT_DATE - INTERVAL '60 days', 'YYYY-MM-DD');

  RETURN jsonb_build_object('ok', true, 'picks', (public.picks_snapshot()) -> 'data', 'count', v_count + 1, 'cap', v_cap);
END; $$;

-- 授权（容错）
DO $$
BEGIN
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_add_cap(text,text,int,boolean) TO anon, authenticated'; EXCEPTION WHEN OTHERS THEN NULL; END;
END $$;

SELECT 'pick_add_cap 已升级：取消每日上限，新增每周 56 上限硬校验（管理员豁免）+ 成员-日锁' AS 结果;
