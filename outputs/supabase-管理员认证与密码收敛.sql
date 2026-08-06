-- ============================================================================
-- supabase-管理员认证与密码收敛.sql
-- 目标：为 C-1（管理员认证服务端化）打下服务端基础，并为 C-3（config 表
--       密码哈希收敛）提供检查与二阶段清理语句。
-- 适用：本项目 Supabase 新库（PostgreSQL 14+，与 supabase-新项目建表脚本.sql 同库）
-- 幂等：全部语句可重复执行
-- 状态：本脚本是"服务端地基"。客户端接入（doLogin 改调 admin_verify、
--       isAdminNow 校验服务端 token、syncToFB 剔除 pwd）是后续前端版本的工作，
--       在客户端接入完成前，执行本脚本不会改变任何现有行为（纯增量）。
-- ============================================================================

create extension if not exists pgcrypto;

-- ----------------------------------------------------------------------------
-- 1. 管理员凭据表（单例行）+ 令牌密钥表
--    设计：RLS 无任何策略 + FORCE，直连/PostgREST 一律拒绝；
--    数据只能通过下方 SECURITY DEFINER 函数访问。
-- ----------------------------------------------------------------------------
create table if not exists public.admin_creds (
  id         int primary key default 1 check (id = 1),
  pwd_hash   text not null,             -- sha256 hex(64)，与前端 sha256() 一致
  updated_at timestamptz not null default now()
);

create table if not exists public.admin_secret (
  id           int primary key default 1 check (id = 1),
  token_secret text not null
);

-- 尝试记录表（限流用，只写不读给客户端）
create table if not exists public.admin_attempts (
  id bigserial primary key,
  ts timestamptz not null default now(),
  ok boolean not null
);

-- 首次初始化：令牌密钥随机生成；管理员密码播种为 sha256('admin123')。
-- ⚠ 播种后请立即调用 admin_set_pwd 修改默认密码（见文末操作步骤）。
insert into public.admin_secret (id, token_secret)
select 1, encode(gen_random_bytes(32), 'hex')
where not exists (select 1 from public.admin_secret);

insert into public.admin_creds (id, pwd_hash)
select 1, encode(digest('admin123', 'sha256'), 'hex')
where not exists (select 1 from public.admin_creds);

alter table public.admin_creds    enable row level security;
alter table public.admin_secret   enable row level security;
alter table public.admin_attempts enable row level security;
alter table public.admin_creds    force row level security;
alter table public.admin_secret   force row level security;
alter table public.admin_attempts force row level security;
-- 不创建任何 policy：anon/authenticated 直接访问 = 全部拒绝
revoke all on public.admin_creds    from anon, authenticated;
revoke all on public.admin_secret   from anon, authenticated;
revoke all on public.admin_attempts from anon, authenticated;

-- ----------------------------------------------------------------------------
-- 2. admin_verify：服务端管理员校验（C-1 核心）
--    入参：client_hash = 前端 sha256(输入密码) 的 hex
--    返回：{ok:true, token, exp} 或 {ok:false, reason}
--    防护：5 分钟内全局失败 >=10 次即拒绝（rate_limited）；
--          比较经 hmac 包装，减弱直接文本比较的时序侧信道（非绝对恒定时间）。
-- ----------------------------------------------------------------------------
create or replace function public.admin_verify(client_hash text)
returns json
language plpgsql security definer set search_path = public as $$
declare
  stored        text;
  recent_fails  int;
  exp           timestamptz;
  token         text;
begin
  if client_hash is null or client_hash !~ '^[a-f0-9]{64}$' then
    return json_build_object('ok', false, 'reason', 'bad_input');
  end if;

  select count(*) into recent_fails
  from admin_attempts
  where ts > now() - interval '5 minutes' and not ok;
  if recent_fails >= 10 then
    return json_build_object('ok', false, 'reason', 'rate_limited');
  end if;

  select pwd_hash into stored from admin_creds where id = 1;
  if stored is null then
    return json_build_object('ok', false, 'reason', 'not_configured');
  end if;

  if hmac(stored, 'cmp', 'sha256') = hmac(client_hash, 'cmp', 'sha256') then
    insert into admin_attempts (ok) values (true);
    exp := date_trunc('second', now() + interval '2 hours');
    token := encode(hmac('admin|' || to_char(exp, 'YYYY-MM-DD"T"HH24:MI:SS'),
                         (select token_secret from admin_secret where id = 1),
                         'sha256'), 'hex');
    return json_build_object('ok', true, 'token', token,
                             'exp', to_char(exp, 'YYYY-MM-DD"T"HH24:MI:SS'));
  else
    insert into admin_attempts (ok) values (false);
    return json_build_object('ok', false, 'reason', 'bad_credentials');
  end if;
end $$;

-- ----------------------------------------------------------------------------
-- 3. admin_token_valid：供后续写操作 RPC 复用的 token 校验
-- ----------------------------------------------------------------------------
create or replace function public.admin_token_valid(token text, exp_text text)
returns boolean
language plpgsql security definer set search_path = public as $$
declare
  expected text;
begin
  if token is null or exp_text is null
     or exp_text !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$' then
    return false;
  end if;
  if to_timestamp(exp_text, 'YYYY-MM-DD"T"HH24:MI:SS') < now() then
    return false;
  end if;
  expected := encode(hmac('admin|' || exp_text,
                          (select token_secret from admin_secret where id = 1),
                          'sha256'), 'hex');
  return hmac(expected, 'cmp', 'sha256') = hmac(token, 'cmp', 'sha256');
end $$;

-- ----------------------------------------------------------------------------
-- 4. admin_set_pwd：凭有效 token 修改管理员密码（仅接受 sha256 hex）
-- ----------------------------------------------------------------------------
create or replace function public.admin_set_pwd(token text, exp_text text, new_hash text)
returns json
language plpgsql security definer set search_path = public as $$
begin
  if not public.admin_token_valid(token, exp_text) then
    return json_build_object('ok', false, 'reason', 'bad_token');
  end if;
  if new_hash is null or new_hash !~ '^[a-f0-9]{64}$' then
    return json_build_object('ok', false, 'reason', 'bad_input');
  end if;
  update admin_creds set pwd_hash = new_hash, updated_at = now() where id = 1;
  return json_build_object('ok', true);
end $$;

revoke all on function public.admin_verify(text)        from public, anon, authenticated;
revoke all on function public.admin_token_valid(text, text) from public, anon, authenticated;
revoke all on function public.admin_set_pwd(text, text, text) from public, anon, authenticated;
grant execute on function public.admin_verify(text)        to anon, authenticated;
grant execute on function public.admin_token_valid(text, text) to anon, authenticated;
grant execute on function public.admin_set_pwd(text, text, text) to anon, authenticated;

-- ============================================================================
-- 5. C-3 密码哈希收敛：检查与二阶段清理
-- ============================================================================

-- 5.1 检查：config 表 team 行中还残留多少成员密码字段（立即可执行，只读）
select count(*) as members_with_pwd
from config c,
     lateral jsonb_array_elements(c.data) m
where c.id = 'team'
  and m ->> 'pwd' is not null
  and m ->> 'pwd' <> '';

-- 5.2 ⚠ 二阶段清理（暂勿执行，保留为注释）：
--     前提条件：① 成员认证已服务端化（成员密码不再经 config 分发）；
--               ② 所有在线设备已升级到"上传不带 pwd"的前端版本。
--     在此之前执行会导致新设备/重置密码无法获得凭据，直接破坏登录。
-- update config
-- set data = (select jsonb_agg(m - 'pwd')
--             from jsonb_array_elements(config.data) m),
--     updated_at = extract(epoch from now()) * 1000
-- where id = 'team';

-- ============================================================================
-- 6. 操作步骤（执行本脚本后）
-- ============================================================================
-- ① 立即改默认密码（避免任何人用 admin123 通过服务端校验）：
--    先取 token：
--      select public.admin_verify(encode(digest('admin123','sha256'),'hex'));
--    再用返回的 token/exp 设置新密码哈希（示例：新密码 'MyNewPwd!234'）：
--      select public.admin_set_pwd('<token>', '<exp>',
--             encode(digest('MyNewPwd!234','sha256'),'hex'));
-- ② 前端后续版本接入：doLogin → admin_verify；isAdminNow → 本地 exp 检查 +
--    关键写操作前 admin_token_valid；syncToFB 上行剔除 pwd。
-- ③ 客户端全面切换并观察一个完整工作日后，再评估执行 5.2 清理。
-- ============================================================================
