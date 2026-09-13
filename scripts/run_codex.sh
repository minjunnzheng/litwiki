#!/bin/bash
# Explicit Codex worklist only; WORKFLOW §A-4 requires the user's model selection.
# The shared batch runner preserves agent failures and leaves verification to the caller.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <worklist.txt>" >&2
  exit 2
fi
exec bash "$ROOT/scripts/batch_digest.sh" "$1" 6 "$ROOT/scripts/codex_one.sh"
