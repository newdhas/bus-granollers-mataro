#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pymupdf
import requests

from monitor_timetable import (
    USER_AGENT,
    action_output,
    now_iso,
    parse_pdf,
    resolve_official_pdf,
    schedule_hash,
    update_data_js,
    load_state,
    save_state,
)

MOUTE_URL = (
    "https://mou-te.gencat.cat/MouteAPI/rest/infrastructure/line/timetable"
    "?language=ca_ES&liniaId=02494&network=cat&project=001"
)
STATE_FILE = Path("monitor/e13-state.json")
DATA_FILE = Path("data.js")
REQUIRED_SERVICE_CODES = {"30", "298", "365", "366", "367"}
REQUIRED_TEXT = (
    "mataró",
    "granollers",
    "sabadell",
    "sant crist",
    "camí del mig",
    "estació d’autobusos",
)


def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def normalize(value: str) -> str:
    return (
        value.lower()
        .replace("’", "'")
        .replace("à", "a").replace("á", "a")
        .replace("è", "e").replace("é", "e")
        .replace("í", "i").replace("ï", "i")
        .replace("ò", "o").replace("ó", "o")
        .replace("ú", "u").replace("ü", "u")
    )


def fetch_moute(session: requests.Session) -> tuple[str, bytes]:
    response = session.get(
        MOUTE_URL,
        timeout=45,
        allow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"},
    )
    response.raise_for_status()
    blob = response.content
    ctype = response.headers.get("content-type", "").lower()
    if not blob.startswith(b"%PDF-") and "application/pdf" not in ctype:
        raise RuntimeError(f"Mou-te no ha devuelto un PDF (content-type={ctype!r})")
    return response.url, blob


def validate_moute(blob: bytes, sagales_schedule: dict) -> dict:
    doc = pymupdf.open(stream=blob, filetype="pdf")
    if doc.page_count < 1:
        raise RuntimeError("PDF de Mou-te vacío")

    page_texts = [page.get_text() for page in doc]
    text = "\n".join(page_texts)
    ntext = normalize(text)

    if "e13" not in ntext or "l0494" not in ntext:
        raise RuntimeError("El PDF de Mou-te ya no parece corresponder a la línea L0494/e13")

    for needle in REQUIRED_TEXT:
        if normalize(needle) not in ntext:
            raise RuntimeError(f"Falta una referencia esperada en Mou-te: {needle}")

    present_codes = set(re.findall(r"(?<!\d)(30|298|365|366|367)(?!\d)", text))
    missing_codes = REQUIRED_SERVICE_CODES - present_codes
    if missing_codes:
        raise RuntimeError(f"Faltan códigos de servicio de Mou-te: {sorted(missing_codes)}")

    # Cross-source verification. Sagalés is parsed into the exact trips used by the app.
    # Mou-te is the primary authority: every departure and arrival time that Sagalés
    # proposes must be present in the current Mou-te timetable before publication.
    moute_times = set(re.findall(r"(?<!\d)([0-2]?\d[.:][0-5]\d)(?!\d)", text))
    moute_times = {t.replace(".", ":").zfill(5) for t in moute_times}

    expected_times = set()
    total_trips = 0
    for calendar in ("weekday", "summer", "winter"):
        for direction in ("toMataro", "toGranollers"):
            trips = sagales_schedule[calendar][direction]
            total_trips += len(trips)
            for trip in trips:
                expected_times.add(trip["departure"])
                expected_times.add(trip["arrival"])

    missing_times = sorted(expected_times - moute_times)
    if missing_times:
        sample = ", ".join(missing_times[:12])
        raise RuntimeError(
            f"Mou-te no contiene todas las horas propuestas por Sagalés; faltan {len(missing_times)}: {sample}"
        )

    # Basic guards against an unexpectedly small/changed document.
    if total_trips < 100:
        raise RuntimeError(f"Número total de viajes extraídos sospechoso: {total_trips}")
    if len(moute_times) < 80:
        raise RuntimeError(f"Mou-te contiene muy pocas horas reconocibles: {len(moute_times)}")

    return {
        "page_count": doc.page_count,
        "service_codes": sorted(present_codes),
        "recognized_times": len(moute_times),
        "cross_checked_times": len(expected_times),
        "cross_check": "all_sagales_times_present_in_moute",
    }


def emit(status: str, alert: bool, updated: bool, pdf_url: str, message: str) -> None:
    action_output("status", status)
    action_output("alert", "true" if alert else "false")
    action_output("updated", "true" if updated else "false")
    action_output("pdf_url", pdf_url)
    action_output("message", message.replace("\n", " "))


def main() -> int:
    state = load_state(STATE_FILE)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ca-ES,es;q=0.9"})

    try:
        # Primary source: Generalitat / Mou-te.
        moute_url, moute_blob = fetch_moute(session)
        moute_hash = sha256(moute_blob)

        # Secondary source: operator PDF. It remains the structured extractor because
        # its stable layout is already covered by strict parser validations.
        sagales_url, sagales_blob, sagales_label = resolve_official_pdf(session)
        sagales_hash = sha256(sagales_blob)
        parsed = parse_pdf(sagales_blob)
        parsed_hash = schedule_hash(parsed)

        moute_meta = validate_moute(moute_blob, parsed)
        accepted_schedule = state.get("accepted_schedule_sha256") or parsed_hash

        common_state = {
            "last_checked_at": now_iso(),
            "primary_source": "Generalitat de Catalunya · Mou-te",
            "primary_url": moute_url,
            "primary_pdf_sha256": moute_hash,
            "secondary_source": "Sagalés",
            "secondary_url": sagales_url,
            "secondary_pdf_sha256": sagales_hash,
            "secondary_label": sagales_label,
            "moute_validation": moute_meta,
        }

        if parsed_hash == accepted_schedule:
            state.update(common_state)
            state.update({
                "accepted_pdf_sha256": sagales_hash,
                "accepted_pdf_url": sagales_url,
                "accepted_pdf_label": sagales_label,
                "accepted_moute_pdf_sha256": moute_hash,
                "accepted_moute_pdf_url": moute_url,
                "accepted_schedule_sha256": parsed_hash,
                "pending_pdf_sha256": None,
                "pending_pdf_url": None,
                "pending_detected_at": None,
                "pending_error": None,
                "dual_source_status": "validated",
            })
            save_state(STATE_FILE, state)
            emit("unchanged", False, False, moute_url, "Mou-te y Sagalés validados; horario sin cambios")
            print("Mou-te (primaria) y Sagalés (contraste) coinciden con el horario aceptado.")
            return 0

        # A new schedule can only reach data.js after Mou-te has validated every time.
        update_data_js(DATA_FILE, parsed)
        state.update(common_state)
        state.update({
            "accepted_pdf_sha256": sagales_hash,
            "accepted_pdf_url": sagales_url,
            "accepted_pdf_label": sagales_label,
            "accepted_moute_pdf_sha256": moute_hash,
            "accepted_moute_pdf_url": moute_url,
            "accepted_schedule_sha256": parsed_hash,
            "last_changed_at": now_iso(),
            "pending_pdf_sha256": None,
            "pending_pdf_url": None,
            "pending_detected_at": None,
            "pending_error": None,
            "dual_source_status": "validated-update",
        })
        save_state(STATE_FILE, state)
        emit("updated", False, True, moute_url, "Nuevo horario validado por Mou-te y contrastado con Sagalés")
        print("Nuevo horario validado por Mou-te y Sagalés; data.js actualizado.")
        return 0

    except Exception as exc:
        state.update({
            "last_checked_at": now_iso(),
            "dual_source_status": "pending-review",
            "pending_detected_at": now_iso(),
            "pending_error": str(exc),
        })
        save_state(STATE_FILE, state)
        emit("pending-review", True, False, state.get("primary_url", MOUTE_URL), str(exc))
        print(f"Validación dual fallida; data.js NO se modifica: {exc}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
