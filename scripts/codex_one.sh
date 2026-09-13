#!/bin/bash
# Digest ONE paper via Codex CLI. Usage: codex_one.sh <citekey> [model]
# Use only when Codex was selected for this task (WORKFLOW §A-4).
# Model default gpt-5.6-sol applies only after that explicit selection.
#
# Flags note (codex-cli 0.147.0): --full-auto was removed, and --sandbox is
# mutually exclusive with --approve-for-me (which already implies
# workspace-write). Do not reintroduce either.
ck="$1"
model="${2:-gpt-5.6-sol}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "START $ck ($model)  $(date +%H:%M:%S)"
codex exec --approve-for-me -C "$ROOT" -m "$model" \
  "Digest paper $ck into this knowledge base. Follow meta/CODEX-TASK.md exactly, processing ONLY citekey $ck. Stop after step 7 of the per-paper procedure. Do NOT open an xreview/ai-review round for this — the verification gate is the main session's job, not yours." \
  > "$ROOT/meta/codex-logs/$ck.log" 2>&1
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "FAIL  $ck (agent exit $rc; see meta/codex-logs/)" >&2
  exit "$rc"
fi
echo "DRAFT SESSION FINISHED  $ck (caller must inspect output, verify sources and apply; not integrated)"
