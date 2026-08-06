-- ============================================================
-- 新加坡项目（御史）收尾脚本
-- 迁移数据完成后执行，共 3 件事：
-- 1. 重置 punches / logs 自增序列（防止新打卡 id 冲突）
-- 2. 开启 picks 表 Realtime（多人协同实时同步用）
-- 执行位置：Supabase Dashboard → SQL Editor → Run
-- ============================================================

-- 1) 重置自增序列到当前最大 id
SELECT setval(pg_get_serial_sequence('punches','id'), (SELECT MAX(id) FROM punches));
SELECT setval(pg_get_serial_sequence('logs','id'), (SELECT MAX(id) FROM logs));

-- 2) picks 表加入 Realtime 发布（前端订阅选班变化用）
ALTER PUBLICATION supabase_realtime ADD TABLE picks;

-- 3) 自检：确认序列和发布已生效
SELECT last_value FROM punches_id_seq;
SELECT last_value FROM logs_id_seq;
SELECT tablename FROM pg_publication_tables WHERE pubname='supabase_realtime';
-- 期望最后一项结果里包含 picks
