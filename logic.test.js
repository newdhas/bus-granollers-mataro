import test from "node:test";
import assert from "node:assert/strict";
import { TIMETABLES } from "./data.js";
import { getScheduleType, getUpcomingTrips, tripsForDate, makeTripDates } from "./logic.js";

test("un día laborable devuelve cinco próximas salidas ordenadas", () => {
  const now = new Date(2026, 8, 7, 9, 3, 0);
  const trips = getUpcomingTrips(now, "toMataro", 5);
  assert.equal(trips.length, 5);
  assert.ok(trips.every(t => t.departureDate >= now));
  for (let i = 1; i < trips.length; i++) {
    assert.ok(trips[i].departureDate >= trips[i - 1].departureDate);
  }
});

test("la Diada 11/09/2026 usa horario de festivo de verano", () => {
  const date = new Date(2026, 8, 11, 12, 0);
  assert.equal(getScheduleType(date), "summer");
});

test("domingo no incluye expediciones exclusivas de sábado laborable", () => {
  const date = new Date(2026, 8, 6);
  const trips = tripsForDate(date, "toGranollers");
  assert.equal(trips.some(t => t.saturdayOnly), false);
});

test("sábado laborable incluye la expedición marcada para sábado", () => {
  const date = new Date(2026, 8, 5);
  const trips = tripsForDate(date, "toGranollers");
  assert.equal(trips.some(t => t.saturdayOnly), true);
});

test("una llegada pasada medianoche queda en el día siguiente", () => {
  const date = new Date(2026, 8, 5);
  const { departureDate, arrivalDate } = makeTripDates(date, { departure: "23:50", arrival: "00:20" });
  assert.equal(arrivalDate.getDate(), departureDate.getDate() + 1);
});

test("todos los calendarios tienen ambos sentidos, horas válidas y salidas únicas", () => {
  const time = /^\d{2}:\d{2}$/;
  for (const calendar of ["weekday", "summer", "winter"]) {
    for (const direction of ["toMataro", "toGranollers"]) {
      const trips = TIMETABLES[calendar][direction];
      assert.ok(Array.isArray(trips));
      assert.ok(trips.length >= 8);
      assert.equal(new Set(trips.map(t => t.departure)).size, trips.length);
      for (const trip of trips) {
        assert.match(trip.departure, time);
        assert.match(trip.arrival, time);
      }
    }
  }
});
