#!/usr/bin/env python3
from pathlib import Path
import json
import fitz

result = {}
for line in range(1, 9):
    doc = fitz.open(Path(f"mataro-bus-official/line-{line}.pdf"))
    pages = []
    for pno, page in enumerate(doc, start=1):
        found = page.find_tables()
        tables = []
        for idx, table in enumerate(found.tables):
            data = table.extract()
            tables.append({
                "index": idx,
                "bbox": list(table.bbox),
                "rows": len(data),
                "cols": max((len(r) for r in data), default=0),
                "data": data,
            })
        pages.append({"page": pno, "tables": tables})
    result[str(line)] = pages

Path("mataro-bus-tables.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print("Wrote mataro-bus-tables.json")
