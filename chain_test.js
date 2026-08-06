function toM(t){const[h,m]=t.split(':').map(Number);return h*60+m;}

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

function names(ch){return ch.map(s=>s.name).join('-');}

const shifts=[
  {name:'17-18',start:'17:00',end:'18:00'},
  {name:'18-19',start:'18:00',end:'19:00'},
  {name:'19-20',start:'19:00',end:'20:00'},
  {name:'20-21',start:'20:00',end:'21:00'},
  {name:'12-13',start:'12:00',end:'13:00'},
  {name:'13-14',start:'13:00',end:'14:00'},
  {name:'00-01',start:'00:00',end:'01:00'}
];
const chains=buildConsecutiveChains(shifts);
print('分组结果：');
chains.forEach((ch,i)=>print(i+1+'. '+names(ch)));

// 断言
function assert(cond,msg){if(!cond)throw new Error('FAIL: '+msg);print('PASS: '+msg);}
assert(chains.length===4,'7个班次应分成4组：3对+1个单');
assert(names(chains[0])==='00-01','00-01 单独');
assert(names(chains[1])==='12-13-13-14','12-13 和 13-14 成对');
assert(names(chains[2])==='17-18-18-19','17-18 和 18-19 成对');
assert(names(chains[3])==='19-20-20-21','19-20 和 20-21 成对');

// 三个连续班次
const triple=[
  {name:'A',start:'09:00',end:'10:00'},
  {name:'B',start:'10:00',end:'11:00'},
  {name:'C',start:'11:00',end:'12:00'}
];
const t=buildConsecutiveChains(triple);
assert(t.length===2,'三个连续班次应分成一对加一个单');
assert(names(t[0])==='A-B'&&names(t[1])==='C','A-B 成对，C 单独');

print('\n连班链长度限制测试通过 ✅');
