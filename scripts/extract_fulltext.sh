#!/bin/bash
# Extract fulltext/<citekey>.txt (with [[p.N]] page markers) for every entry
# in meta/map.json that has a PDF. Requires: pdftotext (brew install poppler).
#   bash scripts/extract_fulltext.sh            # all missing
#   bash scripts/extract_fulltext.sh <citekey>  # one (re)extract
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAP="$ROOT/meta/map.json"
OUT="$ROOT/fulltext"
mkdir -p "$OUT"
command -v pdftotext >/dev/null || { echo "ERROR: pdftotext not found (brew install poppler)"; exit 1; }
[ -f "$MAP" ] || { echo "ERROR: $MAP missing — run scripts/zotero_map.py first"; exit 1; }

python3 - "$MAP" "${1:-}" <<'EOF' | while IFS=$'\t' read -r key pdf; do
import json, sys
m = json.load(open(sys.argv[1]))
only = sys.argv[2] if len(sys.argv) > 2 else ""
for k, v in sorted(m.items()):
    if v.get("pdf") and (not only or k == only):
        print(f"{k}\t{v['pdf']}")
EOF
  txt="$OUT/$key.txt"
  if [ -s "$txt" ] && [ -z "${1:-}" ]; then continue; fi
  if [ ! -f "$pdf" ]; then echo "SKIP $key (missing PDF)"; continue; fi
  if pdftotext -q "$pdf" - > "$txt.raw" 2>/dev/null; then
    # form-feed -> [[p.N]] page markers; N = PDF page number
    python3 - "$txt.raw" "$txt" <<'PYEOF'
import sys
raw = open(sys.argv[1], encoding="utf-8", errors="replace").read()
pages = raw.split("\f")
out = []
for i, p in enumerate(pages, 1):
    if p.strip():
        out.append(f"[[p.{i}]]\n{p.strip()}")
open(sys.argv[2], "w", encoding="utf-8").write("\n\n".join(out) + "\n")
PYEOF
    rm -f "$txt.raw"
    echo "OK   $key ($(wc -c < "$txt" | tr -d ' ') bytes)"
  else
    rm -f "$txt.raw"; echo "FAIL $key"
  fi
done
echo "done. $(ls "$OUT" | grep -c '.txt$') fulltext files."
