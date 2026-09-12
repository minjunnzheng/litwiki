# Synthetic end-to-end example

These invented teaching documents are not papers or scientific evidence. The
workflow license covers them. Run `python3 -B scripts/demo.py` from the repository
root. It copies this example into temporary storage, validates notes, searches
original pages, checks source drift, and exercises pending/approved/stale grading
with explicitly simulated human labels. No AI service or PDF download is used.

Read `fulltext/tokens.txt` → `lit/tokens.md` → `claims/clm-tokens-01.md` →
`qa/qa-demo.md`. `cases.json` adds an alternative-source conflict and a
corpus-scoped absent answer. All distributed case approvals are pending.
