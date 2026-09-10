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

import pymupdf
import requests
from bs4 import BeautifulSoup

SOURCE_PAGES = [
    "https://www.sagales.com/es/linia/555",
    "https://www.sagales.com/es/lineas/4?origenCL=34&destiCL=65",
]
USER_AGENT = "Mozilla/5.0 (compatible; e13-timetable-monitor/1.1; +https://github.com/newdhas/bus-granollers-mataro)"
TIME_RE = re.compile(r"^(?:\d{1,2}\.\d{2}|-)$")
CODE_RE = re.compile(r"^\d{4}$")
PDF_IN_TEXT_RE = re.compile(r"(?:https?://|/)[^\"'()<>\s]+?\.pdf(?:\?[^\"'()<>\s]*)?", re.I)
QUOTED_PDF_RE = re.compile(r"[\"']([^\"']+?\.pdf(?:\?[^\"']*)?)[\"']", re.I)
LEFT_CODES = ["3314", "9735", "9299", "2365", "9458", "4925", "4930", "8804", "2929"]
RIGHT_CODES = ["2929", "2931", "2932", "9458", "2365", "9323", "3630", "3237", "3314"]
BLUE_TARGET = (0.74, 0.894, 0.968)
BASELINE_SCHEDULE_SHA256 = "3e29755acc20c2631b1c34e11f4b544c252085309426ef3e3f2a44cc97d1c132"


class MonitorError(RuntimeError):
    pass


class PendingTimetable(MonitorError):
    def __init__(self, url: str, pdf_bytes: bytes, reason: str):
        super().__init__(reason)
        self.url = url
        self.pdf_bytes = pdf_bytes
        self.reason = reason


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
    """Return every PDF-like URL on the Sagalés page, best candidates first.

    Sagalés mixes the timetable link with PDF attachments for incidents, so a
    URL is never trusted just because it is the first PDF found.
    """
    soup = BeautifulSoup(html, "html.parser")
    candidates: dict[str, int] = {}

    def add(raw: Any, score: int, context: str = "") -> None:
        if isinstance(raw, (list, tuple)):
            for value in raw:
                add(value, score, context)
            return
        if raw is None:
            return
        raw = str(raw).replace("&amp;", "&")
        matches = PDF_IN_TEXT_RE.findall(raw)
        if matches:
            values = matches
        elif ".pdf" in raw.lower() and not raw.lower().startswith("javascript:"):
            values = [raw.strip(" \"'()")]
        else:
            values = []

        context_l = context.lower()
        for value in values:
            value = value.replace("\\/", "/")
            url = urljoin(base_url, value)
            local_score = score
            if "horario" in context_l or "horaris" in context_l:
                local_score += 120
            if "e13" in context_l:
                local_score += 100
            if "incid" in context_l or "afect" in context_l or "adjunt" in context_l:
                local_score -= 60
            candidates[url] = max(local_score, candidates.get(url, -10_000))

    for tag in soup.find_all(True):
        own_text = " ".join(tag.stripped_strings)
        parent_text = " ".join(tag.parent.stripped_strings) if tag.parent else ""
        context = f"{own_text} {parent_text}"
        for value in tag.attrs.values():
            add(value, 10, context)

    for match in QUOTED_PDF_RE.finditer(html):
        start = max(0, match.start() - 350)
        end = min(len(html), match.end() + 350)
        add(match.group(1), 5, html[start:end])

    # Last-resort scan for absolute/root-relative PDF URLs not inside quotes.
    for match in PDF_IN_TEXT_RE.finditer(html):
        start = max(0, match.start() - 350)
        end = min(len(html), match.end() + 350)
        add(match.group(0), 0, html[start:end])

    return sorted(((score, url) for url, score in candidates.items()), reverse=True)


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


def extract_route(page: pymupdf.Page, left: bool, dep_col: int, arr_col: int) -> list[dict[str, Any]]:
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


def validate_timetables(data: dict[str, Any], doc: pymupdf.Document) -> None:
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

    # Safety check: the current document format uses exactly one blue Saturday-only
    # row per direction in each weekend table. A changed layout requires review.
    for calendar in ("summer", "winter"):
        for direction in ("toMataro", "toGranollers"):
            marked = sum(1 for t in data[calendar][direction] if t["saturdayOnly"])
            if marked != 1:
                raise MonitorError(f"Marcado azul de sábado inesperado en {calendar}/{direction}: {marked}")


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


def looks_like_e13_timetable(pdf_bytes: bytes) -> bool:
    """Loose signature used only to decide whether a failed PDF deserves an alert."""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        if doc.page_count < 3:
            return False
        text = "\n".join(doc[i].get_text().lower() for i in range(min(3, doc.page_count)))
    except Exception:
        return False
    return (
        "granollers" in text
        and "mataró" in text
        and "sabadell" in text
        and ("e13" in text or "dilluns a divendres" in text)
    )


def discover_timetable(session: requests.Session) -> tuple[str, bytes, dict[str, Any]]:
    """Find the actual e13 timetable, not an incident/notice attachment."""
    errors: list[str] = []
    seen: set[str] = set()
    likely_changed: list[tuple[int, str, bytes, str]] = []

    for source in SOURCE_PAGES:
        try:
            page = fetch(session, source)
        except Exception as exc:
            errors.append(f"{source}: {exc}")
            continue

        candidates = candidate_pdf_urls(page.text, page.url)
        for score, url in candidates[:40]:
            if url in seen:
                continue
            seen.add(url)
            try:
                response = fetch(session, url)
                content_type = response.headers.get("content-type", "").lower()
                if not (response.content.startswith(b"%PDF-") or "application/pdf" in content_type):
                    continue
                pdf_bytes = response.content
                try:
                    parsed = parse_pdf(pdf_bytes)
                    print(f"PDF de horario e13 validado: {response.url}")
                    return response.url, pdf_bytes, parsed
                except Exception as exc:
                    if looks_like_e13_timetable(pdf_bytes):
                        likely_changed.append((score, response.url, pdf_bytes, str(exc)))
                    else:
                        errors.append(f"Descartado PDF no-horario {response.url}: {exc}")
            except Exception as exc:
                errors.append(f"{url}: {exc}")

    if likely_changed:
        likely_changed.sort(key=lambda item: item[0], reverse=True)
        _score, url, pdf_bytes, reason = likely_changed[0]
        raise PendingTimetable(url, pdf_bytes, reason)

    detail = " | ".join(errors[-8:])
    raise MonitorError("No se ha localizado un PDF de horario e13 válido en Sagalés." + (f" {detail}" if detail else ""))


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


def record_pending(state_path: Path, state: dict[str, Any], pdf_url: str, pdf_bytes: bytes, error: str) -> None:
    raw_hash = hashlib.sha256(pdf_bytes).hexdigest()
    new_alert = raw_hash != state.get("pending_pdf_sha256") and raw_hash != state.get("accepted_pdf_sha256")
    state.update({
        "pending_pdf_sha256": raw_hash,
        "pending_pdf_url": pdf_url,
        "pending_detected_at": now_iso(),
        "pending_error": error,
    })
    save_state(state_path, state)
    action_output("alert", "true" if new_alert else "false")
    action_output("status", "pending-review")
    action_output("updated", "false")
    action_output("pdf_url", pdf_url)
    action_output("message", error.replace("\n", " "))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-pdf", help="Usa un PDF local para probar el parser")
    parser.add_argument("--state", default="monitor/e13-state.json")
    parser.add_argument("--data", default="data.js")
    args = parser.parse_args()

    state_path = Path(args.state)
    data_path = Path(args.data)
    state = load_state(state_path)

    if args.local_pdf:
        pdf_url = "local-file"
        pdf_bytes = Path(args.local_pdf).read_bytes()
        try:
            parsed = parse_pdf(pdf_bytes)
        except Exception as exc:
            record_pending(state_path, state, pdf_url, pdf_bytes, str(exc))
            return 0
    else:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "es-ES,es;q=0.9"})
        try:
            pdf_url, pdf_bytes, parsed = discover_timetable(session)
        except PendingTimetable as exc:
            record_pending(state_path, state, exc.url, exc.pdf_bytes, exc.reason)
            print(f"PDF e13 probable pendiente de revisión: {exc.reason}")
            return 0
        except Exception as exc:
            action_output("status", "error")
            action_output("alert", "false")
            action_output("updated", "false")
            action_output("pdf_url", "")
            action_output("message", str(exc).replace("\n", " "))
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    raw_hash = hashlib.sha256(pdf_bytes).hexdigest()
    parsed_hash = schedule_hash(parsed)
    accepted_schedule = state.get("accepted_schedule_sha256") or BASELINE_SCHEDULE_SHA256

    if parsed_hash == accepted_schedule:
        state.update({
            "accepted_pdf_sha256": raw_hash,
            "accepted_pdf_url": pdf_url,
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
        print("Horario oficial sin cambios.")
        return 0

    update_data_js(data_path, parsed)
    state.update({
        "accepted_pdf_sha256": raw_hash,
        "accepted_pdf_url": pdf_url,
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
    print("Nuevo horario e13 validado: data.js actualizado automáticamente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
