import test from "node:test";
import assert from "node:assert/strict";
import { getScheduleType, getUpcomingTrips, tripsForDate, makeTripDates } from "./logic.js";

test("lunes laborable 07/09/2026 a las 09:03: próximos Granollers→Mataró", () => {
  const now = new Date(2026, 8, 7, 9, 3, 0);
  const trips = getUpcomingTrips(now, "toMataro", 5);
  assert.deepEqual(trips.map(t => t.departure), ["09:12","09:42","09:53","10:06","10:16"]);
});

test("festivo 11/09/2026 usa horario verano de fin de semana", () => {
  const d = new Date(2026, 8, 11, 12, 0);
  assert.equal(getScheduleType(d), "summer");
});

test("domingo no incluye saturdayOnly", () => {
  const d = new Date(2026, 8, 6);
  const trips = tripsForDate(d, "toMataro");
  assert.equal(trips.some(t => t.saturdayOnly), false);
});

test("sábado laborable incluye saturdayOnly", () => {
  const d = new Date(2026, 8, 5);
  const trips = tripsForDate(d, "toMataro");
  assert.equal(trips.some(t => t.departure === "23:50" && t.saturdayOnly), true);
});

test("23:50→00:20 llega al día siguiente", () => {
  const d = new Date(2026, 8, 5);
  const { departureDate, arrivalDate } = makeTripDates(d, { departure:"23:50", arrival:"00:20" });
  assert.equal(arrivalDate.getDate(), departureDate.getDate() + 1);
});
