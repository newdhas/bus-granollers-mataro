
import { COORDS, ROUTES, HOLIDAY_YEARS } from "./data.js";
import { getUpcomingTrips, getCalendarLabel, minutesUntil } from "./logic.js";

const $ = (id) => document.getElementById(id);

const clock = $("clock");
const locationText = $("locationText");
const locateBtn = $("locateBtn");
const toMataroBtn = $("toMataroBtn");
const toGranollersBtn = $("toGranollersBtn");
const originName = $("originName");
const destinationName = $("destinationName");
const calendarChip = $("calendarChip");
const calendarWarning = $("calendarWarning");
const results = $("results");

let direction = localStorage.getItem("busDirection") || "toMataro";
let locationResolved = false;

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

function setDirection(nextDirection, render = true) {
  direction = nextDirection;
  localStorage.setItem("busDirection", direction);

  toMataroBtn.classList.toggle("active", direction === "toMataro");
  toGranollersBtn.classList.toggle("active", direction === "toGranollers");

  const route = ROUTES[direction];
  originName.textContent = route.origin;
  destinationName.textContent = route.destination;

  if (render) renderTrips();
}

function renderTrips() {
  const now = new Date();
  clock.textContent = formatTime(now);

  const trips = getUpcomingTrips(now, direction, 5);

  const todayCalendar = getCalendarLabel(now);
  const tomorrowTrip = trips.find(trip => dayLabel(trip.departureDate, now) === "mañana");
  if (tomorrowTrip) {
    const tomorrowCalendar = getCalendarLabel(tomorrowTrip.departureDate);
    calendarChip.textContent = tomorrowCalendar === todayCalendar
      ? `Hoy y mañana: ${todayCalendar}`
      : `Hoy: ${todayCalendar} · Mañana: ${tomorrowCalendar}`;
  } else {
    calendarChip.textContent = `Hoy: ${todayCalendar}`;
  }

  if (!HOLIDAY_YEARS.has(now.getFullYear())) {
    calendarWarning.textContent = `Aviso: los festivos automáticos de ${now.getFullYear()} no están cargados; sábados y domingos sí se detectan correctamente.`;
    calendarWarning.classList.remove("hidden");
  } else {
    calendarWarning.classList.add("hidden");
  }

  if (!trips.length) {
    results.innerHTML = `<div class="empty">No se han encontrado próximas expediciones en los próximos días.</div>`;
    return;
  }

  const first = trips[0];
  const firstDay = dayLabel(first.departureDate, now);
  const firstTag = firstDay === "hoy" ? "" : `<span class="day-tag">${firstDay}</span>`;

  const rows = trips.slice(1).map(trip => `
    <article class="trip-row">
      <div>
        <div class="trip-time">${formatTime(trip.departureDate)}</div>
        ${dayLabel(trip.departureDate, now) === "hoy" ? "" : `<span class="day-tag">${dayLabel(trip.departureDate, now)}</span>`}
      </div>
      <div class="trip-countdown">${countdownText(now, trip.departureDate)}</div>
      <div class="trip-arrival">
        <span>Llegada</span>
        <strong>${formatTime(trip.arrivalDate)}</strong>
      </div>
    </article>
  `).join("");

  results.innerHTML = `
    <article class="next-card">
      <div class="next-label">PRÓXIMO</div>
      <div class="next-main">
        <div>
          <div class="next-time">${formatTime(first.departureDate)}</div>
          <div class="countdown">${countdownText(now, first.departureDate)} ${firstTag}</div>
        </div>
        <div class="arrival">
          <span>Llegada</span>
          <strong>${formatTime(first.arrivalDate)}</strong>
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

setDirection(direction, false);
renderTrips();
useLocation();

setInterval(renderTrips, 60_000);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js"));
}
