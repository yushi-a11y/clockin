-- ============================================================
-- 考勤打卡系统 · 并发选班修复脚本 v2（2026-07-23）
-- 目的：修复"多人同时选班互相覆盖（选不上 / 选了自动消失）"
--
-- ★★★ 重要：请按 Cmd+A 全选本文件全部内容，再点 Run ★★★
--     真正创建函数的是最下面的 CREATE FUNCTION，必须一起执行。
--
-- 执行位置：Supabase Dashboard → SQL Editor → New query → 全选 → Run
-- 本脚本可安全重复执行（幂等）。
-- ============================================================

-- 1) 创建服务器端原子写入函数（行锁排队，杜绝并发覆盖）
CREATE OR REPLACE FUNCTION public.pick_set(
  p_date text,          -- 日期，如 '2026-07-24'
  p_mid  text,          -- 成员 id（文本形式，如 '3'）
  p_sids jsonb          -- 该成员当天的班次 id 数组，如 [8, 9, 12]
)
RETURNS jsonb           -- 返回写入后的最新完整选班数据
LANGUAGE plpgsql
AS $$
DECLARE
  cur jsonb;
BEGIN
  -- 行锁：所有并发选班写入在此排队，逐个执行，互不覆盖
  PERFORM 1 FROM config WHERE id = 'picks' FOR UPDATE;

  SELECT data INTO cur FROM config WHERE id = 'picks';
  IF cur IS NULL THEN cur := '{}'::jsonb; END IF;

  -- 只修改"当前成员、当天"这一条，不动其他人
  IF cur -> p_date IS NULL THEN
    cur := jsonb_set(cur, ARRAY[p_date], '{}'::jsonb, true);
  END IF;
  cur := jsonb_set(cur, ARRAY[p_date, p_mid], p_sids, true);

  UPDATE config
     SET data = cur,
         updated_at = (EXTRACT(epoch FROM now()) * 1000)::bigint
   WHERE id = 'picks';

  RETURN cur;
END;
$$;

-- 2) 授权前端角色调用（容错：即使角色不存在也不报错、不影响函数创建）
DO $$ BEGIN
  EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_set(text, text, jsonb) TO anon';
EXCEPTION WHEN OTHERS THEN NULL;
END $$;
DO $$ BEGIN
  EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_set(text, text, jsonb) TO authenticated';
EXCEPTION WHEN OTHERS THEN NULL;
END $$;

-- 3) 自检：函数存在则返回一行 pick_set；不存在则下方会报错提示
SELECT proname AS 函数名, '创建成功，可以部署前端了' AS 状态
FROM pg_proc WHERE proname = 'pick_set' LIMIT 1;

-- 如果上面返回空（No rows returned），说明函数没建成功，
-- 请确认你【全选了整个文件】再 Run 一次；仍失败请把红色报错发我。
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'pick_set') THEN
    RAISE EXCEPTION 'pick_set 函数未创建成功！请全选整个脚本重新执行。';
  END IF;
END $$;
