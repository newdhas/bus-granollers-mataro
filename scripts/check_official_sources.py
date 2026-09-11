#!/usr/bin/env python3
import csv
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

GTFS_URL = "https://analisi.transparenciacatalunya.cat/download/bca2-b4i3/application/zip"
SAGALES_URL = "https://www.sagales.com/es/lineas/4?origenCL=34&destiCL=65#"
STATUS_FILE = "official-status.json"
SCHEDULE_FILE = "official-schedule.json"
DATA_FILE = "data.js"
USER_AGENT = "bus-granollers-mataro-checker/1.0 (+https://github.com/newdhas/bus-granollers-mataro)"


def fetch(url, timeout=60):
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


def read_csv_from_zip(zf, name):
    with zf.open(name) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        return list(csv.DictReader(text))


def ymd_to_date(value):
    return datetime.strptime(value, "%Y%m%d").date()


def time_hhmm(value):
    if not value:
        return None
    parts = value.split(":")
    if len(parts) < 2:
        return None
    hour, minute = int(parts[0]), int(parts[1])
    return f"{hour % 24:02d}:{minute:02d}"


def time_minutes(value):
    parts = value.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def find_stop_ids(stops):
    found = {"granollers_bus": set(), "sant_crist": set(), "mataro_terminal": set()}
    names = defaultdict(list)
    for s in stops:
        sid = s.get("stop_id", "")
        n = norm(s.get("stop_name", ""))
        names[n].append(sid)
        if "granollers" in n and "estacio" in n and ("autobus" in n or "bus" in n):
            found["granollers_bus"].add(sid)
        if "sant crist" in n and "cami del mig" in n:
            found["sant_crist"].add(sid)
        if "mataro" in n and ("renfe" in n or "rodalies" in n or ("estacio" in n and "ferroc" in n)):
            found["mataro_terminal"].add(sid)

    # Fallbacks for common naming variants.
    if not found["granollers_bus"]:
        for n, ids in names.items():
            if "granollers" in n and "autobus" in n:
                found["granollers_bus"].update(ids)
    if not found["sant_crist"]:
        for n, ids in names.items():
            if "sant crist" in n:
                found["sant_crist"].update(ids)
    if not found["mataro_terminal"]:
        for n, ids in names.items():
            if "mataro" in n and ("renfe" in n or "estacio" in n):
                found["mataro_terminal"].update(ids)
    return found


def parse_gtfs(zip_bytes):
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
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

    route_rows = []
    for r in routes:
        short = norm(r.get("route_short_name", ""))
        long_name = norm(r.get("route_long_name", ""))
        if short in {"e13", "13"} or ("mataro" in long_name and "granollers" in long_name and "sabadell" in long_name):
            route_rows.append(r)
    if not route_rows:
        raise RuntimeError("No se ha encontrado la línea e13 en routes.txt")

    route_ids = {r["route_id"] for r in route_rows}
    route_trips = {t["trip_id"]: t for t in trips if t.get("route_id") in route_ids}
    if not route_trips:
        raise RuntimeError("La e13 existe pero no tiene viajes en trips.txt")

    stop_ids = find_stop_ids(stops)
    for key, ids in stop_ids.items():
        if not ids:
            raise RuntimeError(f"No se ha localizado la parada requerida: {key}")

    by_trip = defaultdict(list)
    relevant_trip_ids = set(route_trips)
    for st in stop_times:
        tid = st.get("trip_id")
        if tid in relevant_trip_ids:
            try:
                seq = int(st.get("stop_sequence") or 0)
            except ValueError:
                seq = 0
            by_trip[tid].append((seq, st))
    for rows in by_trip.values():
        rows.sort(key=lambda x: x[0])

    trip_pairs = {}
    for tid, rows in by_trip.items():
        positions = defaultdict(list)
        for seq, st in rows:
            sid = st.get("stop_id")
            for key, ids in stop_ids.items():
                if sid in ids:
                    positions[key].append((seq, st))

        def first_after(origin_key, destination_key):
            candidates = []
            for oseq, ost in positions.get(origin_key, []):
                for dseq, dst in positions.get(destination_key, []):
                    if dseq > oseq:
                        dep = ost.get("departure_time") or ost.get("arrival_time")
                        arr = dst.get("arrival_time") or dst.get("departure_time")
                        if dep and arr:
                            candidates.append((oseq, dseq, dep, arr))
            return sorted(candidates)[0] if candidates else None

        to_mataro = first_after("granollers_bus", "mataro_terminal")
        to_granollers = first_after("sant_crist", "granollers_bus")
        pair = None
        if to_mataro:
            _, _, dep, arr = to_mataro
            pair = ("toMataro", dep, arr)
        elif to_granollers:
            _, _, dep, arr = to_granollers
            pair = ("toGranollers", dep, arr)
        if pair:
            trip_pairs[tid] = pair

    if not any(v[0] == "toMataro" for v in trip_pairs.values()) or not any(v[0] == "toGranollers" for v in trip_pairs.values()):
        raise RuntimeError("No se han podido identificar ambos sentidos de la e13")

    service_ids = {route_trips[tid].get("service_id") for tid in trip_pairs}
    base_calendar = {}
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
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

    coverage_dates = []
    for info in base_calendar.values():
        coverage_dates.extend([info["start"], info["end"]])
    coverage_dates.extend(exceptions.keys())
    if not coverage_dates:
        raise RuntimeError("No hay calendario de servicio para la e13")

    def active_services(d):
        active = set()
        weekday = d.weekday()
        for sid, info in base_calendar.items():
            if info["start"] <= d <= info["end"] and info["days"][weekday]:
                active.add(sid)
        for sid, exception_type in exceptions.get(d, {}).items():
            if exception_type == 1:
                active.add(sid)
            elif exception_type == 2:
                active.discard(sid)
        return active

    def schedule_for(d):
        active = active_services(d)
        out = {"toMataro": [], "toGranollers": []}
        seen = {"toMataro": set(), "toGranollers": set()}
        for tid, (direction, dep_raw, arr_raw) in trip_pairs.items():
            if route_trips[tid].get("service_id") not in active:
                continue
            dep, arr = time_hhmm(dep_raw), time_hhmm(arr_raw)
            if not dep or not arr:
                continue
            key = (dep, arr)
            if key not in seen[direction]:
                seen[direction].add(key)
                out[direction].append({"departure": dep, "arrival": arr})
        for direction in out:
            out[direction].sort(key=lambda x: time_minutes(x["departure"]))
        return out

    return {
        "route_rows": route_rows,
        "stop_ids": {k: sorted(v) for k, v in stop_ids.items()},
        "coverage_start": min(coverage_dates),
        "coverage_end": max(coverage_dates),
        "schedule_for": schedule_for,
    }


def parse_reference_data(path=DATA_FILE):
    text = open(path, encoding="utf-8").read()
    holidays = set(re.findall(r'"(20\d\d-\d\d-\d\d)"', text.split("export const HOLIDAY_YEARS", 1)[0]))
    result = {}
    for schedule_type in ("weekday", "summer", "winter"):
        start = text.find(f"  {schedule_type}: {{")
        if start < 0:
            raise RuntimeError(f"No se puede leer {schedule_type} de data.js")
        next_positions = [p for p in [text.find("  weekday: {", start + 1), text.find("  summer: {", start + 1), text.find("  winter: {", start + 1), text.find("\n};", start + 1)] if p >= 0]
        end = min(next_positions) if next_positions else len(text)
        block = text[start:end]
        m = re.search(r'toMataro:\s*\[(.*?)\],\s*toGranollers:\s*\[(.*?)\]', block, re.S)
        if not m:
            raise RuntimeError(f"No se pueden leer los sentidos de {schedule_type}")
        result[schedule_type] = {}
        for direction, arr_text in (("toMataro", m.group(1)), ("toGranollers", m.group(2))):
            trips = []
            for dep, arr, saturday in re.findall(r'p\("(\d\d:\d\d)","(\d\d:\d\d)"(?:,(true))?\)', arr_text):
                trips.append({"departure": dep, "arrival": arr, "saturdayOnly": saturday == "true"})
            result[schedule_type][direction] = trips
    return holidays, result


def reference_schedule_for(d, holidays, tables):
    is_holiday = d.isoformat() in holidays
    weekend = d.weekday() >= 5 or is_holiday
    if not weekend:
        schedule_type = "weekday"
    else:
        schedule_type = "summer" if 6 <= d.month <= 9 else "winter"
    saturday_working = d.weekday() == 5 and not is_holiday
    out = {}
    for direction, trips in tables[schedule_type].items():
        out[direction] = [
            {"departure": t["departure"], "arrival": t["arrival"]}
            for t in trips if not t["saturdayOnly"] or saturday_working
        ]
    return schedule_type, out


def compare_schedules(gtfs, holidays, tables, today):
    checks = []
    # Compare a useful window spanning weekdays/weekends and the Oct seasonal boundary.
    candidate_dates = [today + timedelta(days=i) for i in range(0, 35)]
    for d in candidate_dates:
        if not (gtfs["coverage_start"] <= d <= gtfs["coverage_end"]):
            continue
        schedule_type, reference = reference_schedule_for(d, holidays, tables)
        official = gtfs["schedule_for"](d)
        # Empty official schedule on a date where our reference has service is meaningful.
        same = official == reference
        checks.append({
            "date": d.isoformat(),
            "reference_type": schedule_type,
            "match": same,
            "official_counts": {k: len(v) for k, v in official.items()},
            "reference_counts": {k: len(v) for k, v in reference.items()},
        })
    return checks


def discover_sagales_pdf():
    html_bytes, final_url, _ = fetch(SAGALES_URL, timeout=45)
    html = html_bytes.decode("utf-8", errors="replace")
    low = norm(html)
    # Keep a page hash as diagnostic, but alerting is based on the timetable PDF hash when found.
    page_hash = sha256(html_bytes)
    raw_lower = html.lower()
    idx = raw_lower.find("e13")
    segment = html[idx:idx + 20000] if idx >= 0 else html
    hrefs = re.findall(r'href\s*=\s*["\']([^"\']+)["\']', segment, flags=re.I)
    candidates = []
    for href in hrefs:
        h = href.lower()
        if ".pdf" in h or "horari" in h or "schedule" in h:
            candidates.append(urllib.parse.urljoin(final_url, href))
    pdf_url = candidates[0] if candidates else None
    pdf_hash = None
    if pdf_url:
        try:
            pdf_bytes, pdf_final, _ = fetch(pdf_url, timeout=60)
            if pdf_bytes.startswith(b"%PDF"):
                pdf_url = pdf_final
                pdf_hash = sha256(pdf_bytes)
        except Exception:
            pass
    return {"page_sha256": page_hash, "pdf_url": pdf_url, "pdf_sha256": pdf_hash}


def main():
    previous = {}
    if os.path.exists(STATUS_FILE):
        try:
            previous = json.load(open(STATUS_FILE, encoding="utf-8"))
        except Exception:
            previous = {}

    now = datetime.now(timezone.utc)
    today = datetime.now().astimezone().date()
    status = {
        "checked_at": now.isoformat().replace("+00:00", "Z"),
        "state": "error",
        "alert": False,
        "gtfs": {"url": GTFS_URL},
        "sagales": {"url": SAGALES_URL},
    }

    try:
        gtfs_bytes, gtfs_final_url, headers = fetch(GTFS_URL, timeout=90)
        gtfs_hash = sha256(gtfs_bytes)
        gtfs = parse_gtfs(gtfs_bytes)
        holidays, tables = parse_reference_data()
        checks = compare_schedules(gtfs, holidays, tables, today)
        all_match = bool(checks) and all(c["match"] for c in checks)
        current_covered = gtfs["coverage_start"] <= today <= gtfs["coverage_end"]

        status["gtfs"].update({
            "resolved_url": gtfs_final_url,
            "sha256": gtfs_hash,
            "coverage_start": gtfs["coverage_start"].isoformat(),
            "coverage_end": gtfs["coverage_end"].isoformat(),
            "current_date_covered": current_covered,
            "route": [
                {"route_id": r.get("route_id"), "short_name": r.get("route_short_name"), "long_name": r.get("route_long_name")}
                for r in gtfs["route_rows"]
            ],
            "matched_stop_ids": gtfs["stop_ids"],
            "comparison": checks,
            "matches_reference": all_match,
        })

        # Generate a compact date-specific snapshot. It is only marked usable after matching
        # our currently verified PDF-derived timetable over the comparison window.
        dates = {}
        start = max(today - timedelta(days=1), gtfs["coverage_start"])
        end = min(today + timedelta(days=400), gtfs["coverage_end"])
        d = start
        while d <= end:
            sched = gtfs["schedule_for"](d)
            if sched["toMataro"] or sched["toGranollers"]:
                dates[d.isoformat()] = sched
            d += timedelta(days=1)

        schedule_doc = {
            "generated_at": status["checked_at"],
            "source": "Generalitat de Catalunya · Mou-te GTFS",
            "source_url": GTFS_URL,
            "gtfs_sha256": gtfs_hash,
            "coverage_start": gtfs["coverage_start"].isoformat(),
            "coverage_end": gtfs["coverage_end"].isoformat(),
            "usable": bool(current_covered and all_match),
            "dates": dates,
        }
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as fh:
            json.dump(schedule_doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")

        sagales = discover_sagales_pdf()
        status["sagales"].update(sagales)

        old_gtfs_hash = previous.get("gtfs", {}).get("sha256")
        old_pdf_hash = previous.get("sagales", {}).get("pdf_sha256")
        gtfs_changed = bool(old_gtfs_hash and old_gtfs_hash != gtfs_hash)
        pdf_changed = bool(old_pdf_hash and sagales.get("pdf_sha256") and old_pdf_hash != sagales.get("pdf_sha256"))
        status["changes"] = {"gtfs_changed": gtfs_changed, "sagales_pdf_changed": pdf_changed}

        if not current_covered:
            status["state"] = "stale_gtfs"
            status["message"] = "El GTFS oficial no cubre la fecha actual; se mantiene el horario verificado del PDF de Sagalés."
            status["alert"] = True
        elif not all_match:
            status["state"] = "mismatch"
            status["message"] = "El GTFS oficial difiere del horario actualmente verificado; no se activa automáticamente."
            status["alert"] = True
        else:
            status["state"] = "ok"
            status["message"] = "GTFS oficial y horario verificado coinciden; el snapshot oficial puede usarse con seguridad."
            status["alert"] = bool(gtfs_changed or pdf_changed)

        if pdf_changed:
            status["message"] += " Se ha detectado un cambio en el PDF oficial de Sagalés."

    except Exception as exc:
        status["state"] = "error"
        status["message"] = f"Error comprobando fuentes oficiales: {exc}"
        status["alert"] = True
        status["error"] = repr(exc)

    with open(STATUS_FILE, "w", encoding="utf-8") as fh:
        json.dump(status, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")

    print(json.dumps(status, ensure_ascii=False, indent=2))
    # Do not fail the workflow for stale/mismatch; the workflow will open an issue and
    # keep the known-good timetable online. Only unexpected script crashes are represented
    # in status.json and still committed for diagnosis.
    return 0


if __name__ == "__main__":
    sys.exit(main())
