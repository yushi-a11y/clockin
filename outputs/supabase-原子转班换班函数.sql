-- ============================================================
--  原子转班 / 换班服务端函数：pick_transfer / pick_exchange
--  作用：把"转出方删 + 接收方加"合并进【同一个加锁事务】，
--       从结构上根治转班/换班的并发与"满员误判"问题。
--
--  ⚠️ 重要：请用 Cmd+A（全选）后再点 Run / 运行！
--  执行位置：Supabase Dashboard（御史项目）→ SQL Editor → Run
--  幂等：CREATE OR REPLACE，可安全重复执行。
--
--  背景（线上 2026-09-09 复现）：
--    前端在 Supabase 后端下没有 pick_transfer/pick_exchange，
--    只能"组合降级"（先删/先加两步）。当某时段【含转出方正好满员】
--    （如 sid22 上限 5、当前 5 人里包含转出方）时，两步组合会被
--    pick_add_cap 把尚未离场的转出方计入人数而误判"满员"，导致接收失败。
--    转班对一个时段的名额其实是【净零变化】（走一个、来一个），本不该被满员卡住。
--
--  本函数的净零名额语义：
--    统计时段人数时【排除转出方】（他正要离场）。只有"排除转出方后仍 ≥ 上限"
--    才是真超员，才拒绝。这样"含转出方正好满员"的合法转班可以正常通过。
--    —— 与前端 Firestore 适配器 pick_transfer/pick_exchange 的判定完全一致。
--
--  返回（与前端契约一致）：
--    成功     → {"ok":true, "alreadyApplied":<bool>}（不再回传完整 picks，降低 Egress）
--    失败     → {"ok":false, "reason":"invalid|not_owner|duplicate|full|weekfull", ...}（已取消每日上限，不再返回 dayfull）
--    写入结果由当前客户端本地幂等应用，并由 picks Realtime 差量及周期性权威快照自愈。
--    前端 atomicTransferPick/atomicExchangePicks 会优先调用本函数；
--    只有函数不存在时才回退到组合降级。部署本函数后【无需改前端】。
--
--  锁顺序：与既有 pick_add_cap 全局一致 —— 先取"成员-日"锁（按 key 排序），
--         再取"时段"锁（按 key 排序），杜绝交叉死锁。
-- ============================================================

-- ---------- 1) 转班：from_mid 把 p_date 的 p_sid 转给 to_mid ----------
CREATE OR REPLACE FUNCTION public.pick_transfer(
  p_date text, p_from_mid text, p_to_mid text, p_sid int
)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  v_cap        int := 0;
  v_w          int := 6;   -- weekStartDay，默认 6（周六），与前端 DEF_SELCFG 一致
  v_from_holds boolean;
  v_to_holds   boolean;
  v_cnt        int;
  v_dow        int;
  v_diff       int;
  v_ws         date;
  v_day_keys   text[];
  v_k          text;
BEGIN
  IF p_date IS NULL OR p_sid IS NULL OR p_from_mid IS NULL OR p_to_mid IS NULL OR p_from_mid = p_to_mid THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'invalid');
  END IF;

  -- 锁：先"成员-日"（转出方/接收方，按 key 排序去重），再"时段"
  SELECT array_agg(DISTINCT x ORDER BY x) INTO v_day_keys
    FROM unnest(ARRAY[
      'pickday:' || p_date || ':' || p_from_mid,
      'pickday:' || p_date || ':' || p_to_mid
    ]) AS x;
  FOREACH v_k IN ARRAY v_day_keys LOOP
    PERFORM pg_advisory_xact_lock(hashtext(v_k));
  END LOOP;
  PERFORM pg_advisory_xact_lock(hashtext('pickcap:' || p_date || ':' || p_sid::text));

  SELECT EXISTS(SELECT 1 FROM public.picks WHERE date = p_date AND mid = p_from_mid AND sid = p_sid) INTO v_from_holds;
  SELECT EXISTS(SELECT 1 FROM public.picks WHERE date = p_date AND mid = p_to_mid   AND sid = p_sid) INTO v_to_holds;

  -- 幂等：转出方已无、接收方已有 → 视为此前已应用（重复点击/回执丢失安全）
  IF (NOT v_from_holds) AND v_to_holds THEN
    RETURN jsonb_build_object('ok', true, 'alreadyApplied', true);
  END IF;
  IF NOT v_from_holds THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'not_owner');
  END IF;
  IF v_to_holds THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'duplicate');
  END IF;

  -- 选班已取消每日上限（单日数量不限），此处不再做接收方 dayfull 校验。

  -- 时段名额：净零 —— 排除转出方后计数，仍 ≥ 上限才是真超员
  BEGIN
    SELECT COALESCE((data #>> ARRAY[p_date, p_sid::text])::int, 0) INTO v_cap FROM config WHERE id = 'slotcap';
  EXCEPTION WHEN OTHERS THEN v_cap := 0;
  END;
  IF v_cap IS NULL THEN v_cap := 0; END IF;
  IF v_cap > 0 THEN
    SELECT COUNT(*)::int INTO v_cnt FROM public.picks
      WHERE date = p_date AND sid = p_sid AND mid <> p_from_mid;
    IF v_cnt >= v_cap THEN
      RETURN jsonb_build_object('ok', false, 'reason', 'full', 'count', v_cnt, 'cap', v_cap);
    END IF;
  END IF;

  -- 每周上限：接收方本周（含新转入的 1 个）> 56 则拒绝；weekStartDay 读 config.selcfg
  BEGIN
    SELECT COALESCE((data ->> 'weekStartDay')::int, 6) INTO v_w FROM config WHERE id = 'selcfg';
  EXCEPTION WHEN OTHERS THEN v_w := 6;
  END;
  IF v_w IS NULL THEN v_w := 6; END IF;
  v_dow  := EXTRACT(DOW FROM p_date::date)::int;      -- 0=周日..6=周六，与 JS getDay() 一致
  v_diff := ((v_dow - v_w) % 7 + 7) % 7;
  v_ws   := p_date::date - v_diff;
  SELECT COUNT(*)::int INTO v_cnt FROM public.picks
    WHERE mid = p_to_mid
      AND date >= to_char(v_ws, 'YYYY-MM-DD')
      AND date <= to_char(v_ws + 6, 'YYYY-MM-DD');
  IF v_cnt + 1 > 56 THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'weekfull', 'count', v_cnt, 'max', 56);
  END IF;

  -- 应用（同一事务，原子）：转出方删、接收方加
  DELETE FROM public.picks WHERE date = p_date AND mid = p_from_mid AND sid = p_sid;
  INSERT INTO public.picks(date, mid, sid) VALUES (p_date, p_to_mid, p_sid)
    ON CONFLICT (date, mid, sid) DO NOTHING;
  DELETE FROM public.picks WHERE date < to_char(CURRENT_DATE - INTERVAL '60 days', 'YYYY-MM-DD');

  -- 不再刷新 config.picks 兼容大对象；picks 行表是唯一权威源，Realtime 会广播本次两行差量。
  RETURN jsonb_build_object('ok', true, 'alreadyApplied', false);
END; $$;


-- ---------- 2) 双向换班：giver 把 give_sid@give_date 给 receiver；receiver 把 take_sid@take_date 给 giver ----------
CREATE OR REPLACE FUNCTION public.pick_exchange(
  p_give_date text, p_giver_mid text, p_give_sid int,
  p_take_date text, p_receiver_mid text, p_take_sid int
)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  v_give_cap      int := 0;
  v_take_cap      int := 0;
  v_w             int := 6;
  v_giver_gives   boolean;   -- giver 持有 give_sid@give_date
  v_receiver_takes boolean;  -- receiver 持有 take_sid@take_date
  v_receiver_give boolean;   -- receiver 已持有 give_sid@give_date（重复）
  v_giver_take    boolean;   -- giver 已持有 take_sid@take_date（重复）
  v_cnt           int;
  v_proj          int;
  v_ws1           date; v_ws2 date;
  v_day_keys      text[]; v_cap_keys text[]; v_k text;
BEGIN
  IF p_give_date IS NULL OR p_take_date IS NULL OR p_give_sid IS NULL OR p_take_sid IS NULL
     OR p_giver_mid IS NULL OR p_receiver_mid IS NULL OR p_giver_mid = p_receiver_mid THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'invalid');
  END IF;

  -- 锁：全部"成员-日"锁（排序去重）→ 全部"时段"锁（排序去重）
  SELECT array_agg(DISTINCT x ORDER BY x) INTO v_day_keys
    FROM unnest(ARRAY[
      'pickday:' || p_give_date || ':' || p_giver_mid,
      'pickday:' || p_give_date || ':' || p_receiver_mid,
      'pickday:' || p_take_date || ':' || p_giver_mid,
      'pickday:' || p_take_date || ':' || p_receiver_mid
    ]) AS x;
  FOREACH v_k IN ARRAY v_day_keys LOOP
    PERFORM pg_advisory_xact_lock(hashtext(v_k));
  END LOOP;
  SELECT array_agg(DISTINCT x ORDER BY x) INTO v_cap_keys
    FROM unnest(ARRAY[
      'pickcap:' || p_give_date || ':' || p_give_sid::text,
      'pickcap:' || p_take_date || ':' || p_take_sid::text
    ]) AS x;
  FOREACH v_k IN ARRAY v_cap_keys LOOP
    PERFORM pg_advisory_xact_lock(hashtext(v_k));
  END LOOP;

  SELECT EXISTS(SELECT 1 FROM public.picks WHERE date = p_give_date AND mid = p_giver_mid    AND sid = p_give_sid) INTO v_giver_gives;
  SELECT EXISTS(SELECT 1 FROM public.picks WHERE date = p_take_date AND mid = p_receiver_mid AND sid = p_take_sid) INTO v_receiver_takes;
  SELECT EXISTS(SELECT 1 FROM public.picks WHERE date = p_give_date AND mid = p_receiver_mid AND sid = p_give_sid) INTO v_receiver_give;
  SELECT EXISTS(SELECT 1 FROM public.picks WHERE date = p_take_date AND mid = p_giver_mid    AND sid = p_take_sid) INTO v_giver_take;

  -- 幂等：已完成互换
  IF (NOT v_giver_gives) AND v_giver_take AND v_receiver_give AND (NOT v_receiver_takes) THEN
    RETURN jsonb_build_object('ok', true, 'alreadyApplied', true);
  END IF;
  IF (NOT v_giver_gives) OR (NOT v_receiver_takes) THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'not_owner');
  END IF;
  IF v_receiver_give OR v_giver_take THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'duplicate');
  END IF;

  -- 时段名额（各自净零：排除该时段的转出方）
  BEGIN SELECT COALESCE((data #>> ARRAY[p_give_date, p_give_sid::text])::int, 0) INTO v_give_cap FROM config WHERE id = 'slotcap'; EXCEPTION WHEN OTHERS THEN v_give_cap := 0; END;
  BEGIN SELECT COALESCE((data #>> ARRAY[p_take_date, p_take_sid::text])::int, 0) INTO v_take_cap FROM config WHERE id = 'slotcap'; EXCEPTION WHEN OTHERS THEN v_take_cap := 0; END;
  IF v_give_cap IS NULL THEN v_give_cap := 0; END IF;
  IF v_take_cap IS NULL THEN v_take_cap := 0; END IF;
  IF v_give_cap > 0 THEN
    SELECT COUNT(*)::int INTO v_cnt FROM public.picks WHERE date = p_give_date AND sid = p_give_sid AND mid <> p_giver_mid;
    IF v_cnt >= v_give_cap THEN RETURN jsonb_build_object('ok', false, 'reason', 'full', 'count', v_cnt, 'cap', v_give_cap); END IF;
  END IF;
  IF v_take_cap > 0 THEN
    SELECT COUNT(*)::int INTO v_cnt FROM public.picks WHERE date = p_take_date AND sid = p_take_sid AND mid <> p_receiver_mid;
    IF v_cnt >= v_take_cap THEN RETURN jsonb_build_object('ok', false, 'reason', 'full', 'count', v_cnt, 'cap', v_take_cap); END IF;
  END IF;

  -- 选班已取消每日上限（单日数量不限），不再做 dayfull 校验。

  -- 每周上限：对 giver/receiver × week(give_date)/week(take_date) 计算投影（含本次增减）
  BEGIN SELECT COALESCE((data ->> 'weekStartDay')::int, 6) INTO v_w FROM config WHERE id = 'selcfg'; EXCEPTION WHEN OTHERS THEN v_w := 6; END;
  IF v_w IS NULL THEN v_w := 6; END IF;
  v_ws1 := p_give_date::date - (((EXTRACT(DOW FROM p_give_date::date)::int - v_w) % 7 + 7) % 7);
  v_ws2 := p_take_date::date - (((EXTRACT(DOW FROM p_take_date::date)::int - v_w) % 7 + 7) % 7);

  -- giver @ week(give_date)：失去 give_sid(give_date 必在此窗) / 若 take_date 同窗则获得 take_sid
  SELECT COUNT(*)::int INTO v_proj FROM public.picks WHERE mid = p_giver_mid AND date >= to_char(v_ws1,'YYYY-MM-DD') AND date <= to_char(v_ws1+6,'YYYY-MM-DD');
  v_proj := v_proj - (CASE WHEN p_give_date::date BETWEEN v_ws1 AND v_ws1+6 THEN 1 ELSE 0 END)
                   + (CASE WHEN p_take_date::date BETWEEN v_ws1 AND v_ws1+6 THEN 1 ELSE 0 END);
  IF v_proj > 56 THEN RETURN jsonb_build_object('ok', false, 'reason', 'weekfull', 'count', v_proj, 'max', 56); END IF;

  -- giver @ week(take_date)
  SELECT COUNT(*)::int INTO v_proj FROM public.picks WHERE mid = p_giver_mid AND date >= to_char(v_ws2,'YYYY-MM-DD') AND date <= to_char(v_ws2+6,'YYYY-MM-DD');
  v_proj := v_proj - (CASE WHEN p_give_date::date BETWEEN v_ws2 AND v_ws2+6 THEN 1 ELSE 0 END)
                   + (CASE WHEN p_take_date::date BETWEEN v_ws2 AND v_ws2+6 THEN 1 ELSE 0 END);
  IF v_proj > 56 THEN RETURN jsonb_build_object('ok', false, 'reason', 'weekfull', 'count', v_proj, 'max', 56); END IF;

  -- receiver @ week(give_date)
  SELECT COUNT(*)::int INTO v_proj FROM public.picks WHERE mid = p_receiver_mid AND date >= to_char(v_ws1,'YYYY-MM-DD') AND date <= to_char(v_ws1+6,'YYYY-MM-DD');
  v_proj := v_proj + (CASE WHEN p_give_date::date BETWEEN v_ws1 AND v_ws1+6 THEN 1 ELSE 0 END)
                   - (CASE WHEN p_take_date::date BETWEEN v_ws1 AND v_ws1+6 THEN 1 ELSE 0 END);
  IF v_proj > 56 THEN RETURN jsonb_build_object('ok', false, 'reason', 'weekfull', 'count', v_proj, 'max', 56); END IF;

  -- receiver @ week(take_date)
  SELECT COUNT(*)::int INTO v_proj FROM public.picks WHERE mid = p_receiver_mid AND date >= to_char(v_ws2,'YYYY-MM-DD') AND date <= to_char(v_ws2+6,'YYYY-MM-DD');
  v_proj := v_proj + (CASE WHEN p_give_date::date BETWEEN v_ws2 AND v_ws2+6 THEN 1 ELSE 0 END)
                   - (CASE WHEN p_take_date::date BETWEEN v_ws2 AND v_ws2+6 THEN 1 ELSE 0 END);
  IF v_proj > 56 THEN RETURN jsonb_build_object('ok', false, 'reason', 'weekfull', 'count', v_proj, 'max', 56); END IF;

  -- 应用（同一事务，原子）
  DELETE FROM public.picks WHERE date = p_give_date AND mid = p_giver_mid    AND sid = p_give_sid;
  DELETE FROM public.picks WHERE date = p_take_date AND mid = p_receiver_mid AND sid = p_take_sid;
  INSERT INTO public.picks(date, mid, sid) VALUES
    (p_give_date, p_receiver_mid, p_give_sid),
    (p_take_date, p_giver_mid,    p_take_sid)
    ON CONFLICT (date, mid, sid) DO NOTHING;
  DELETE FROM public.picks WHERE date < to_char(CURRENT_DATE - INTERVAL '60 days', 'YYYY-MM-DD');

  -- 不再刷新 config.picks 兼容大对象；picks 行表是唯一权威源，Realtime 会广播本次四行差量。
  RETURN jsonb_build_object('ok', true, 'alreadyApplied', false);
END; $$;


-- ---------- 3) 授权（容错：角色不存在也不报错） ----------
DO $$
BEGIN
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_transfer(text,text,text,int) TO anon';            EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_transfer(text,text,text,int) TO authenticated';    EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_exchange(text,text,int,text,text,int) TO anon';         EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_exchange(text,text,int,text,text,int) TO authenticated'; EXCEPTION WHEN OTHERS THEN NULL; END;
END $$;


-- ---------- 4) 自检 ----------
DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n
    FROM pg_proc p JOIN pg_namespace ns ON ns.oid = p.pronamespace
   WHERE ns.nspname = 'public' AND p.proname IN ('pick_transfer','pick_exchange');
  IF n < 2 THEN
    RAISE EXCEPTION '自检失败：pick_transfer / pick_exchange 未全部创建成功（当前 %/2），请确认已全选脚本运行', n;
  END IF;
END $$;

SELECT 'pick_transfer / pick_exchange 创建成功，前端会自动优先使用（无需改前端）' AS 结果;
