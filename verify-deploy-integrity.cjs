const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync('index.html', 'utf8');
const failures = [];
const assert = (condition, message) => {
  if (!condition) failures.push(message);
};

assert(Buffer.byteLength(html) > 600000, '主页体积异常，可能被旧版精简副本覆盖');
assert(html.split('\n').length > 9000, '主页行数异常，可能丢失完整功能模块');

const requiredMarkers = [
  ['反馈入口', 'openFeedbackPanel()'],
  ['员工反馈历史', 'renderFeedbackHistoryList'],
  ['反馈实时刷新', "supa.channel('feedback-sync')"],
  ['双向换班发起', 'async function initiateExchange'],
  ['双向换班确认', 'async function acceptExchange'],
  ['员工绩效展示', 'function renderPerformanceView'],
  ['绩效首拉同步', 'fetchPerformancesConfig()'],
  ['绩效失败回滚', '绩效保存失败，已恢复原数据'],
  ['权威选班快照', "supa.rpc('picks_snapshot')"],
  ['每周 56 上限', 'const MAX_PER_WEEK=56'],
  ['单日不限口径', 'function dayValid(n){return n}'],
  ['提前 2 分钟打卡', 'const PUNCH_EARLY_MIN=2'],
  ['选班逐格保存队列', 'async function drainPickWriteQueue'],
  ['选班稳定按钮刷新', 'function patchPickView'],
  ['选班快照待保存保护', 'function overlayPendingPicks']
];
for (const [name, marker] of requiredMarkers) {
  assert(html.includes(marker), `${name}缺失`);
}

assert(!/if\s*\(\s*_pickBusy\s*\)/.test(html), '选班重新出现吞掉连续点击的全局忙锁');
assert(!/const\s+MAX_PER_DAY\s*=/.test(html), '重新出现每日选班上限常量');
assert(!/function\s+dayValid\s*\(n\)\s*\{\s*return\s+Math\.min/.test(html), '有效合计重新按每日上限截断');
assert(/const\s+inSW=it=>\{[^}]*start-PUNCH_EARLY_MIN\*60000/.test(html), '打卡动作解析未使用提前 2 分钟规则');

const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)]
  .map(match => match[1].trim())
  .filter(Boolean);
assert(scripts.length >= 1, '未找到内联脚本');
scripts.forEach((source, index) => {
  try {
    new vm.Script(source, { filename: `index.html:inline-script-${index + 1}` });
  } catch (error) {
    failures.push(`内联脚本 ${index + 1} 语法错误：${error.message}`);
  }
});

if (failures.length) {
  console.error('部署完整性校验失败：');
  failures.forEach(item => console.error(`- ${item}`));
  process.exit(1);
}

console.log(`部署完整性校验通过：${requiredMarkers.length} 个关键功能标记，${scripts.length} 段脚本语法正常。`);
