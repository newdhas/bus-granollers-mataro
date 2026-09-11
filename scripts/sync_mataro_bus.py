#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://mataro.avanzagrupo.com"
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
    r = session.get(url, timeout=40, allow_redirects=True)
    r.raise_for_status()
    return r


def score_candidate(url: str, text: str, line: int) -> int:
    hay = f"{url} {text}".lower()
    score = 0
    if ".pdf" in url.lower():
        score += 100
    if "horar" in hay:
        score += 40
    if "map" in hay or "plano" in hay or "plànol" in hay:
        score += 10
    if re.search(rf"(?:linea|l[ií]nia|linia)[-_ ]?0*{line}(?:\D|$)", hay):
        score += 25
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
        if score:
            found.append((score, url, text))

    # Liferay sometimes stores document URLs in JSON/JS attributes rather than anchors.
    for raw in re.findall(r'https?://[^"\'<> ]+|/documents/[^"\'<> ]+|/o/[^"\'<> ]+\.pdf[^"\'<> ]*', html, re.I):
        url = urljoin(page_url, raw.replace("&amp;", "&"))
        if ".pdf" in url.lower() or "/documents/" in url.lower():
            found.append((score_candidate(url, "", line), url, ""))

    # Preserve highest score per URL.
    best: dict[str, tuple[int, str]] = {}
    for score, url, text in found:
        if url not in best or score > best[url][0]:
            best[url] = (score, text)
    return sorted(((score, url, text) for url, (score, text) in best.items()), reverse=True)


def resolve_line_pdf(session: requests.Session, line: int) -> tuple[str, bytes, str, str]:
    page_variants = [
        f"{BASE}/detalle-linea?idBusLine={line}",
        f"{BASE}/detalle-linea?idBusLine={line:03d}",
        f"{BASE}/ca/detalle-linea?idBusLine={line}",
        f"{BASE}/ca/detalle-linea?idBusLine={line:03d}",
    ]
    errors: list[str] = []
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
            ctype = pdf.headers.get("content-type", "").lower()
            if pdf.content.startswith(b"%PDF-") or "application/pdf" in ctype:
                return pdf.url, pdf.content, label, resp.url

    raise RuntimeError(
        f"Línea {line}: no se ha encontrado un PDF oficial descargable. "
        + " | ".join(errors[-6:])
    )


def main() -> int:
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
