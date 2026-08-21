// 快速测试：在浏览器控制台粘贴运行
// 测试选班页面渲染速度

console.time('选班渲染');
renderPickView();
console.timeEnd('选班渲染');

// 测试 picks 数据加载
console.time('picks加载');
pullPicksSelCfg(true).then(() => {
  console.timeEnd('picks加载');
  console.log('✅ 选班功能正常');
});
