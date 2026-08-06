-- ============================================================
-- 考勤打卡系统 · Supabase RLS 修复脚本 v2（2026-07-22）
-- 目的：修复"任意打卡记录仍可插入（日期范围校验被绕过）"的漏洞
-- 原因：punches 表上存在遗留的宽松 INSERT 策略，与严格策略 OR 叠加，
--       导致 2020-01-01 这类超范围日期也能写入。
-- 执行位置：Supabase Dashboard → SQL Editor → New query → Run
-- 本脚本可安全重复执行（幂等）。
-- ============================================================

-- ===== 第0步：清理安全测试遗留数据（QoderWork 检测时写入的 __SECTEST__ 行）=====
ALTER TABLE punches DISABLE TRIGGER no_delete_punches;
DELETE FROM punches WHERE name = '__SECTEST__';
ALTER TABLE punches ENABLE TRIGGER no_delete_punches;

-- ===== 第1步：彻底删除四张表上的所有现存策略（含 UI 里手动建的、Supabase 默认的宽松策略）=====
DO $$
DECLARE r RECORD;
BEGIN
  FOR r IN
    SELECT policyname, tablename FROM pg_policies
    WHERE schemaname = 'public' AND tablename IN ('config','punches','claims','logs')
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I ON %I', r.policyname, r.tablename);
  END LOOP;
END $$;

-- ===== 第2步：确保 RLS 已启用 =====
ALTER TABLE config  ENABLE ROW LEVEL SECURITY;
ALTER TABLE punches ENABLE ROW LEVEL SECURITY;
ALTER TABLE claims  ENABLE ROW LEVEL SECURITY;
ALTER TABLE logs    ENABLE ROW LEVEL SECURITY;
-- 强制：即使表 owner 也走 RLS（防止意外绕过）
ALTER TABLE config  FORCE ROW LEVEL SECURITY;
ALTER TABLE punches FORCE ROW LEVEL SECURITY;
ALTER TABLE claims  FORCE ROW LEVEL SECURITY;
ALTER TABLE logs    FORCE ROW LEVEL SECURITY;

-- ===== 第3步：config 表 —— 可读、可增改（限 500KB）、禁删 =====
CREATE POLICY "config_select_all" ON config FOR SELECT USING (true);
CREATE POLICY "config_insert" ON config FOR INSERT
  WITH CHECK (pg_column_size(data::text) < 500000);
CREATE POLICY "config_update" ON config FOR UPDATE
  USING (pg_column_size(data::text) < 500000)
  WITH CHECK (pg_column_size(data::text) < 500000);
-- 不建 DELETE 策略 = 禁止删除 config 行

-- ===== 第4步：punches 表 —— 可读、插入须过日期/时间校验、禁改禁删 =====
CREATE POLICY "punches_select_all" ON punches FOR SELECT USING (true);
CREATE POLICY "punches_insert_validated" ON punches FOR INSERT
  WITH CHECK (
    date ~ '^\d{4}-\d{2}-\d{2}$'
    AND time ~ '^\d{2}:\d{2}$'
    AND date::date >= CURRENT_DATE - INTERVAL '7 days'
    AND date::date <= CURRENT_DATE + INTERVAL '1 day'
  );
-- 不建 UPDATE/DELETE 策略 + 下方触发器 = 双重禁止篡改

-- ===== 第5步：claims 表（设备绑定）—— 全权限（业务需要）=====
CREATE POLICY "claims_select_all" ON claims FOR SELECT USING (true);
CREATE POLICY "claims_insert" ON claims FOR INSERT WITH CHECK (true);
CREATE POLICY "claims_update" ON claims FOR UPDATE USING (true) WITH CHECK (true);
CREATE POLICY "claims_delete" ON claims FOR DELETE USING (true);

-- ===== 第6步：logs 表 —— 可读、可插入、禁改禁删 =====
CREATE POLICY "logs_select_all" ON logs FOR SELECT USING (true);
CREATE POLICY "logs_insert_all" ON logs FOR INSERT WITH CHECK (true);
-- 不建 UPDATE/DELETE 策略 + 下方触发器 = 双重禁止篡改

-- ===== 第7步：不可篡改触发器（幂等重建）=====
CREATE OR REPLACE FUNCTION prevent_logs_update() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'Logs are immutable'; END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS no_update_logs ON logs;
CREATE TRIGGER no_update_logs BEFORE UPDATE ON logs
  FOR EACH ROW EXECUTE FUNCTION prevent_logs_update();

CREATE OR REPLACE FUNCTION prevent_punches_mutation() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'Data is immutable'; END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS no_update_punches ON punches;
CREATE TRIGGER no_update_punches BEFORE UPDATE ON punches
  FOR EACH ROW EXECUTE FUNCTION prevent_punches_mutation();
DROP TRIGGER IF EXISTS no_delete_punches ON punches;
CREATE TRIGGER no_delete_punches BEFORE DELETE ON punches
  FOR EACH ROW EXECUTE FUNCTION prevent_punches_mutation();

-- ===== 第8步：自检 —— 执行后运行这段确认每张表的策略清单 =====
-- SELECT tablename, policyname, cmd FROM pg_policies
-- WHERE schemaname='public' AND tablename IN ('config','punches','claims','logs')
-- ORDER BY tablename, cmd;
-- 期望：punches 只有 1 条 SELECT + 1 条 INSERT（无任何 punches 的 INSERT WITH CHECK(true)）

-- ============================================================
-- 修复后效果验证（在浏览器控制台或 curl 里再试一次超范围插入应当被拒绝）：
--   插入 date=2020-01-01 的打卡 → 应返回 4xx（被 WITH CHECK 拒绝）
-- ============================================================
