#!/bin/bash
# Extract fulltext/<citekey>.txt (with [[p.N]] page markers) for every entry
# in meta/map.json that has a PDF. Requires: pdftotext (brew install poppler).
#   bash scripts/extract_fulltext.sh            # all missing
#   bash scripts/extract_fulltext.sh <citekey>  # one (re)extract
# Exits nonzero if a requested key is unknown or any PDF is missing/fails.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAP="$ROOT/meta/map.json"
OUT="$ROOT/fulltext"
mkdir -p "$OUT"
command -v pdftotext >/dev/null || { echo "ERROR: pdftotext not found (brew install poppler)"; exit 1; }
[ -f "$MAP" ] || { echo "ERROR: $MAP missing — create it (docs/install.md) or run scripts/zotero_map.py"; exit 1; }

list="$(python3 - "$MAP" "${1:-}" <<'EOF'
import json, sys
m = json.load(open(sys.argv[1]))
only = sys.argv[2] if len(sys.argv) > 2 else ""
if only and not (m.get(only) or {}).get("pdf"):
    why = "no pdf path for" if only in m else "unknown citekey"
    sys.exit(f"ERROR: {why} '{only}' in meta/map.json")
for k, v in sorted(m.items()):
    if v.get("pdf") and (not only or k == only):
        print(f"{k}\t{v['pdf']}")
EOF
)" || exit 1

status=0
while IFS=$'\t' read -r key pdf; do
  [ -n "$key" ] || continue
  txt="$OUT/$key.txt"
  if [ -s "$txt" ] && [ -z "${1:-}" ]; then continue; fi
  if [ ! -f "$pdf" ]; then echo "SKIP $key (missing PDF)"; status=1; continue; fi
  if pdftotext -q "$pdf" - > "$txt.raw" 2>/dev/null &&
    # form-feed -> [[p.N]] page markers; N = PDF page number
    python3 - "$txt.raw" "$txt" <<'PYEOF'
import os, sys, tempfile
raw = open(sys.argv[1], encoding="utf-8", errors="replace").read()
pages = raw.split("\f")
out = []
for i, p in enumerate(pages, 1):
    if p.strip():
        out.append(f"[[p.{i}]]\n{p.strip()}")
with tempfile.TemporaryDirectory(prefix=".litwiki-page-", dir=os.path.dirname(sys.argv[2])) as tmpdir:
    ready = os.path.join(tmpdir, "ready")
    with open(ready, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(out) + "\n")
    os.replace(ready, sys.argv[2])
PYEOF
  then
    rm -f "$txt.raw"
    echo "OK   $key ($(wc -c < "$txt" | tr -d ' ') bytes)"
  else
    rm -f "$txt.raw"; echo "FAIL $key"; status=1
  fi
done <<< "$list"
echo "done. $(ls "$OUT" | grep -c '.txt$') fulltext files."
exit $status
