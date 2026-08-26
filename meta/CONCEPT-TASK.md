# CONCEPT-TASK — write or update ONE concept page

Process exactly ONE slug, the one named in the prompt. Do not touch any
other concept.

## Input

A batch JSON (path given in the prompt), one entry per slug:
```bash
python3 -c "import json;print(json.dumps(json.load(open('meta/concept-batch.json'))['<SLUG>'],ensure_ascii=False,indent=1))"
```
Fields: `mode` (`new` or `update`), `papers` (citekeys that proposed this
concept), `why` / `kv` (each proposing paper's justification and key
values), `merged_from` (slugs folded into this one — cover their content
here, and do not create separate pages for them).

## Procedure

1. Read `meta/SCHEMA.md` §concept and copy `meta/templates/tpl-concept.md`.
   Allowed tags: `meta/VOCAB.md` only.
2. For every citekey in `papers`, read `lit/<citekey>.md` and its
   `claims/clm-<citekey>-*.md`. Pull numbers from the claims (they already
   carry verified page anchors). Grep `fulltext/<citekey>.txt` only to
   check a value or find a quote.
3. Also grep `claims/` and `concepts/` for papers already in the vault
   that bear on this concept — a concept page is a cross-corpus synthesis,
   not a summary of one batch.
4. `mode: update` → do not rewrite the page. Add rows to `## Typical values`,
   extend `## Related`, and add at most 2–3 sentences to `## Definition`
   only where the new papers genuinely change it. Preserve every existing
   line and citation.
5. Write/overwrite ONLY `concepts/<slug>.md`.
6. Run `python3 scripts/validate.py` and fix every ERROR you introduced.

## Content requirements

- `## Definition` — 中文為主、技術詞保留英文. What it is, why it matters,
  what it is confused with. Every substantive claim has `[[citekey]]` or
  `[[clm-...]]`.
- `## Key equations` — LaTeX `$$` if there are any, else `none`.
- `## Typical values` — `| context | value | source |`. Numbers verbatim,
  with units. Source is `[[citekey]] p.N` or `[[clm-...]]`. Cross-region
  rows beat a pile from one area.
- `## Related` — `claims:` / `papers:` (one sentence each) / `concepts:`.

## Hard rules

- Every number verbatim from claims or fulltext. Page numbers must exist.
- Do not invent translations. Keep English unless `INSTRUCTIONS.md` names
  a glossary that already has the term.
- Do not send xreview / ai-review; the caller owns the verification gate.
- Only write `concepts/<slug>.md`. Do not modify `lit/`, `claims/`,
  `_catalog.md`, `VOCAB.md`, `meta/log.md`, or `mocs/`.
