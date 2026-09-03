// 在浏览器 Console 中运行此脚本，分析工号 133122 的缺卡详情
// 复制粘贴到 Console 中执行

(function analyzeMissedPunches() {
  const mid = 1; // 工号 133122 的 id
  const monthStr = '2026-08';
  const todayStr = tdStr();
  const isCurrentMonth = monthStr === todayStr.slice(0, 7);
  
  // 获取已批准的请假
  const approvedLeaves = leaves.filter(l =>
    +l.mid === mid && l.status === 'approved' && (l.date || '').slice(0, 7) === monthStr && (!isCurrentMonth || l.date <= todayStr)
  );
  const isShiftOnLeave = (ds, sid) => approvedLeaves.some(l => l.date === ds && Array.isArray(l.sids) && l.sids.includes(sid));
  
  // 获取已批准的补卡
  const acceptedMakeups = makeups.filter(m =>
    +m.mid === mid && m.status === 'accepted' && (m.date || '').slice(0, 7) === monthStr
  );
  
  const missedDetails = [];
  
  Object.keys(picks).forEach(ds => {
    if (ds.slice(0, 7) !== monthStr) return;
    if (isCurrentMonth && ds > todayStr) return;
    
    const shiftIds = picks[ds] && picks[ds][mid];
    if (!Array.isArray(shiftIds) || !shiftIds.length) return;
    
    const dayPunches = getAllPunchesForMember(mid, ds);
    
    shiftIds.forEach(sid => {
      const shift = state.shifts.find(s => s.id === sid);
      if (!shift) return;
      
      let missingS = !dayPunches.some(p => p.sid === sid && p.t === 's');
      let missingE = !dayPunches.some(p => p.sid === sid && p.t === 'e');
      
      // 请假覆盖
      if (isShiftOnLeave(ds, sid)) {
        missingS = false;
        missingE = false;
      }
      
      // 补卡扣除
      if (missingS && acceptedMakeups.some(m => m.date === ds && m.sid === sid && m.t === 's')) {
        missingS = false;
      }
      if (missingE && acceptedMakeups.some(m => m.date === ds && m.sid === sid && m.t === 'e')) {
        missingE = false;
      }
      
      if (missingS || missingE) {
        missedDetails.push({
          date: ds,
          shift: shift.name,
          missing: missingS && missingE ? '上班卡+下班卡' : (missingS ? '上班卡' : '下班卡')
        });
      }
    });
  });
  
  console.log(`\n===== 工号 133122 (${monthStr}) 缺卡详情 =====`);
  console.log(`总缺卡次数：${missedDetails.length}\n`);
  
  if (missedDetails.length === 0) {
    console.log('✓ 无缺卡记录');
  } else {
    console.table(missedDetails);
    console.log('\n详细列表：');
    missedDetails.forEach((d, i) => {
      console.log(`${i + 1}. ${d.date} ${d.shift} - 缺${d.missing}`);
    });
  }
  
  return missedDetails;
})();
