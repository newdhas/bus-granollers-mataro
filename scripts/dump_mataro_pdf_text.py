#!/usr/bin/env python3
from pathlib import Path
import json
import fitz

out = {}
for line in range(1, 9):
    path = Path(f"mataro-bus-official/line-{line}.pdf")
    doc = fitz.open(path)
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text("text")
        pages.append({"page": i + 1, "text": text[:12000]})
    out[str(line)] = {"pages": pages}

Path("mataro-bus-pdf-text.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print("Wrote mataro-bus-pdf-text.json")
