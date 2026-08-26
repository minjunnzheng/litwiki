---
name: litwiki
description: Answer questions from a literature knowledge base (litwiki) — digested papers with per-fact page citations. Use when the user asks about the literature (a paper's parameters, comparisons between papers, a concept's definition or typical values, "which papers discuss X", "is it true that Y"), or asks to add or update notes in the library. Answers are grounded ONLY in the vault; every factual sentence carries a [[citekey]] p.X citation; if the vault lacks the answer the reply is exactly "Not in knowledge base."
---

# litwiki — cited answers from the literature vault

Vault root: `$LITWIKI_ROOT` if set, otherwise the directory that contains
`meta/AI-GUIDE.md` (walk up from the current working directory; if that
fails, ask the user where the vault lives).

This skill is a **thin launcher**. The answering protocol has one home:

**→ Read `$LITWIKI_ROOT/meta/AI-GUIDE.md` in full, then follow it literally.**

That file defines the routing (`qa → claims → lit → fulltext`), the
citation rule, conflict handling, and the output format. Do not answer
before reading it. Do not answer from training memory about these papers.

## When invoked

1. Resolve the vault root as above.
2. Read `meta/AI-GUIDE.md`.
3. Route the question per its §1 algorithm; stop at the first hit.
4. Answer in §5 format: direct answer first, then evidence bullets, each
   factual sentence carrying `[[citekey]] p.X`. After ≥2 keyword variants
   across the layers with no hit, output exactly `Not in knowledge base.`
   plus what you searched.
5. Reply in the user's language (中文 or English); keep citekeys, quotes,
   and technical terms verbatim.

## Writing back (only if the user asks to add or update)

Follow `meta/AI-GUIDE.md` §4 and `meta/WORKFLOW.md`. Use the schemas in
`meta/SCHEMA.md`, tags from `meta/VOCAB.md`, run `python3 scripts/validate.py`
from the vault root, and fix every error before finishing. New-paper
ingestion goes through `meta/EXTRACTION-PROMPT.md` plus INTEGRATE
(WORKFLOW §A-5). Bibliography must pass `scripts/bibcheck` before it
enters any trusted store. After any write, append one line to
`meta/log.md`. Never edit `meta/INSTRUCTIONS.md` without an approved
diff. "跑 litwiki lint" → `meta/LINT.md`.

Multi-file canonical writes use `scripts/transaction.py` and
`meta/TRANSACTIONS.md`. Inspect the exact bundle before apply. Never run
an applying rollback without explicit user approval.

## Other AIs (no skill required)

- **Querying**: open the vault and say "follow `meta/AI-GUIDE.md` exactly,
  then answer: <question>". `CLAUDE.md` / `AGENTS.md` in the vault root
  load that instruction when the session is rooted there.
- **Ingesting via a CLI agent**: `bash scripts/codex_one.sh <citekey>`
  (enforces `meta/CODEX-TASK.md`).

The single source of truth is always `meta/AI-GUIDE.md`.
