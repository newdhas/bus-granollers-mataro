#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

TIME_RE = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b")


def clean(s: str) -> str:
    return " ".join((s or "").replace("\n", " ").split())


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", s)


def vertical_name(values: list[str]) -> str:
    parts = []
    for v in values:
        v = clean(v)
        if not v or TIME_RE.search(v) or v == "---":
            continue
        parts.append(v)
    # The stop labels are printed bottom-to-top in the timetable.
    return clean("".join(reversed(parts)))


def page_stop_candidates(text: str) -> list[str]:
    candidates = []
    seen = set()
    for raw in text.splitlines():
        s = clean(raw)
        if not s or TIME_RE.fullmatch(s) or s == "---":
            continue
        if len(s) < 3 or len(s) > 45:
            continue
        low = s.lower()
        if any(k in low for k in ["direcció", "horaris", "diumenges", "festius", "dissabtes", "feiners", "línia", "linia"]):
            continue
        if re.fullmatch(r"\d+", s):
            continue
        key = norm(s)
        if key and key not in seen:
            seen.add(key)
            candidates.append(s)
    return candidates


def best_match(raw: str, candidates: list[str]) -> str:
    nr = norm(raw)
    if not nr:
        return raw
    exact = [c for c in candidates if norm(c) == nr]
    if exact:
        return exact[0]
    contained = [c for c in candidates if nr in norm(c) or norm(c) in nr]
    if contained:
        return min(contained, key=lambda c: abs(len(norm(c)) - len(nr)))
    # Character overlap fallback, only for plausible labels.
    scored = []
    a = set(nr)
    for c in candidates:
        nc = norm(c)
        if not nc:
            continue
        score = len(a & set(nc)) / max(len(a | set(nc)), 1)
        scored.append((score, c))
    if scored and max(scored)[0] >= 0.45:
        return max(scored)[1]
    return raw


def main() -> None:
    tables = json.loads(Path("mataro-bus-tables.json").read_text(encoding="utf-8"))
    text = json.loads(Path("mataro-bus-pdf-text.json").read_text(encoding="utf-8"))
    out = {}
    for line, pages in tables.items():
        out[line] = []
        page_texts = {p["page"]: p["text"] for p in text[line]["pages"]}
        for page in pages:
            candidates = page_stop_candidates(page_texts.get(page["page"], ""))
            p = {"page": page["page"], "tables": []}
            for table in page["tables"]:
                data = table["data"]
                cols = table["cols"]
                pairs = []
                for name_col in range(0, cols - 1, 2):
                    time_col = name_col + 1
                    name_values = [r[name_col] if name_col < len(r) and r[name_col] else "" for r in data]
                    time_values = [r[time_col] if time_col < len(r) and r[time_col] else "" for r in data]
                    raw_name = vertical_name(name_values)
                    name = best_match(raw_name, candidates)
                    times = []
                    for v in time_values:
                        times += TIME_RE.findall(clean(v))
                    # Some first/last row times are merged into the name cell. Include
                    # only tokens there if that row contains multiple times.
                    for v in name_values:
                        toks = TIME_RE.findall(clean(v))
                        if len(toks) > 1:
                            times += toks
                    dedup=[]
                    for t in times:
                        h,m=t.split(":")
                        t=f"{int(h):02d}:{m}"
                        if t not in dedup: dedup.append(t)
                    pairs.append({"raw_name": raw_name, "name": name, "count": len(dedup), "first": dedup[:3], "last": dedup[-3:]})
                p["tables"].append({"index": table["index"], "bbox": table["bbox"], "pairs": pairs})
            out[line].append(p)
    Path("mataro-bus-table-summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("Wrote mataro-bus-table-summary.json")


if __name__ == "__main__":
    main()
