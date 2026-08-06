-- ============================================================
--  选班数据瘦身 + RLS 限制放宽 + 函数自动清理
--  解决问题：picks 数据无限增长 → 撞上 config 表 500KB RLS 限制
--           → UPDATE 静默失败（选了自动消失）/ 报错（选不上）/ 传输慢（延迟高）
--
--  ⚠️ 重要：请用 Cmd+A（全选）后再点 Run / 运行！
--  本脚本在 Supabase SQL 编辑器以 postgres 身份运行，可绕过 RLS 做清理。
--  可安全重复执行（幂等）。
-- ============================================================

-- ===== 第0步：记录瘦身前大小（运行后看 Results 里的数字）=====
SELECT '瘦身前' AS 阶段, pg_column_size(data::text) AS picks_字节数
  FROM config WHERE id = 'picks';

-- ===== 第1步：一次性清理 60 天前的历史选班（postgres 绕过 RLS）=====
UPDATE config
   SET data = (SELECT COALESCE(jsonb_object_agg(k, v), '{}'::jsonb)
                 FROM jsonb_each(data) AS t(k, v)
                WHERE k >= to_char(CURRENT_DATE - INTERVAL '60 days', 'YYYY-MM-DD')),
       updated_at = (EXTRACT(epoch FROM now()) * 1000)::bigint
 WHERE id = 'picks';

-- ===== 第2步：放宽 config 表 RLS 大小限制 500KB → 5MB（留出充足余量）=====
DROP POLICY IF EXISTS "config_insert" ON config;
DROP POLICY IF EXISTS "config_update" ON config;
CREATE POLICY "config_insert" ON config FOR INSERT
  WITH CHECK (pg_column_size(data::text) < 5000000);
CREATE POLICY "config_update" ON config FOR UPDATE
  USING (pg_column_size(data::text) < 5000000)
  WITH CHECK (pg_column_size(data::text) < 5000000);

-- ===== 第3步：重建三个选班函数，写入时自动清理 60 天前数据（blob 永远保持小巧）=====

-- pick_set：整体设置（管理员整格编辑/一键清空用）
CREATE OR REPLACE FUNCTION public.pick_set(p_date text, p_mid text, p_sids jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE cur jsonb;
BEGIN
  PERFORM 1 FROM config WHERE id = 'picks' FOR UPDATE;
  SELECT data INTO cur FROM config WHERE id = 'picks';
  IF cur IS NULL THEN cur := '{}'::jsonb; END IF;
  IF cur -> p_date IS NULL THEN cur := jsonb_set(cur, ARRAY[p_date], '{}'::jsonb, true); END IF;
  cur := jsonb_set(cur, ARRAY[p_date, p_mid], p_sids, true);
  -- 自动清理 60 天前数据，防止 blob 增长撞 RLS 限制
  cur := (SELECT COALESCE(jsonb_object_agg(k, v), '{}'::jsonb)
            FROM jsonb_each(cur) AS t(k, v)
           WHERE k >= to_char(CURRENT_DATE - INTERVAL '60 days', 'YYYY-MM-DD'));
  UPDATE config SET data = cur, updated_at = (EXTRACT(epoch FROM now()) * 1000)::bigint WHERE id = 'picks';
  RETURN cur;
END; $$;

-- pick_add：增量加一个班次
CREATE OR REPLACE FUNCTION public.pick_add(p_date text, p_mid text, p_sid int)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE cur jsonb; arr jsonb;
BEGIN
  PERFORM 1 FROM config WHERE id = 'picks' FOR UPDATE;
  SELECT data INTO cur FROM config WHERE id = 'picks';
  IF cur IS NULL THEN cur := '{}'::jsonb; END IF;
  IF cur -> p_date IS NULL THEN cur := jsonb_set(cur, ARRAY[p_date], '{}'::jsonb, true); END IF;
  arr := COALESCE(cur -> p_date -> p_mid, '[]'::jsonb);
  IF NOT (arr @> to_jsonb(p_sid)) THEN arr := arr || to_jsonb(p_sid); END IF;
  cur := jsonb_set(cur, ARRAY[p_date, p_mid], arr, true);
  cur := (SELECT COALESCE(jsonb_object_agg(k, v), '{}'::jsonb)
            FROM jsonb_each(cur) AS t(k, v)
           WHERE k >= to_char(CURRENT_DATE - INTERVAL '60 days', 'YYYY-MM-DD'));
  UPDATE config SET data = cur, updated_at = (EXTRACT(epoch FROM now()) * 1000)::bigint WHERE id = 'picks';
  RETURN cur;
END; $$;

-- pick_add_cap：满员原子校验 + 加班次
CREATE OR REPLACE FUNCTION public.pick_add_cap(p_date text, p_mid text, p_sid int, p_admin boolean)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE cur jsonb; arr jsonb; caprow jsonb; v_cap int; v_count int;
BEGIN
  PERFORM 1 FROM config WHERE id = 'picks' FOR UPDATE;
  SELECT data INTO cur FROM config WHERE id = 'picks';
  IF cur IS NULL THEN cur := '{}'::jsonb; END IF;
  SELECT data INTO caprow FROM config WHERE id = 'slotcap';
  v_cap := 0;
  IF caprow IS NOT NULL THEN
    v_cap := COALESCE((caprow #>> ARRAY[p_date, p_sid::text])::int, 0);
  END IF;
  SELECT COUNT(*) INTO v_count
    FROM jsonb_each(cur -> p_date) AS kv
   WHERE kv.value @> to_jsonb(p_sid);
  IF v_cap > 0 AND v_count >= v_cap AND NOT p_admin THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'full', 'count', v_count, 'cap', v_cap);
  END IF;
  IF cur -> p_date IS NULL THEN cur := jsonb_set(cur, ARRAY[p_date], '{}'::jsonb, true); END IF;
  arr := COALESCE(cur -> p_date -> p_mid, '[]'::jsonb);
  IF NOT (arr @> to_jsonb(p_sid)) THEN arr := arr || to_jsonb(p_sid); END IF;
  cur := jsonb_set(cur, ARRAY[p_date, p_mid], arr, true);
  cur := (SELECT COALESCE(jsonb_object_agg(k, v), '{}'::jsonb)
            FROM jsonb_each(cur) AS t(k, v)
           WHERE k >= to_char(CURRENT_DATE - INTERVAL '60 days', 'YYYY-MM-DD'));
  UPDATE config SET data = cur, updated_at = (EXTRACT(epoch FROM now()) * 1000)::bigint WHERE id = 'picks';
  RETURN jsonb_build_object('ok', true, 'picks', cur, 'count', v_count + 1, 'cap', v_cap);
END; $$;

-- ===== 第4步：记录瘦身后大小 =====
SELECT '瘦身后' AS 阶段, pg_column_size(data::text) AS picks_字节数
  FROM config WHERE id = 'picks';

SELECT '完成：已清理历史数据、放宽限制到 5MB、函数已加自动清理' AS 结果;
