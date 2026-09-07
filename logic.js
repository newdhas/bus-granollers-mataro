
import { HOLIDAYS, TIMETABLES } from "./data.js";

export function dateKey(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function isHoliday(date) {
  return HOLIDAYS.has(dateKey(date));
}

export function getScheduleType(date) {
  const day = date.getDay();
  const weekendOrHoliday = day === 0 || day === 6 || isHoliday(date);
  if (!weekendOrHoliday) return "weekday";

  const month = date.getMonth() + 1;
  return month >= 6 && month <= 9 ? "summer" : "winter";
}

export function getCalendarLabel(date) {
  const type = getScheduleType(date);
  if (type === "weekday") return "Laborable";
  return type === "summer"
    ? "Fin de semana/festivo · verano"
    : "Fin de semana/festivo · invierno";
}

function timeParts(value) {
  const [h, m] = value.split(":").map(Number);
  return { h, m, minutes: h * 60 + m };
}

export function makeTripDates(serviceDate, trip) {
  const dep = timeParts(trip.departure);
  const arr = timeParts(trip.arrival);

  const departureDate = new Date(serviceDate);
  departureDate.setHours(dep.h, dep.m, 0, 0);

  const arrivalDate = new Date(serviceDate);
  arrivalDate.setHours(arr.h, arr.m, 0, 0);
  if (arr.minutes < dep.minutes) arrivalDate.setDate(arrivalDate.getDate() + 1);

  return { departureDate, arrivalDate };
}

export function tripsForDate(serviceDate, direction) {
  const type = getScheduleType(serviceDate);
  const isSaturdayWorking = serviceDate.getDay() === 6 && !isHoliday(serviceDate);

  return TIMETABLES[type][direction]
    .filter(trip => !trip.saturdayOnly || isSaturdayWorking)
    .map(trip => ({ ...trip, ...makeTripDates(serviceDate, trip), scheduleType: type }));
}

export function getUpcomingTrips(now, direction, count = 5) {
  const result = [];

  for (let offset = 0; offset < 8 && result.length < count; offset++) {
    const serviceDate = new Date(now);
    serviceDate.setHours(0, 0, 0, 0);
    serviceDate.setDate(serviceDate.getDate() + offset);

    for (const trip of tripsForDate(serviceDate, direction)) {
      if (trip.departureDate >= now) {
        result.push({ ...trip, serviceDate: new Date(serviceDate) });
        if (result.length >= count) break;
      }
    }
  }

  return result;
}

export function minutesUntil(now, future) {
  return Math.max(0, Math.ceil((future - now) / 60000));
}
