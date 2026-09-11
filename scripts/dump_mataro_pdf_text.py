#!/usr/bin/env python3
from pathlib import Path
import json
import fitz

out = {}
out_dir = Path("mataro-bus-text")
out_dir.mkdir(exist_ok=True)

for line in range(1, 9):
    path = Path(f"mataro-bus-official/line-{line}.pdf")
    doc = fitz.open(path)
    pages = []
    chunks = []
    for i, page in enumerate(doc):
        text = page.get_text("text")
        pages.append({"page": i + 1, "text": text[:12000]})
        chunks.append(f"===== PAGE {i + 1} =====\n{text}")
    out[str(line)] = {"pages": pages}
    (out_dir / f"line-{line}.txt").write_text("\n".join(chunks), encoding="utf-8")

Path("mataro-bus-pdf-text.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print("Wrote Mataró Bus extracted text")
