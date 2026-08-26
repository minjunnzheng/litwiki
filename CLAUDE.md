# litwiki — literature knowledge base

MANDATORY: Before answering ANY question about the literature, read
`meta/AI-GUIDE.md` and follow its protocol exactly. Do not answer from
your own training knowledge; answer only from files in this vault.

Quick facts:
- One paper = one note in `lit/`, filename = Better BibTeX citekey.
- Full text of every PDF is in `fulltext/<citekey>.txt` (grep-able).
- Route with `python3 scripts/search.py "<keywords>"` (local BM25 over
  catalog/lit/claims/concepts/qa); do not read `_catalog.md` whole.
- Atomic facts live in `claims/`; verified answers are cached in `qa/`.
- `data/` = unverified per-sample number index (locator only; cite fulltext, never data/).
- Every factual statement you output MUST carry a citation `[[citekey]] p.X`.
- If the vault does not contain the answer, say exactly:
  "Not in knowledge base." — never guess, never fill from memory.
- After any write to the vault, append one line to `meta/log.md`.
- Multi-file canonical writes use `scripts/transaction.py` and
  `meta/TRANSACTIONS.md`; inspect the exact bundle before apply. Never run an
  applying rollback/recovery without the user's explicit approval.
- `meta/INSTRUCTIONS.md` (owner's priorities) is read-only for AI —
  propose diffs, never edit directly.
