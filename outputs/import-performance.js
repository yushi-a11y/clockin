// 在 ClockIn 管理后台「绩效录入」页面，按 F12 打开控制台，粘贴后回车即可批量导入。
// 匹配规则：按「小二名称」精确匹配现有成员；找不到则跳过。
(async () => {
  const rows = [
    { name: '云客服8593490', rank: 1.00 },
    { name: '云客服3065861', rank: 0.80 },
    { name: '云客服3072437', rank: 1.00 },
    { name: '云客服8027356', rank: 0.95 },
    { name: '云客服8091129', rank: 1.00 },
    { name: '云客服8191398', rank: 1.00 },
    { name: '云客服8596120', rank: 0.90 },
    { name: '云客服8593305', rank: 1.00 },
    { name: '云客服133122',  rank: 0.95 },
    { name: '云客服3060017', rank: 0.95 },
    { name: '云客服3051105', rank: 1.00 },
    { name: '云客服8191272', rank: 0.95 },
    { name: '云客服8598314', rank: 1.00 },
    { name: '云客服8139540', rank: 1.00 },
    { name: '云客服8094271', rank: 1.00 },
    { name: '云客服8597644', rank: 1.00 },
    { name: '云客服8600441', rank: 0.90 }
  ];

  const month = perfMonthStr();
  let added = 0, skipped = [];

  for (const r of rows) {
    const m = TEAM.find(x => x.name === r.name);
    if (!m) {
      skipped.push(r.name);
      continue;
    }
    const mid = +m.id;
    const score = Math.min(100, Math.max(0, Math.round(r.rank * 100)));
    const existingIdx = performances.findIndex(p => p.month === month && +p.mid === mid);
    const rec = {
      id: existingIdx >= 0 ? performances[existingIdx].id : ('pf' + Date.now() + '_' + Math.random().toString(36).slice(2, 6)),
      month,
      mid,
      name: m.name,
      workDays: 0,
      workHours: 0,
      lateCount: 0,
      missCount: 0,
      leaveDays: 0,
      score,
      remark: '批量导入',
      ts: Date.now(),
      updatedBy: '管理员'
    };
    if (existingIdx >= 0) {
      performances[existingIdx] = rec;
    } else {
      performances.push(rec);
    }
    added++;
  }

  performances.sort((a, b) => b.month.localeCompare(a.month) || b.ts - a.ts);
  svPerformances();
  try { await syncPerformances(); } catch (e) { console.warn('同步失败', e); }
  renderPerformanceAdmin();
  logEvent('绩效录入', `批量导入 ${added} 条绩效记录（${month}）`);
  showToast(`已导入 ${added} 条绩效记录`);
  if (skipped.length) {
    console.warn('未匹配到成员，已跳过：', skipped);
  }
})();
