/**
 * 选班核心操作性能测试
 * 测试 atomicAddPick / atomicRemovePick 的响应时间
 */

(async function() {
  console.log('=== 选班核心操作测试 ===\n');

  if (!selectedMember) {
    console.error('❌ 请先选择成员');
    return;
  }

  const testDate = tdStr();
  const testMid = selectedMember.id;

  // 获取当前选班状态
  const currentPicks = (picks[testDate] && picks[testDate][testMid]) || [];
  console.log(`当前 ${testDate} 已选班次:`, currentPicks);

  // 测试 1: 添加班次
  if (state.shifts.length > 0) {
    const testShiftId = state.shifts[0].id;

    console.time('atomicAddPick');
    const addResult = await atomicAddPick(testDate, testMid, testShiftId);
    console.timeEnd('atomicAddPick');
    console.log('添加结果:', addResult ? '成功' : '失败');

    // 测试 2: 移除班次
    console.time('atomicRemovePick');
    const removeResult = await atomicRemovePick(testDate, testMid, testShiftId);
    console.timeEnd('atomicRemovePick');
    console.log('移除结果:', removeResult ? '成功' : '失败');
  }

  // 测试 3: 连续选班操作 (模拟用户快速点击)
  console.log('\n=== 连续操作测试 (10次) ===');
  const start = performance.now();

  for (let i = 0; i < 10; i++) {
    if (state.shifts[i % state.shifts.length]) {
      await atomicAddPick(testDate, testMid, state.shifts[i % state.shifts.length].id);
    }
  }

  const end = performance.now();
  const avgTime = (end - start) / 10;
  console.log(`10次连续选班平均: ${avgTime.toFixed(1)}ms/次`);
  console.log(avgTime < 100 ? '✅ 流畅' : avgTime < 300 ? '⚠️ 可接受' : '❌ 卡顿');

  // 恢复原始状态
  setMemberPick(testDate, testMid, currentPicks);
  sv('cp6', picks);
  console.log('\n已恢复原始选班状态');
})();
