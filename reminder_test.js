// 打卡提醒功能单元测试（在 JSC 中模拟浏览器环境）

var REMINDER_LEAD_MIN = 5;
var reminderTimer = null;
var reminderEnabled = false;

// 模拟环境
var window = this;
var document = { hidden: false };
var Notification = function(title, opts) {
  this.title = title;
  this.body = opts && opts.body;
};
Notification.permission = 'default';
Notification.requestPermission = function() {};

var _timers = [];
function setInterval(fn, ms) { _timers.push(fn); return _timers.length; }
function clearInterval(id) { _timers[id - 1] = null; }

var _store = {};
var localStorage = {
  getItem: function(k) { return _store[k] === undefined ? null : _store[k]; },
  setItem: function(k, v) { _store[k] = String(v); },
  removeItem: function(k) { delete _store[k]; }
};

var _toasts = [];
function showToast(msg) { _toasts.push(msg); }

var _punches = [];
function getAllPunchesForMember(mid, date) { return _punches; }

var _serverNow = new Date();
function serverDate() { return new Date(_serverNow.getTime()); }
function syncServerTime() { return Promise.resolve(); }
function tdStr() { return '2026-08-03'; }

function toM(t) {
  const [h, m] = t.split(':').map(Number);
  return h * 60 + m;
}

function shiftDateTimes(sh, dateStr) {
  const sD = new Date(dateStr + 'T' + sh.start);
  let eD = new Date(dateStr + 'T' + sh.end);
  if (eD.getTime() <= sD.getTime()) eD.setDate(eD.getDate() + 1);
  return { sD: sD, eD: eD };
}

var state = { shifts: [] };
function memberShifts(member, date) { return member.shiftIds || []; }

// ===== 从 index.html 原样复制的提醒逻辑 =====
function isReminderEnabled(){return localStorage.getItem('clockin_reminder')==='1';}
function setReminderEnabled(enabled){
  localStorage.setItem('clockin_reminder',enabled?'1':'0');
  reminderEnabled=enabled;
  if(enabled){
    requestNotificationPermission();
    startReminderTimer();
    showToast('已开启打卡提醒');
  }else{
    stopReminderTimer();
    showToast('已关闭打卡提醒');
  }
}
function requestNotificationPermission(){
  if('Notification' in window && Notification.permission!=='granted' && Notification.permission!=='denied'){
    Notification.requestPermission();
  }
}
function notifyReminder(title,body){
  let shown=false;
  if('Notification' in window && Notification.permission==='granted' && document.hidden){
    try{new Notification(title,{body});shown=true}catch(e){}
  }
  if(!shown) showToast(`${title} · ${body}`);
}
function reminderLogKey(date,sid,type){return `${date}_${sid}_${type}`;}
function reminderLog(){
  try{return JSON.parse(localStorage.getItem('clockin_reminder_log')||'{}')}catch(e){return{}}
}
function markReminded(key){
  const log=reminderLog();log[key]=Date.now();localStorage.setItem('clockin_reminder_log',JSON.stringify(log));
}
function clearOldReminderLog(){
  const log=reminderLog(),cut=Date.now()-86400000,next={};
  Object.entries(log).forEach(([k,v])=>{if(v>cut)next[k]=v});
  localStorage.setItem('clockin_reminder_log',JSON.stringify(next));
}
function stopReminderTimer(){if(reminderTimer){clearInterval(reminderTimer);reminderTimer=null}}
function startReminderTimer(){
  stopReminderTimer();
  if(!selectedMember||!isReminderEnabled())return;
  checkReminders();
  reminderTimer=setInterval(checkReminders,60000);
}
async function checkReminders(){
  if(!selectedMember||!isReminderEnabled())return;
  await syncServerTime();
  const today=tdStr();
  const punches=getAllPunchesForMember(selectedMember.id,today);
  const myShifts=state.shifts.filter(s=>s.enabled&&memberShifts(selectedMember,today).includes(s.id));
  const now=serverDate();
  const leadMs=REMINDER_LEAD_MIN*60000;
  clearOldReminderLog();
  const log=reminderLog();
  for(const sh of myShifts){
    const {sD,eD}=shiftDateTimes(sh,today);
    const startKey=reminderLogKey(today,sh.id,'s');
    if(!punches.find(p=>p.sid===sh.id&&p.t==='s') && now.getTime()>=sD.getTime()-leadMs && now.getTime()<=sD.getTime() && !log[startKey]){
      notifyReminder('⏰ 即将开始上班',`${sh.name} 还有 ${REMINDER_LEAD_MIN} 分钟开始，请准备打上班卡`);
      markReminded(startKey);
    }
    const endKey=reminderLogKey(today,sh.id,'e');
    if(!punches.find(p=>p.sid===sh.id&&p.t==='e') && now.getTime()>=eD.getTime()-leadMs && now.getTime()<=eD.getTime() && !log[endKey]){
      notifyReminder('⏰ 即将下班',`${sh.name} 还有 ${REMINDER_LEAD_MIN} 分钟结束，请准备打下班卡`);
      markReminded(endKey);
    }
  }
}

// ===== 测试数据 =====
var selectedMember = { id: 1, name: '测试员', shiftIds: [101] };
state.shifts = [{ id: 101, name: '早班', start: '09:00', end: '17:00', enabled: true }];

function setTime(h, m) {
  _serverNow = new Date('2026-08-03T' + (h < 10 ? '0' + h : h) + ':' + (m < 10 ? '0' + m : m) + ':00');
}

function assert(cond, msg) {
  if (!cond) throw new Error('ASSERT FAIL: ' + msg);
  print('PASS: ' + msg);
}

function lastToast() { return _toasts[_toasts.length - 1]; }

async function runTests() {
  // 开启提醒
  setReminderEnabled(true);
  assert(isReminderEnabled() === true, '提醒开关可以开启');

  // 1. 上班前 5 分钟内，未打上班卡 -> 提醒
  _toasts = []; _punches = [];
  _store['clockin_reminder_log'] = '{}';
  setTime(8, 57);
  await checkReminders();
  assert(_toasts.length === 1 && lastToast().indexOf('即将开始上班') !== -1, '上班前5分钟且未打卡时弹出上班提醒');

  // 2. 已经打过上班卡 -> 不重复提醒
  _toasts = [];
  _punches = [{ sid: 101, t: 's', time: '08:59' }];
  setTime(8, 57);
  await checkReminders();
  assert(_toasts.length === 0, '已打上班卡时不再提醒上班');

  // 3. 上班时间已过后 -> 不提醒
  _toasts = []; _punches = [];
  _store['clockin_reminder_log'] = '{}';
  setTime(9, 10);
  await checkReminders();
  assert(_toasts.length === 0, '上班时间过后不在提醒窗口内');

  // 4. 下班前 5 分钟内，未打下班卡 -> 提醒
  _toasts = []; _punches = [{ sid: 101, t: 's', time: '09:00' }];
  _store['clockin_reminder_log'] = '{}';
  setTime(16, 57);
  await checkReminders();
  assert(_toasts.length === 1 && lastToast().indexOf('即将下班') !== -1, '下班前5分钟且未打卡时弹出下班提醒');

  // 5. 已经提醒过 -> 不重复提醒
  _toasts = [];
  setTime(16, 58);
  await checkReminders();
  assert(_toasts.length === 0, '同一天同一班次已提醒过不再重复');

  // 6. 关闭提醒 -> 定时器停止，checkReminders 不再触发
  _toasts = [];
  _store['clockin_reminder_log'] = '{}';
  setReminderEnabled(false);
  setTime(8, 57);
  _punches = [];
  await checkReminders();
  var hasReminderToast = _toasts.some(function(t){ return t.indexOf('即将') !== -1; });
  assert(!hasReminderToast, '关闭提醒后不再触发上班/下班提醒');

  print('\n全部测试通过 ✅');
}

runTests().catch(function(e) {
  print('TEST ERROR: ' + e.message);
  print(e.stack);
});
