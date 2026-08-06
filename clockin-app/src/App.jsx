import { useState, useEffect, useCallback, useRef } from 'react'
import * as XLSX from 'xlsx'

const STORAGE_KEY = 'clockin_data_v2'
const DEFAULT_SHIFTS = [
  { id: 1, name: '早班', start: '08:00', end: '12:00', tolerance: 5, enabled: true },
  { id: 2, name: '午班', start: '13:00', end: '17:00', tolerance: 5, enabled: true },
  { id: 3, name: '晚班', start: '18:00', end: '21:00', tolerance: 10, enabled: true },
  { id: 4, name: '夜班', start: '22:00', end: '06:00', tolerance: 15, enabled: false }
]
const TEAM = [
  { id: 1, name: '李思远', dept: '产品研发部' },
  { id: 2, name: '王晓峰', dept: '市场运营部' },
  { id: 3, name: '陈雨晴', dept: '设计部' },
  { id: 4, name: '赵子涵', dept: '客户服务部' },
  { id: 5, name: '刘佳欣', dept: '人力资源部' },
  { id: 6, name: '张明远', dept: '产品研发部' },
  { id: 7, name: '孙浩然', dept: '财务部' },
  { id: 8, name: '周雨桐', dept: '市场运营部' }
]
const AVATAR_COLORS = [
  { bg: '#dbeafe', fg: '#2563eb' }, { bg: '#fce7f3', fg: '#db2777' },
  { bg: '#dcfce7', fg: '#16a34a' }, { bg: '#fef3c7', fg: '#d97706' },
  { bg: '#f1f5f9', fg: '#64748b' }, { bg: '#dbeafe', fg: '#2563eb' },
  { bg: '#ccfbf1', fg: '#0d9488' }, { bg: '#fce7f3', fg: '#db2777' }
]

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) { const d = JSON.parse(raw); if (d.shifts && d.punches) return d }
  } catch (e) {}
  return { shifts: JSON.parse(JSON.stringify(DEFAULT_SHIFTS)), punches: {}, settings: { autoMark: true, notify: true } }
}
function saveState(s) { localStorage.setItem(STORAGE_KEY, JSON.stringify(s)) }
function todayStr() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}` }
function nowMin() { const d = new Date(); return d.getHours() * 60 + d.getMinutes() }
function toMin(t) { const [h, m] = t.split(':').map(Number); return h * 60 + m }
function toTime(m) { m = ((m % 1440) + 1440) % 1440; return `${String(Math.floor(m/60)).padStart(2,'0')}:${String(m%60).padStart(2,'0')}` }
function fmtDate(s) { const d = new Date(s + 'T00:00:00'); const w = ['日','一','二','三','四','五','六']; return `${d.getMonth()+1}月${d.getDate()}日 周${w[d.getDay()]}` }
function greet() { const h = new Date().getHours(); return h < 6 ? '夜深了' : h < 12 ? '早上好' : h < 14 ? '中午好' : h < 18 ? '下午好' : '晚上好' }

function shiftStatus(shift, punches) {
  const now = nowMin(), sMin = toMin(shift.start), eMin = toMin(shift.end)
  const cross = eMin < sMin
  const started = cross ? (now >= sMin || now < eMin) : now >= sMin
  const ended = cross ? (now >= eMin && now < sMin) : now >= eMin
  const sp = punches.find(p => p.shiftId === shift.id && p.type === 'start')
  const ep = punches.find(p => p.shiftId === shift.id && p.type === 'end')
  let ss = 'wait', es = 'wait'
  if (sp) { ss = toMin(sp.time) <= sMin + shift.tolerance ? 'ok' : 'late' }
  else if (ended) ss = 'miss'
  if (ep) es = 'ok'
  else if (ended) es = 'miss'
  let ov = 'wait'
  if (ss === 'ok' && es === 'ok') ov = 'ok'
  else if (ss === 'miss' || es === 'miss') ov = 'miss'
  else if (ss === 'late') ov = 'warn'
  else if (ss === 'ok' && es === 'wait') ov = 'active'
  return { ss, es, ov, started, ended, sp, ep, cross }
}

function mockPunches(memberId, shifts) {
  const now = nowMin(), mock = []
  shifts.filter(s => s.enabled).forEach(shift => {
    const seed = (memberId * 7 + shift.id * 13) % 100, sMin = toMin(shift.start), eMin = toMin(shift.end)
    if (now > sMin) mock.push({ shiftId: shift.id, type: 'start', time: toTime(sMin + seed % 8 - 2) })
    if (now > eMin) mock.push({ shiftId: shift.id, type: 'end', time: toTime(eMin + (seed * 3) % 6 - 1) })
  })
  return mock
}

// Icons
const ClockIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="9"/><polyline points="12 9 12 12 14.5 14.5"/></svg>
const CheckIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
const XIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
const WarnIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
const DocIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
const UserIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
const UploadIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
const DownloadIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
const GridIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
const TeamIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
const GearIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
const BarIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>

export default function App() {
  const [state, setState] = useState(loadState)
  const [view, setView] = useState('mobile')
  const [mobileTab, setMobileTab] = useState('clock')
  const [adminPanel, setAdminPanel] = useState('overview')
  const [now, setNow] = useState(new Date())
  const [toast, setToast] = useState('')
  const [pendingImport, setPendingImport] = useState(null)
  const [search, setSearch] = useState('')
  const fileRef = useRef(null)

  const update = useCallback(fn => {
    setState(prev => { const next = typeof fn === 'function' ? fn(prev) : fn; saveState(next); return next })
  }, [])

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(''), 2500) }
  const today = todayStr()
  const todayPunches = state.punches[today] || []
  const enabled = state.shifts.filter(s => s.enabled)

  // Next action
  const getNext = () => {
    for (const shift of enabled) {
      const st = shiftStatus(shift, todayPunches)
      if (!st.started && toMin(shift.start) - 15 <= nowMin()) return { shift, type: 'start', label: '上班打卡', hint: `${shift.name} · ${shift.start} 开始` }
      if (st.ss === 'ok' && st.es === 'wait') return { shift, type: 'end', label: '下班打卡', hint: `${shift.name} · ${shift.end} 结束` }
      if (st.ss === 'wait' && st.started) return { shift, type: 'start', label: '上班打卡（迟到）', hint: `${shift.name} · 已迟到` }
    }
    return null
  }
  const action = getNext()

  const doPunch = () => {
    if (!action) return
    const n = new Date(), time = `${String(n.getHours()).padStart(2,'0')}:${String(n.getMinutes()).padStart(2,'0')}`
    update(s => {
      const punches = { ...s.punches }
      if (!punches[today]) punches[today] = []
      punches[today] = [...punches[today], { shiftId: action.shift.id, type: action.type, time, ts: n.getTime() }]
      return { ...s, punches }
    })
    showToast(`打卡成功 · ${time}`)
  }

  // Stats
  let okC = 0, actC = 0, missC = 0
  enabled.forEach(s => { const st = shiftStatus(s, todayPunches); if (st.ov === 'ok') okC++; else if (st.ov === 'active') actC++; else if (st.ov === 'miss') missC++ })

  // Admin stats
  const adminStats = () => {
    let normal = 0, anomaly = 0
    TEAM.forEach(m => {
      const mp = m.id === 6 ? todayPunches : mockPunches(m.id, state.shifts)
      let ok = true
      enabled.forEach(s => { const st = shiftStatus(s, mp); if (st.ov === 'miss' || st.ss === 'late') ok = false })
      if (ok) normal++; else anomaly++
    })
    return { total: TEAM.length, normal, anomaly, rate: TEAM.length > 0 ? ((normal / TEAM.length) * 100).toFixed(1) : '0' }
  }
  const stats = adminStats()

  // Excel handlers
  const handleFile = (file) => {
    const reader = new FileReader()
    reader.onload = (ev) => {
      try {
        const wb = XLSX.read(new Uint8Array(ev.target.result), { type: 'array' })
        const ws = wb.Sheets[wb.SheetNames[0]]
        const json = XLSX.utils.sheet_to_json(ws, { defval: '' })
        if (!json.length) { showToast('文件为空'); return }
        const shifts = []
        json.forEach((row, i) => {
          const keys = Object.keys(row)
          let name = '', start = '', end = '', tol = 5
          keys.forEach(k => {
            const v = String(row[k]).trim(), kl = k.toLowerCase()
            if (kl.includes('名称') || kl.includes('班次') || kl.includes('name') || (!name && keys.indexOf(k) === 0)) name = v
            if (kl.includes('开始') || kl.includes('start') || kl.includes('上班')) start = v
            if (kl.includes('结束') || kl.includes('end') || kl.includes('下班')) end = v
            if (kl.includes('容差') || kl.includes('tolerance') || kl.includes('分钟')) tol = parseInt(v) || 5
          })
          if (name && start && end) {
            const clean = t => { if (typeof t === 'number') { const d = XLSX.SSF.parse_date_code(t); if (d) return `${String(d.H||0).padStart(2,'0')}:${String(d.m||0).padStart(2,'0')}` } return String(t).substring(0, 5) }
            shifts.push({ id: Date.now() + i, name, start: clean(start), end: clean(end), tolerance: tol, enabled: true })
          }
        })
        if (!shifts.length) { showToast('未识别到有效班次'); return }
        setPendingImport(shifts)
      } catch (err) { showToast('解析失败: ' + err.message) }
    }
    reader.readAsArrayBuffer(file)
  }

  const confirmImport = () => {
    if (!pendingImport?.length) return
    update(s => ({ ...s, shifts: pendingImport }))
    setPendingImport(null)
    showToast(`成功导入 ${pendingImport.length} 个班次`)
  }

  const downloadTemplate = () => {
    const wb = XLSX.utils.book_new()
    const data = [['班次名称', '开始时间', '结束时间', '容差分钟数'], ['早班', '08:00', '12:00', 5], ['午班', '13:00', '17:00', 5]]
    const ws = XLSX.utils.aoa_to_sheet(data)
    ws['!cols'] = [{ wch: 12 }, { wch: 10 }, { wch: 10 }, { wch: 12 }]
    XLSX.utils.book_append_sheet(wb, ws, '班次表')
    XLSX.writeFile(wb, '班次导入模板.xlsx')
  }

  const exportData = () => {
    const wb = XLSX.utils.book_new()
    const data = [['日期', '成员', '部门', '班次', '上班打卡', '下班打卡', '状态']]
    const dates = Object.keys(state.punches).sort().reverse()
    if (!dates.length) dates.push(today)
    dates.forEach(date => {
      TEAM.forEach(member => {
        const mp = member.id === 6 ? (state.punches[date] || []) : mockPunches(member.id, state.shifts)
        enabled.forEach(shift => {
          const sp = mp.find(p => p.shiftId === shift.id && p.type === 'start')
          const ep = mp.find(p => p.shiftId === shift.id && p.type === 'end')
          data.push([date, member.name, member.dept, shift.name, sp?.time || '', ep?.time || '', (sp && ep) ? '正常' : (!sp && !ep) ? '未打卡' : '部分打卡'])
        })
      })
    })
    const ws = XLSX.utils.aoa_to_sheet(data)
    ws['!cols'] = [{ wch: 12 }, { wch: 8 }, { wch: 12 }, { wch: 8 }, { wch: 10 }, { wch: 10 }, { wch: 8 }]
    XLSX.utils.book_append_sheet(wb, ws, '考勤报表')
    XLSX.writeFile(wb, `考勤报表_${today}.xlsx`)
    showToast('报表已导出')
  }

  const clockStr = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`
  const dateStr = `${now.getFullYear()}年${now.getMonth()+1}月${now.getDate()}日 星期${['日','一','二','三','四','五','六'][now.getDay()]}`

  return (
    <div className="app">
      {/* Top Bar */}
      <div className="topbar">
        <span className="brand">Clock<em>In</em></span>
        <button className={`top-btn ${view === 'mobile' ? 'active' : ''}`} onClick={() => setView('mobile')}>员工打卡</button>
        <button className={`top-btn ${view === 'admin' ? 'active' : ''}`} onClick={() => setView('admin')}>管理后台</button>
      </div>

      {/* Toast */}
      <div className={`toast ${toast ? 'show' : ''}`}>{toast}</div>

      {/* Mobile View */}
      {view === 'mobile' && (
        <div className="phone-wrap">
          <div className="phone">
            {mobileTab === 'clock' && (
              <>
                <header className="m-head">
                  <div><div className="greet">{greet()}</div><div className="uname">张明远</div></div>
                  <div className="avatar">张</div>
                </header>
                <section className="clock-sec">
                  <div className="clock-time">{clockStr}</div>
                  <div className="clock-date">{dateStr}</div>
                </section>
                <section className="sum-card">
                  <div className="sec-label">今日出勤</div>
                  <div className="sum-row">
                    <div className="sum-item ok"><div className="n">{okC}</div><div className="l">已完成</div></div>
                    <div className="sum-item pd"><div className="n">{actC}</div><div className="l">进行中</div></div>
                    <div className="sum-item ms"><div className="n">{missC}</div><div className="l">缺卡</div></div>
                  </div>
                </section>
                <section className="period-list">
                  <div className="sec-label">时段打卡</div>
                  {enabled.map(shift => {
                    const st = shiftStatus(shift, todayPunches)
                    const badgeMap = { ok: ['已完成', 'b-ok'], miss: ['有缺卡', 'b-miss'], warn: ['有迟到', 'b-warn'], active: ['进行中', 'b-active'], wait: ['未开始', 'b-wait'] }
                    const [bl, bc] = badgeMap[st.ov]
                    const startIcon = st.ss === 'ok' ? <CheckIcon/> : st.ss === 'miss' ? <XIcon/> : st.ss === 'late' ? <WarnIcon/> : <ClockIcon/>
                    const endIcon = st.es === 'ok' ? <CheckIcon/> : st.es === 'miss' ? <XIcon/> : <ClockIcon/>
                    const sTime = st.sp ? st.sp.time : (st.ss === 'miss' ? '缺卡' : shift.start)
                    const eTime = st.ep ? st.ep.time : (st.es === 'miss' ? '缺卡' : `待打卡 · ${shift.end}`)
                    return (
                      <div key={shift.id} className={`p-card ${st.ov === 'active' ? 'current' : ''}`}>
                        <div className="p-head">
                          <div className="p-name">{shift.name}</div>
                          <span className={`badge ${bc}`}>{bl}</span>
                        </div>
                        <div className="checks">
                          <div className={`chk ${st.ss}`}>
                            <div className="chk-icon">{startIcon}</div>
                            <div className="chk-info">
                              <div className="cl">{st.ss === 'late' ? '上班打卡 · 迟到' : '上班打卡'}</div>
                              <div className="ct">{sTime}</div>
                            </div>
                          </div>
                          <div className={`chk ${st.es}`}>
                            <div className="chk-icon">{endIcon}</div>
                            <div className="chk-info">
                              <div className="cl">下班打卡</div>
                              <div className="ct">{eTime}</div>
                            </div>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </section>
                <div className="punch-wrap">
                  {action ? (
                    <button className="punch-btn" onClick={doPunch}>{action.label}<div className="hint">{action.hint}</div></button>
                  ) : (
                    <button className="punch-btn off" disabled>暂无可打卡时段<div className="hint">所有时段已完成或未开始</div></button>
                  )}
                </div>
              </>
            )}
            {mobileTab === 'hist' && (
              <>
                <header className="m-head"><div><div className="greet">打卡记录</div><div className="uname">近30天</div></div><div className="avatar">张</div></header>
                <section className="hist-sec">
                  {Object.keys(state.punches).length === 0 ? (
                    <div className="empty-state"><DocIcon/><div className="et">暂无打卡记录</div><div className="ed">打卡后记录会自动出现</div></div>
                  ) : Object.keys(state.punches).sort().reverse().map(date => (
                    <div key={date}>
                      <div className="hist-date">{fmtDate(date)}</div>
                      {enabled.map(shift => {
                        const ps = state.punches[date] || []
                        const sp = ps.find(p => p.shiftId === shift.id && p.type === 'start')
                        const ep = ps.find(p => p.shiftId === shift.id && p.type === 'end')
                        const allOk = sp && ep, none = !sp && !ep
                        const dotC = allOk ? 'var(--success)' : none ? 'var(--muted-light)' : 'var(--warning)'
                        const stxt = allOk ? '正常' : none ? '未打卡' : '部分打卡'
                        const bc = allOk ? 'b-ok' : none ? 'b-wait' : 'b-warn'
                        return (
                          <div key={shift.id} className="hist-item">
                            <div className="hist-left">
                              <div className="hist-dot" style={{ background: dotC }}/>
                              <div><div className="hist-p">{shift.name} {shift.start} - {shift.end}</div><div className="hist-t">{sp?.time || '--:--'} / {ep?.time || '--:--'} · {stxt}</div></div>
                            </div>
                            <span className={`badge ${bc}`}>{stxt}</span>
                          </div>
                        )
                      })}
                    </div>
                  ))}
                </section>
              </>
            )}
            {mobileTab === 'me' && (
              <>
                <header className="m-head"><div><div className="greet">设置</div><div className="uname">个人偏好</div></div><div className="avatar">张</div></header>
                <div style={{ padding: 20 }}>
                  <div className="rule-card"><div className="rule-info"><div className="rule-icon muted"><UserIcon/></div><div><div className="rule-name">个人信息</div><div className="rule-desc">张明远 · 产品研发部 · 工号 A1024</div></div></div></div>
                  <div className="rule-card"><div className="rule-info"><div className="rule-icon muted"><GearIcon/></div><div><div className="rule-name">打卡提醒</div><div className="rule-desc">每个时段开始前5分钟提醒</div></div></div><Toggle defaultOn/></div>
                  <div className="rule-card"><div className="rule-info"><div className="rule-icon muted"><DownloadIcon/></div><div><div className="rule-name">数据管理</div><div className="rule-desc">清除所有本地打卡数据</div></div></div><button className="r-btn danger" onClick={() => { if (confirm('确定清除所有数据？')) { update(s => ({ ...s, punches: {} })); showToast('数据已清除') } }}>清除数据</button></div>
                </div>
              </>
            )}
          </div>
          <nav className="tabbar">
            <button className={`tbar-item ${mobileTab === 'clock' ? 'active' : ''}`} onClick={() => setMobileTab('clock')}><ClockIcon/><span>打卡</span></button>
            <button className={`tbar-item ${mobileTab === 'hist' ? 'active' : ''}`} onClick={() => setMobileTab('hist')}><DocIcon/><span>记录</span></button>
            <button className={`tbar-item ${mobileTab === 'me' ? 'active' : ''}`} onClick={() => setMobileTab('me')}><UserIcon/><span>我的</span></button>
          </nav>
        </div>
      )}

      {/* Admin View */}
      {view === 'admin' && (
        <div className="admin-layout">
          <aside className="sidebar">
            <div className="sb-brand"><div className="sb-brand-icon"><ClockIcon/></div><span>ClockIn 管理</span></div>
            <ul className="sb-nav">
              <li><a className={adminPanel === 'overview' ? 'active' : ''} onClick={() => setAdminPanel('overview')}><GridIcon/>出勤概览</a></li>
              <li><a className={adminPanel === 'detail' ? 'active' : ''} onClick={() => setAdminPanel('detail')}><TeamIcon/>团队明细</a></li>
              <li><a className={adminPanel === 'rules' ? 'active' : ''} onClick={() => setAdminPanel('rules')}><GearIcon/>规则配置</a></li>
            </ul>
            <div className="sb-sec">数据</div>
            <ul className="sb-nav">
              <li><a onClick={() => fileRef.current?.click()}><UploadIcon/>导入班次</a></li>
              <li><a onClick={exportData}><DownloadIcon/>导出报表</a></li>
            </ul>
          </aside>
          <main className="main-area">
            {adminPanel === 'overview' && (
              <>
                <div className="page-head"><h1 className="page-title">今日出勤概览</h1><div className="head-actions"><span className="btn-s">{today}</span><button className="btn-p" onClick={exportData}>导出日报</button></div></div>
                <div className="kpi-row">
                  <div className="kpi"><div className="kpi-l">应到人数</div><div className="kpi-v">{stats.total}</div><div className="kpi-d up">全员在岗</div></div>
                  <div className="kpi"><div className="kpi-l">正常出勤</div><div className="kpi-v">{stats.normal}</div><div className={`kpi-d ${stats.normal >= stats.total - 1 ? 'up' : 'down'}`}>{stats.normal >= stats.total - 1 ? '良好' : '需关注'}</div></div>
                  <div className="kpi"><div className="kpi-l">出勤率</div><div className="kpi-v">{stats.rate}%</div><div className={`kpi-d ${parseFloat(stats.rate) >= 90 ? 'up' : 'down'}`}>{parseFloat(stats.rate) >= 90 ? '达标' : '偏低'}</div></div>
                  <div className="kpi"><div className="kpi-l">异常打卡</div><div className="kpi-v">{stats.anomaly}</div><div className={`kpi-d ${stats.anomaly === 0 ? 'up' : 'down'}`}>{stats.anomaly === 0 ? '无异常' : `${stats.anomaly}人异常`}</div></div>
                </div>
                <div className="tbl-card">
                  <div className="tbl-head"><div className="tbl-title">出勤明细</div><input className="tbl-search" placeholder="搜索..." value={search} onChange={e => setSearch(e.target.value)}/></div>
                  <AttTable team={TEAM} shifts={enabled} punches={state.punches[today] || []} search={search} today={today} />
                </div>
              </>
            )}
            {adminPanel === 'detail' && (
              <>
                <div className="page-head"><h1 className="page-title">团队出勤明细</h1></div>
                <div className="tbl-card">
                  <div className="tbl-head"><div className="tbl-title">全部记录</div><input className="tbl-search" placeholder="搜索..." value={search} onChange={e => setSearch(e.target.value)}/></div>
                  <AttTable team={TEAM} shifts={enabled} punches={state.punches[today] || []} search={search} today={today} />
                </div>
              </>
            )}
            {adminPanel === 'rules' && (
              <>
                <div className="page-head"><h1 className="page-title">打卡规则配置</h1><div className="head-actions"><button className="btn-p" onClick={() => fileRef.current?.click()}>导入班次表</button></div></div>
                {state.shifts.map((shift, i) => (
                  <div key={shift.id} className="rule-card">
                    <div className="rule-info">
                      <div className="rule-icon" style={{ background: ['var(--primary-soft)', 'var(--success-soft)', 'var(--warning-soft)', 'var(--surface-alt)'][i % 4], color: ['var(--primary)', 'var(--success)', 'var(--warning)', 'var(--muted)'][i % 4] }}><ClockIcon/></div>
                      <div><div className="rule-name">{shift.name}</div><div className="rule-desc">{shift.start} — {shift.end} · 打卡2次 · 容差{shift.tolerance}分钟</div></div>
                    </div>
                    <div className="rule-actions">
                      <Toggle on={shift.enabled} onChange={() => update(s => ({ ...s, shifts: s.shifts.map(x => x.id === shift.id ? { ...x, enabled: !x.enabled } : x) }))}/>
                      <button className="r-btn" onClick={() => { if (confirm('删除此时段？')) update(s => ({ ...s, shifts: s.shifts.filter(x => x.id !== shift.id) })) }}>删除</button>
                    </div>
                  </div>
                ))}
                <div className="sec-label" style={{ margin: '20px 0 12px' }}>全局设置</div>
                <div className="rule-card"><div className="rule-info"><div className="rule-icon muted"><GearIcon/></div><div><div className="rule-name">缺卡自动标记</div><div className="rule-desc">时段结束后未打卡自动标记为缺卡</div></div></div><Toggle on={state.settings.autoMark} onChange={() => update(s => ({ ...s, settings: { ...s.settings, autoMark: !s.settings.autoMark } }))}/></div>
                <div className="rule-card"><div className="rule-info"><div className="rule-icon muted"><WarnIcon/></div><div><div className="rule-name">异常通知</div><div className="rule-desc">缺卡或迟到超过15分钟时通知主管</div></div></div><Toggle on={state.settings.notify} onChange={() => update(s => ({ ...s, settings: { ...s.settings, notify: !s.settings.notify } }))}/></div>
              </>
            )}
          </main>
        </div>
      )}

      {/* File Input (hidden) */}
      <input ref={fileRef} type="file" accept=".xlsx,.xls" style={{ display: 'none' }} onChange={e => { if (e.target.files[0]) handleFile(e.target.files[0]); e.target.value = '' }}/>

      {/* Import Modal */}
      {pendingImport && (
        <div className="modal-overlay show" onClick={e => { if (e.target === e.currentTarget) setPendingImport(null) }}>
          <div className="modal">
            <h3>导入班次数据</h3>
            <div className="sub">检测到以下班次，确认将替换当前规则。</div>
            <div className="import-preview">
              <table><thead><tr><th>班次名称</th><th>开始</th><th>结束</th><th>容差</th></tr></thead><tbody>
                {pendingImport.map(s => <tr key={s.id}><td>{s.name}</td><td className="mono">{s.start}</td><td className="mono">{s.end}</td><td>{s.tolerance}分钟</td></tr>)}
              </tbody></table>
            </div>
            <div className="modal-actions">
              <button className="btn-s" onClick={() => setPendingImport(null)}>取消</button>
              <button className="btn-p" onClick={confirmImport}>确认导入</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Toggle({ on, onChange, defaultOn }) {
  const [v, setV] = useState(defaultOn ?? on ?? false)
  const isOn = on !== undefined ? on : v
  return <div className={`toggle ${isOn ? 'on' : ''}`} onClick={() => { setV(!v); onChange?.() }}/>
}

function AttTable({ team, shifts, punches, search, today }) {
  const q = search.toLowerCase()
  const members = team.filter(m => !q || m.name.includes(q) || m.dept.includes(q))
  return (
    <table><thead><tr><th>成员</th>{shifts.map(s => <th key={s.id}>{s.name}</th>)}<th>状态</th></tr></thead><tbody>
      {members.map((member, mi) => {
        const mp = member.id === 6 ? punches : mockPunches(member.id, { filter: () => shifts })
        let allOk = true, hasMiss = false
        const cells = shifts.map(shift => {
          const st = shiftStatus(shift, mp)
          if (st.ov !== 'ok' && st.ov !== 'wait') allOk = false
          if (st.ov === 'miss') hasMiss = true
          const sTime = st.sp?.time || '--:--', eTime = st.ep?.time || '--:--'
          const cls = (st.ss === 'late' || st.ov === 'miss') ? 'warn' : ''
          return <td key={shift.id} className={`mono ${cls}`}>{sTime} / {eTime}</td>
        })
        const badge = allOk ? <span className="badge b-ok">正常</span> : hasMiss ? <span className="badge b-miss">缺卡</span> : <span className="badge b-warn">异常</span>
        const c = AVATAR_COLORS[mi % AVATAR_COLORS.length]
        return (
          <tr key={member.id}>
            <td><div className="u-cell"><div className="u-av" style={{ background: c.bg, color: c.fc }}>{member.name[0]}</div><div><div style={{ fontWeight: 500 }}>{member.name}</div><div style={{ fontSize: 11, color: 'var(--muted)' }}>{member.dept}</div></div></div></td>
            {cells}<td>{badge}</td>
          </tr>
        )
      })}
    </tbody></table>
  )
}
