// ============================================================
// Supabase Edge Function: sync-dingtalk
// 每小时自动从钉钉在线表格（监控选班表）读取"今日"排班，
// 并写入 Supabase 的 config 表 (id='team')。
// 网页端已经每 30 秒自动从 Supabase 刷新，所以不用改动网页。
//
// 部署命令：
//   supabase functions deploy sync-dingtalk --no-verify-jwt
// ============================================================

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

// ---- 需要在 Supabase 后台 (Edge Functions → Secrets) 里配置的变量 ----
const APP_KEY     = Deno.env.get("DINGTALK_APP_KEY")!;          // 钉钉内部应用 AppKey
const APP_SECRET  = Deno.env.get("DINGTALK_APP_SECRET")!;       // 钉钉内部应用 AppSecret
const WORKBOOK_ID = Deno.env.get("DINGTALK_WORKBOOK_ID")!;      // 在线表格 ID（表格右上角"…"→文档信息里可查）
const OPERATOR_ID = Deno.env.get("DINGTALK_OPERATOR_UNIONID")!; // 有权访问该表格的用户 unionId
// 下面两个由 Supabase 运行时自动注入，无需手动填写
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY  = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

// ---- 1. 获取钉钉 access token ----
async function getToken(): Promise<string> {
  const r = await fetch("https://api.dingtalk.com/v1.0/oauth2/accessToken", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ appKey: APP_KEY, appSecret: APP_SECRET }),
  });
  const j = await r.json();
  if (!j.accessToken) throw new Error("获取钉钉 token 失败: " + JSON.stringify(j));
  return j.accessToken as string;
}

// ---- 2. 列出表格里所有工作表 ----
async function listSheets(token: string): Promise<{ id: string; name: string }[]> {
  const url =
    `https://api.dingtalk.com/v1.0/doc/workbooks/${WORKBOOK_ID}/sheets` +
    `?operatorId=${encodeURIComponent(OPERATOR_ID)}`;
  const r = await fetch(url, { headers: { "x-acs-dingtalk-access-token": token } });
  const j = await r.json();
  const list = j.value || j.sheets || [];
  if (!Array.isArray(list)) throw new Error("读取工作表列表失败: " + JSON.stringify(j));
  return list.map((s: any) => ({ id: s.id, name: s.name }));
}

// ---- 3. 读取某工作表的单元格区域，返回二维数组 ----
async function getRange(token: string, sheetId: string, range: string): Promise<any[][]> {
  const url =
    `https://api.dingtalk.com/v1.0/doc/workbooks/${WORKBOOK_ID}/sheets/${sheetId}` +
    `/ranges/${encodeURIComponent(range)}?operatorId=${encodeURIComponent(OPERATOR_ID)}`;
  const r = await fetch(url, { headers: { "x-acs-dingtalk-access-token": token } });
  const j = await r.json();
  return (j.values as any[][]) || [];
}

// ---- 4. 解析今日排班（与网页端逻辑完全一致）----
// 布局：A列=班次时段, B~H=日期(上午段); I列=班次, J~P=日期(下午段); Q列=班次, R~X=日期(夜间段)
// 工号 → 班次ID 映射：7~23 点 → id=小时；0 点 → 24；1 点 → 25
function parseSchedule(values: any[][], existingTeam: any[]): any[] {
  // Supabase 运行在 UTC，换算成北京时间（UTC+8）取"今天"
  const cn = new Date(Date.now() + 8 * 3600 * 1000);
  const todayM = cn.getUTCMonth() + 1;
  const todayD = cn.getUTCDate();
  const tag = `${todayM}月${todayD}日`;

  const header = values[0] || [];
  // 在给定列区间(1-based，与网页端一致)里找到含今日日期的列
  const findTodayCol = (from: number, to: number): number => {
    for (let c = from; c <= to; c++) {
      const v = header[c - 1];
      if (v != null) {
        const s = typeof v === "object" ? JSON.stringify(v) : String(v);
        if (s.includes(tag)) return c;
      }
    }
    return -1;
  };
  const tCL = findTodayCol(2, 8);   // 上午段 B~H
  const tCM = findTodayCol(10, 16); // 下午段 J~P
  const tCR = findTodayCol(18, 24); // 夜间段 R~X
  if (tCL < 0 && tCM < 0 && tCR < 0) {
    throw new Error(`未在表中找到 ${tag} 的列`);
  }

  type Slot = { eid: string; hours: Set<number> };
  const slots: Slot[] = [];

  const parseCol = (shiftCol: number, dataCol: number) => {
    if (dataCol < 0) return;
    for (let r = 1; r <= 50; r++) {
      const cell = values[r]?.[shiftCol - 1];
      if (cell == null || cell === "") continue;
      const m = String(cell).match(/(\d{2}):(\d{2})~(\d{2}):(\d{2})/);
      if (!m) continue;
      const hour = parseInt(m[1]);
      // 找到下一个班次时段行，确定本时段的员工范围
      let actualEnd = r + 1;
      for (let rr = r + 1; rr <= 50; rr++) {
        const cc = values[rr]?.[shiftCol - 1];
        if (cc != null && String(cc).match(/\d{2}:\d{2}~\d{2}:\d{2}/)) { actualEnd = rr; break; }
        if (rr === 50) actualEnd = 51;
      }
      for (let er = r; er < actualEnd; er++) {
        const ec = values[er]?.[dataCol - 1];
        let num = NaN;
        if (typeof ec === "number") num = ec;
        else if (typeof ec === "string" && /^\d+(\.\d+)?$/.test(ec.trim())) num = parseFloat(ec);
        if (!isNaN(num) && num > 1000) {
          const eid = String(Math.round(num));
          let ex = slots.find((s) => s.eid === eid);
          if (!ex) { ex = { eid, hours: new Set() }; slots.push(ex); }
          ex.hours.add(hour);
        }
      }
    }
  };
  parseCol(1, tCL);   // A列班次 + 上午段
  parseCol(9, tCM);   // I列班次 + 下午段
  parseCol(17, tCR);  // Q列班次 + 夜间段

  if (!slots.length) throw new Error(`未找到 ${tag} 的排班数据`);

  const newTeam: any[] = [];
  let nid = 1;
  slots
    .sort((a, b) => a.eid.localeCompare(b.eid))
    .forEach((s) => {
      const hours = Array.from(s.hours).sort((a, b) => a - b);
      const sids = hours.map((h) => (h >= 7 ? h : h === 0 ? 24 : h === 1 ? 25 : h));
      const existing = existingTeam.find((m: any) => m.name === s.eid);
      if (existing) newTeam.push({ ...existing, shiftIds: sids });
      else newTeam.push({ id: nid++, name: s.eid, dept: "", shiftIds: sids });
    });
  // 保留没有排班的既有成员（清空其班次）
  existingTeam.forEach((m: any) => {
    if (!newTeam.find((n) => n.name === m.name)) newTeam.push({ ...m, shiftIds: [] });
  });
  newTeam.forEach((m, i) => (m.id = i + 1));
  return newTeam;
}

// ---- 主流程 ----
Deno.serve(async () => {
  try {
    const supa = createClient(SUPABASE_URL, SERVICE_KEY);
    const token = await getToken();

    const sheets = await listSheets(token);
    const dateSheets = sheets.filter((s) => /\d+月\d+日/.test(s.name));
    if (!dateSheets.length) throw new Error("未找到包含日期的工作表");
    const sheet = dateSheets[0]; // 与网页端一致：取第一个含日期的工作表（最新）

    const values = await getRange(token, sheet.id, "A1:X60");

    const { data: teamRow } = await supa
      .from("config").select("data").eq("id", "team").single();
    const existingTeam = teamRow?.data || [];

    const newTeam = parseSchedule(values, existingTeam);

    await supa.from("config").upsert(
      { id: "team", data: newTeam, updated_at: Date.now() },
      { onConflict: "id" },
    );

    return new Response(
      JSON.stringify({ ok: true, sheet: sheet.name, count: newTeam.length, at: new Date().toISOString() }),
      { headers: { "Content-Type": "application/json" } },
    );
  } catch (e) {
    return new Response(
      JSON.stringify({ ok: false, error: String(e) }),
      { status: 500, headers: { "Content-Type": "application/json" } },
    );
  }
});
