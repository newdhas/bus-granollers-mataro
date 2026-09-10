#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import fitz
import requests
from bs4 import BeautifulSoup

SOURCE_PAGES = [
    "https://www.sagales.com/es/linia/555",
    "https://www.sagales.com/es/lineas/4?origenCL=34&destiCL=65",
]
USER_AGENT = "Mozilla/5.0 (compatible; e13-timetable-monitor/1.0; +https://github.com/newdhas/bus-granollers-mataro)"
TIME_RE = re.compile(r"^(?:\d{1,2}\.\d{2}|-)$")
CODE_RE = re.compile(r"^\d{4}$")
PDF_RE = re.compile(r"https?://[^\"'<>\s]+?\.pdf(?:\?[^\"'<>\s]*)?", re.I)
LEFT_CODES = ["3314", "9735", "9299", "2365", "9458", "4925", "4930", "8804", "2929"]
RIGHT_CODES = ["2929", "2931", "2932", "9458", "2365", "9323", "3630", "3237", "3314"]
BLUE_TARGET = (0.74, 0.894, 0.968)
BASELINE_SCHEDULE_SHA256 = "3e29755acc20c2631b1c34e11f4b544c252085309426ef3e3f2a44cc97d1c132"


class MonitorError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def action_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")
    else:
        print(f"OUTPUT {name}={value}")


def fetch(session: requests.Session, url: str) -> requests.Response:
    response = session.get(url, timeout=30, allow_redirects=True)
    response.raise_for_status()
    return response


def candidate_pdf_urls(html: str, base_url: str) -> list[tuple[int, str]]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: dict[str, int] = {}

    def add(raw: str, score: int) -> None:
        if not raw:
            return
        match = re.search(r"(?:https?://|/)[^\"'()\s]+?\.pdf(?:\?[^\"'()\s]*)?", raw, re.I)
        if match:
            raw = match.group(0)
        if ".pdf" not in raw.lower():
            return
        url = urljoin(base_url, raw.replace("&amp;", "&"))
        candidates[url] = max(score, candidates.get(url, -1))

    for anchor in soup.find_all("a"):
        text = " ".join(anchor.stripped_strings).lower()
        parent_text = " ".join(anchor.parent.stripped_strings).lower() if anchor.parent else ""
        score = 0
        if "horario" in text or "horaris" in text:
            score += 100
        if "pdf" in text:
            score += 30
        if "e13" in parent_text:
            score += 80
        for raw in (anchor.get("href", ""), anchor.get("data-href", ""), anchor.get("data-url", ""), anchor.get("onclick", "")):
            add(raw, score + (20 if "e13" in raw.lower() else 0))

    for match in PDF_RE.findall(html):
        add(match, 100 if "e13" in match.lower() else 20)

    return sorted(((score, url) for url, score in candidates.items()), reverse=True)


def discover_pdf(session: requests.Session) -> tuple[str, bytes]:
    errors: list[str] = []
    for source in SOURCE_PAGES:
        try:
            page = fetch(session, source)
        except Exception as exc:
            errors.append(f"{source}: {exc}")
            continue

        for _, url in candidate_pdf_urls(page.text, page.url):
            try:
                response = fetch(session, url)
                content_type = response.headers.get("content-type", "").lower()
                if response.content.startswith(b"%PDF-") or "application/pdf" in content_type:
                    return response.url, response.content
            except Exception as exc:
                errors.append(f"{url}: {exc}")

    raise MonitorError("No se ha podido localizar/descargar el PDF oficial. " + " | ".join(errors[-5:]))


def is_blue(fill: Any) -> bool:
    if not fill or len(fill) < 3:
        return False
    distance = sum((float(fill[i]) - BLUE_TARGET[i]) ** 2 for i in range(3)) ** 0.5
    return distance < 0.16


def group_by_y(items: list[tuple[float, float, str]], tolerance: float) -> list[list[tuple[float, float, str]]]:
    items = sorted(items)
    groups: list[list[tuple[float, float, str]]] = []
    for item in items:
        if not groups:
            groups.append([item])
            continue
        mean_y = statistics.mean(x[0] for x in groups[-1])
        if abs(item[0] - mean_y) > tolerance:
            groups.append([item])
        else:
            groups[-1].append(item)
    return groups


def half_rows(page: fitz.Page, left: bool) -> list[tuple[list[str | None], bool]]:
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
        raise MonitorError(f"Ha cambiado la estructura/códigos de paradas: {codes[:9]} != {expected}")
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
        raise MonitorError(f"Hora no válida en PDF: {value}")
    return f"{hour:02d}:{minute:02d}"


def extract_route(page: fitz.Page, left: bool, dep_col: int, arr_col: int) -> list[dict[str, Any]]:
    result = []
    for cols, saturday_only in half_rows(page, left):
        departure = norm_time(cols[dep_col])
        arrival = norm_time(cols[arr_col])
        if departure and arrival:
            result.append({"departure": departure, "arrival": arrival, "saturdayOnly": bool(saturday_only)})
    return result


def minutes(value: str) -> int:
    hour, minute = (int(x) for x in value.split(":"))
    return hour * 60 + minute


def validate_timetables(data: dict[str, Any], doc: fitz.Document) -> None:
    if doc.page_count < 3:
        raise MonitorError(f"PDF inesperado: solo tiene {doc.page_count} páginas")

    text0 = doc[0].get_text().lower()
    text1 = doc[1].get_text().lower()
    text2 = doc[2].get_text().lower()
    if "dilluns a divendres" not in text0:
        raise MonitorError("La página 1 ya no parece ser el horario laborable")
    if "1 de juny" not in text1 or "30 setembre" not in text1:
        raise MonitorError("La página 2 ya no parece ser el horario junio-septiembre")
    if ("1 d’octubre" not in text2 and "1 d'octubre" not in text2) or "31 de maig" not in text2:
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
                    arr += 24 * 60
                duration = arr - dep
                if not (15 <= duration <= 65):
                    raise MonitorError(f"Duración sospechosa {duration} min: {calendar}/{direction} {trip}")

    # Hoy el PDF usa una única fila azul por sentido en cada tabla de fin de semana.
    # Si cambia el formato, se detiene la actualización y se pide revisión manual.
    for calendar in ("summer", "winter"):
        for direction in ("toMataro", "toGranollers"):
            marked = sum(1 for t in data[calendar][direction] if t["saturdayOnly"])
            if marked != 1:
                raise MonitorError(f"Marcado azul de sábado inesperado en {calendar}/{direction}: {marked}")


def parse_pdf(pdf_bytes: bytes) -> dict[str, Any]:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
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
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
        raise MonitorError(f"No se encuentra TIMETABLES en {path}")
    prefix = current.split(marker, 1)[0]
    path.write_text(prefix + render_timetables(data), encoding="utf-8")


def load_state(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-pdf", help="Usa un PDF local para probar el parser")
    parser.add_argument("--state", default="monitor/e13-state.json")
    parser.add_argument("--data", default="data.js")
    args = parser.parse_args()

    state_path = Path(args.state)
    data_path = Path(args.data)
    state = load_state(state_path)

    pdf_url = "local-file"
    if args.local_pdf:
        pdf_bytes = Path(args.local_pdf).read_bytes()
    else:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "es-ES,es;q=0.9"})
        try:
            pdf_url, pdf_bytes = discover_pdf(session)
        except Exception as exc:
            action_output("status", "error")
            action_output("alert", "false")
            action_output("message", str(exc).replace("\n", " "))
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    raw_hash = hashlib.sha256(pdf_bytes).hexdigest()

    try:
        parsed = parse_pdf(pdf_bytes)
        parsed_hash = schedule_hash(parsed)
    except Exception as exc:
        if raw_hash != state.get("pending_pdf_sha256") and raw_hash != state.get("accepted_pdf_sha256"):
            state.update({
                "pending_pdf_sha256": raw_hash,
                "pending_pdf_url": pdf_url,
                "pending_detected_at": now_iso(),
                "pending_error": str(exc),
            })
            save_state(state_path, state)
            action_output("alert", "true")
        else:
            action_output("alert", "false")
        action_output("status", "pending-review")
        action_output("pdf_url", pdf_url)
        action_output("message", str(exc).replace("\n", " "))
        print(f"Nuevo PDF no validado: {exc}")
        return 0

    accepted_schedule = state.get("accepted_schedule_sha256") or BASELINE_SCHEDULE_SHA256

    if parsed_hash == accepted_schedule:
        changed_state = raw_hash != state.get("accepted_pdf_sha256") or pdf_url != state.get("accepted_pdf_url")
        if changed_state:
            state.update({
                "accepted_pdf_sha256": raw_hash,
                "accepted_pdf_url": pdf_url,
                "accepted_schedule_sha256": parsed_hash,
                "last_changed_at": state.get("last_changed_at") or now_iso(),
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
        print("Horario oficial sin cambios.")
        return 0

    update_data_js(data_path, parsed)
    state.update({
        "accepted_pdf_sha256": raw_hash,
        "accepted_pdf_url": pdf_url,
        "accepted_schedule_sha256": parsed_hash,
        "last_changed_at": now_iso(),
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
    print("Nuevo horario e13 validado: data.js actualizado automáticamente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
