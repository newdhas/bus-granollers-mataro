import { COORDS, HOLIDAY_YEARS } from "./data.js";
import { STOP_CHOICES } from "./stops-data.js";
import {
  dateKey,
  getUpcomingTripsForStops,
  tripsForStopsDate,
  getCalendarLabel,
  minutesUntil,
  getStop,
} from "./logic.js";

const $ = (id) => document.getElementById(id);

const clock = $("clock");
const pageTitle = $("pageTitle");
const locationText = $("locationText");
const locateBtn = $("locateBtn");
const toMataroBtn = $("toMataroBtn");
const toGranollersBtn = $("toGranollersBtn");
const originStopSelect = $("originStopSelect");
const destinationStopSelect = $("destinationStopSelect");
const scheduleDate = $("scheduleDate");
const dateDisplayLabel = $("dateDisplayLabel");
const prevDateBtn = $("prevDateBtn");
const nextDateBtn = $("nextDateBtn");
const todayBtn = $("todayBtn");
const calendarChip = $("calendarChip");
const calendarWarning = $("calendarWarning");
const results = $("results");

let direction = localStorage.getItem("busDirection") || "toMataro";
let locationResolved = false;
let datePinned = false;

function haversineKm(a, b) {
  const R = 6371;
  const toRad = deg => deg * Math.PI / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);

  const x = Math.sin(dLat/2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon/2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(x), Math.sqrt(1-x));
}

function formatTime(date) {
  return date.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
}

function parseDateInput(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
  if (!match) return null;
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 12, 0, 0, 0);
}

function isSameDay(a, b) {
  return a.getFullYear() === b.getFullYear()
    && a.getMonth() === b.getMonth()
    && a.getDate() === b.getDate();
}

function longDateLabel(date) {
  return date.toLocaleDateString("es-ES", {
    weekday: "long",
    day: "numeric",
    month: "short",
  });
}

function compactDateLabel(date, now) {
  const base = date.toLocaleDateString("es-ES", {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).replace(/\./g, "");

  const today = new Date(now); today.setHours(0,0,0,0);
  const target = new Date(date); target.setHours(0,0,0,0);
  const diff = Math.round((target - today) / 86400000);
  if (diff === 0) return `Hoy · ${base}`;
  if (diff === 1) return `Mañana · ${base}`;
  if (diff === -1) return `Ayer · ${base}`;
  return base;
}

function dayLabel(date, now) {
  const a = new Date(now); a.setHours(0,0,0,0);
  const b = new Date(date); b.setHours(0,0,0,0);
  const diff = Math.round((b - a) / 86400000);
  if (diff === 0) return "hoy";
  if (diff === 1) return "mañana";
  return date.toLocaleDateString("es-ES", { weekday: "short", day: "numeric", month: "short" });
}

function countdownText(now, date) {
  const mins = minutesUntil(now, date);
  if (mins <= 1) return "sale en 1 min";
  return `sale en ${mins} min`;
}

function durationText(departureDate, arrivalDate) {
  const mins = Math.round((arrivalDate - departureDate) / 60000);
  return `${mins} min`;
}

function selectedServiceDate(now = new Date()) {
  return parseDateInput(scheduleDate.value) || new Date(now.getFullYear(), now.getMonth(), now.getDate(), 12, 0, 0, 0);
}

function setSelectedDate(date, pin = true) {
  scheduleDate.value = dateKey(date);
  datePinned = pin && !isSameDay(date, new Date());
  renderTrips();
}

function shiftSelectedDate(days) {
  const date = selectedServiceDate();
  date.setDate(date.getDate() + days);
  setSelectedDate(date, true);
}

function stopStorageKey(kind) {
  return `e13Stop:${direction}:${kind}`;
}

function optionForStop(stopId) {
  const stop = getStop(direction, stopId);
  if (!stop) return "";
  return `<option value="${stop.id}">${stop.name}</option>`;
}

function populateStopSelectors() {
  const config = STOP_CHOICES[direction];
  const storedOrigin = localStorage.getItem(stopStorageKey("origin"));
  const storedDestination = localStorage.getItem(stopStorageKey("destination"));
  const origin = config.origins.includes(storedOrigin) ? storedOrigin : config.defaultOrigin;
  const destination = config.destinations.includes(storedDestination) ? storedDestination : config.defaultDestination;

  originStopSelect.innerHTML = config.origins.map(optionForStop).join("");
  destinationStopSelect.innerHTML = config.destinations.map(optionForStop).join("");
  originStopSelect.value = origin;
  destinationStopSelect.value = destination;
}

function currentStops() {
  return {
    originStopId: originStopSelect.value,
    destinationStopId: destinationStopSelect.value,
  };
}

function setDirection(nextDirection, render = true) {
  direction = nextDirection;
  localStorage.setItem("busDirection", direction);

  toMataroBtn.classList.toggle("active", direction === "toMataro");
  toGranollersBtn.classList.toggle("active", direction === "toGranollers");
  populateStopSelectors();

  if (render) renderTrips();
}

function renderTrips() {
  const now = new Date();
  clock.textContent = formatTime(now);

  if (!datePinned) scheduleDate.value = dateKey(now);
  const serviceDate = selectedServiceDate(now);
  const viewingToday = isSameDay(serviceDate, now);
  dateDisplayLabel.textContent = compactDateLabel(serviceDate, now);
  todayBtn.classList.toggle("hidden", viewingToday);
  pageTitle.textContent = viewingToday ? "Próximo bus" : "Horario e13";

  const { originStopId, destinationStopId } = currentStops();
  const trips = tripsForStopsDate(serviceDate, direction, originStopId, destinationStopId);

  if (viewingToday) {
    calendarChip.textContent = `Hoy: ${getCalendarLabel(now)}`;
  } else {
    calendarChip.textContent = `${longDateLabel(serviceDate)} · ${getCalendarLabel(serviceDate)}`;
  }

  if (!HOLIDAY_YEARS.has(serviceDate.getFullYear())) {
    calendarWarning.textContent = `Aviso: los festivos automáticos de ${serviceDate.getFullYear()} no están cargados; sábados y domingos sí se detectan correctamente.`;
    calendarWarning.classList.remove("hidden");
  } else {
    calendarWarning.classList.add("hidden");
  }

  if (!trips.length) {
    results.innerHTML = `<div class="empty">No se han encontrado expediciones para estas paradas el ${longDateLabel(serviceDate)}.</div>`;
    return;
  }

  if (!viewingToday) {
    const first = trips[0];
    const rows = trips.slice(1).map(trip => `
      <article class="trip-row">
        <div class="trip-time">${formatTime(trip.departureDate)}</div>
        <div class="trip-countdown">${durationText(trip.departureDate, trip.arrivalDate)}</div>
        <div class="trip-arrival">
          <span>Llegada</span>
          <strong>${formatTime(trip.arrivalDate)}</strong>
        </div>
      </article>
    `).join("");

    results.innerHTML = `
      <article class="next-card">
        <div class="next-label">PRIMER BUS</div>
        <div class="next-main">
          <div>
            <div class="next-time">${formatTime(first.departureDate)}</div>
            <div class="countdown">${trips.length} expediciones · horario completo</div>
          </div>
          <div class="arrival">
            <span>Llegada</span>
            <strong>${formatTime(first.arrivalDate)}</strong>
          </div>
        </div>
      </article>
      ${rows}
    `;
    return;
  }

  const nextToday = trips.find(trip => trip.departureDate >= now);
  const nextTrip = nextToday || getUpcomingTripsForStops(now, direction, originStopId, destinationStopId, 1)[0];

  const rows = trips.map(trip => `
    <article class="trip-row">
      <div class="trip-time">${formatTime(trip.departureDate)}</div>
      <div class="trip-countdown">${durationText(trip.departureDate, trip.arrivalDate)}</div>
      <div class="trip-arrival">
        <span>Llegada</span>
        <strong>${formatTime(trip.arrivalDate)}</strong>
      </div>
    </article>
  `).join("");

  if (!nextTrip) {
    results.innerHTML = rows;
    return;
  }

  const nextDay = dayLabel(nextTrip.departureDate, now);
  const nextTag = nextDay === "hoy" ? "" : `<span class="day-tag">${nextDay}</span>`;

  results.innerHTML = `
    <article class="next-card">
      <div class="next-label">PRÓXIMO</div>
      <div class="next-main">
        <div>
          <div class="next-time">${formatTime(nextTrip.departureDate)}</div>
          <div class="countdown">${countdownText(now, nextTrip.departureDate)} ${nextTag}</div>
        </div>
        <div class="arrival">
          <span>Llegada</span>
          <strong>${formatTime(nextTrip.arrivalDate)}</strong>
        </div>
      </div>
    </article>
    ${rows}
  `;
}

function useLocation() {
  if (!("geolocation" in navigator)) {
    locationText.textContent = "GPS no disponible · selección manual";
    locationResolved = true;
    return;
  }

  locationText.textContent = "Detectando…";
  navigator.geolocation.getCurrentPosition(
    pos => {
      const here = { lat: pos.coords.latitude, lon: pos.coords.longitude };
      const dG = haversineKm(here, COORDS.granollers);
      const dM = haversineKm(here, COORDS.mataro);
      const nearest = Math.min(dG, dM);

      if (nearest > 35) {
        locationText.textContent = "Fuera de Granollers/Mataró · elige trayecto";
      } else if (dG <= dM) {
        locationText.textContent = `Granollers · aprox. ${dG.toFixed(1)} km del centro`;
        setDirection("toMataro");
      } else {
        locationText.textContent = `Mataró · aprox. ${dM.toFixed(1)} km del centro`;
        setDirection("toGranollers");
      }
      locationResolved = true;
    },
    () => {
      locationText.textContent = "Ubicación no disponible · selección manual";
      locationResolved = true;
    },
    { enableHighAccuracy: false, timeout: 8000, maximumAge: 300000 }
  );
}

locateBtn.addEventListener("click", useLocation);
toMataroBtn.addEventListener("click", () => setDirection("toMataro"));
toGranollersBtn.addEventListener("click", () => setDirection("toGranollers"));
originStopSelect.addEventListener("change", () => {
  localStorage.setItem(stopStorageKey("origin"), originStopSelect.value);
  renderTrips();
});
destinationStopSelect.addEventListener("change", () => {
  localStorage.setItem(stopStorageKey("destination"), destinationStopSelect.value);
  renderTrips();
});
prevDateBtn.addEventListener("click", () => shiftSelectedDate(-1));
nextDateBtn.addEventListener("click", () => shiftSelectedDate(1));
todayBtn.addEventListener("click", () => setSelectedDate(new Date(), false));
scheduleDate.addEventListener("change", () => {
  const chosen = selectedServiceDate();
  datePinned = !isSameDay(chosen, new Date());
  renderTrips();
});

scheduleDate.value = dateKey(new Date());
setDirection(direction, false);
renderTrips();
useLocation();

setInterval(renderTrips, 60_000);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js"));
}
