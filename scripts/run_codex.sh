#!/bin/bash
# Drive a CLI agent over a worklist (one citekey per line).
# Usage: bash scripts/run_codex.sh <worklist.txt>
# Skips citekeys that already have meta/digest-reports/<ck>.json.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIST="${1:-}"
[ -n "$LIST" ] && [ -f "$LIST" ] || { echo "Usage: $0 <worklist.txt>"; exit 1; }
cd "$ROOT"
mkdir -p meta/codex-logs meta/digest-reports

grep -v '^#' "$LIST" | while read -r ck; do
  ck="${ck%%#*}"; ck="$(echo "$ck" | tr -d '[:space:]')"
  [ -z "$ck" ] && continue
  [ -f "meta/digest-reports/$ck.json" ] && continue
  echo "$ck"
done | xargs -P 6 -n 1 bash "$ROOT/scripts/codex_one.sh"
echo "=== batch finished $(date +%H:%M:%S): $(ls meta/digest-reports | wc -l | tr -d " ") reports total ==="
