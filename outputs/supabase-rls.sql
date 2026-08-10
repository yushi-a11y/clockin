-- ============================================
-- 考勤打卡系统 · Supabase RLS 安全策略
-- 适用于：未启用 Supabase Auth、前端 anon key 直连的架构
-- 执行位置：Supabase Dashboard → SQL Editor → New query → Run
-- ============================================

-- ===== 第1步：先删除旧的宽松策略（如果存在） =====
DROP POLICY IF EXISTS "config_read_all" ON config;
DROP POLICY IF EXISTS "config_write_auth" ON config;
DROP POLICY IF EXISTS "config_update_auth" ON config;
DROP POLICY IF EXISTS "config_delete_auth" ON config;
DROP POLICY IF EXISTS "punches_read_all" ON punches;
DROP POLICY IF EXISTS "punches_insert_check" ON punches;
DROP POLICY IF EXISTS "claims_all" ON claims;
DROP POLICY IF EXISTS "logs_read_all" ON logs;
DROP POLICY IF EXISTS "logs_insert_all" ON logs;

-- 也删掉 Supabase 自动生成的默认全开放策略（如果存在的话）
DROP POLICY IF EXISTS "Enable read access for all users" ON config;
DROP POLICY IF EXISTS "Enable insert for all users" ON config;
DROP POLICY IF EXISTS "Enable update for all users" ON config;
DROP POLICY IF EXISTS "Enable delete for all users" ON config;
DROP POLICY IF EXISTS "Enable read access for all users" ON punches;
DROP POLICY IF EXISTS "Enable insert for all users" ON punches;
DROP POLICY IF EXISTS "Enable read access for all users" ON claims;
DROP POLICY IF EXISTS "Enable insert for all users" ON claims;
DROP POLICY IF EXISTS "Enable read access for all users" ON logs;
DROP POLICY IF EXISTS "Enable insert for all users" ON logs;

-- ===== 第2步：启用 RLS =====
ALTER TABLE config ENABLE ROW LEVEL SECURITY;
ALTER TABLE punches ENABLE ROW LEVEL SECURITY;
ALTER TABLE claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE logs ENABLE ROW LEVEL SECURITY;

-- ===== 第3步：config 表策略 =====
-- 所有人可读（前端需要拉取班次/选班/规则等数据）
CREATE POLICY "config_select_all" ON config
  FOR SELECT USING(true);

-- 允许插入和更新（前端需要写入选班/规则/换班等数据）
-- 但限制 data 字段不能是超大 JSON（防止恶意注入大量数据）
CREATE POLICY "config_insert" ON config
  FOR INSERT WITH CHECK(
    pg_column_size(data::text) < 500000  -- 单行 data 不超过 500KB
  );

CREATE POLICY "config_update" ON config
  FOR UPDATE USING(
    pg_column_size(data::text) < 500000
  );

-- 关键：禁止删除 config 行（保护核心配置不被清空）
-- 注意：不创建 DELETE policy = 默认拒绝所有删除
-- 如果需要 adminClearAll 功能，可以改用下面的条件删除策略：
-- CREATE POLICY "config_delete_restricted" ON config
--   FOR DELETE USING(id = '_test');  -- 仅允许删除 _test 行（连接测试用）

-- ===== 第4步：punches 表策略 =====
-- 所有人可读
CREATE POLICY "punches_select_all" ON punches
  FOR SELECT USING(true);

-- 插入时验证：日期在合理范围内、时间格式正确
CREATE POLICY "punches_insert_validated" ON punches
  FOR INSERT WITH CHECK(
    date ~ '^\d{4}-\d{2}-\d{2}$'
    AND time ~ '^\d{2}:\d{2}$'
    AND date::date >= CURRENT_DATE - INTERVAL '8 days'
    AND date::date <= CURRENT_DATE + INTERVAL '1 day'
  );

-- 禁止更新和删除打卡记录（打卡数据不可篡改）
-- 不创建 UPDATE/DELETE policy = 默认拒绝

-- ===== 第5步：claims 表策略（设备绑定） =====
-- 所有人可读可写（设备绑定/解绑需要）
CREATE POLICY "claims_select_all" ON claims
  FOR SELECT USING(true);

CREATE POLICY "claims_insert" ON claims
  FOR INSERT WITH CHECK(true);

CREATE POLICY "claims_update" ON claims
  FOR UPDATE USING(true);

CREATE POLICY "claims_delete" ON claims
  FOR DELETE USING(true);

-- ===== 第6步：logs 表策略（操作日志） =====
-- 所有人可读
CREATE POLICY "logs_select_all" ON logs
  FOR SELECT USING(true);

-- 所有人可插入
CREATE POLICY "logs_insert_all" ON logs
  FOR INSERT WITH CHECK(true);

-- 禁止更新和删除日志（日志不可篡改）
-- 不创建 UPDATE/DELETE policy = 默认拒绝

-- ===== 第7步：给 logs 加触发器，双重保险禁止 UPDATE =====
CREATE OR REPLACE FUNCTION prevent_logs_update() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'Logs are immutable - updates not allowed';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS no_update_logs ON logs;
CREATE TRIGGER no_update_logs
  BEFORE UPDATE ON logs
  FOR EACH ROW EXECUTE FUNCTION prevent_logs_update();

-- ===== 第8步：给 punches 加触发器，禁止 UPDATE/DELETE =====
CREATE OR REPLACE FUNCTION prevent_punches_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'Punches are immutable - updates and deletes not allowed';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS no_update_punches ON punches;
CREATE TRIGGER no_update_punches
  BEFORE UPDATE ON punches
  FOR EACH ROW EXECUTE FUNCTION prevent_punches_mutation();

DROP TRIGGER IF EXISTS no_delete_punches ON punches;
CREATE TRIGGER no_delete_punches
  BEFORE DELETE ON punches
  FOR EACH ROW EXECUTE FUNCTION prevent_punches_mutation();

-- ============================================
-- 执行完毕后的安全效果：
-- ✅ 任何拿到 API Key 的人可以读取数据（正常功能需要）
-- ✅ 可以插入/更新 config 数据（选班/规则等正常功能需要）
-- ❌ 不能删除 config 行（保护核心配置不被清空）
-- ❌ 不能插入超过 7 天范围的打卡记录
-- ❌ 不能修改或删除任何打卡记录（打卡数据不可篡改）
-- ❌ 不能修改或删除任何操作日志（日志不可篡改）
-- ❌ 单条 config 数据不能超过 500KB（防止恶意注入）
-- ============================================
