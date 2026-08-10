-- 将 punches 表的 RLS 插入策略从 7 天放宽到 8 天
-- 解决补卡申请在 7 天边界被 RLS 拒绝的问题
-- 执行时间：2026-08-10

DROP POLICY IF EXISTS "punches_insert_validated" ON punches;

CREATE POLICY "punches_insert_validated" ON punches
  FOR INSERT WITH CHECK(
    date ~ '^\d{4}-\d{2}-\d{2}$'
    AND time ~ '^\d{2}:\d{2}$'
    AND date::date >= CURRENT_DATE - INTERVAL '8 days'
    AND date::date <= CURRENT_DATE + INTERVAL '1 day'
  );
