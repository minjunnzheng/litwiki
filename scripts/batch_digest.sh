#!/bin/bash
# batch_digest.sh <worklist.txt> <parallel> <runner>
#   worklist = one citekey per line (blank lines / # comments ignored)
#   parallel = required positive concurrency limit
#   runner   = required explicit runner selected for this task
#
# The explicit worklist determines scope; old report files do not prove completion.
# Digest agents draft per-paper replacements outside the vault (AGENT-TASK).
# The caller verifies and applies them, then completes WORKFLOW §A-5 INTEGRATE.
# Do not automatically retry the whole list; inspect outputs and select unfinished keys.
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
mkdir -p meta/agent-logs

todo=()
while read -r ck; do
  ck="${ck%%#*}"; ck="$(echo "$ck" | tr -d '[:space:]')"
  [ -z "$ck" ] && continue
  [ -s "fulltext/$ck.txt" ] || { echo "SKIP  $ck (no/empty fulltext)"; continue; }
  todo+=("$ck")
done < "$list"

echo "== ${#todo[@]} papers to digest, $par at a time, runner=$(basename "$runner") =="
echo "== started $(date '+%F %T') =="
pids=()
for ck in "${todo[@]}"; do
  while [ "$(jobs -rp | wc -l)" -ge "$par" ]; do sleep 5; done
  bash "$runner" "$ck" &
  pids+=("$!")
  sleep 2
done
failed=0
for pid in "${pids[@]}"; do
  wait "$pid" || failed=1
done
echo "== agent batch exited (failures=$failed; caller verification/apply still required) $(date '+%F %T') =="

python3 - "$ROOT" <<'EOF'
import json, os, glob, sys
root = sys.argv[1]
tot = cost = out = 0
n = 0
for f in glob.glob(os.path.join(root, "meta/agent-logs/*.json")):
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
exit "$failed"
