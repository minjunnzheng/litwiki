#!/bin/bash
# batch_digest.sh <worklist.txt> <parallel> <runner>
#   worklist = one citekey per line (blank lines / # comments ignored)
#   parallel = required positive concurrency limit
#   runner   = required explicit runner selected for this task
#
# Already-digested papers (meta/digest-reports/<ck>.json exists) are skipped,
# so the batch is resumable: re-run the same command after an interruption.
# Digest agents only write lit/ + claims/, which is why parallel is safe
# (see meta/CODEX-TASK.md). INTEGRATE (_catalog.md, concepts/, backlinks) is
# NOT done here — run it once after the whole batch, per WORKFLOW §A-5.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$#" -ne 3 ]; then
  echo "Usage: batch_digest.sh <worklist.txt> <parallel> <explicit-runner>" >&2
  exit 2
fi
list="$1"
par="$2"
runner="$3"
[[ "$par" =~ ^[1-9][0-9]*$ ]] || { echo "parallel must be a positive integer" >&2; exit 2; }
[ -f "$list" ] && [ -f "$runner" ] || { echo "missing worklist or runner" >&2; exit 2; }
list="$(cd "$(dirname "$list")" && pwd)/$(basename "$list")"
runner="$(cd "$(dirname "$runner")" && pwd)/$(basename "$runner")"

cd "$ROOT" || exit 1
mkdir -p meta/codex-logs

todo=()
while read -r ck; do
  ck="${ck%%#*}"; ck="$(echo "$ck" | tr -d '[:space:]')"
  [ -z "$ck" ] && continue
  [ -f "meta/digest-reports/$ck.json" ] && { echo "SKIP  $ck (already digested)"; continue; }
  [ -s "fulltext/$ck.txt" ] || { echo "SKIP  $ck (no/empty fulltext)"; continue; }
  todo+=("$ck")
done < "$list"

echo "== ${#todo[@]} papers to digest, $par at a time, runner=$(basename "$runner") =="
echo "== started $(date '+%F %T') =="
for ck in "${todo[@]}"; do
  while [ "$(jobs -rp | wc -l)" -ge "$par" ]; do sleep 5; done
  bash "$runner" "$ck" &
  sleep 2
done
wait
echo "== finished $(date '+%F %T') =="

python3 - "$ROOT" <<'EOF'
import json, os, glob, sys
root = sys.argv[1]
tot = cost = out = 0
n = 0
for f in glob.glob(os.path.join(root, "meta/codex-logs/*.json")):
    try:
        d = json.load(open(f))
        u = d.get("usage") or {}
        if not u:
            continue
        tot += u.get("total_tokens", 0)
        out += u.get("output_tokens", 0)
        cost += d.get("total_cost_usd", 0)
        n += 1
    except Exception:
        pass
print(f"== usage over {n} runs: total_tokens={tot:,}  output_tokens={out:,}  cost=${cost:.2f} ==")
EOF
