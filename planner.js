import { HOLIDAYS } from './data.js';
import { tripsForStopsDate } from './logic.js';

const LINES = [
  [1,'Circular'],[2,'Circular'],[3,'Camí de la Serra · Vista Alegre · Rocafonda'],[4,'Cirera · Molins'],
  [5,'Rodalies · Hospital de Mataró'],[6,'Institut Català Salut · Ctra. de Mata'],[7,'Pl. Tereses · Cerdanyola'],[8,'Rodalies · Galícia']
];

const SUMMER_PERIODS = {
  2026: ['2026-07-27','2026-08-21']
};

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
let allGroups = [];

function pad2(value){ return String(value).padStart(2,'0'); }
function dateKey(d){ return `${d.getFullYear()}-${pad2(d.getMonth()+1)}-${pad2(d.getDate())}`; }
function parseDate(value){
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
  if(!m) return new Date();
  return new Date(Number(m[1]), Number(m[2])-1, Number(m[3]), 12, 0, 0, 0);
}
function timeToMinutes(value){
  const m = /^(\d{1,2}):(\d{2})$/.exec(value || '');
  if(!m) return null;
  return Number(m[1])*60 + Number(m[2]);
}
function formatMinutes(value){
  const normalized = ((value % 1440) + 1440) % 1440;
  return `${pad2(Math.floor(normalized/60))}:${pad2(normalized%60)}`;
}
function minutesFromDate(date, serviceDate){
  const start = new Date(serviceDate); start.setHours(0,0,0,0);
  return Math.round((date - start) / 60000);
}
function durationLabel(mins){
  if(mins < 60) return `${mins} min`;
  const h = Math.floor(mins/60), m = mins%60;
  return m ? `${h} h ${m} min` : `${h} h`;
}
function normalizeName(value){
  return String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/\s+/g,' ').trim();
}
function isRodalies(name){ return /rodalies/i.test(name || ''); }
function isSummer(d){
  const p = SUMMER_PERIODS[d.getFullYear()];
  if(!p) return false;
  const key = dateKey(d);
  return key >= p[0] && key <= p[1];
}
function dayType(d){
  if(HOLIDAYS.has(dateKey(d)) || d.getDay() === 0) return 'holiday';
  if(d.getDay() === 6) return 'saturday';
  return 'weekday';
}
function dayTypeLabel(type){
  return {weekday:'Laborable',saturday:'Sábado',holiday:'Domingo/festivo'}[type] || 'Horario';
}
function classifyGroup(page, table){
  const [x1,y1] = table.bbox || [0,0];
  let type = 'weekday';
  if(x1 >= 390 && y1 < 300) type = 'saturday';
  else if(x1 >= 390 && y1 >= 300) type = 'holiday';
  return { dayType:type, season:page >= 3 ? 'summer' : 'winter' };
}
function normalizeTime(value){
  const match = String(value || '').match(/\b(\d{1,2}):(\d{2})\b/);
  if(!match) return null;
  const h = Number(match[1]), m = Number(match[2]);
  if(h > 23 || m > 59) return null;
  return `${pad2(h)}:${pad2(m)}`;
}
function timeColumns(rawTable, stopCount){
  const cols = rawTable.cols || Math.max(0,...(rawTable.data || []).map(row => row.length));
  if(cols >= stopCount * 2) return Array.from({length:stopCount},(_,i)=>i*2+1);

  const scored = [];
  for(let c=0;c<cols;c++){
    let rowsWithTime = 0;
    for(const row of rawTable.data || []) if(normalizeTime(row[c])) rowsWithTime++;
    if(rowsWithTime >= 2) scored.push({c,rowsWithTime});
  }
  return scored.sort((a,b)=>a.c-b.c).slice(0,stopCount).map(x=>x.c);
}
function buildGroup(lineId, pageNumber, summaryTable, rawTable){
  const stops = (summaryTable.pairs || []).map((p,i)=>({
    name:p.name || p.raw_name || `Parada ${i+1}`
  }));
  if(stops.length < 2 || !rawTable?.data?.length) return null;

  const cols = timeColumns(rawTable, stops.length);
  if(cols.length < stops.length) return null;

  const trips = [];
  for(const row of rawTable.data){
    const times = stops.map((_,i)=>normalizeTime(row[cols[i]]));
    if(times.filter(Boolean).length >= 2) trips.push(times);
  }
  if(!trips.length) return null;

  return {
    lineId,
    page:pageNumber,
    table:summaryTable.index,
    stops,
    trips,
    ...classifyGroup(pageNumber, summaryTable)
  };
}
function extractAllGroups(){
  const out = [];
  for(const [lineId] of LINES){
    const summaries = summaryData?.[String(lineId)] || [];
    const raws = tableData?.[String(lineId)] || [];
    for(const page of summaries){
      const rawPage = raws.find(p=>p.page === page.page);
      for(const table of page.tables || []){
        const rawTable = rawPage?.tables?.find(t=>t.index === table.index);
        const group = buildGroup(lineId, page.page, table, rawTable);
        if(group) out.push(group);
      }
    }
  }
  return out;
}
function groupsForDate(serviceDate, lineValue='all'){
  const type = dayType(serviceDate);
  const season = isSummer(serviceDate) ? 'summer' : 'winter';
  const lines = lineValue === 'all' ? allGroups : allGroups.filter(g=>String(g.lineId)===String(lineValue));
  let groups = lines.filter(g=>g.dayType===type && g.season===season);
  if(!groups.length) groups = lines.filter(g=>g.dayType===type);
  return groups;
}
function rodaliesAfter(group, originIndex){
  for(let i=originIndex+1;i<group.stops.length;i++) if(isRodalies(group.stops[i].name)) return i;
  return -1;
}
function originNames(serviceDate, lineValue){
  const names = new Map();
  for(const group of groupsForDate(serviceDate,lineValue)){
    for(let i=0;i<group.stops.length;i++){
      if(rodaliesAfter(group,i) < 0) continue;
      const name = group.stops[i].name;
      const key = normalizeName(name);
      if(!names.has(key)) names.set(key,name);
    }
  }
  return [...names.values()].sort((a,b)=>a.localeCompare(b,'es'));
}
function urbanTrips(serviceDate, lineValue, originName, minDeparture){
  const originKey = normalizeName(originName);
  const found = [];

  for(const group of groupsForDate(serviceDate,lineValue)){
    const originIndex = group.stops.findIndex(s=>normalizeName(s.name)===originKey);
    if(originIndex < 0) continue;
    const rodIndex = rodaliesAfter(group,originIndex);
    if(rodIndex < 0) continue;

    for(const row of group.trips){
      const depRaw = row[originIndex], arrRaw = row[rodIndex];
      if(!depRaw || !arrRaw) continue;
      const dep = timeToMinutes(depRaw), rawArr = timeToMinutes(arrRaw);
      if(dep == null || rawArr == null) continue;
      const arr = rawArr < dep ? rawArr + 1440 : rawArr;
      if(dep < minDeparture || arr - dep <= 0 || arr - dep > 120) continue;
      found.push({lineId:group.lineId, originName:group.stops[originIndex].name, dep, arr});
    }
  }

  const dedupe = new Map();
  for(const trip of found){
    const key = `${trip.lineId}-${trip.dep}-${trip.arr}`;
    if(!dedupe.has(key)) dedupe.set(key,trip);
  }
  return [...dedupe.values()].sort((a,b)=>a.dep-b.dep || a.arr-b.arr);
}
function e13Trips(serviceDate, destinationId){
  return tripsForStopsDate(serviceDate,'toGranollers','3314',destinationId).map(trip=>({
    dep:minutesFromDate(trip.departureDate,serviceDate),
    arr:minutesFromDate(trip.arrivalDate,serviceDate),
    trip
  }));
}
function buildConnections(serviceDate, lineValue, originName, minDeparture, maxArrival, transfer, destinationId){
  const urbans = urbanTrips(serviceDate,lineValue,originName,minDeparture);
  const e13 = e13Trips(serviceDate,destinationId);
  const byE13 = new Map();

  for(const urban of urbans){
    const connection = e13.find(bus=>bus.dep >= urban.arr + transfer);
    if(!connection) continue;
    if(maxArrival != null && connection.arr > maxArrival) continue;

    const item = {
      urban,
      e13:connection,
      wait:connection.dep - urban.arr,
      total:connection.arr - urban.dep
    };
    const key = `${connection.dep}-${connection.arr}`;
    const previous = byE13.get(key);
    if(!previous || item.urban.dep > previous.urban.dep) byE13.set(key,item);
  }

  return [...byE13.values()]
    .sort((a,b)=>a.e13.arr-b.e13.arr || b.urban.dep-a.urban.dep)
    .slice(0,6);
}
function routeCard(route, destinationName){
  return `
    <article class="route-option">
      <div class="route-option-head">
        <div>
          <div class="route-duration">${durationLabel(route.total)}</div>
          <div class="route-window">${formatMinutes(route.urban.dep)} – ${formatMinutes(route.e13.arr)}</div>
        </div>
        <div class="route-arrival"><span>Llegada</span><strong>${formatMinutes(route.e13.arr)}</strong></div>
      </div>
      <div class="route-chain">
        <span class="route-pill urban">${route.urban.lineId}</span>
        <span class="route-arrow-small">›</span>
        <span class="route-pill e13">e13</span>
      </div>
      <div class="route-steps">
        <div class="route-step"><time>${formatMinutes(route.urban.dep)}</time><span>Línea ${route.urban.lineId} desde <strong>${route.urban.originName}</strong></span></div>
        <div class="route-step"><time>${formatMinutes(route.urban.arr)}</time><span>Llegada a <strong>Rodalies Mataró</strong> · ${route.wait} min hasta el e13</span></div>
        <div class="route-step"><time>${formatMinutes(route.e13.dep)}</time><span>e13 desde <strong>Rodalies Mataró · costat muntanya</strong></span></div>
        <div class="route-step"><time>${formatMinutes(route.e13.arr)}</time><span>Llegada a <strong>${destinationName}</strong></span></div>
      </div>
    </article>`;
}
function updateStatus(serviceDate){
  const type = dayType(serviceDate);
  const season = isSummer(serviceDate) ? 'horario de verano' : 'horario ordinario';
  const count = originNames(serviceDate,lineSelect.value).length;
  statusBox.textContent = `${dayTypeLabel(type)} · ${season} Mataró Bus · ${count} paradas con enlace calculable a Rodalies.`;
}
function refreshStops(){
  if(!allGroups.length) return;
  const serviceDate = parseDate(dateInput.value);
  const previous = stopSelect.value;
  const names = originNames(serviceDate,lineSelect.value);
  stopSelect.innerHTML = names.map(name=>`<option value="${name.replace(/&/g,'&amp;').replace(/"/g,'&quot;')}">${name}</option>`).join('');

  if(names.includes(previous)) stopSelect.value = previous;
  else {
    const preferred = names.find(name=>normalizeName(name)==='hospital de mataro');
    if(preferred) stopSelect.value = preferred;
  }
  stopSelect.disabled = !names.length;
  searchBtn.disabled = !names.length;
  updateStatus(serviceDate);
}
function searchRoutes(){
  if(!allGroups.length || !stopSelect.value) return;
  const serviceDate = parseDate(dateInput.value);
  const minDeparture = timeToMinutes(departInput.value) ?? 0;
  const maxArrival = arriveInput.value ? timeToMinutes(arriveInput.value) : null;
  const transfer = Number(transferSelect.value) || 5;
  const destinationId = destinationSelect.value;
  const destinationName = destinationSelect.options[destinationSelect.selectedIndex]?.textContent || 'Granollers';

  if(maxArrival != null && maxArrival < minDeparture){
    resultsBox.className = 'planner-results empty-state';
    resultsBox.innerHTML = 'La hora límite de llegada es anterior a la hora mínima de salida.';
    return;
  }

  const routes = buildConnections(serviceDate,lineSelect.value,stopSelect.value,minDeparture,maxArrival,transfer,destinationId);
  if(!routes.length){
    resultsBox.className = 'planner-results empty-state';
    resultsBox.innerHTML = `No encuentro una combinación ${stopSelect.value} → Rodalies → e13 dentro de ese margen. Prueba una salida anterior, una llegada más tarde o un margen de transbordo menor.`;
    return;
  }

  resultsBox.className = 'planner-results';
  resultsBox.innerHTML = routes.map(route=>routeCard(route,destinationName)).join('') + `
    <div class="route-warning">Horarios programados, no tiempo real. Una incidencia o retraso puede hacer que un enlace calculado no sea posible.</div>`;
}
function setDefaults(){
  const now = new Date();
  dateInput.value = dateKey(now);
  departInput.value = `${pad2(now.getHours())}:${pad2(now.getMinutes())}`;
  const later = new Date(now.getTime() + 2*60*60*1000);
  if(later.getDate() === now.getDate()) arriveInput.value = `${pad2(later.getHours())}:${pad2(later.getMinutes())}`;
  else arriveInput.value = '23:59';
}
async function loadData(){
  try{
    const [summaryRes,tableRes] = await Promise.all([
      fetch('./mataro-bus-table-summary.json',{cache:'no-store'}),
      fetch('./mataro-bus-tables.json',{cache:'no-store'})
    ]);
    if(!summaryRes.ok || !tableRes.ok) throw new Error('No se han podido cargar los horarios');
    [summaryData,tableData] = await Promise.all([summaryRes.json(),tableRes.json()]);
    allGroups = extractAllGroups();
    if(!allGroups.length) throw new Error('No se han podido interpretar los horarios');
    refreshStops();
    searchRoutes();
  }catch(error){
    statusBox.textContent = 'No se han podido cargar los horarios urbanos.';
    resultsBox.className = 'planner-results empty-state';
    resultsBox.textContent = 'El planificador no está disponible ahora mismo. Las vistas e13 y Mataró Bus siguen funcionando con normalidad.';
  }
}

lineSelect.innerHTML = `<option value="all">Todas las líneas</option>` + LINES.map(([id,name])=>`<option value="${id}">Línea ${id} · ${name}</option>`).join('');
setDefaults();
lineSelect.addEventListener('change',()=>{refreshStops();searchRoutes()});
dateInput.addEventListener('change',()=>{refreshStops();searchRoutes()});
stopSelect.addEventListener('change',searchRoutes);
departInput.addEventListener('change',searchRoutes);
arriveInput.addEventListener('change',searchRoutes);
transferSelect.addEventListener('change',searchRoutes);
destinationSelect.addEventListener('change',searchRoutes);
searchBtn.addEventListener('click',searchRoutes);

function tick(){ plannerClock.textContent = new Date().toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'}); }
tick(); setInterval(tick,30000);
loadData();
