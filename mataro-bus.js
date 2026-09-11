import { HOLIDAYS } from './data.js';

const lines = [
  [1,'Circular'],[2,'Circular'],[3,'Camí de la Serra · Vista Alegre · Rocafonda'],[4,'Cirera · Molins'],
  [5,'Rodalies · Hospital de Mataró'],[6,'Institut Català Salut · Ctra. de Mata'],[7,'Pl. Tereses · Cerdanyola'],[8,'Rodalies · Galícia']
];

const root=document.getElementById('urbanLines');
const detail=document.getElementById('lineDetail');
const detailTitle=document.getElementById('detailTitle');
const scheduleSelect=document.getElementById('scheduleSelect');
const stopSelect=document.getElementById('stopSelect');
const nextDepartures=document.getElementById('nextDepartures');
const allTimes=document.getElementById('allTimes');
const pdfLink=document.getElementById('pdfLink');
const closeDetail=document.getElementById('closeDetail');

let summaryData=null;
let tableData=null;
let groups=[];

root.innerHTML=lines.map(([id,name])=>`
  <button class="urban-line" type="button" data-line="${id}">
    <span class="line-badge">${id}</span>
    <span style="min-width:0"><strong>Línea ${id}</strong><span>${name}</span></span>
    <span style="margin-left:auto;font-size:20px;opacity:.45">›</span>
  </button>`).join('');

function minutes(v){const [h,m]=v.split(':').map(Number);return h*60+m}
function nowMinutes(){const d=new Date();return d.getHours()*60+d.getMinutes()}
function findTimes(value){return typeof value==='string' ? (value.match(/\b\d{2}:\d{2}\b/g)||[]) : []}
function dateKey(d){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`}
function isSummer(d){const md=(d.getMonth()+1)*100+d.getDate();return md>=615&&md<=914}
function dayType(d){
  if(HOLIDAYS.has(dateKey(d)) || d.getDay()===0) return 'holiday';
  if(d.getDay()===6) return 'saturday';
  return 'weekday';
}
function calendarLabel(g){
  const day={weekday:'Laborable',saturday:'Sábado',holiday:'Domingo/festivo'}[g.dayType]||'Horario';
  return `${day} · ${g.season==='summer'?'verano':'invierno'}`;
}

function classifyGroup(page,table){
  const [x1,y1]=table.bbox||[0,0];
  let type='weekday';
  if(x1>=390 && y1<300) type='saturday';
  else if(x1>=390 && y1>=300) type='holiday';
  return {dayType:type,season:page>=3?'summer':'winter'};
}

function extractGroups(summaryLine,rawLine){
  const out=[];
  for(const page of summaryLine||[]){
    for(const table of page.tables||[]){
      const rawPage=(rawLine||[]).find(p=>p.page===page.page);
      const rawTable=rawPage?.tables?.find(t=>t.index===table.index);
      if(!rawTable?.data?.length || !table.pairs?.length) continue;

      const cols=rawTable.cols||Math.max(...rawTable.data.map(r=>r.length));
      const timeCols=[];
      for(let c=0;c<cols;c++){
        const times=[];
        for(const row of rawTable.data) times.push(...findTimes(row[c]));
        const unique=[...new Set(times)].sort((a,b)=>minutes(a)-minutes(b));
        if(unique.length>=2) timeCols.push(unique);
      }

      const stops=table.pairs.map((p,i)=>({name:p.name||p.raw_name||`Parada ${i+1}`,times:timeCols[i]||[]})).filter(s=>s.times.length);
      if(stops.length){
        const cal=classifyGroup(page.page,table);
        out.push({page:page.page,table:table.index,stops,...cal});
      }
    }
  }
  return out;
}

function autoGroupIndex(){
  const now=new Date();
  const wantedDay=dayType(now);
  const wantedSeason=isSummer(now)?'summer':'winter';
  let i=groups.findIndex(g=>g.dayType===wantedDay&&g.season===wantedSeason);
  if(i<0) i=groups.findIndex(g=>g.dayType===wantedDay);
  if(i<0) i=0;
  return i;
}

function renderStops(){
  const group=groups[Number(scheduleSelect.value)||0];
  stopSelect.innerHTML=(group?.stops||[]).map((s,i)=>`<option value="${i}">${s.name}</option>`).join('');
  renderTimes();
}

function renderTimes(){
  const group=groups[Number(scheduleSelect.value)||0];
  const stop=group?.stops?.[Number(stopSelect.value)||0];
  const times=stop?.times||[];
  const now=nowMinutes();
  const upcoming=times.filter(t=>minutes(t)>=now).slice(0,5);

  if(upcoming.length){
    nextDepartures.innerHTML=`<div class="next-box"><div style="font-size:12px;font-weight:800;letter-spacing:.08em">PRÓXIMAS SALIDAS · ${calendarLabel(group).toUpperCase()}</div><div class="next-time">${upcoming[0]}</div><div style="margin-top:7px;font-weight:700">${upcoming.slice(1).join(' · ')||'Última salida disponible'}</div></div>`;
  }else{
    nextDepartures.innerHTML=`<div class="next-box"><strong>No quedan salidas posteriores</strong><div style="margin-top:6px">${calendarLabel(group)}</div></div>`;
  }
  allTimes.innerHTML=times.map(t=>`<span class="time-chip">${t}</span>`).join('');
}

async function openLine(id){
  const line=lines.find(([n])=>n===id);
  detailTitle.textContent=`Línea ${id} · ${line?.[1]||''}`;
  pdfLink.href=`./mataro-bus-official/line-${id}.pdf`;
  detail.classList.remove('hidden');
  nextDepartures.innerHTML='<div class="next-box">Cargando horario…</div>';
  allTimes.innerHTML='';
  detail.scrollIntoView({behavior:'smooth',block:'start'});

  try{
    if(!summaryData || !tableData){
      const [summaryRes,tableRes]=await Promise.all([
        fetch('./mataro-bus-table-summary.json',{cache:'no-store'}),
        fetch('./mataro-bus-tables.json',{cache:'no-store'})
      ]);
      if(!summaryRes.ok || !tableRes.ok) throw new Error('No se pudo cargar el horario');
      [summaryData,tableData]=await Promise.all([summaryRes.json(),tableRes.json()]);
    }
    groups=extractGroups(summaryData[String(id)],tableData[String(id)]);
    if(!groups.length) throw new Error('Sin datos extraídos');
    scheduleSelect.innerHTML=groups.map((g,i)=>`<option value="${i}">${calendarLabel(g)} · bloque ${i+1}</option>`).join('');
    scheduleSelect.value=String(autoGroupIndex());
    renderStops();
  }catch(e){
    scheduleSelect.innerHTML='';stopSelect.innerHTML='';
    nextDepartures.innerHTML=`<div class="next-box"><strong>No he podido mostrar los datos.</strong><div style="margin-top:6px">Puedes abrir el PDF oficial debajo.</div></div>`;
  }
}

root.addEventListener('click',e=>{const b=e.target.closest('[data-line]');if(b)openLine(Number(b.dataset.line));});
scheduleSelect.addEventListener('change',renderStops);
stopSelect.addEventListener('change',renderTimes);
closeDetail.addEventListener('click',()=>detail.classList.add('hidden'));

function tick(){document.getElementById('urbanClock').textContent=new Date().toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'});if(!detail.classList.contains('hidden'))renderTimes()}
tick();setInterval(tick,30000);