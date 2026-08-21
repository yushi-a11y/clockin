/**
 * 选班功能性能测试脚本
 * 在浏览器控制台中运行此脚本，测试选班流程的流畅度
 */

(function() {
  console.log('=== 选班功能性能测试 ===');
  console.log('测试时间:', new Date().toLocaleString('zh-CN'));
  console.log('');

  const results = [];

  // 测试 1: renderPickView 渲染性能
  function testRenderPickView() {
    return new Promise(resolve => {
      const start = performance.now();
      renderPickView();
      const end = performance.now();
      const duration = end - start;
      results.push({
        name: '选班页面渲染 (renderPickView)',
        duration: duration.toFixed(1),
        unit: 'ms',
        status: duration < 100 ? '优秀' : duration < 300 ? '良好' : '需优化'
      });
      console.log(`✓ 选班页面渲染: ${duration.toFixed(1)}ms [${results[results.length-1].status}]`);
      resolve();
    });
  }

  // 测试 2: slotCount 计算性能
  function testSlotCount() {
    return new Promise(resolve => {
      const en = enabledShiftsSorted();
      const curWs = weekStartOf(new Date());
      const days = weekDaysArr(curWs);
      const start = performance.now();

      // 模拟 renderPickView 中的 slotCount 预计算
      const slotCountCache = {};
      days.forEach(dObj => {
        const dStr = ymd(dObj);
        slotCountCache[dStr] = {};
        en.forEach(sh => {
          slotCountCache[dStr][sh.id] = slotCount(dStr, sh.id, selectedMember ? selectedMember.id : null);
        });
      });

      const end = performance.now();
      const duration = end - start;
      results.push({
        name: 'slotCount 预计算 (7天×N班次)',
        duration: duration.toFixed(1),
        unit: 'ms',
        status: duration < 50 ? '优秀' : duration < 150 ? '良好' : '需优化'
      });
      console.log(`✓ slotCount 预计算: ${duration.toFixed(1)}ms [${results[results.length-1].status}]`);
      resolve();
    });
  }

  // 测试 3: picks 数据加载性能 (pullPicksSelCfg)
  async function testPicksLoad() {
    const start = performance.now();
    await pullPicksSelCfg(true);
    const end = performance.now();
    const duration = end - start;
    results.push({
      name: 'picks 数据加载 (pullPicksSelCfg)',
      duration: duration.toFixed(1),
      unit: 'ms',
      status: duration < 500 ? '优秀' : duration < 1000 ? '良好' : '需优化'
    });
    console.log(`✓ picks 数据加载: ${duration.toFixed(1)}ms [${results[results.length-1].status}]`);
  }

  // 测试 4: 本地选班写入性能 (setMemberPick)
  function testLocalPickWrite() {
    return new Promise(resolve => {
      const testDate = tdStr();
      const testMid = selectedMember ? selectedMember.id : 1;
      const testSids = [1, 2, 3];

      const start = performance.now();
      // 模拟连续 10 次选班操作
      for (let i = 0; i < 10; i++) {
        setMemberPick(testDate, testMid, testSids);
      }
      const end = performance.now();
      const duration = end - start;
      const avgDuration = duration / 10;

      results.push({
        name: '本地选班写入 (10次 setMemberPick 平均)',
        duration: avgDuration.toFixed(2),
        unit: 'ms/次',
        status: avgDuration < 1 ? '优秀' : avgDuration < 5 ? '良好' : '需优化'
      });
      console.log(`✓ 本地选班写入: ${avgDuration.toFixed(2)}ms/次 [${results[results.length-1].status}]`);
      resolve();
    });
  }

  // 测试 5: 完整选班流程 (渲染 + 数据加载)
  async function testFullFlow() {
    const start = performance.now();
    await pullPicksSelCfg(true);
    renderPickView();
    const end = performance.now();
    const duration = end - start;
    results.push({
      name: '完整选班流程 (加载+渲染)',
      duration: duration.toFixed(1),
      unit: 'ms',
      status: duration < 600 ? '优秀' : duration < 1200 ? '良好' : '需优化'
    });
    console.log(`✓ 完整选班流程: ${duration.toFixed(1)}ms [${results[results.length-1].status}]`);
  }

  // 运行所有测试
  async function runAllTests() {
    console.log('开始测试...\n');

    await testSlotCount();
    await testLocalPickWrite();
    await testRenderPickView();
    await testPicksLoad();
    await testFullFlow();

    console.log('\n=== 测试结果汇总 ===');
    console.table(results);

    const excellentCount = results.filter(r => r.status === '优秀').length;
    const goodCount = results.filter(r => r.status === '良好').length;
    const needOptimizeCount = results.filter(r => r.status === '需优化').length;

    console.log(`\n优秀: ${excellentCount} 项 | 良好: ${goodCount} 项 | 需优化: ${needOptimizeCount} 项`);

    if (needOptimizeCount === 0) {
      console.log('\n✅ 选班功能流畅度正常，可以正常使用！');
    } else {
      console.log('\n⚠️ 有性能需优化的项目，但基本功能不受影响');
    }

    return results;
  }

  // 启动测试
  runAllTests().catch(err => {
    console.error('测试出错:', err);
  });
})();
