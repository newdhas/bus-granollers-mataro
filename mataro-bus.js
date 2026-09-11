const lines = [
  [1,"Circular"],
  [2,"Circular"],
  [3,"Camí de la Serra · Vista Alegre · Rocafonda"],
  [4,"Cirera · Molins"],
  [5,"Rodalies · Hospital de Mataró"],
  [6,"Institut Català Salut · Ctra. de Mata"],
  [7,"Pl. Tereses · Cerdanyola"],
  [8,"Rodalies · Galícia"],
];

const root = document.getElementById('urbanLines');
root.innerHTML = lines.map(([id,name]) => `
  <a class="urban-line" href="https://mataro.avanzagrupo.com/detalle-linea?idBusLine=${id}" target="_blank" rel="noopener noreferrer">
    <span class="line-badge">${id}</span>
    <span style="min-width:0"><strong>Línea ${id}</strong><span>${name}</span></span>
    <span style="margin-left:auto;font-size:20px;opacity:.45">›</span>
  </a>
`).join('');

function tick(){
  document.getElementById('urbanClock').textContent = new Date().toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'});
}
tick();
setInterval(tick,30000);
