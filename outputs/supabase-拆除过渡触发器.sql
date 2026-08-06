-- ============================================================
--  拆除过渡触发器（降低延迟 · 消除 config 行锁）
--
--  背景：服务端化改造时加了一个过渡触发器 picks_sync_config，
--       每次选班变动都把整块 JSON 重新聚合写回 config，
--       用于照顾"还没刷新到新版"的旧客户端。它会带来额外延迟，
--       并把 config 行锁重新引入。
--  现在大家基本都已刷新到新版前端（直接读 picks 表快照），
--       这个触发器可以拆掉，延迟会明显下降。
--
--  ⚠️ 执行前提：确认团队都已刷新到新版页面（顶部无"检测到新版本"横幅）。
--  ⚠️ Cmd+A 全选后运行。可安全重复执行。
-- ============================================================

DROP TRIGGER IF EXISTS picks_sync_config ON public.picks;
DROP FUNCTION IF EXISTS public.sync_picks_to_config();

-- 自检：确认触发器已不存在
DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n FROM pg_trigger WHERE tgname = 'picks_sync_config';
  IF n > 0 THEN
    RAISE EXCEPTION '自检失败：触发器仍未拆除';
  END IF;
END $$;

SELECT '过渡触发器已拆除，延迟优化生效' AS 结果;
