-- ============================================================
-- 新加坡项目（御史）· 每日选班上限修复
-- 问题：pick_add_cap 只校验"时段满员"，不校验"该成员当天已选几个"，
--       快速连点时浏览器端 7 个上限被绕过，出现一天选 8 个的情况。
-- 修复：在服务器端同一事务内加"每日上限"硬校验（与前端 MAX_PER_DAY=7 一致），
--       并加"成员-日"级咨询锁，杜绝并发连点绕过计数。
-- 执行位置：Supabase Dashboard（御史项目）→ SQL Editor → Run
-- 幂等：可重复执行。
-- ============================================================

CREATE OR REPLACE FUNCTION public.pick_add_cap(p_date text, p_mid text, p_sid int, p_admin boolean)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE v_cap int := 0; v_count int; v_day int;
BEGIN
  -- 读取该日期该时段的容量配置
  BEGIN
    SELECT COALESCE((data #>> ARRAY[p_date, p_sid::text])::int, 0) INTO v_cap
      FROM config WHERE id = 'slotcap';
  EXCEPTION WHEN OTHERS THEN v_cap := 0;
  END;
  IF v_cap IS NULL THEN v_cap := 0; END IF;

  -- 锁顺序固定：先"成员-日"锁，再"时段"锁（全局一致顺序，避免死锁）
  -- 成员-日锁：把同一人同一天的所有选班串行化，保证下面每日计数不被并发绕过
  PERFORM pg_advisory_xact_lock(hashtext('pickday:' || p_date || ':' || p_mid));
  -- 时段锁：把同一时段（跨成员）的容量校验串行化
  PERFORM pg_advisory_xact_lock(hashtext('pickcap:' || p_date || ':' || p_sid::text));

  -- [新增] 每日上限：该成员当天已有 ≥7 个时段 → 拒绝第 8 个
  -- 注意：7 需与前端 MAX_PER_DAY 保持一致；管理员同样受限（超额分配请走单元格编辑器）
  SELECT COUNT(*)::int INTO v_day FROM public.picks WHERE date = p_date AND mid = p_mid;
  IF v_day >= 7 THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'dayfull', 'count', v_day, 'max', 7);
  END IF;

  -- 时段容量校验（管理员可超额）
  SELECT COUNT(*)::int INTO v_count FROM public.picks WHERE date = p_date AND sid = p_sid;
  IF v_cap > 0 AND v_count >= v_cap AND NOT p_admin THEN
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

SELECT 'pick_add_cap 已升级：新增每日 7 个上限硬校验 + 成员-日锁' AS 结果;
