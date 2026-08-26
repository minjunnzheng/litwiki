#!/bin/bash
# concept_one.sh <slug> [model] — write/update ONE concepts/<slug>.md via grok.
# Driven by meta/CONCEPT-TASK.md + meta/concept-batch-<date>.json.
set -u
slug="$1"
model="${2:-grok-4.6}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GROK="${GROK_BIN:-$HOME/.grok/bin/grok}"
mkdir -p "$ROOT/meta/codex-logs"
echo "START concept:$slug ($model)  $(date +%H:%M:%S)"
"$GROK" --cwd "$ROOT" -m "$model" --no-plan --always-approve --max-turns 120 \
  --output-format json \
  -p "Write the concept page for slug $slug. Follow meta/CONCEPT-TASK.md exactly, processing ONLY slug $slug." \
  > "$ROOT/meta/codex-logs/concept-$slug.json" 2>"$ROOT/meta/codex-logs/concept-$slug.err"
if [ -s "$ROOT/concepts/$slug.md" ]; then
  echo "DONE  concept:$slug  $(date +%H:%M:%S)  $(python3 "$ROOT/scripts/_usage_line.py" "$ROOT/meta/codex-logs/concept-$slug.json" 2>/dev/null)"
else
  echo "FAIL  concept:$slug  $(date +%H:%M:%S)"
fi
