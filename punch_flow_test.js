// 模拟连班链最多2个班次后的打卡流程

var _now = new Date('2026-08-03T16:58:00');
function serverDate(){ return new Date(_now.getTime()); }
function nowM(){ const d=serverDate(); return d.getHours()*60+d.getMinutes(); }
function tdStr(){ return '2026-08-03'; }
function parseYmd(s){ const [y,m,day]=s.split('-').map(Number); return new Date(y,m-1,day); }

function toM(t){ const [h,m]=t.split(':').map(Number); return h*60+m; }

function shiftDateTimes(sh,dateStr){
  const sD=parseYmd(dateStr); const [shh,smm]=sh.start.split(':').map(Number); sD.setHours(shh,smm,0,0);
  const eD=parseYmd(dateStr); const [ehh,emm]=sh.end.split(':').map(Number); eD.setHours(ehh,emm,0,0);
  if(sh.cross||eD<=sD) eD.setDate(eD.getDate()+1);
  return {sD,eD};
}
function inStartWindow(sh,dateStr,nowDt){ if(!nowDt) nowDt=serverDate(); const {sD}=shiftDateTimes(sh,dateStr); const tol=(sh.tolerance||0)*60000; return Math.abs(nowDt.getTime()-sD.getTime())<=tol; }
function inEndWindow(sh,dateStr,nowDt){ if(!nowDt) nowDt=serverDate(); const {eD}=shiftDateTimes(sh,dateStr); const tol=(sh.tolerance||0)*60000; return Math.abs(nowDt.getTime()-eD.getTime())<=tol; }

function ss(sh,p,ctxDate){
  const now=nowM(),sM=toM(sh.start); let eM=toM(sh.end); if(sh.cross||eM<=sM)eM+=1440;
  const dur=eM-sM;
  const td=tdStr();
  const d=ctxDate||td;
  let started,ended;
  if(d===td){
    const sD=parseYmd(d); const [shh,smm]=sh.start.split(':').map(Number); sD.setHours(shh,smm,0,0);
    const eD=parseYmd(d); const [ehh,emm]=sh.end.split(':').map(Number); eD.setHours(ehh,emm,0,0);
    if(sh.cross||eD<=sD)eD.setDate(eD.getDate()+1);
    const nowDt=serverDate();
    started=nowDt>=sD;
    ended=nowDt>=eD;
  }else if(d<td){ started=true; ended=true; }else{ started=false; ended=false; }
  const sp=p.find(x=>x.sid===sh.id&&x.t==='s'), ep=p.find(x=>x.sid===sh.id&&x.t==='e');
  let sss='w', es='w';
  if(sp) sss=toM(sp.time)<=sM+sh.tolerance?'ok':'late'; else if(ended) sss='miss';
  if(ep) es='ok'; else if(ended) es='miss';
  let ov='w';
  if(sss==='ok'&&es==='ok') ov='ok'; else if(sss==='miss'||es==='miss') ov='miss'; else if(sss==='late') ov='warn'; else if(sss==='ok'&&es==='w') ov='active';
  return {ss:sss,es,ov,started,ended,sp,ep};
}

function buildConsecutiveChains(shifts){
  if(!shifts||!shifts.length)return[];
  const arr=shifts.slice().sort((a,b)=>toM(a.start)-toM(b.start));
  const chains=[];let cur=[arr[0]];
  for(let i=1;i<arr.length;i++){
    if(cur.length<2&&arr[i].start===arr[i-1].end){cur.push(arr[i])}
    else{chains.push(cur);cur=[arr[i]]}
  }
  chains.push(cur);
  return chains;
}

function findActiveChain(shifts,punches,ctxDate){
  const chains=buildConsecutiveChains(shifts);
  for(const ch of chains){
    if(ch.length<2)continue;
    const first=ch[0],last=ch[ch.length-1];
    const fss=ss(first,punches,ctxDate),lss=ss(last,punches,ctxDate);
    if(!lss.ep&&(fss.sp||inStartWindow(first,ctxDate)))return ch;
  }
  return null;
}

function chooseAction(shifts,punches,ctxDate){
  const activeChain=findActiveChain(shifts,punches,ctxDate);
  if(activeChain){
    const ch=activeChain,first=ch[0],last=ch[ch.length-1];
    const fss=ss(first,punches,ctxDate),lss=ss(last,punches,ctxDate);
    print('choose fss='+JSON.stringify(fss)+' inStart='+inStartWindow(first,ctxDate));
    if(fss.ss==='w'&&inStartWindow(first,ctxDate)) return {sh:first,t:'s',label:'上班打卡',shared:null};
    else if(!lss.ep){
      let action=null;
      for(let i=0;i<ch.length-1;i++){
        const prev=ch[i],next=ch[i+1];
        const pst=ss(prev,punches,ctxDate),nst=ss(next,punches,ctxDate);
        if(pst.sp&&!pst.ep&&!nst.sp&&(inEndWindow(prev,ctxDate)||inStartWindow(next,ctxDate))){
          return {sh:prev,t:'e',label:'连班交接打卡',shared:next};
        }
      }
      if(!action&&inEndWindow(last,ctxDate)) return {sh:last,t:'e',label:'下班打卡',shared:null};
    }
  }else{
    for(const sh of shifts){
      const st=ss(sh,punches,ctxDate);
      if(st.ss==='w'&&inStartWindow(sh,ctxDate)) return {sh,t:'s',label:'上班打卡',shared:null};
      if(st.sp&&!st.ep&&inEndWindow(sh,ctxDate)) return {sh,t:'e',label:'下班打卡',shared:null};
    }
  }
  return null;
}

var punches=[];
var shifts=[
  {id:1,name:'17-18',start:'17:00',end:'18:00',tolerance:5,enabled:true},
  {id:2,name:'18-19',start:'18:00',end:'19:00',tolerance:5,enabled:true},
  {id:3,name:'19-20',start:'19:00',end:'20:00',tolerance:5,enabled:true},
  {id:4,name:'20-21',start:'20:00',end:'21:00',tolerance:5,enabled:true}
];

function setTime(h,m){ _now = new Date('2026-08-03T'+(h<10?'0'+h:h)+':'+(m<10?'0'+m:m)+':00'); }
function formatP(){ return punches.map(p=>p.t+p.sid+'@'+p.time).sort().join(','); }
function assert(cond,msg){ if(!cond) throw new Error('FAIL: '+msg); print('PASS: '+msg); }

function click(){
  const active=findActiveChain(shifts,punches,tdStr());
  print('activeChain='+JSON.stringify(active && active.map(s=>s.name))+' now='+_now.toLocaleString());
  const action=chooseAction(shifts,punches,tdStr());
  if(!action){ print('无可用打卡动作 @ '+_now.toLocaleString()); return null; }
  const t=String(_now.getHours()).padStart(2,'0')+':'+String(_now.getMinutes()).padStart(2,'0');
  punches.push({sid:action.sh.id,t:action.t,time:t,ts:_now.getTime()});
  if(action.shared) punches.push({sid:action.shared.id,t:'s',time:t,ts:_now.getTime()});
  return action;
}

// 1. 16:58 开始 17-18
setTime(16,58);
const a1=click();
assert(a1 && a1.label==='上班打卡' && a1.sh.id===1, '16:58 能打 17-18 上班卡');
assert(formatP()==='s1@16:58','只有 17-18 上班卡');

// 2. 18:03 交接 17-18/18-19
setTime(18,3);
const a2=click();
assert(a2 && a2.label==='连班交接打卡' && a2.sh.id===1 && a2.shared.id===2, '18:03 连班交接 17-18 下班 + 18-19 上班');
assert(formatP()==='e1@18:03,s1@16:58,s2@18:03','17-18 完成，18-19 开始');

// 3. 19:03 先结束第一对的 18-19（不同链之间不共享交接打卡）
setTime(19,3);
const a3=click();
assert(a3 && a3.label==='下班打卡' && a3.sh.id===2, '19:03 先打 18-19 下班卡');

// 4. 同时间再开始第二对 19-20
const a4=click();
assert(a4 && a4.label==='上班打卡' && a4.sh.id===3, '19:03 再打 19-20 上班卡（新的一对）');

// 5. 20:03 交接 19-20/20-21
setTime(20,3);
const a5=click();
assert(a5 && a5.label==='连班交接打卡' && a5.sh.id===3 && a5.shared.id===4, '20:03 连班交接 19-20 下班 + 20-21 上班');

// 6. 21:03 结束 20-21
setTime(21,3);
const a6=click();
assert(a6 && a6.label==='下班打卡' && a6.sh.id===4, '21:03 能打 20-21 下班卡');

// 验证最终每张卡都有上下班
for(const sh of shifts){
  assert(punches.some(p=>p.sid===sh.id&&p.t==='s'), sh.name+' 有上班卡');
  assert(punches.some(p=>p.sid===sh.id&&p.t==='e'), sh.name+' 有下班卡');
}

print('\n四班次连班（每链最多2个）打卡流程测试通过 ✅');
