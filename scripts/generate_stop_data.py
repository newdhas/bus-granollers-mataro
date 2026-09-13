#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pymupdf
import requests

from monitor_timetable import USER_AGENT, half_rows, norm_time, resolve_official_pdf

STOP_SEQUENCES = {
    "toMataro": [
        ("2929", "Estació d’Autobusos de Sabadell", "Sabadell"),
        ("2931", "Av. Barberà · Tetuan", "Sabadell"),
        ("2932", "Av. Barberà · Pl. Montserrat Roig", "Sabadell"),
        ("9458", "Estació Rodalies Granollers Centre", "Granollers"),
        ("2365", "Estació d’Autobusos de Granollers", "Granollers"),
        ("9323", "Via Sèrgia · Camí del Mig", "Mataró"),
        ("3630", "Porta Laietana · Tecnocampus", "Mataró"),
        ("3237", "Estació Rodalies de Mataró · Costat Mar", "Mataró"),
        ("3314", "Estació Rodalies de Mataró · Costat Muntanya", "Mataró"),
    ],
    "toGranollers": [
        ("3314", "Estació Rodalies de Mataró · Costat Muntanya", "Mataró"),
        ("9735", "Av. del Maresme · Tecnocampus", "Mataró"),
        ("9299", "Sant Crist · Camí del Mig", "Mataró"),
        ("2365", "Estació d’Autobusos de Granollers", "Granollers"),
        ("9458", "Estació Rodalies Granollers Centre", "Granollers"),
        ("4925", "Av. Barberà · Calders", "Sabadell"),
        ("4930", "Latorre · Fra Luis de León · Baixador", "Sabadell"),
        ("8804", "Vidal · Ctra. de Caldes", "Sabadell"),
        ("2929", "Estació d’Autobusos de Sabadell", "Sabadell"),
    ],
}

STOP_CHOICES = {
    "toMataro": {
        "origins": ["9458", "2365"],
        "destinations": ["9323", "3630", "3237", "3314"],
        "defaultOrigin": "2365",
        "defaultDestination": "3314",
    },
    "toGranollers": {
        "origins": ["3314", "9735", "9299"],
        "destinations": ["2365", "9458"],
        "defaultOrigin": "9299",
        "defaultDestination": "2365",
    },
}


def js_string(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def extract_rows(page: pymupdf.Page, left: bool):
    rows = []
    for cols, saturday_only in half_rows(page, left):
        times = [norm_time(value) for value in cols]
        if not any(times):
            continue
        rows.append({"times": times, "saturdayOnly": bool(saturday_only)})
    return rows


def validate_rows(data):
    expected_ranges = {"weekday": (40, 60), "summer": (20, 35), "winter": (12, 25)}
    for calendar, directions in data.items():
        low, high = expected_ranges[calendar]
        for direction, rows in directions.items():
            if not low <= len(rows) <= high:
                raise RuntimeError(f"Número de filas sospechoso en {calendar}/{direction}: {len(rows)}")
            for row in rows:
                if len(row["times"]) != 9:
                    raise RuntimeError(f"Fila con columnas inesperadas en {calendar}/{direction}")
            if calendar != "weekday":
                marked = sum(1 for row in rows if row["saturdayOnly"])
                if marked != 1:
                    raise RuntimeError(f"Marcado de sábado inesperado en {calendar}/{direction}: {marked}")


def parse_full_rows(pdf_bytes: bytes):
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    if doc.page_count < 3:
        raise RuntimeError(f"PDF inesperado: {doc.page_count} páginas")
    data = {
        "weekday": {
            "toMataro": extract_rows(doc[0], left=False),
            "toGranollers": extract_rows(doc[0], left=True),
        },
        "summer": {
            "toMataro": extract_rows(doc[1], left=False),
            "toGranollers": extract_rows(doc[1], left=True),
        },
        "winter": {
            "toMataro": extract_rows(doc[2], left=False),
            "toGranollers": extract_rows(doc[2], left=True),
        },
    }
    validate_rows(data)
    return data


def render(data) -> str:
    lines = [
        "// Generado automáticamente desde el PDF oficial de Sagalés. No editar a mano.",
        "const r = (times, saturdayOnly = false) => ({ times, saturdayOnly });",
        "",
    ]

    lines.append("export const STOP_SEQUENCES = {")
    for direction in ("toMataro", "toGranollers"):
        lines.append(f"  {direction}: [")
        for stop_id, name, city in STOP_SEQUENCES[direction]:
            lines.append(f"    {{ id: {js_string(stop_id)}, name: {js_string(name)}, city: {js_string(city)} }},")
        lines.append("  ],")
    lines.append("};")
    lines.append("")

    lines.append("export const STOP_CHOICES = {")
    for direction in ("toMataro", "toGranollers"):
        cfg = STOP_CHOICES[direction]
        lines.append(f"  {direction}: {{")
        lines.append("    origins: [" + ", ".join(js_string(x) for x in cfg["origins"]) + "],")
        lines.append("    destinations: [" + ", ".join(js_string(x) for x in cfg["destinations"]) + "],")
        lines.append(f"    defaultOrigin: {js_string(cfg['defaultOrigin'])},")
        lines.append(f"    defaultDestination: {js_string(cfg['defaultDestination'])},")
        lines.append("  },")
    lines.append("};")
    lines.append("")

    lines.append("export const STOP_TIMETABLES = {")
    for calendar in ("weekday", "summer", "winter"):
        lines.append(f"  {calendar}: {{")
        for direction in ("toMataro", "toGranollers"):
            lines.append(f"    {direction}: [")
            for row in data[calendar][direction]:
                rendered_times = ", ".join("null" if t is None else js_string(t) for t in row["times"])
                suffix = ", true" if row["saturdayOnly"] else ""
                lines.append(f"      r([{rendered_times}]{suffix}),")
            lines.append("    ],")
        lines.append("  },")
    lines.append("};")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-pdf")
    parser.add_argument("--output", default="stops-data.js")
    parser.add_argument("--state", default="monitor/e13-state.json")
    args = parser.parse_args()

    if args.local_pdf:
        pdf_bytes = Path(args.local_pdf).read_bytes()
        source = args.local_pdf
    else:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "es-ES,es;q=0.9"})
        source, pdf_bytes, _label = resolve_official_pdf(session)

        state_path = Path(args.state)
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            accepted_hash = state.get("accepted_pdf_sha256")
            current_hash = hashlib.sha256(pdf_bytes).hexdigest()
            if accepted_hash and current_hash != accepted_hash:
                print("El PDF actual de Sagalés aún no está aceptado; stops-data.js se mantiene sin cambios.")
                return 0

    data = parse_full_rows(pdf_bytes)
    Path(args.output).write_text(render(data), encoding="utf-8")
    print(f"Datos de paradas e13 generados desde {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
