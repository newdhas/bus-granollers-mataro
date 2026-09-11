#!/usr/bin/env python3
import csv
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone

GTFS_URL = "https://analisi.transparenciacatalunya.cat/download/bca2-b4i3/application/zip"
STATUS_FILE = "official-status.json"
SCHEDULE_FILE = "official-schedule.json"
DATA_FILE = "data.js"
USER_AGENT = "bus-granollers-mataro-checker/2.0 (+https://github.com/newdhas/bus-granollers-mataro)"

# Official stop codes from the Sagalés e13 timetable PDF.
TARGET_STOP_CODES = {
    "granollers_bus": "2365",
    "sant_crist": "9299",
    "mataro_terminal": "3314",
}


def fetch(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), resp.geturl(), dict(resp.headers)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def norm(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.lower().replace("’", "'")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def digits(value):
    return "".join(re.findall(r"\d", value or ""))


def read_csv_from_zip(zf, name):
    with zf.open(name) as raw:
        return list(csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")))


def ymd_to_date(value):
    return datetime.strptime(value, "%Y%m%d").date()


def hhmm(value):
    if not value:
        return None
    parts = value.split(":")
    if len(parts) < 2:
        return None
    return f"{int(parts[0]) % 24:02d}:{int(parts[1]):02d}"


def hhmm_minutes(value):
    h, m = value.split(":")
    return int(h) * 60 + int(m)


def find_route_rows(routes):
    rows = []
    for r in routes:
        short = norm(r.get("route_short_name", ""))
        long_name = norm(r.get("route_long_name", ""))
        if short == "e13" or ("mataro" in long_name and "granollers" in long_name and "sabadell" in long_name):
            rows.append(r)
    if not rows:
        raise RuntimeError("No se ha encontrado la línea e13 en routes.txt")
    return rows


def find_stop_ids(stops):
    found = {k: set() for k in TARGET_STOP_CODES}

    # Primary method: official numeric stop_code from the Sagalés timetable.
    for s in stops:
        sid = s.get("stop_id", "")
        stop_code_digits = digits(s.get("stop_code", ""))
        stop_id_digits = digits(sid)
        for key, code in TARGET_STOP_CODES.items():
            if stop_code_digits == code or stop_code_digits.endswith(code) or stop_id_digits == code or stop_id_digits.endswith(code):
                found[key].add(sid)

    # Name fallback only for any stop code that was not present in this GTFS export.
    for s in stops:
        sid = s.get("stop_id", "")
        name = norm(s.get("stop_name", ""))
        if not found["granollers_bus"] and "granollers" in name and "estacio" in name and ("autobus" in name or "bus" in name):
            found["granollers_bus"].add(sid)
        if not found["sant_crist"] and "sant crist" in name and "cami del mig" in name:
            found["sant_crist"].add(sid)
        if not found["mataro_terminal"] and "mataro" in name and ("rodalies" in name or "renfe" in name or "estacio" in name):
            found["mataro_terminal"].add(sid)

    missing = [k for k, v in found.items() if not v]
    if missing:
        raise RuntimeError(f"No se han localizado las paradas oficiales por código/nombre: {', '.join(missing)}")
    return found


def find_ordered_pair(rows, origin_ids, destination_ids):
    origins = [(seq, st) for seq, st in rows if st.get("stop_id") in origin_ids]
    destinations = [(seq, st) for seq, st in rows if st.get("stop_id") in destination_ids]
    candidates = []
    for oseq, ost in origins:
        for dseq, dst in destinations:
            if dseq > oseq:
                dep = ost.get("departure_time") or ost.get("arrival_time")
                arr = dst.get("arrival_time") or dst.get("departure_time")
                if dep and arr:
                    candidates.append((oseq, dseq, dep, arr))
    return min(candidates, default=None)


def parse_gtfs(blob):
    zf = zipfile.ZipFile(io.BytesIO(blob))
    required = {"routes.txt", "trips.txt", "stop_times.txt", "stops.txt"}
    missing = required - set(zf.namelist())
    if missing:
        raise RuntimeError(f"GTFS incompleto; faltan: {', '.join(sorted(missing))}")

    routes = read_csv_from_zip(zf, "routes.txt")
    trips = read_csv_from_zip(zf, "trips.txt")
    stops = read_csv_from_zip(zf, "stops.txt")
    stop_times = read_csv_from_zip(zf, "stop_times.txt")
    calendar = read_csv_from_zip(zf, "calendar.txt") if "calendar.txt" in zf.namelist() else []
    calendar_dates = read_csv_from_zip(zf, "calendar_dates.txt") if "calendar_dates.txt" in zf.namelist() else []

    route_rows = find_route_rows(routes)
    route_ids = {r.get("route_id") for r in route_rows}
    route_trips = {t.get("trip_id"): t for t in trips if t.get("route_id") in route_ids}
    if not route_trips:
        raise RuntimeError("La e13 existe pero no tiene viajes en trips.txt")

    stop_ids = find_stop_ids(stops)

    by_trip = defaultdict(list)
    for st in stop_times:
        tid = st.get("trip_id")
        if tid not in route_trips:
            continue
        try:
            seq = int(st.get("stop_sequence") or 0)
        except ValueError:
            seq = 0
        by_trip[tid].append((seq, st))
    for rows in by_trip.values():
        rows.sort(key=lambda x: x[0])

    trip_pairs = {}
    for tid, rows in by_trip.items():
        gm = find_ordered_pair(rows, stop_ids["granollers_bus"], stop_ids["mataro_terminal"])
        mg = find_ordered_pair(rows, stop_ids["sant_crist"], stop_ids["granollers_bus"])
        if gm:
            _, _, dep, arr = gm
            trip_pairs[tid] = ("toMataro", dep, arr)
        elif mg:
            _, _, dep, arr = mg
            trip_pairs[tid] = ("toGranollers", dep, arr)

    directions = {v[0] for v in trip_pairs.values()}
    if directions != {"toMataro", "toGranollers"}:
        counts = {d: sum(1 for v in trip_pairs.values() if v[0] == d) for d in ("toMataro", "toGranollers")}
        raise RuntimeError(f"No se han podido identificar ambos sentidos de la e13. Viajes detectados: {counts}; paradas: { {k: sorted(v) for k,v in stop_ids.items()} }")

    service_ids = {route_trips[tid].get("service_id") for tid in trip_pairs}
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    base_calendar = {}
    for row in calendar:
        sid = row.get("service_id")
        if sid not in service_ids:
            continue
        base_calendar[sid] = {
            "start": ymd_to_date(row["start_date"]),
            "end": ymd_to_date(row["end_date"]),
            "days": [row.get(day, "0") == "1" for day in weekdays],
        }

    exceptions = defaultdict(dict)
    for row in calendar_dates:
        sid = row.get("service_id")
        if sid in service_ids:
            exceptions[ymd_to_date(row["date"])][sid] = int(row.get("exception_type") or 0)

    coverage = []
    for info in base_calendar.values():
        coverage.extend([info["start"], info["end"]])
    coverage.extend(exceptions.keys())
    if not coverage:
        raise RuntimeError("No hay calendario de servicio para la e13")

    def active_services(d):
        active = set()
        wd = d.weekday()
        for sid, info in base_calendar.items():
            if info["start"] <= d <= info["end"] and info["days"][wd]:
                active.add(sid)
        for sid, typ in exceptions.get(d, {}).items():
            if typ == 1:
                active.add(sid)
            elif typ == 2:
                active.discard(sid)
        return active

    def schedule_for(d):
        active = active_services(d)
        out = {"toMataro": [], "toGranollers": []}
        seen = {"toMataro": set(), "toGranollers": set()}
        for tid, (direction, dep_raw, arr_raw) in trip_pairs.items():
            if route_trips[tid].get("service_id") not in active:
                continue
            dep, arr = hhmm(dep_raw), hhmm(arr_raw)
            if not dep or not arr:
                continue
            key = (dep, arr)
            if key in seen[direction]:
                continue
            seen[direction].add(key)
            out[direction].append({"departure": dep, "arrival": arr})
        for direction in out:
            out[direction].sort(key=lambda x: hhmm_minutes(x["departure"]))
        return out

    return {
        "route_rows": route_rows,
        "stop_ids": {k: sorted(v) for k, v in stop_ids.items()},
        "trip_counts": {d: sum(1 for v in trip_pairs.values() if v[0] == d) for d in ("toMataro", "toGranollers")},
        "coverage_start": min(coverage),
        "coverage_end": max(coverage),
        "schedule_for": schedule_for,
    }


def parse_reference_data():
    text = open(DATA_FILE, encoding="utf-8").read()
    holidays = set(re.findall(r'"(20\d\d-\d\d-\d\d)"', text.split("export const HOLIDAY_YEARS", 1)[0]))
    result = {}
    for schedule_type in ("weekday", "summer", "winter"):
        start = text.find(f"  {schedule_type}: {{")
        if start < 0:
            raise RuntimeError(f"No se puede leer {schedule_type} de data.js")
        candidates = [p for p in [text.find("  weekday: {", start + 1), text.find("  summer: {", start + 1), text.find("  winter: {", start + 1), text.find("\n};", start + 1)] if p >= 0]
        end = min(candidates) if candidates else len(text)
        block = text[start:end]
        m = re.search(r'toMataro:\s*\[(.*?)\],\s*toGranollers:\s*\[(.*?)\]', block, re.S)
        if not m:
            raise RuntimeError(f"No se pueden leer los sentidos de {schedule_type}")
        result[schedule_type] = {}
        for direction, arr_text in (("toMataro", m.group(1)), ("toGranollers", m.group(2))):
            result[schedule_type][direction] = [
                {"departure": dep, "arrival": arr, "saturdayOnly": sat == "true"}
                for dep, arr, sat in re.findall(r'p\("(\d\d:\d\d)","(\d\d:\d\d)"(?:,(true))?\)', arr_text)
            ]
    return holidays, result


def reference_schedule_for(d, holidays, tables):
    holiday = d.isoformat() in holidays
    weekend = d.weekday() >= 5 or holiday
    kind = "weekday" if not weekend else ("summer" if 6 <= d.month <= 9 else "winter")
    working_saturday = d.weekday() == 5 and not holiday
    out = {}
    for direction, trips in tables[kind].items():
        out[direction] = [
            {"departure": t["departure"], "arrival": t["arrival"]}
            for t in trips if not t["saturdayOnly"] or working_saturday
        ]
    return kind, out


def main():
    now = datetime.now(timezone.utc)
    today = datetime.now().astimezone().date()
    status = {
        "checked_at": now.isoformat().replace("+00:00", "Z"),
        "state": "error",
        "alert": True,
        "gtfs": {"url": GTFS_URL},
    }

    try:
        blob, final_url, _ = fetch(GTFS_URL)
        gtfs = parse_gtfs(blob)
        holidays, tables = parse_reference_data()

        checks = []
        for i in range(35):
            d = today + timedelta(days=i)
            if not (gtfs["coverage_start"] <= d <= gtfs["coverage_end"]):
                continue
            kind, reference = reference_schedule_for(d, holidays, tables)
            official = gtfs["schedule_for"](d)
            checks.append({
                "date": d.isoformat(),
                "reference_type": kind,
                "match": official == reference,
                "official_counts": {k: len(v) for k, v in official.items()},
                "reference_counts": {k: len(v) for k, v in reference.items()},
            })

        covered = gtfs["coverage_start"] <= today <= gtfs["coverage_end"]
        all_match = bool(checks) and all(x["match"] for x in checks)

        status["gtfs"].update({
            "resolved_url": final_url,
            "sha256": sha256(blob),
            "coverage_start": gtfs["coverage_start"].isoformat(),
            "coverage_end": gtfs["coverage_end"].isoformat(),
            "current_date_covered": covered,
            "matched_stop_ids": gtfs["stop_ids"],
            "trip_counts": gtfs["trip_counts"],
            "comparison": checks,
            "matches_reference": all_match,
        })

        dates = {}
        start = max(today - timedelta(days=1), gtfs["coverage_start"])
        end = min(today + timedelta(days=400), gtfs["coverage_end"])
        d = start
        while d <= end:
            sched = gtfs["schedule_for"](d)
            if sched["toMataro"] or sched["toGranollers"]:
                dates[d.isoformat()] = sched
            d += timedelta(days=1)

        usable = bool(covered and all_match)
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as fh:
            json.dump({
                "generated_at": status["checked_at"],
                "source": "Generalitat de Catalunya · GTFS",
                "source_url": GTFS_URL,
                "gtfs_sha256": status["gtfs"]["sha256"],
                "coverage_start": gtfs["coverage_start"].isoformat(),
                "coverage_end": gtfs["coverage_end"].isoformat(),
                "usable": usable,
                "dates": dates,
            }, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")

        if not covered:
            status["state"] = "stale_gtfs"
            status["message"] = "El GTFS oficial no cubre la fecha actual; se mantiene el horario verificado del PDF de Sagalés."
        elif not all_match:
            first_bad = next((x for x in checks if not x["match"]), None)
            status["state"] = "mismatch"
            status["message"] = f"El GTFS oficial difiere del horario verificado. Primera diferencia: {first_bad}."
        else:
            status["state"] = "ok"
            status["alert"] = False
            status["message"] = "GTFS oficial y horario verificado coinciden. El snapshot oficial es seguro para la web."

    except Exception as exc:
        status["state"] = "error"
        status["message"] = f"Error comprobando GTFS oficial: {exc}"
        status["error"] = repr(exc)

    with open(STATUS_FILE, "w", encoding="utf-8") as fh:
        json.dump(status, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")

    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
