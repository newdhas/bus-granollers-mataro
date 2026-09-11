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

let data=null;
let currentLine=null;
let groups=[];

root.innerHTML=lines.map(([id,name])=>`
  <button class="urban-line" type="button" data-line="${id}">
    <span class="line-badge">${id}</span>
    <span style="min-width:0"><strong>Línea ${id}</strong><span>${name}</span></span>
    <span style="margin-left:auto;font-size:20px;opacity:.45">›</span>
  </button>`).join('');

function minutes(v){const [h,m]=v.split(':').map(Number);return h*60+m}
function nowMinutes(){const d=new Date();return d.getHours()*60+d.getMinutes()}

function extractGroups(lineData){
  const out=[];
  for(const page of lineData||[]){
    for(const table of page.tables||[]){
      const stops=(table.pairs||[]).filter(p=>Array.isArray(p.first)&&Array.isArray(p.last));
      if(!stops.length) continue;
      out.push({page:page.page,table:table.index,stops});
    }
  }
  return out;
}

function stopTimes(stop){
  const values=[];
  if(Array.isArray(stop.times)) values.push(...stop.times);
  if(Array.isArray(stop.first)) values.push(...stop.first);
  if(Array.isArray(stop.last)) values.push(...stop.last);
  return [...new Set(values.filter(v=>/^\d{2}:\d{2}$/.test(v)))].sort((a,b)=>minutes(a)-minutes(b));
}

function renderStops(){
  const group=groups[Number(scheduleSelect.value)||0];
  stopSelect.innerHTML=(group?.stops||[]).map((s,i)=>`<option value="${i}">${s.name||s.raw_name||`Parada ${i+1}`}</option>`).join('');
  renderTimes();
}

function renderTimes(){
  const group=groups[Number(scheduleSelect.value)||0];
  const stop=group?.stops?.[Number(stopSelect.value)||0];
  const times=stopTimes(stop||{});
  const now=nowMinutes();
  const upcoming=times.filter(t=>minutes(t)>=now).slice(0,5);

  if(upcoming.length){
    nextDepartures.innerHTML=`<div class="next-box"><div style="font-size:12px;font-weight:800;letter-spacing:.08em">PRÓXIMAS SALIDAS</div><div class="next-time">${upcoming[0]}</div><div style="margin-top:7px;font-weight:700">${upcoming.slice(1).join(' · ')||'Última salida disponible'}</div></div>`;
  }else{
    nextDepartures.innerHTML=`<div class="next-box"><strong>No quedan horas posteriores en este bloque</strong></div>`;
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
    if(!data){
      const r=await fetch('./mataro-bus-table-summary.json',{cache:'no-store'});
      if(!r.ok) throw new Error('No se pudo cargar el horario');
      data=await r.json();
    }
    groups=extractGroups(data[String(id)]);
    if(!groups.length) throw new Error('Sin datos extraídos');
    scheduleSelect.innerHTML=groups.map((g,i)=>`<option value="${i}">Horario ${i+1} · pág. ${g.page}</option>`).join('');
    renderStops();
  }catch(e){
    scheduleSelect.innerHTML='';
    stopSelect.innerHTML='';
    nextDepartures.innerHTML=`<div class="next-box"><strong>No he podido mostrar los datos.</strong><div style="margin-top:6px">Puedes abrir el PDF oficial debajo.</div></div>`;
  }
}

root.addEventListener('click',e=>{const b=e.target.closest('[data-line]');if(b)openLine(Number(b.dataset.line));});
scheduleSelect.addEventListener('change',renderStops);
stopSelect.addEventListener('change',renderTimes);
closeDetail.addEventListener('click',()=>detail.classList.add('hidden'));

function tick(){document.getElementById('urbanClock').textContent=new Date().toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'});if(!detail.classList.contains('hidden'))renderTimes()}
tick();setInterval(tick,30000);
