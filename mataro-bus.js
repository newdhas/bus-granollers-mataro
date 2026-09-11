import { HOLIDAYS } from './data.js';

const lines = [
  [1,'Circular'],[2,'Circular'],[3,'Camí de la Serra · Vista Alegre · Rocafonda'],[4,'Cirera · Molins'],
  [5,'Rodalies · Hospital de Mataró'],[6,'Institut Català Salut · Ctra. de Mata'],[7,'Pl. Tereses · Cerdanyola'],[8,'Rodalies · Galícia'],
];

const ROSSELLO = {
  weekday: ['05:36','06:36','06:57','07:06','07:14','07:27','07:39','07:53','08:09','08:18','08:29','08:42','08:55','09:09','09:23','09:36','09:49','10:02','10:15','10:27','10:40','10:53','11:06','11:19','11:32','11:44','11:57','12:10','12:24','12:37','12:50','13:02','13:15','13:28','13:41','13:54','14:07','14:19','14:32','14:45','14:59','15:13','15:27','15:40','15:52','16:04','16:17','16:31','16:45','16:59','17:12','17:25','17:38','17:52','18:06','18:20','18:33','18:45','18:58','19:12','19:26','19:39','19:50','20:03','20:14','20:28','20:45','21:03','21:14','21:27','21:40','21:54','22:09','22:22','22:33','22:46'],
  saturday: ['06:47','07:23','07:52','08:14','08:38','09:01','09:23','09:46','10:11','10:35','10:59','11:23','11:49','12:14','12:40','13:07','13:33','14:00','14:25','14:50','15:16','15:41','16:06','16:31','16:56','17:21','17:47','18:13','18:40','19:06','19:33','20:01','20:27','20:53','21:16','21:40','22:20'],
  holiday: ['08:22','08:58','09:30','10:02','10:36','11:10','11:43','12:17','12:53','13:29','14:04','14:40','15:13','15:47','16:20','16:54','17:30','18:04','18:40','19:16','19:53','20:29','21:03','21:36','22:11'],
  summerWeekday: ['05:41','06:43','07:06','07:18','07:28','07:45','08:00','08:12','08:24','08:36','08:49','09:02','09:15','09:28','09:41','09:54','10:07','10:20','10:33','10:46','10:59','11:13','11:26','11:39','11:52','12:06','12:21','12:35','12:49','13:03','13:17','13:32','13:46','13:58','14:12','14:26','14:39','14:52','15:04','15:17','15:30','15:44','15:57','16:09','16:22','16:36','16:50','17:03','17:16','17:29','17:43','17:57','18:11','18:27','18:41','18:55','19:10','19:25','19:40','19:55','20:10','20:23','20:36','20:49','21:02','21:22','21:42','22:10','22:24'],
};

const LABELS = {weekday:'Laborable', saturday:'Sábado', holiday:'Festivo', summerWeekday:'Laborable verano'};
let selected = autoType(new Date());

function dateKey(d){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`}
function autoType(d){
  if(HOLIDAYS.has(dateKey(d)) || d.getDay()===0) return 'holiday';
  if(d.getDay()===6) return 'saturday';
  return 'weekday';
}
function minutes(v){const [h,m]=v.split(':').map(Number); return h*60+m}
function nowMinutes(){const d=new Date(); return d.getHours()*60+d.getMinutes()}
function nextTimes(type,count=5){
  const now=nowMinutes();
  return ROSSELLO[type].filter(v=>minutes(v)>=now).slice(0,count);
}
function until(v){const diff=minutes(v)-nowMinutes(); return diff<=0?'ahora':`en ${diff} min`}
function renderSchedule(){
  document.querySelectorAll('#scheduleTabs button').forEach(b=>b.classList.toggle('active',b.dataset.type===selected));
  const upcoming=nextTimes(selected,5);
  const next=document.getElementById('urbanNext');
  const list=document.getElementById('urbanDepartures');
  if(!upcoming.length){
    next.innerHTML=`<div class="urban-next"><strong>No quedan salidas hoy</strong><div class="count">Horario: ${LABELS[selected]}</div></div>`;
    list.innerHTML=''; return;
  }
  next.innerHTML=`<article class="urban-next"><div style="font-size:12px;font-weight:800;letter-spacing:.08em">PRÓXIMO · ${LABELS[selected].toUpperCase()}</div><div class="time">${upcoming[0]}</div><div class="count">${until(upcoming[0])}</div></article>`;
  list.innerHTML=upcoming.slice(1).map(v=>`<div class="departure-row"><strong>${v}</strong><span>${until(v)}</span></div>`).join('');
}

const tabs=document.getElementById('scheduleTabs');
tabs.innerHTML=Object.entries(LABELS).map(([type,label])=>`<button type="button" data-type="${type}">${label}</button>`).join('');
tabs.addEventListener('click',e=>{const b=e.target.closest('button[data-type]');if(!b)return; selected=b.dataset.type; renderSchedule();});

const root=document.getElementById('urbanLines');
root.innerHTML=lines.map(([id,name])=>`
  <button class="urban-line" type="button" data-line="${id}">
    <span class="line-badge">${id}</span>
    <span style="min-width:0"><strong>Línea ${id}</strong><span>${name}</span></span>
    <span style="margin-left:auto;font-size:20px;opacity:.45">›</span>
  </button>`).join('');

const pdfPanel=document.getElementById('pdfPanel');
const pdfFrame=document.getElementById('pdfFrame');
const pdfTitle=document.getElementById('pdfTitle');
const closePdf=document.getElementById('closePdf');

function openLinePdf(id){
  const line=lines.find(([lineId])=>lineId===id);
  if(!line)return;
  const [,name]=line;
  pdfTitle.textContent=`Línea ${id} · ${name}`;
  pdfFrame.src=`./mataro-bus-official/line-${id}.pdf#view=FitH`;
  pdfPanel.classList.remove('hidden');
  pdfPanel.scrollIntoView({behavior:'smooth',block:'start'});
}
function closeLinePdf(){
  pdfFrame.src='about:blank';
  pdfPanel.classList.add('hidden');
}

root.addEventListener('click',e=>{
  const b=e.target.closest('[data-line]'); if(!b)return;
  openLinePdf(Number(b.dataset.line));
});
closePdf.addEventListener('click',closeLinePdf);

function tick(){document.getElementById('urbanClock').textContent=new Date().toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'});renderSchedule();}
tick(); setInterval(tick,30000);
