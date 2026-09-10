#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import pymupdf
import requests
from bs4 import BeautifulSoup

LINE_PAGE = "https://www.sagales.com/es/linia/555"
PDF_RESOLVER = "https://www.sagales.com/front/js-nexus/planificador/pdf.php"
USER_AGENT = "Mozilla/5.0 (compatible; e13-timetable-monitor/1.2; +https://github.com/newdhas/bus-granollers-mataro)"
TIME_RE = re.compile(r"^(?:\d{1,2}\.\d{2}|-)$")
CODE_RE = re.compile(r"^\d{4}$")
LEFT_CODES = ["3314", "9735", "9299", "2365", "9458", "4925", "4930", "8804", "2929"]
RIGHT_CODES = ["2929", "2931", "2932", "9458", "2365", "9323", "3630", "3237", "3314"]
BLUE_TARGET = (0.74, 0.894, 0.968)
BASELINE_SCHEDULE_SHA256 = "3e29755acc20c2631b1c34e11f4b544c252085309426ef3e3f2a44cc97d1c132"


class MonitorError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def action_output(name: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")
    else:
        print(f"OUTPUT {name}={value}")


def fetch(session: requests.Session, url: str, **kwargs: Any) -> requests.Response:
    response = session.get(url, timeout=30, allow_redirects=True, **kwargs)
    response.raise_for_status()
    return response


def resolve_official_pdf(session: requests.Session) -> tuple[str, bytes, str]:
    """Use the same endpoint as Sagalés' 'Horarios (pdf)' button.

    The public line page calls:
      pdfBus('555','-1','es')
    which in turn requests pdf.php?id=555&ids=-1&idioma=es.
    The response contains the current timetable attachment and description.
    """
    response = fetch(
        session,
        PDF_RESOLVER,
        params={"id": "555", "ids": "-1", "idioma": "es", "nocache": str(time.time())},
        headers={"Referer": LINE_PAGE},
    )
    soup = BeautifulSoup(response.text, "html.parser")
    candidates: list[tuple[int, str, str]] = []

    for tag in soup.find_all(["a", "iframe", "embed", "object"]):
        raw = tag.get("href") or tag.get("src") or tag.get("data")
        if not raw:
            continue
        url = urljoin(response.url, raw)
        text = " ".join(tag.stripped_strings).strip()
        haystack = f"{url} {text}".lower()
        score = 0
        if ".pdf" in url.lower():
            score += 50
        if "e13" in haystack:
            score += 100
        if "sabadell" in haystack and "granollers" in haystack and ("matar" in haystack):
            score += 80
        candidates.append((score, url, text))

    # The resolver currently exposes fichero_N inside a hidden <pre> too.
    # Keep this fallback so a small HTML template change does not break monitoring.
    for filename in re.findall(r"([A-Za-z0-9._-]+\.pdf)", response.text, re.I):
        candidates.append((40, urljoin("https://www.sagales.com/uploads/imagenes/", filename), ""))

    seen: set[str] = set()
    errors: list[str] = []
    for _score, url, label in sorted(candidates, reverse=True):
        if url in seen:
            continue
        seen.add(url)
        try:
            pdf = fetch(session, url, headers={"Referer": LINE_PAGE})
            ctype = pdf.headers.get("content-type", "").lower()
            if pdf.content.startswith(b"%PDF-") or "application/pdf" in ctype:
                return pdf.url, pdf.content, label
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    detail = " | ".join(errors[-4:])
    raise MonitorError("El botón oficial de horarios no ha devuelto un PDF descargable." + (f" {detail}" if detail else ""))


def is_blue(fill: Any) -> bool:
    if not fill or len(fill) < 3:
        return False
    distance = sum((float(fill[i]) - BLUE_TARGET[i]) ** 2 for i in range(3)) ** 0.5
    return distance < 0.16


def group_by_y(items: list[tuple[float, float, str]], tolerance: float) -> list[list[tuple[float, float, str]]]:
    groups: list[list[tuple[float, float, str]]] = []
    for item in sorted(items):
        if not groups:
            groups.append([item])
            continue
        mean_y = statistics.mean(x[0] for x in groups[-1])
        if abs(item[0] - mean_y) > tolerance:
            groups.append([item])
        else:
            groups[-1].append(item)
    return groups


def half_rows(page: pymupdf.Page, left: bool) -> list[tuple[list[str | None], bool]]:
    code_words: list[tuple[float, float, str]] = []
    time_words: list[tuple[float, float, str]] = []

    for word in page.get_text("words"):
        x0, y0, x1, _y1, text, *_ = word
        x = (x0 + x1) / 2
        in_half = x < page.rect.width / 2 if left else x > page.rect.width / 2
        if not in_half:
            continue
        if CODE_RE.fullmatch(text):
            code_words.append((y0, x, text))
        if TIME_RE.fullmatch(text):
            time_words.append((y0, x, text))

    code_groups = group_by_y(code_words, 3.0)
    if not code_groups:
        raise MonitorError("No se ha encontrado la fila de códigos de parada")

    code_group = sorted(max(code_groups, key=len), key=lambda x: x[1])
    codes = [x[2] for x in code_group]
    expected = LEFT_CODES if left else RIGHT_CODES
    if codes[:9] != expected:
        raise MonitorError(f"Ha cambiado la estructura de paradas: {codes[:9]} != {expected}")
    centers = [x[1] for x in code_group[:9]]

    blue_rects = []
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if rect and rect.width > 100 and rect.height > 5 and is_blue(drawing.get("fill")):
            blue_rects.append(rect)

    rows: list[tuple[list[str | None], bool]] = []
    for group in group_by_y(time_words, 4.0):
        cols: list[str | None] = [None] * 9
        mean_y = statistics.mean(x[0] for x in group)
        for _y, x, text in group:
            idx = min(range(9), key=lambda i: abs(x - centers[i]))
            if abs(x - centers[idx]) < 28:
                cols[idx] = text
        if sum(v is not None for v in cols) < 2:
            continue
        saturday_only = any(
            rect.y0 - 4 <= mean_y <= rect.y1 + 4
            and ((left and rect.x0 < page.rect.width / 2) or ((not left) and rect.x1 > page.rect.width / 2))
            for rect in blue_rects
        )
        rows.append((cols, saturday_only))
    return rows


def norm_time(value: str | None) -> str | None:
    if not value or value == "-":
        return None
    hour, minute = (int(x) for x in value.split("."))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise MonitorError(f"Hora no válida: {value}")
    return f"{hour:02d}:{minute:02d}"


def extract_route(page: pymupdf.Page, left: bool, dep_col: int, arr_col: int) -> list[dict[str, Any]]:
    trips: list[dict[str, Any]] = []
    for cols, saturday_only in half_rows(page, left):
        departure = norm_time(cols[dep_col])
        arrival = norm_time(cols[arr_col])
        if departure and arrival:
            trips.append({"departure": departure, "arrival": arrival, "saturdayOnly": bool(saturday_only)})
    return trips


def minutes(value: str) -> int:
    h, m = (int(x) for x in value.split(":"))
    return h * 60 + m


def validate_timetables(data: dict[str, Any], doc: pymupdf.Document) -> None:
    if doc.page_count < 3:
        raise MonitorError(f"PDF inesperado: {doc.page_count} páginas")

    texts = [doc[i].get_text().lower() for i in range(3)]
    if "dilluns a divendres" not in texts[0]:
        raise MonitorError("La página 1 ya no parece ser el horario laborable")
    if "1 de juny" not in texts[1] or "30 setembre" not in texts[1]:
        raise MonitorError("La página 2 ya no parece ser el horario junio-septiembre")
    if ("1 d’octubre" not in texts[2] and "1 d'octubre" not in texts[2]) or "31 de maig" not in texts[2]:
        raise MonitorError("La página 3 ya no parece ser el horario octubre-mayo")

    ranges = {"weekday": (20, 80), "summer": (8, 50), "winter": (8, 50)}
    for calendar, directions in data.items():
        low, high = ranges[calendar]
        for direction, trips in directions.items():
            if not (low <= len(trips) <= high):
                raise MonitorError(f"Número de expediciones sospechoso en {calendar}/{direction}: {len(trips)}")
            departures = [minutes(t["departure"]) for t in trips]
            if departures != sorted(departures) or len(departures) != len(set(departures)):
                raise MonitorError(f"Salidas desordenadas o duplicadas en {calendar}/{direction}")
            for trip in trips:
                dep = minutes(trip["departure"])
                arr = minutes(trip["arrival"])
                if arr < dep:
                    arr += 1440
                if not (15 <= arr - dep <= 65):
                    raise MonitorError(f"Duración sospechosa en {calendar}/{direction}: {trip}")

    # En el formato actual hay una fila azul (solo sábado laborable) por sentido
    # en cada tabla de fin de semana. Si Sagalés cambia ese formato, no se publica.
    for calendar in ("summer", "winter"):
        for direction in ("toMataro", "toGranollers"):
            marked = sum(1 for trip in data[calendar][direction] if trip["saturdayOnly"])
            if marked != 1:
                raise MonitorError(f"Marcado de sábado inesperado en {calendar}/{direction}: {marked}")


def parse_pdf(pdf_bytes: bytes) -> dict[str, Any]:
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise MonitorError(f"No se puede abrir el PDF: {exc}") from exc

    data = {
        "weekday": {
            "toMataro": extract_route(doc[0], left=False, dep_col=4, arr_col=8),
            "toGranollers": extract_route(doc[0], left=True, dep_col=2, arr_col=3),
        },
        "summer": {
            "toMataro": extract_route(doc[1], left=False, dep_col=4, arr_col=8),
            "toGranollers": extract_route(doc[1], left=True, dep_col=2, arr_col=3),
        },
        "winter": {
            "toMataro": extract_route(doc[2], left=False, dep_col=4, arr_col=8),
            "toGranollers": extract_route(doc[2], left=True, dep_col=2, arr_col=3),
        },
    }
    validate_timetables(data, doc)
    return data


def schedule_hash(data: dict[str, Any]) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def render_timetables(data: dict[str, Any]) -> str:
    lines = ["export const TIMETABLES = {"]
    for calendar in ("weekday", "summer", "winter"):
        lines.append(f"  {calendar}: {{")
        for direction in ("toMataro", "toGranollers"):
            lines.append(f"    {direction}: [")
            rendered = []
            for trip in data[calendar][direction]:
                suffix = ",true" if trip["saturdayOnly"] else ""
                rendered.append(f'p("{trip["departure"]}","{trip["arrival"]}"{suffix})')
            for i in range(0, len(rendered), 4):
                lines.append("      " + ",".join(rendered[i:i + 4]) + ",")
            lines.append("    ],")
        lines.append("  },")
        lines.append("")
    lines.append("};")
    return "\n".join(lines) + "\n"


def update_data_js(path: Path, data: dict[str, Any]) -> None:
    current = path.read_text(encoding="utf-8")
    marker = "export const TIMETABLES = {"
    if marker not in current:
        raise MonitorError("No se encuentra TIMETABLES en data.js")
    prefix = current.split(marker, 1)[0]
    path.write_text(prefix + render_timetables(data), encoding="utf-8")


def load_state(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mark_pending(state_path: Path, state: dict[str, Any], pdf_url: str, pdf_bytes: bytes, error: str) -> None:
    raw_hash = hashlib.sha256(pdf_bytes).hexdigest()
    new_alert = raw_hash != state.get("pending_pdf_sha256") and raw_hash != state.get("accepted_pdf_sha256")
    state.update({
        "pending_pdf_sha256": raw_hash,
        "pending_pdf_url": pdf_url,
        "pending_detected_at": now_iso(),
        "pending_error": error,
    })
    save_state(state_path, state)
    action_output("status", "pending-review")
    action_output("alert", "true" if new_alert else "false")
    action_output("updated", "false")
    action_output("pdf_url", pdf_url)
    action_output("message", error.replace("\n", " "))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-pdf")
    parser.add_argument("--state", default="monitor/e13-state.json")
    parser.add_argument("--data", default="data.js")
    args = parser.parse_args()

    state_path = Path(args.state)
    data_path = Path(args.data)
    state = load_state(state_path)

    if args.local_pdf:
        pdf_url = "local-file"
        pdf_bytes = Path(args.local_pdf).read_bytes()
        label = "local"
    else:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "es-ES,es;q=0.9"})
        try:
            pdf_url, pdf_bytes, label = resolve_official_pdf(session)
        except Exception as exc:
            action_output("status", "error")
            action_output("alert", "false")
            action_output("updated", "false")
            action_output("pdf_url", "")
            action_output("message", str(exc).replace("\n", " "))
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    raw_hash = hashlib.sha256(pdf_bytes).hexdigest()
    try:
        parsed = parse_pdf(pdf_bytes)
    except Exception as exc:
        mark_pending(state_path, state, pdf_url, pdf_bytes, str(exc))
        print(f"PDF oficial nuevo/inesperado; no se publica: {exc}")
        return 0

    parsed_hash = schedule_hash(parsed)
    accepted_schedule = state.get("accepted_schedule_sha256") or BASELINE_SCHEDULE_SHA256

    if parsed_hash == accepted_schedule:
        needs_state_update = (
            raw_hash != state.get("accepted_pdf_sha256")
            or pdf_url != state.get("accepted_pdf_url")
            or state.get("pending_pdf_sha256") is not None
            or state.get("pending_pdf_url") is not None
        )
        if needs_state_update:
            state.update({
                "accepted_pdf_sha256": raw_hash,
                "accepted_pdf_url": pdf_url,
                "accepted_pdf_label": label,
                "accepted_schedule_sha256": parsed_hash,
                "last_checked_at": now_iso(),
                "pending_pdf_sha256": None,
                "pending_pdf_url": None,
                "pending_detected_at": None,
                "pending_error": None,
            })
            save_state(state_path, state)
        action_output("status", "unchanged")
        action_output("alert", "false")
        action_output("updated", "false")
        action_output("pdf_url", pdf_url)
        action_output("message", "Horario oficial sin cambios")
        print(f"Horario oficial e13 validado y sin cambios: {pdf_url}")
        return 0

    update_data_js(data_path, parsed)
    state.update({
        "accepted_pdf_sha256": raw_hash,
        "accepted_pdf_url": pdf_url,
        "accepted_pdf_label": label,
        "accepted_schedule_sha256": parsed_hash,
        "last_changed_at": now_iso(),
        "last_checked_at": now_iso(),
        "pending_pdf_sha256": None,
        "pending_pdf_url": None,
        "pending_detected_at": None,
        "pending_error": None,
    })
    save_state(state_path, state)
    action_output("status", "updated")
    action_output("alert", "false")
    action_output("updated", "true")
    action_output("pdf_url", pdf_url)
    action_output("message", "Nuevo horario e13 validado y aplicado automáticamente")
    print(f"Nuevo horario e13 validado y aplicado: {pdf_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
