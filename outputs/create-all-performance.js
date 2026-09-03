// 在浏览器 Console 中运行此脚本，为所有成员创建 2026-08 月的绩效记录
// 复制粘贴到 Console 中执行

(function createAllPerformanceRecords() {
  const month = '2026-08';
  const existingMids = new Set(performances.filter(p => p.month === month).map(p => +p.mid));
  const newRecords = [];
  
  TEAM.forEach(m => {
    if (existingMids.has(+m.id)) {
      console.log(`跳过 ${m.name}（已存在）`);
      return;
    }
    
    const rec = {
      id: 'pf' + Date.now() + '_' + Math.random().toString(36).slice(2, 6),
      month: month,
      mid: +m.id,
      name: m.name,
      workDays: 0,
      workHours: 0,
      lateCount: 0,
      missCount: 0,
      leaveDays: 0,
      score: 0,
      remark: '待录入',
      ts: Date.now(),
      updatedBy: '管理员'
    };
    
    performances.push(rec);
    newRecords.push(m.name);
  });
  
  if (newRecords.length === 0) {
    console.log('✓ 所有成员已有绩效记录');
    return;
  }
  
  performances.sort((a, b) => b.month.localeCompare(a.month) || b.ts - a.ts);
  svPerformances();
  syncPerformances();
  
  console.log(`\n===== 已创建 ${newRecords.length} 条绩效记录 =====`);
  console.log(newRecords.map((n, i) => `${i + 1}. ${n}`).join('\n'));
  console.log('\n刷新页面后查看');
  
  renderPerformanceAdmin();
})();
