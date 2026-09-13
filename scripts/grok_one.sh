#!/bin/bash
# Digest ONE paper via Grok CLI. Usage: grok_one.sh <citekey> [model]
# Use only when Grok was selected for this task (WORKFLOW §A-4).
#
# Flags note: --permission-mode acceptEdits makes grok silently do nothing;
# use --always-approve. grok has no global rules file, so everything it needs
# must be in CODEX-TASK.md / EXTRACTION-PROMPT.md.
ck="$1"
model="${2:-grok-4.6}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GROK="${GROK_BIN:-$HOME/.grok/bin/grok}"
mkdir -p "$ROOT/meta/codex-logs"
echo "START $ck ($model)  $(date +%H:%M:%S)"
# --output-format json so the run's token usage / cost is recorded per paper
# (grok's plain output reports no usage at all).
"$GROK" --cwd "$ROOT" -m "$model" --no-plan --always-approve --max-turns 120 \
  --output-format json \
  -p "Digest paper $ck into this knowledge base. Follow meta/CODEX-TASK.md exactly, processing ONLY citekey $ck. Stop after step 7 of the per-paper procedure." \
  > "$ROOT/meta/codex-logs/$ck.json" 2>"$ROOT/meta/codex-logs/$ck.err"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "FAIL  $ck (agent exit $rc; see meta/codex-logs/)" >&2
  exit "$rc"
fi
echo "DRAFT SESSION FINISHED  $ck (caller must inspect output, verify sources and apply; not integrated)"
