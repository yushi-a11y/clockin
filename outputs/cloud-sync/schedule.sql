-- ============================================================
-- 每小时自动触发 sync-dingtalk（在 Supabase → SQL Editor 里运行一次）
-- 依赖 pg_cron + pg_net 扩展（Supabase 免费版即可）
-- ============================================================

-- 1. 开启扩展
create extension if not exists pg_cron;
create extension if not exists pg_net;

-- 2. （可选）先删掉旧任务，避免重复
select cron.unschedule('sync-dingtalk-hourly')
where exists (select 1 from cron.job where jobname = 'sync-dingtalk-hourly');

-- 3. 每小时的第 0 分钟调用一次 Edge Function
--    ↓↓↓ 把 <你的项目地址> 换成你的 Supabase 项目域名，例如：
--        https://qwbmvdtbosrizavzdzyp.supabase.co
select cron.schedule(
  'sync-dingtalk-hourly',
  '0 * * * *',
  $$
  select net.http_post(
    url     := 'https://qwbmvdtbosrizavzdzyp.supabase.co/functions/v1/sync-dingtalk',
    headers := jsonb_build_object('Content-Type', 'application/json'),
    body    := '{}'::jsonb
  );
  $$
);

-- 4. 查看已排的定时任务
select jobid, jobname, schedule, active from cron.job;

-- 5. 查看最近执行记录（排错用）
-- select * from cron.job_run_details order by start_time desc limit 20;

-- ------------------------------------------------------------
-- 想改频率？把上面的 '0 * * * *' 换成别的：
--   每 30 分钟：  '*/30 * * * *'
--   每 2 小时：   '0 */2 * * *'
--   工作时间每小时(7点~23点): '0 7-23 * * *'
-- ------------------------------------------------------------
