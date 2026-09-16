import { HOLIDAYS } from './data.js';
import { tripsForStopsDate } from './logic.js';

const LINES = [
  [1,'Circular'],[2,'Circular'],[3,'Camí de la Serra · Vista Alegre · Rocafonda'],[4,'Cirera · Molins'],
  [5,'Rodalies · Hospital de Mataró'],[6,'Institut Català Salut · Ctra. de Mata'],[7,'Pl. Tereses · Cerdanyola'],[8,'Rodalies · Galícia']
];

const $ = id => document.getElementById(id);
const plannerClock = $('plannerClock');
const lineSelect = $('plannerLine');
const stopSelect = $('plannerStop');
const dateInput = $('plannerDate');
const departInput = $('plannerDepart');
const arriveInput = $('plannerArrive');
const transferSelect = $('plannerTransfer');
const destinationSelect = $('plannerDestination');
const searchBtn = $('plannerSearch');
const statusBox = $('plannerStatus');
const resultsBox = $('plannerResults');

let summaryData = null;
let tableData = null;
let pdfTextData = null;
let allGroups = [];
let loadPromise = null;

function pad2(v){ return String(v).padStart(2,'0'); }
function dateKey(d){ return `${d.getFullYear()}-${pad2(d.getMonth()+1)}-${pad2(d.getDate())}`; }
function parseDate(value){
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
  return m ? new Date(Number(m[1]),Number(m[2])-1,Number(m[3]),12,0,0,0) : new Date();
}
function timeToMinutes(value){
  const m = /^(\d{1,2}):(\d{2})$/.exec(value || '');
  return m ? Number(m[1])*60 + Number(m[2]) : null;
}
function formatMinutes(value){
  const n=((value%1440)+1440)%1440;
  return `${pad2(Math.floor(n/60))}:${pad2(n%60)}`;
}
function minutesFromDate(date, serviceDate){
  const start=new Date(serviceDate); start.setHours(0,0,0,0);
  return Math.round((date-start)/60000);
}
function durationLabel(mins){
  if(mins<60) return `${mins} min`;
  const h=Math.floor(mins/60),m=mins%60;
  return m ? `${h} h ${m} min` : `${h} h`;
}
function normalizeName(value){
  return String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/\s+/g,' ').trim();
}
function isRodalies(name){ return /rodalies/i.test(name||''); }
function dayType(d){
  if(HOLIDAYS.has(dateKey(d)) || d.getDay()===0) return 'holiday';
  if(d.getDay()===6) return 'saturday';
  return 'weekday';
}
function dayTypeLabel(type){ return {weekday:'Laborable',saturday:'Sábado',holiday:'Domingo/festivo'}[type] || 'Horario'; }

function findTimes(value){
  const out=[];
  for(const match of String(value||'').matchAll(/\b(\d{1,2}):(\d{2})\b/g)){
    const h=Number(match[1]),m=Number(match[2]);
    if(h<=23 && m<=59) out.push(`${pad2(h)}:${pad2(m)}`);
  }
  return out;
}

function pageInfo(lineId,pageNumber){
  const page=(pdfTextData?.[String(lineId)]?.pages||[]).find(p=>p.page===pageNumber);
  const text=normalizeName(page?.text||'');
  const hasWeekday=text.includes('feiners');
  const hasSaturday=text.includes('dissabtes');
  const hasHoliday=text.includes('diumenges i festius');
  const dayFlags=[hasWeekday,hasSaturday,hasHoliday].filter(Boolean).length;
  let singleDayType=null;
  if(dayFlags===1){
    if(hasWeekday) singleDayType='weekday';
    else if(hasSaturday) singleDayType='saturday';
    else if(hasHoliday) singleDayType='holiday';
  }
  let season=null;
  if(text.includes('horaris estiu')) season='summer';
  else if(text.includes('horaris hivern')) season='winter';
  return {singleDayType,season};
}

function classifyGroup(lineId,pageNumber,table){
  const meta=pageInfo(lineId,pageNumber);
  let type=meta.singleDayType;
  if(!type){
    const [x1,y1]=table.bbox||[0,0];
    if(x1>=390 && y1<300) type='saturday';
    else if(x1>=390 && y1>=300) type='holiday';
    else type='weekday';
  }
  return {dayType:type,season:meta.season || (pageNumber>=3?'summer':'winter')};
}

function timeColumns(rawTable,stopCount){
  const cols=rawTable.cols || Math.max(0,...(rawTable.data||[]).map(row=>Array.isArray(row)?row.length:0));
  if(cols>=stopCount*2) return Array.from({length:stopCount},(_,i)=>i*2+1);
  const scored=[];
  for(let c=0;c<cols;c++){
    let score=0;
    for(const row of rawTable.data||[]) if(Array.isArray(row)) score+=findTimes(row[c]).length;
    if(score) scored.push({c,score});
  }
  return scored.sort((a,b)=>a.c-b.c).slice(0,stopCount).map(x=>x.c);
}

function buildGroup(lineId,pageNumber,summaryTable,rawTable){
  const stops=(summaryTable.pairs||[]).map((p,i)=>({name:p.name||p.raw_name||`Parada ${i+1}`}));
  if(stops.length<2 || !rawTable?.data?.length) return null;
  const cols=timeColumns(rawTable,stops.length);
  if(cols.length<stops.length) return null;

  const tripMap=new Map();
  const addTrip=trip=>{
    if(trip.filter(Boolean).length<2) return;
    const key=trip.map(v=>v||'-').join('|');
    if(!tripMap.has(key)) tripMap.set(key,trip);
  };

  for(const row of rawTable.data){
    if(!Array.isArray(row)) continue;

    // Normal PDF rows: one timetable column per stop. Some cells contain
    // two or more departures separated by line breaks; keep every one.
    const perStop=stops.map((_,i)=>findTimes(row[cols[i]]));
    const maxCount=Math.max(0,...perStop.map(v=>v.length));
    if(perStop.filter(v=>v.length).length>=2){
      for(let n=0;n<maxCount;n++) addTrip(perStop.map(v=>v[n]||null));
    }

    // Avanza also packs complete rows into a single cell at table edges.
    // Recover those rows in stop order instead of dropping them.
    for(const cell of row){
      const packed=findTimes(cell);
      if(packed.length>=stops.length && packed.length%stops.length===0){
        for(let i=0;i<packed.length;i+=stops.length) addTrip(packed.slice(i,i+stops.length));
      }
    }
  }

  const trips=[...tripMap.values()];
  if(!trips.length) return null;
  return {lineId,page:pageNumber,table:summaryTable.index,stops,trips,...classifyGroup(lineId,pageNumber,summaryTable)};
}

function extractAllGroups(){
  const out=[];
  for(const [lineId] of LINES){
    const summaries=summaryData?.[String(lineId)]||[];
    const raws=tableData?.[String(lineId)]||[];
    for(const page of summaries){
      const rawPage=raws.find(p=>p.page===page.page);
      for(const table of page.tables||[]){
        const rawTable=rawPage?.tables?.find(t=>t.index===table.index);
        const group=buildGroup(lineId,page.page,table,rawTable);
        if(group) out.push(group);
      }
    }
  }
  return out;
}

function groupsForDate(serviceDate,lineValue='all'){
  const type=dayType(serviceDate);
  const wantedSeason='winter';
  const source=lineValue==='all'?allGroups:allGroups.filter(g=>String(g.lineId)===String(lineValue));
  let groups=source.filter(g=>g.dayType===type && g.season===wantedSeason);
  if(!groups.length) groups=source.filter(g=>g.dayType===type);
  return groups;
}

function rodaliesAfter(group,originIndex){
  for(let i=originIndex+1;i<group.stops.length;i++) if(isRodalies(group.stops[i].name)) return i;
  return -1;
}

function originNames(serviceDate,lineValue){
  const names=new Map();
  for(const group of groupsForDate(serviceDate,lineValue)){
    for(let i=0;i<group.stops.length;i++){
      if(rodaliesAfter(group,i)<0) continue;
      const name=group.stops[i].name;
      const key=normalizeName(name);
      if(!names.has(key)) names.set(key,name);
    }
  }
  return [...names.values()].sort((a,b)=>a.localeCompare(b,'es'));
}

function urbanTrips(serviceDate,lineValue,originName,minDeparture){
  const originKey=normalizeName(originName);
  const found=[];
  for(const group of groupsForDate(serviceDate,lineValue)){
    const originIndex=group.stops.findIndex(s=>normalizeName(s.name)===originKey);
    if(originIndex<0) continue;
    const rodIndex=rodaliesAfter(group,originIndex);
    if(rodIndex<0) continue;
    for(const row of group.trips){
      const depRaw=row[originIndex],arrRaw=row[rodIndex];
      if(!depRaw||!arrRaw) continue;
      const dep=timeToMinutes(depRaw),rawArr=timeToMinutes(arrRaw);
      if(dep==null||rawArr==null) continue;
      const arr=rawArr<dep?rawArr+1440:rawArr;
      if(dep<minDeparture || arr-dep<=0 || arr-dep>120) continue;
      found.push({lineId:group.lineId,originName:group.stops[originIndex].name,dep,arr});
    }
  }
  const dedupe=new Map();
  for(const trip of found){
    const key=`${trip.lineId}-${trip.dep}-${trip.arr}`;
    if(!dedupe.has(key)) dedupe.set(key,trip);
  }
  return [...dedupe.values()].sort((a,b)=>a.dep-b.dep || a.arr-b.arr);
}

function e13Trips(serviceDate,destinationId){
  return tripsForStopsDate(serviceDate,'toGranollers','3314',destinationId).map(trip=>({
    dep:minutesFromDate(trip.departureDate,serviceDate),
    arr:minutesFromDate(trip.arrivalDate,serviceDate)
  }));
}

function buildConnections(serviceDate,lineValue,originName,minDeparture,maxArrival,transfer,destinationId){
  const urbans=urbanTrips(serviceDate,lineValue,originName,minDeparture);
  const e13=e13Trips(serviceDate,destinationId);
  const byE13=new Map();
  for(const urban of urbans){
    const connection=e13.find(bus=>bus.dep>=urban.arr+transfer);
    if(!connection) continue;
    if(maxArrival!=null && connection.arr>maxArrival) continue;
    const item={urban,e13:connection,wait:connection.dep-urban.arr,total:connection.arr-urban.dep};
    const key=`${connection.dep}-${connection.arr}`;
    const previous=byE13.get(key);
    if(!previous || item.urban.dep>previous.urban.dep) byE13.set(key,item);
  }
  return {routes:[...byE13.values()].sort((a,b)=>a.e13.arr-b.e13.arr || b.urban.dep-a.urban.dep).slice(0,8),urbanCount:urbans.length,e13Count:e13.length};
}

function routeCard(route,destinationName){
  return `<article class="route-option">
    <div class="route-option-head">
      <div><div class="route-duration">${durationLabel(route.total)}</div><div class="route-window">${formatMinutes(route.urban.dep)} – ${formatMinutes(route.e13.arr)}</div></div>
      <div class="route-arrival"><span>Llegada</span><strong>${formatMinutes(route.e13.arr)}</strong></div>
    </div>
    <div class="route-chain"><span class="route-pill urban">${route.urban.lineId}</span><span class="route-arrow-small">›</span><span class="route-pill e13">e13</span></div>
    <div class="route-steps">
      <div class="route-step"><time>${formatMinutes(route.urban.dep)}</time><span>Línea ${route.urban.lineId} desde <strong>${route.urban.originName}</strong></span></div>
      <div class="route-step"><time>${formatMinutes(route.urban.arr)}</time><span>Llegada a <strong>Rodalies Mataró</strong> · ${route.wait} min hasta el e13</span></div>
      <div class="route-step"><time>${formatMinutes(route.e13.dep)}</time><span>e13 desde <strong>Rodalies Mataró · costat muntanya</strong></span></div>
      <div class="route-step"><time>${formatMinutes(route.e13.arr)}</time><span>Llegada a <strong>${destinationName}</strong></span></div>
    </div>
  </article>`;
}

function updateStatus(serviceDate){
  const type=dayType(serviceDate);
  const count=originNames(serviceDate,lineSelect.value).length;
  statusBox.textContent=`${dayTypeLabel(type)} · ${count} paradas con enlace calculable a Rodalies.`;
}

function refreshStops(){
  if(!allGroups.length) return false;
  const serviceDate=parseDate(dateInput.value);
  const previous=stopSelect.value;
  const names=originNames(serviceDate,lineSelect.value);
  stopSelect.innerHTML=names.map(name=>`<option value="${name.replace(/&/g,'&amp;').replace(/"/g,'&quot;')}">${name}</option>`).join('');
  if(names.includes(previous)) stopSelect.value=previous;
  else {
    const preferred=names.find(name=>normalizeName(name)==='hospital de mataro');
    if(preferred) stopSelect.value=preferred;
  }
  stopSelect.disabled=!names.length;
  searchBtn.disabled=!names.length;
  updateStatus(serviceDate);
  return names.length>0;
}

async function ensureData(){
  if(allGroups.length) return true;
  if(!loadPromise){
    statusBox.textContent='Cargando horarios oficiales…';
    searchBtn.disabled=true;
    loadPromise=(async()=>{
      const [summaryRes,tableRes,textRes]=await Promise.all([
        fetch('./mataro-bus-table-summary.json',{cache:'no-store'}),
        fetch('./mataro-bus-tables.json',{cache:'no-store'}),
        fetch('./mataro-bus-pdf-text.json',{cache:'no-store'})
      ]);
      if(!summaryRes.ok||!tableRes.ok||!textRes.ok) throw new Error('No se han podido descargar los horarios urbanos');
      [summaryData,tableData,pdfTextData]=await Promise.all([summaryRes.json(),tableRes.json(),textRes.json()]);
      allGroups=extractAllGroups();
      if(!allGroups.length) throw new Error('No se han podido interpretar los horarios urbanos');
      refreshStops();
      return true;
    })().finally(()=>{ if(allGroups.length) searchBtn.disabled=!stopSelect.value; });
  }
  return loadPromise;
}

async function searchRoutes(){
  resultsBox.className='planner-results empty-state planner-loading';
  resultsBox.textContent='Buscando combinaciones…';
  try{
    await ensureData();
    if(!stopSelect.value && !refreshStops()){
      resultsBox.className='planner-results empty-state';
      resultsBox.textContent='No hay paradas con enlace calculable a Rodalies para esta selección.';
      return;
    }
    const serviceDate=parseDate(dateInput.value);
    const minDeparture=timeToMinutes(departInput.value)??0;
    const maxArrival=arriveInput.value?timeToMinutes(arriveInput.value):null;
    const transfer=Number(transferSelect.value)||5;
    const destinationId=destinationSelect.value;
    const destinationName=destinationSelect.options[destinationSelect.selectedIndex]?.textContent||'Granollers';

    if(maxArrival!=null && maxArrival<minDeparture){
      resultsBox.className='planner-results empty-state';
      resultsBox.textContent='La hora límite de llegada es anterior a la hora mínima de salida.';
      return;
    }

    const {routes,urbanCount,e13Count}=buildConnections(serviceDate,lineSelect.value,stopSelect.value,minDeparture,maxArrival,transfer,destinationId);
    if(!routes.length){
      resultsBox.className='planner-results empty-state';
      if(!urbanCount) resultsBox.innerHTML=`No he encontrado salidas urbanas publicadas desde <strong>${stopSelect.value}</strong> después de ${departInput.value}.`;
      else if(!e13Count) resultsBox.textContent='No hay expediciones e13 compatibles con ese día y destino.';
      else resultsBox.innerHTML=`He encontrado ${urbanCount} salidas urbanas, pero ninguna enlaza con el e13 dentro del margen elegido.`;
      return;
    }

    resultsBox.className='planner-results';
    resultsBox.innerHTML=routes.map(route=>routeCard(route,destinationName)).join('')+
      '<div class="route-warning">Horarios programados, no tiempo real. Una incidencia o retraso puede hacer que un enlace calculado no sea posible.</div>';
  }catch(error){
    console.error('Route planner error',error);
    statusBox.textContent='No se han podido cargar los horarios urbanos.';
    resultsBox.className='planner-results empty-state';
    resultsBox.textContent=error?.message||'Error al calcular la ruta.';
  }
}

function setDefaults(){
  const now=new Date();
  dateInput.value=dateKey(now);
  departInput.value=`${pad2(now.getHours())}:${pad2(now.getMinutes())}`;
  const later=new Date(now.getTime()+4*60*60*1000);
  arriveInput.value=later.getDate()===now.getDate()?`${pad2(later.getHours())}:${pad2(later.getMinutes())}`:'23:59';
}

lineSelect.innerHTML='<option value="all">Todas las líneas</option>'+LINES.map(([id,name])=>`<option value="${id}">Línea ${id} · ${name}</option>`).join('');
setDefaults();
lineSelect.addEventListener('change',()=>{refreshStops();searchRoutes();});
dateInput.addEventListener('change',()=>{refreshStops();searchRoutes();});
stopSelect.addEventListener('change',searchRoutes);
departInput.addEventListener('change',searchRoutes);
arriveInput.addEventListener('change',searchRoutes);
transferSelect.addEventListener('change',searchRoutes);
destinationSelect.addEventListener('change',searchRoutes);
searchBtn.addEventListener('click',searchRoutes);

function tick(){ plannerClock.textContent=new Date().toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'}); }
tick(); setInterval(tick,30000);
ensureData().then(searchRoutes).catch(()=>{});
