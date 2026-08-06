-- ============================================================
--  增量选班原子函数：pick_add / pick_remove
--  作用：解决 15 人同时选班时"选了又被取消 / 选不上"的并发覆盖问题
--
--  ⚠️ 重要：请用 Cmd+A（全选）后再点 Run / 运行！
--     不要只选中某一段运行，否则函数不会被创建。
--
--  原理：之前的 pick_set 是"整体覆盖"——客户端读到旧快照后把整个班次
--     数组覆盖写回，会把别人/自己刚选的班次冲掉。
--     pick_add / pick_remove 改为"增量"：服务器端先 FOR UPDATE 锁住
--     picks 行，基于【最新】数据只增加或删除【一个】班次，再写回。
--     这样无论多少人同时操作、客户端快照多旧，都不会互相覆盖。
--
--  说明：pick_set（整体设置）保留不动，管理员"整格编辑/一键清空"仍用它。
-- ============================================================

-- ---------- 1) 增加一个班次 ----------
CREATE OR REPLACE FUNCTION public.pick_add(p_date text, p_mid text, p_sid int)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
  cur jsonb;
  arr jsonb;
BEGIN
  -- 锁住 picks 这一行，排队执行，避免并发互相覆盖
  PERFORM 1 FROM config WHERE id = 'picks' FOR UPDATE;

  SELECT data INTO cur FROM config WHERE id = 'picks';
  IF cur IS NULL THEN
    cur := '{}'::jsonb;
  END IF;

  -- 确保 date 层存在
  IF cur -> p_date IS NULL THEN
    cur := jsonb_set(cur, ARRAY[p_date], '{}'::jsonb, true);
  END IF;

  -- 取出该成员当天的班次数组（不存在则为空数组）
  arr := COALESCE(cur -> p_date -> p_mid, '[]'::jsonb);

  -- 去重后追加这个班次
  IF NOT (arr @> to_jsonb(p_sid)) THEN
    arr := arr || to_jsonb(p_sid);
  END IF;

  cur := jsonb_set(cur, ARRAY[p_date, p_mid], arr, true);

  UPDATE config
     SET data = cur,
         updated_at = (EXTRACT(epoch FROM now()) * 1000)::bigint
   WHERE id = 'picks';

  RETURN cur;
END;
$$;


-- ---------- 2) 删除一个班次 ----------
CREATE OR REPLACE FUNCTION public.pick_remove(p_date text, p_mid text, p_sid int)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
  cur jsonb;
  arr jsonb;
BEGIN
  PERFORM 1 FROM config WHERE id = 'picks' FOR UPDATE;

  SELECT data INTO cur FROM config WHERE id = 'picks';
  IF cur IS NULL THEN
    cur := '{}'::jsonb;
  END IF;

  IF cur -> p_date IS NULL THEN
    cur := jsonb_set(cur, ARRAY[p_date], '{}'::jsonb, true);
  END IF;

  arr := COALESCE(cur -> p_date -> p_mid, '[]'::jsonb);

  -- 过滤掉这个班次
  SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
    INTO arr
    FROM jsonb_array_elements(arr) elem
   WHERE elem <> to_jsonb(p_sid);

  cur := jsonb_set(cur, ARRAY[p_date, p_mid], arr, true);

  UPDATE config
     SET data = cur,
         updated_at = (EXTRACT(epoch FROM now()) * 1000)::bigint
   WHERE id = 'picks';

  RETURN cur;
END;
$$;


-- ---------- 3) 授权（容错：即使角色不存在也不报错） ----------
DO $$
BEGIN
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_add(text,text,int) TO anon';      EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_add(text,text,int) TO authenticated'; EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_remove(text,text,int) TO anon';      EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_remove(text,text,int) TO authenticated'; EXCEPTION WHEN OTHERS THEN NULL; END;
END $$;


-- ---------- 4) 自检：确认两个函数都已创建 ----------
DO $$
DECLARE
  n int;
BEGIN
  SELECT count(*) INTO n
    FROM pg_proc p
    JOIN pg_namespace ns ON ns.oid = p.pronamespace
   WHERE ns.nspname = 'public'
     AND p.proname IN ('pick_add','pick_remove');
  IF n < 2 THEN
    RAISE EXCEPTION '自检失败：pick_add / pick_remove 未全部创建成功（当前 %/2），请确认已全选脚本后运行', n;
  END IF;
END $$;

SELECT 'pick_add / pick_remove 创建成功，可以部署前端了' AS 结果;
