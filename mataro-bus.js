import { HOLIDAYS } from './data.js';

const lines = [
  [1,'Circular'],[2,'Circular'],[3,'Camí de la Serra · Vista Alegre · Rocafonda'],[4,'Cirera · Molins'],
  [5,'Rodalies · Hospital de Mataró'],[6,'Institut Català Salut · Ctra. de Mata'],[7,'Pl. Tereses · Cerdanyola'],[8,'Rodalies · Galícia']
];

const LINE1_STOPS = [
  'Rodalies','Ronda Barceló','Plaça Dr. Fleming','President Macià','Sant Valentí','Ed. de Vidre - TecnoCampus',
  'Institut Català Salut','Gatassa','Rosselló','València','Ronda Cerdanya','Vallès','Ample','Roca Blanca',
  'Escola El Turó','Euskadi','Irlanda','Parc La Llàntia','Blanes','La Llàntia','Cementiri Les Valls','Mataró Parc',
  'Hospital de Mataró','El Cargol','Santa Anna','Muralla','Camínet','Parc Central','Cabanellas','Escola Freta',
  'P. Picasso','Perú','Caputxins','Sant Oleguer','CAP Cirera Molins','Cirera'
];

const ROSSELLO = {
  weekday: ['05:36','06:36','06:57','07:06','07:14','07:27','07:39','07:53','08:09','08:18','08:29','08:42','08:55','09:09','09:23','09:36','09:49','10:02','10:15','10:27','10:40','10:53','11:06','11:19','11:32','11:44','11:57','12:10','12:24','12:37','12:50','13:02','13:15','13:28','13:41','13:54','14:07','14:19','14:32','14:45','14:59','15:13','15:27','15:40','15:52','16:04','16:17','16:31','16:45','16:59','17:12','17:25','17:38','17:52','18:06','18:20','18:33','18:45','18:58','19:12','19:26','19:39','19:50','20:03','20:14','20:28','20:45','21:03','21:14','21:27','21:40','21:54','22:09','22:22','22:33','22:46'],
  saturday: ['06:47','07:23','07:52','08:14','08:38','09:01','09:23','09:46','10:11','10:35','10:59','11:23','11:49','12:14','12:40','13:07','13:33','14:00','14:25','14:50','15:16','15:41','16:06','16:31','16:56','17:21','17:47','18:13','18:40','19:06','19:33','20:01','20:27','20:53','21:16','21:40','22:20'],
  holiday: ['08:22','08:58','09:30','10:02','10:36','11:10','11:43','12:17','12:53','13:29','14:04','14:40','15:13','15:47','16:20','16:54','17:30','18:04','18:40','19:16','19:53','20:29','21:03','21:36','22:11'],
  summerWeekday: ['05:41','06:43','07:06','07:18','07:28','07:45','08:00','08:12','08:24','08:36','08:49','09:02','09:15','09:28','09:41','09:54','10:07','10:20','10:33','10:46','10:59','11:13','11:26','11:39','11:52','12:06','12:21','12:35','12:49','13:03','13:17','13:32','13:46','13:58','14:12','14:26','14:39','14:52','15:04','15:17','15:30','15:44','15:57','16:09','16:22','16:36','16:50','17:03','17:16','17:29','17:43','17:57','18:11','18:27','18:41','18:55','19:10','19:25','19:40','19:55','20:10','20:23','20:36','20:49','21:02','21:22','21:42','22:10','22:24']
};

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
let currentLine=null;

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
function rosselloTimes(group){
  if(!group) return [];
  if(group.dayType==='holiday') return ROSSELLO.holiday;
  if(group.dayType==='saturday') return ROSSELLO.saturday;
  if(group.season==='summer') return ROSSELLO.summerWeekday;
  return ROSSELLO.weekday;
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
  if(currentLine===1){
    stopSelect.innerHTML=LINE1_STOPS.map(name=>`<option value="${name}">${name}${name==='Rosselló'?' · 1024':''}</option>`).join('');
    const preferred=[...stopSelect.options].find(o=>o.value==='Rosselló');
    if(preferred) stopSelect.value='Rosselló';
  }else{
    stopSelect.innerHTML=(group?.stops||[]).map((s,i)=>`<option value="${i}">${s.name}</option>`).join('');
  }
  renderTimes();
}

function renderTimes(){
  const group=groups[Number(scheduleSelect.value)||0];
  let times=[];
  let stopName='';

  if(currentLine===1){
    stopName=stopSelect.value;
    if(stopName==='Rosselló'){
      times=rosselloTimes(group);
    }else{
      const extracted=(group?.stops||[]).find(s=>s.name.toLowerCase()===stopName.toLowerCase());
      times=extracted?.times||[];
    }
  }else{
    const stop=group?.stops?.[Number(stopSelect.value)||0];
    stopName=stop?.name||'';
    times=stop?.times||[];
  }

  const now=nowMinutes();
  const upcoming=times.filter(t=>minutes(t)>=now).slice(0,5);

  if(!times.length){
    nextDepartures.innerHTML=`<div class="next-box"><strong>${stopName||'Esta parada'} está en el recorrido oficial</strong><div style="margin-top:6px">El PDF general no publica horas exactas para esta parada. No las voy a estimar.</div></div>`;
    allTimes.innerHTML='';
    return;
  }

  if(upcoming.length){
    nextDepartures.innerHTML=`<div class="next-box"><div style="font-size:12px;font-weight:800;letter-spacing:.08em">PRÓXIMAS SALIDAS · ${calendarLabel(group).toUpperCase()}</div><div class="next-time">${upcoming[0]}</div><div style="margin-top:7px;font-weight:700">${upcoming.slice(1).join(' · ')||'Última salida disponible'}</div></div>`;
  }else{
    nextDepartures.innerHTML=`<div class="next-box"><strong>No quedan salidas posteriores</strong><div style="margin-top:6px">${calendarLabel(group)}</div></div>`;
  }
  allTimes.innerHTML=times.map(t=>`<span class="time-chip">${t}</span>`).join('');
}

async function openLine(id){
  currentLine=id;
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
