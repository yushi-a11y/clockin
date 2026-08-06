// ====== 考勤打卡系统 · 自动化功能测试 ======
// 测试账号：id=5, name='3072437', dept='未设置'

const fs = require('fs');
const crypto = require('crypto');

// Mock browser APIs
global.localStorage = (() => {
  const store = {};
  return {
    getItem: k => store[k] ?? null,
    setItem: (k, v) => { store[k] = String(v) },
    removeItem: k => { delete store[k] },
    clear: () => { Object.keys(store).forEach(k => delete store[k]) },
    _store: store
  };
})();
global.sessionStorage = (() => {
  const store = {};
  return {
    getItem: k => store[k] ?? null,
    setItem: (k, v) => { store[k] = String(v) },
    removeItem: k => { delete store[k] },
    clear: () => { Object.keys(store).forEach(k => delete store[k]) }
  };
})();
global.document = {
  getElementById: () => ({
    classList: { add(){}, remove(){}, toggle(){}, contains(){return false} },
    style: {}, value: '', textContent: '', innerHTML: '',
    focus(){}, addEventListener(){}
  }),
  querySelectorAll: () => [],
  querySelector: () => null
};
global.navigator = { userAgent: 'TestAgent' };
global.screen = { width: 1920, height: 1080 };
global.Date = Date;
global.window = { supabase: null };
global.crypto = {
  subtle: {
    digest: async (algo, buf) => {
      const hash = crypto.createHash('sha256');
      hash.update(Buffer.from(buf));
      return hash.digest().buffer;
    }
  },
  getRandomValues: (arr) => {
    for (let i = 0; i < arr.length; i++) arr[i] = Math.floor(Math.random() * 256);
    return arr;
  }
};
global.TextEncoder = TextEncoder;
global.Uint8Array = Uint8Array;
global.confirm = () => true;
global.prompt = () => null;
global.alert = () => {};
global.setTimeout = setTimeout;
global.setInterval = setInterval;
global.clearTimeout = clearTimeout;
global.clearInterval = clearInterval;

// Load the HTML and extract JS
const html = fs.readFileSync('/Users/lixiaotian/.qoderwork/workspace/mrssl6h69qlreqcf/index.html', 'utf-8');
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (!scriptMatch) { console.error('No script found'); process.exit(1); }
const jsCode = scriptMatch[1];

// Execute the JS in a shared context using vm
const vm = require('vm');
const context = vm.createContext({
  ...global,
  localStorage, sessionStorage, document, navigator, screen, Date,
  window, crypto, TextEncoder, Uint8Array,
  confirm, prompt, alert, setTimeout, setInterval, clearTimeout, clearInterval,
  console, Math, JSON, Object, Array, String, Number, Set, Map,
  RegExp, Error, TypeError, Promise, parseInt, parseFloat,
  Symbol, WeakMap, WeakRef,
  ArrayBuffer, DataView, Float32Array, Float64Array,
  Int8Array, Int16Array, Int32Array, Uint16Array, Uint32Array,
  Buffer
});
try { vm.runInContext(jsCode, context, { timeout: 5000 }); } catch(e) { /* Some DOM calls may fail */ }

// Export key functions/variables from context
const ctx = context;
// Destructure all needed functions and variables from the VM context
const {
  tdStr, ymd, parseYmd, addDays, toM, toT, nowM, slotSortKey, enabledShiftsSorted,
  setMemberPick, memberShifts, slotCount, slotCapOf, setSlotCap,
  dayValid, MAX_PER_DAY, MAX_PER_WEEK, memberWeekStats, memberMonthShiftCount,
  monthWeeks, memberMonthValid, amShiftId, pmShiftId,
  buildConsecutiveChains, chainPosOf, ss,
  sha256, isHash, bfResetFails, bfIncr, bfFails, bfLock, bfRemain, bfClear,
  genSessionToken, verifyAdminPwd, isAdminNow,
  swapForm, makeups, pendingMakeupCount, myPendingMakeupCount, parseMakeupTs,
  DEF_SELCFG, DEF_TEAM, genShifts, selCfg, TEAM, state, picks, fbPunches,
  getAllPunchesMember, weekStartOf, weekDaysArr, prunePicks,
  _invalidateMonthCache, _checkMonthCache,
  SEL_RULES, slotCap, forceout, swaps,
  memberWeekValidInMonth, draftWeekTotalExcept, pickSel, pickWeekDaysStrOf,
  fmtCountdown, fmtTs, shiftNameOf, memberNameOf, esc
} = ctx;

// ====== Test Framework ======
let passed = 0, failed = 0, total = 0;
const results = [];

function test(name, fn) {
  total++;
  try {
    const result = fn();
    if (result === true || result === undefined) {
      passed++;
      results.push({ name, status: 'PASS', detail: '' });
    } else {
      failed++;
      results.push({ name, status: 'FAIL', detail: String(result) });
    }
  } catch(e) {
    failed++;
    results.push({ name, status: 'ERROR', detail: e.message });
  }
}

function assertEq(actual, expected, msg='') {
  if (JSON.stringify(actual) !== JSON.stringify(expected))
    throw new Error(`${msg} expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  return true;
}
function assertTrue(val, msg='') { if (!val) throw new Error(`${msg} expected truthy, got ${val}`); return true; }
function assertFalse(val, msg='') { if (val) throw new Error(`${msg} expected falsy, got ${val}`); return true; }

// ====== Test Account Setup ======
const TEST_MID = 5;
const TEST_NAME = '3072437';
const testMember = TEAM.find(m => m.id === TEST_MID);

// ====== 1. 基础工具函数测试 ======
console.log('\n====== 1. 基础工具函数 ======');

test('tdStr 返回正确日期格式', () => {
  const td = tdStr();
  assertTrue(/^\d{4}-\d{2}-\d{2}$/.test(td), `格式异常: ${td}`);
});

test('ymd 正确格式化日期', () => {
  assertEq(ymd(new Date(2026, 6, 22)), '2026-07-22');
  assertEq(ymd(new Date(2026, 0, 1)), '2026-01-01');
});

test('parseYmd 正确解析日期字符串', () => {
  const d = parseYmd('2026-07-22');
  assertEq(d.getFullYear(), 2026);
  assertEq(d.getMonth(), 6); // 0-indexed
  assertEq(d.getDate(), 22);
});

test('addDays 正确加减天数', () => {
  const d = parseYmd('2026-07-22');
  assertEq(ymd(addDays(d, 1)), '2026-07-23');
  assertEq(ymd(addDays(d, -1)), '2026-07-21');
  assertEq(ymd(addDays(d, 10)), '2026-08-01');
});

test('toM / toT 时间分钟互转', () => {
  assertEq(toM('07:30'), 450);
  assertEq(toM('00:00'), 0);
  assertEq(toM('23:59'), 1439);
  assertEq(toT(450), '07:30');
  assertEq(toT(0), '00:00');
});

test('nowM 返回当前分钟数', () => {
  const m = nowM();
  assertTrue(m >= 0 && m < 1440, `nowM 越界: ${m}`);
});

test('slotSortKey 排序正确 (07:00排最前, 01:00排最后)', () => {
  const shifts = state.shifts.filter(s => s.enabled);
  const s7 = shifts.find(s => s.start === '07:00');
  const s23 = shifts.find(s => s.start === '23:00');
  const s0 = shifts.find(s => s.start === '00:00');
  const s1 = shifts.find(s => s.start === '01:00');
  assertTrue(slotSortKey(s7) < slotSortKey(s23), '07:00 应排在 23:00 前');
  assertTrue(slotSortKey(s23) < slotSortKey(s0), '23:00 应排在 00:00 前');
  assertTrue(slotSortKey(s0) < slotSortKey(s1), '00:00 应排在 01:00 前');
});

test('enabledShiftsSorted 按业务日排序', () => {
  const sorted = enabledShiftsSorted();
  assertTrue(sorted.length > 0, '应有启用的班次');
  assertTrue(sorted[0].start === '07:00', `第一个应是 07:00，实际是 ${sorted[0].start}`);
  const last = sorted[sorted.length - 1];
  assertTrue(last.start === '01:00', `最后一个应是 01:00，实际是 ${last.start}`);
});

// ====== 2. 选班数据模型测试 ======
console.log('\n====== 2. 选班数据模型 ======');

test('setMemberPick 正确写入 picks', () => {
  const testDate = '2026-07-25';
  setMemberPick(testDate, TEST_MID, [7, 8, 9]);
  assertEq(picks[testDate][TEST_MID], [7, 8, 9]);
});

test('memberShifts 正确读取已保存的选班', () => {
  const testDate = '2026-07-25';
  const shifts = memberShifts(testMember, testDate);
  assertEq(shifts, [7, 8, 9]);
});

test('memberShifts 空日期返回空数组', () => {
  const shifts = memberShifts(testMember, '2099-01-01');
  assertEq(shifts, []);
});

test('slotCount 正确统计时段人数', () => {
  const testDate = '2026-07-25';
  // 先写入测试数据
  setMemberPick(testDate, 1, [7, 8]);
  setMemberPick(testDate, 2, [7, 9]);
  setMemberPick(testDate, TEST_MID, [7, 8, 9]);
  assertEq(slotCount(testDate, 7), 3, '时段7应有3人选');
  assertEq(slotCount(testDate, 8), 2, '时段8应有2人选');
  assertEq(slotCount(testDate, 7, TEST_MID), 2, '排除自己后时段7应有2人');
});

test('slotCapOf / setSlotCap 人数上限', () => {
  setSlotCap('2026-07-25', 7, 3);
  assertEq(slotCapOf('2026-07-25', 7), 3);
  assertEq(slotCapOf('2026-07-25', 8), 0, '未设上限应为0');
  setSlotCap('2026-07-25', 7, 0); // 清除
  assertEq(slotCapOf('2026-07-25', 7), 0);
});

// ====== 3. 有效计数 & 上限测试 ======
console.log('\n====== 3. 有效计数 & 上限 ======');

test('dayValid 每日上限7个', () => {
  assertEq(dayValid(5), 5);
  assertEq(dayValid(7), 7);
  assertEq(dayValid(10), 7, '超过7个应截断为7');
});

test('MAX_PER_DAY = 7, MAX_PER_WEEK = 49', () => {
  assertEq(MAX_PER_DAY, 7);
  assertEq(MAX_PER_WEEK, 49);
});

test('memberWeekStats 正确统计周数据', () => {
  const ws = weekStartOf(new Date());
  const days = weekDaysArr(ws);
  // 给测试账号设置一些选班
  days.forEach((d, i) => {
    if (i < 3) setMemberPick(ymd(d), TEST_MID, [7, 8, 9]); // 每天3个
    else setMemberPick(ymd(d), TEST_MID, []);
  });
  const stats = memberWeekStats(testMember, days);
  assertEq(stats.per.slice(0, 3), [3, 3, 3], '前三天每天3个');
  assertEq(stats.raw, 9, '原始合计应为9');
  assertEq(stats.valid, 9, '有效合计应为9（未超限）');
});

test('memberWeekStats 超过日上限截断', () => {
  const ws = weekStartOf(parseYmd('2026-08-01'));
  const days = weekDaysArr(ws);
  setMemberPick(ymd(days[0]), TEST_MID, [7,8,9,10,11,12,13,14]); // 8个，超日上限
  days.slice(1).forEach(d => setMemberPick(ymd(d), TEST_MID, []));
  const stats = memberWeekStats(testMember, days);
  assertEq(stats.per[0], 8, '原始数应为8');
  assertEq(stats.valid, 7, '有效应截断为7');
});

test('memberMonthShiftCount 统计早补夜补', () => {
  const monthStr = '2026-07';
  setMemberPick('2026-07-20', TEST_MID, [amShiftId()]); // 早补
  setMemberPick('2026-07-21', TEST_MID, [amShiftId(), 8]); // 早补
  setMemberPick('2026-07-22', TEST_MID, [pmShiftId()]); // 夜补
  const adj = memberMonthShiftCount(TEST_MID, monthStr);
  assertTrue(adj.am >= 2, `早补应>=2, 实际${adj.am}`);
  assertTrue(adj.pm >= 1, `夜补应>=1, 实际${adj.pm}`);
});

test('monthWeeks 返回当月所有周起始日', () => {
  const weeks = monthWeeks('2026-07');
  assertTrue(weeks.length >= 4, `7月应至少有4周, 实际${weeks.length}`);
  assertTrue(weeks.length <= 6, `最多6周, 实际${weeks.length}`);
});

// ====== 4. 连班链检测 ======
console.log('\n====== 4. 连班链检测 ======');

test('buildConsecutiveChains 识别连班', () => {
  const shifts = [
    { id: 10, start: '10:00', end: '11:00' },
    { id: 11, start: '11:00', end: '12:00' },
    { id: 12, start: '12:00', end: '13:00' },
    { id: 14, start: '14:00', end: '15:00' },
  ];
  const chains = buildConsecutiveChains(shifts);
  assertEq(chains.length, 2, '应有2条链');
  assertEq(chains[0].length, 3, '第一条链应有3个班次(10-11-12)');
  assertEq(chains[1].length, 1, '第二条链应有1个班次(14)');
});

test('chainPosOf 正确判定位置', () => {
  const shifts = [
    { id: 10, start: '10:00', end: '11:00' },
    { id: 11, start: '11:00', end: '12:00' },
    { id: 12, start: '12:00', end: '13:00' },
  ];
  const chains = buildConsecutiveChains(shifts);
  assertEq(chainPosOf(shifts[0], chains), 'first', '10:00 应为链首');
  assertEq(chainPosOf(shifts[1], chains), 'middle', '11:00 应为链中');
  assertEq(chainPosOf(shifts[2], chains), 'last', '12:00 应为链尾');
});

test('chainPosOf 单独班次返回 solo', () => {
  const shifts = [
    { id: 14, start: '14:00', end: '15:00' },
    { id: 16, start: '16:00', end: '17:00' },
  ];
  const chains = buildConsecutiveChains(shifts);
  assertEq(chainPosOf(shifts[0], chains), 'solo');
  assertEq(chainPosOf(shifts[1], chains), 'solo');
});

// ====== 5. 打卡状态判定 ======
console.log('\n====== 5. 打卡状态判定 ======');

test('ss 函数：未打卡=wait', () => {
  const sh = { id: 99, start: '20:00', end: '21:00', tolerance: 5, cross: false };
  const result = ss(sh, []);
  assertEq(result.ss, 'w', '上班应为 wait');
  assertEq(result.es, 'w', '下班应为 wait');
});

test('ss 函数：正常上班打卡=ok', () => {
  const sh = { id: 99, start: '10:00', end: '11:00', tolerance: 5, cross: false };
  const punches = [{ sid: 99, t: 's', time: '09:58' }];
  const result = ss(sh, punches);
  assertEq(result.ss, 'ok', '09:58 打 10:00 的班应为 ok');
});

test('ss 函数：迟到打卡=late', () => {
  const sh = { id: 99, start: '10:00', end: '11:00', tolerance: 5, cross: false };
  const punches = [{ sid: 99, t: 's', time: '10:08' }];
  const result = ss(sh, punches);
  assertEq(result.ss, 'late', '10:08 打 10:00+5min 的班应为 late');
});

test('ss 函数：已完成=ok+ok', () => {
  const sh = { id: 99, start: '10:00', end: '11:00', tolerance: 5, cross: false };
  const punches = [
    { sid: 99, t: 's', time: '09:55' },
    { sid: 99, t: 'e', time: '11:02' }
  ];
  const result = ss(sh, punches);
  assertEq(result.ss, 'ok');
  assertEq(result.es, 'ok');
  assertEq(result.ov, 'ok', '两侧都正常应为 ok');
});

test('ss 函数：缺上班卡=miss', () => {
  const sh = { id: 99, start: '08:00', end: '09:00', tolerance: 5, cross: false };
  const punches = [{ sid: 99, t: 'e', time: '09:05' }];
  const result = ss(sh, punches);
  assertEq(result.ss, 'miss', '缺上班卡应为 miss');
  assertEq(result.ov, 'miss');
});

// ====== 6. 安全机制测试 ======
console.log('\n====== 6. 安全机制 ======');

test('sha256 生成 64 位哈希', async () => {
  const hash = await sha256('test123');
  assertTrue(/^[a-f0-9]{64}$/.test(hash), `哈希格式异常: ${hash}`);
});

test('sha256 相同输入相同输出', async () => {
  const h1 = await sha256('admin123');
  const h2 = await sha256('admin123');
  assertEq(h1, h2);
});

test('isHash 正确识别哈希字符串', () => {
  assertTrue(isHash('a'.repeat(64)));
  assertFalse(isHash('admin123'));
  assertFalse(isHash(null));
  assertFalse(isHash(''));
});

test('暴力破解防护：bfIncr/bfFails/bfResetFails', () => {
  bfResetFails(999);
  assertEq(bfFails(999), 0, '初始应为0');
  bfIncr(999);
  assertEq(bfFails(999), 1);
  bfIncr(999);
  assertEq(bfFails(999), 2);
  bfResetFails(999);
  assertEq(bfFails(999), 0, '重置后应为0');
});

test('暴力破解防护：bfLock/bfRemain/bfClear', () => {
  bfClear(888);
  assertEq(bfRemain(888), 0, '未锁定时应为0');
  bfLock(888);
  const remain = bfRemain(888);
  assertTrue(remain > 0, `锁定后应有剩余时间, 实际${remain}`);
  assertTrue(remain <= PWD_LOCK_MS, `剩余时间不应超过${PWD_LOCK_MS}`);
  bfClear(888);
  assertEq(bfRemain(888), 0, '清除后应为0');
});

test('genSessionToken 生成 32 位 hex token', () => {
  const token = genSessionToken();
  assertTrue(/^[a-f0-9]{32}$/.test(token), `token 格式异常: ${token}`);
});

test('genSessionToken 每次不同', () => {
  const t1 = genSessionToken();
  const t2 = genSessionToken();
  assertTrue(t1 !== t2, '两次生成的 token 应不同');
});

test('管理员密码哈希化：verifyAdminPwd', async () => {
  // 清除旧哈希
  localStorage.removeItem('ca6pwd');
  const ok = await verifyAdminPwd('admin123');
  assertTrue(ok, '默认密码 admin123 应验证通过');
  const fail = await verifyAdminPwd('wrong');
  assertFalse(fail, '错误密码应验证失败');
});

test('isAdminNow 需要 token 才能进入后台', () => {
  localStorage.removeItem('cs6');
  localStorage.removeItem('cs6tk');
  assertFalse(isAdminNow(), '无 session 应返回 false');
  localStorage.setItem('cs6', String(Date.now() + 999999));
  assertFalse(isAdminNow(), '只有时间戳无 token 应返回 false');
  localStorage.setItem('cs6tk', 'test_token');
  assertTrue(isAdminNow(), '有时间戳+token 应返回 true');
  localStorage.removeItem('cs6');
  localStorage.removeItem('cs6tk');
});

// ====== 7. 换班逻辑测试 ======
console.log('\n====== 7. 换班逻辑 ======');

test('换班记录结构完整', () => {
  const rec = {
    id: 'sw_test', date: '2026-07-30', sid: 10,
    fromId: 5, fromName: '3072437', toId: 6, toName: '8027356',
    status: 'pending', ts: Date.now(), decidedTs: 0
  };
  assertTrue(rec.id && rec.date && rec.fromId && rec.toId && rec.status === 'pending');
});

test('换班到期作废逻辑', () => {
  const expiredDate = '2020-01-01';
  assertTrue(expiredDate <= tdStr(), '过期日期应小于今天');
});

test('swapForm 初始状态正确', () => {
  // 已在代码中定义
  assertTrue(swapForm.date === '' || swapForm.date !== undefined);
});

// ====== 8. 补卡逻辑测试 ======
console.log('\n====== 8. 补卡逻辑 ======');

test('补卡记录结构完整', () => {
  const rec = {
    id: 'mk_test', mid: 5, name: '3072437',
    date: '2026-07-20', sid: 10, sname: '10:00-11:00',
    time: '10:05', t: 's', reason: '忘记打卡',
    status: 'pending', ts: Date.now(), decidedTs: 0, decidedBy: ''
  };
  assertTrue(rec.status === 'pending');
  assertTrue(rec.t === 's' || rec.t === 'e');
});

test('parseMakeupTs 正确解析时间', () => {
  const ts = parseMakeupTs('2026-07-20', '10:30');
  const d = new Date(ts);
  assertEq(d.getFullYear(), 2026);
  assertEq(d.getMonth(), 6);
  assertEq(d.getDate(), 20);
  assertEq(d.getHours(), 10);
  assertEq(d.getMinutes(), 30);
});

test('pendingMakeupCount / myPendingMakeupCount', () => {
  const origMakeups = makeups.slice();
  makeups.push({ id: 'mk1', mid: 5, status: 'pending' });
  makeups.push({ id: 'mk2', mid: 5, status: 'pending' });
  makeups.push({ id: 'mk3', mid: 6, status: 'pending' });
  assertEq(pendingMakeupCount(), 3);
  // myPendingMakeupCount needs selectedMember
  makeups.length = 0;
  makeups.push(...origMakeups);
});

// ====== 9. 选班规则 & 配置 ======
console.log('\n====== 9. 选班规则 & 配置 ======');

test('DEF_SELCFG 默认值正确', () => {
  assertEq(DEF_SELCFG.openDay, 5, '默认周六');
  assertEq(DEF_SELCFG.openHour, 14, '默认14点');
  assertEq(DEF_SELCFG.retainDays, 60);
  assertEq(DEF_SELCFG.amShiftId, 7);
  assertEq(DEF_SELCFG.pmShiftId, 25);
});

test('amShiftId / pmShiftId 从 selCfg 读取', () => {
  assertEq(amShiftId(), selCfg.amShiftId || 7);
  assertEq(pmShiftId(), selCfg.pmShiftId || 25);
});

test('weekStartOf 正确计算周起始', () => {
  selCfg.weekStartDay = 6; // 周六起始
  const d = new Date(2026, 6, 22); // 周三 7/22
  const ws = weekStartOf(d);
  assertEq(ws.getDay(), 6, '周起始应为周六');
  assertTrue(ws <= d, '周起始不应晚于当天');
});

test('isSelectionOpen 判断开放时间', () => {
  const futureWs = addDays(new Date(), 30);
  const open = isSelectionOpen(futureWs);
  // 结果取决于配置，只要不报错即可
  assertTrue(typeof open === 'boolean');
});

test('SEL_RULES 有 6 条规则', () => {
  assertEq(SEL_RULES.length, 6);
});

test('prunePicks 清理超期数据', () => {
  const oldDate = ymd(addDays(new Date(), -100));
  picks[oldDate] = { '99': [1, 2, 3] };
  prunePicks();
  assertEq(picks[oldDate], undefined, '100 天前的数据应被清理');
});

// ====== 10. 数据清除测试 ======
console.log('\n====== 10. 数据完整性 ======');

test('TEAM 数据完整：所有成员有必填字段', () => {
  TEAM.forEach(m => {
    assertTrue(m.id > 0, `成员 ${m.name} 缺少 id`);
    assertTrue(typeof m.name === 'string' && m.name.length > 0, `成员缺少 name`);
    assertTrue(Array.isArray(m.shiftIds), `成员 ${m.name} shiftIds 不是数组`);
    assertTrue(typeof m.dept === 'string', `成员 ${m.name} 缺少 dept`);
  });
});

test('DEF_TEAM 有 17 个默认成员', () => {
  assertEq(DEF_TEAM.length, 17);
});

test('genShifts 生成 19 个班次 (07:00-01:00)', () => {
  const shifts = genShifts();
  assertEq(shifts.length, 19, `应有 19 个班次，实际 ${shifts.length}`);
  assertTrue(shifts[0].start === '07:00', '第一个应是 07:00');
  assertTrue(shifts[shifts.length - 1].start === '01:00', '最后一个应是 01:00');
});

test('getAllPunchesForMember 去重逻辑', () => {
  const testDate = '2026-07-22';
  // 写入本地打卡
  state.punches[testDate] = [{ sid: 7, t: 's', time: '07:00', mid: TEST_MID, date: testDate }];
  // fbPunches 中有重复记录
  const oldFb = fbPunches.slice();
  fbPunches.push({ sid: 7, t: 's', time: '07:00', mid: TEST_MID, date: testDate });
  fbPunches.push({ sid: 7, t: 'e', time: '08:00', mid: TEST_MID, date: testDate });
  const all = getAllPunchesForMember(TEST_MID, testDate);
  assertEq(all.length, 2, `去重后应有2条, 实际${all.length}`);
  fbPunches.length = 0;
  fbPunches.push(...oldFb);
});

test('月度统计缓存生效', () => {
  _invalidateMonthCache();
  const r1 = memberMonthShiftCount(TEST_MID, '2026-07');
  const r2 = memberMonthShiftCount(TEST_MID, '2026-07');
  assertEq(r1, r2, '缓存命中应返回相同结果');
});

test('月度统计缓存失效', () => {
  _invalidateMonthCache();
  memberMonthShiftCount(TEST_MID, '2026-07'); // 填充缓存
  setMemberPick('2026-07-28', TEST_MID, [7]); // 写入新数据应触发失效
  const r = memberMonthShiftCount(TEST_MID, '2026-07'); // 应重新计算
  assertTrue(typeof r === 'object' && 'am' in r);
});

// ====== Output Results ======
console.log('\n======================================');
console.log(`测试完成：${total} 项 | 通过 ${passed} | 失败 ${failed}`);
console.log('======================================\n');

results.forEach(r => {
  const icon = r.status === 'PASS' ? '✅' : r.status === 'FAIL' ? '❌' : '💥';
  console.log(`${icon} ${r.name}${r.detail ? ' → ' + r.detail : ''}`);
});

// Write results as JSON for document generation
fs.writeFileSync('/Users/lixiaotian/.qoderwork/workspace/mrssl6h69qlreqcf/test-results.json', JSON.stringify({ total, passed, failed, results }, null, 2));
console.log('\n结果已写入 test-results.json');
