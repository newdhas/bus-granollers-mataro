#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup

BASE = "https://mataro.avanzagrupo.com"
DOC_BASE = f"{BASE}/documents/1527332/2689989"
OUT_DIR = Path("mataro-bus-official")
META = Path("mataro-bus-sources.json")
UA = "Mozilla/5.0 (compatible; bus-granollers-mataro/1.0; +https://github.com/newdhas/bus-granollers-mataro)"
LINE_NAMES = {
    1: "Circular",
    2: "Circular",
    3: "Camí de la Serra - Vista Alegre - Rocafonda",
    4: "Cirera - Molins",
    5: "Rodalies - Hospital de Mataró",
    6: "Institut Català Salut - Ctra. de Mata",
    7: "Pl. Tereses - Cerdanyola",
    8: "Rodalies - Galícia",
}


def fetch(session: requests.Session, url: str) -> requests.Response:
    verify = urlparse(url).hostname != "mataro.avanzagrupo.com"
    r = session.get(url, timeout=40, allow_redirects=True, verify=verify)
    r.raise_for_status()
    return r


def is_pdf(response: requests.Response) -> bool:
    return response.content.startswith(b"%PDF-") or "application/pdf" in response.headers.get("content-type", "").lower()


def score_candidate(url: str, text: str, line: int) -> int:
    hay = f"{url} {text}".lower()
    if "certificadoens" in hay or "wp-content" in hay:
        return -1000
    score = 0
    if ".pdf" in url.lower():
        score += 100
    if "horar" in hay:
        score += 40
    if "map" in hay or "plano" in hay or "plànol" in hay:
        score += 10
    if re.search(rf"(?:linea|l[ií]nia|linia)[-_ ]?0*{line}(?:\D|$)", hay):
        score += 25
    if f"/{line}.pdf" in url.lower():
        score += 200
    if "matar" in hay:
        score += 15
    return score


def extract_pdf_candidates(page_url: str, html: str, line: int) -> list[tuple[int, str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[tuple[int, str, str]] = []
    for tag in soup.find_all(["a", "iframe", "embed", "object", "source"]):
        raw = tag.get("href") or tag.get("src") or tag.get("data")
        if not raw:
            continue
        url = urljoin(page_url, raw)
        text = " ".join(tag.stripped_strings).strip()
        score = score_candidate(url, text, line)
        if score > 0:
            found.append((score, url, text))

    for raw in re.findall(r'https?://[^"\'<> ]+|/documents/[^"\'<> ]+|/o/[^"\'<> ]+\.pdf[^"\'<> ]*', html, re.I):
        url = urljoin(page_url, raw.replace("&amp;", "&"))
        score = score_candidate(url, "", line)
        if score > 0 and (".pdf" in url.lower() or "/documents/" in url.lower()):
            found.append((score, url, ""))

    best: dict[str, tuple[int, str]] = {}
    for score, url, text in found:
        if url not in best or score > best[url][0]:
            best[url] = (score, text)
    return sorted(((score, url, text) for url, (score, text) in best.items()), reverse=True)


def resolve_line_pdf(session: requests.Session, line: int) -> tuple[str, bytes, str, str]:
    detail_page = f"{BASE}/detalle-linea?idBusLine={line}"
    errors: list[str] = []

    # Avanza's current official line documents follow this stable Liferay path.
    # Lines 3 and 7 expose exactly this URL in the page; try the same official
    # document slot for all lines before falling back to HTML discovery.
    direct = f"{DOC_BASE}/{line}.pdf"
    try:
        pdf = fetch(session, direct)
        if is_pdf(pdf):
            return pdf.url, pdf.content, "Horario oficial Avanza", detail_page
    except Exception as exc:
        errors.append(f"{direct}: {exc}")

    page_variants = [
        detail_page,
        f"{BASE}/detalle-linea?idBusLine={line:03d}",
        f"{BASE}/ca/detalle-linea?idBusLine={line}",
        f"{BASE}/ca/detalle-linea?idBusLine={line:03d}",
    ]
    for page in page_variants:
        try:
            resp = fetch(session, page)
        except Exception as exc:
            errors.append(f"{page}: {exc}")
            continue
        for _score, url, label in extract_pdf_candidates(resp.url, resp.text, line):
            try:
                pdf = fetch(session, url)
            except Exception as exc:
                errors.append(f"{url}: {exc}")
                continue
            if is_pdf(pdf):
                return pdf.url, pdf.content, label or "Horario oficial Avanza", resp.url

    raise RuntimeError(f"Línea {line}: no se ha encontrado un PDF oficial de horario. " + " | ".join(errors[-8:]))


def main() -> int:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "ca,es;q=0.9,en;q=0.6"})
    OUT_DIR.mkdir(exist_ok=True)

    meta = {
        "source": "Avanza · Mataró Bus",
        "official_index": f"{BASE}/lineas-y-horarios/todas-las-lineas",
        "lines": {},
    }

    for line, name in LINE_NAMES.items():
        url, data, label, page = resolve_line_pdf(session, line)
        target = OUT_DIR / f"line-{line}.pdf"
        target.write_bytes(data)
        meta["lines"][str(line)] = {
            "name": name,
            "detail_page": page,
            "pdf_url": url,
            "pdf_file": str(target),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "label": label,
        }
        print(f"L{line}: {url} -> {target} ({len(data)} bytes)")

    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {META}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
