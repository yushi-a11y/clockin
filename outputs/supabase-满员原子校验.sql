-- ============================================================
--  满员原子校验函数：pick_add_cap
--  作用：把"检查时段是否满员"和"加入班次"合并到同一个加锁事务里，
--       彻底杜绝并发下"两人都通过满员校验→超员"的边界问题。
--
--  ⚠️ 重要：请用 Cmd+A（全选）后再点 Run / 运行！
--
--  原理：之前的满员判断在前端做——先查人数、再调用加班，两步之间
--       有时间差，15 人同时抢最后一个名额时可能都查到"还有空"然后
--       全部加进去，导致超员。
--       pick_add_cap 在服务器端 FOR UPDATE 锁住 picks 行后，先数当前
--       人数，满员就拒绝（管理员可超额），不满才加入，全程原子。
--
--  返回：
--    成功 → {"ok":true, "picks":<最新完整数据>, "count":N, "cap":C}
--    满员 → {"ok":false, "reason":"full", "count":N, "cap":C}
--
--  说明：pick_add / pick_remove / pick_set 保留不动，本函数只新增。
-- ============================================================

CREATE OR REPLACE FUNCTION public.pick_add_cap(p_date text, p_mid text, p_sid int, p_admin boolean)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
  cur    jsonb;
  arr    jsonb;
  caprow jsonb;
  v_cap  int;
  v_count int;
BEGIN
  -- 锁住 picks 行：检查人数 与 加入班次 在同一把锁内完成，杜绝并发超员
  PERFORM 1 FROM config WHERE id = 'picks' FOR UPDATE;

  SELECT data INTO cur FROM config WHERE id = 'picks';
  IF cur IS NULL THEN
    cur := '{}'::jsonb;
  END IF;

  -- 读取该日期该时段的人数上限（0 / 未配置 = 不限）
  SELECT data INTO caprow FROM config WHERE id = 'slotcap';
  v_cap := 0;
  IF caprow IS NOT NULL THEN
    v_cap := COALESCE((caprow #>> ARRAY[p_date, p_sid::text])::int, 0);
  END IF;

  -- 统计当前已选该时段的人数（锁内读取，保证与后续写入原子一致）
  SELECT COUNT(*) INTO v_count
    FROM jsonb_each(cur -> p_date) AS kv
   WHERE kv.value @> to_jsonb(p_sid);

  -- 满员则拒绝（管理员可超额分配）
  IF v_cap > 0 AND v_count >= v_cap AND NOT p_admin THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'full', 'count', v_count, 'cap', v_cap);
  END IF;

  -- 确保 date 层存在
  IF cur -> p_date IS NULL THEN
    cur := jsonb_set(cur, ARRAY[p_date], '{}'::jsonb, true);
  END IF;

  -- 去重后追加班次
  arr := COALESCE(cur -> p_date -> p_mid, '[]'::jsonb);
  IF NOT (arr @> to_jsonb(p_sid)) THEN
    arr := arr || to_jsonb(p_sid);
  END IF;
  cur := jsonb_set(cur, ARRAY[p_date, p_mid], arr, true);

  UPDATE config
     SET data = cur,
         updated_at = (EXTRACT(epoch FROM now()) * 1000)::bigint
   WHERE id = 'picks';

  RETURN jsonb_build_object('ok', true, 'picks', cur, 'count', v_count + 1, 'cap', v_cap);
END;
$$;


-- ---------- 授权（容错：角色不存在也不报错） ----------
DO $$
BEGIN
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_add_cap(text,text,int,boolean) TO anon';          EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN EXECUTE 'GRANT EXECUTE ON FUNCTION public.pick_add_cap(text,text,int,boolean) TO authenticated'; EXCEPTION WHEN OTHERS THEN NULL; END;
END $$;


-- ---------- 自检 ----------
DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n
    FROM pg_proc p JOIN pg_namespace ns ON ns.oid = p.pronamespace
   WHERE ns.nspname = 'public' AND p.proname = 'pick_add_cap';
  IF n < 1 THEN
    RAISE EXCEPTION '自检失败：pick_add_cap 未创建成功，请确认已全选脚本后运行';
  END IF;
END $$;

SELECT 'pick_add_cap 创建成功，可以部署前端了' AS 结果;
