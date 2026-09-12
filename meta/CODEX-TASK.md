# CODEX-TASK — digest one paper (hand-off kit)

Task for an external coding agent (Codex, Grok, or similar). Work inside
the vault root (the directory that contains `meta/AI-GUIDE.md`). Process
exactly the citekey named in the prompt.

## Per-paper procedure (one citekey)

1. Read `meta/EXTRACTION-PROMPT.md` and `meta/SCHEMA.md` — follow them
   exactly. Allowed tags: `meta/VOCAB.md`. Owner priorities:
   `meta/INSTRUCTIONS.md`.
2. Get metadata from `meta/map.json` (built by `scripts/zotero_map.py`):
   ```bash
   python3 -c "import json;print(json.dumps(json.load(open('meta/map.json'))['<CITEKEY>'],ensure_ascii=False)[:24000])"
   ```
   If the citekey is missing, stop and report it — do not reconstruct
   metadata from memory.
3. Read the entire fulltext `fulltext/<CITEKEY>.txt`. It contains
   `[[p.N]]` page markers — those N values are the page anchors.
4. Write `lit/<CITEKEY>.md` (frontmatter per SCHEMA `lit`; set
   `status: digested`, `digested_by: <your model name>`,
   `digested_date: <today ISO>`), and 3–10 claim files
   `claims/clm-<CITEKEY>-01.md`, `-02.md`, … (SCHEMA `claim`).
5. In `## Relevance`, link only citekeys that already appear in
   `_catalog.md`.
6. Write `meta/digest-reports/<CITEKEY>.json`:
   ```json
   {"citekey":"...","ok":true,"one_liner":"one-sentence summary",
    "topics":[],"methods":[],"regions":[],"new_tag_proposals":[],
    "claims_written":[],"concept_candidates":[],"problems":[]}
   ```
7. Run `python3 scripts/validate.py` — fix every ERROR you introduced
   before stopping. Broken-link warnings to papers not yet ingested are
   expected; ignore those.

## Hard rules

- Every number verbatim from the fulltext — never estimate or recall from
  training memory. Every finding/claim carries a real `p.N` anchor.
- **Anchor a number to the page the number is printed on**, not the page
  where it is discussed. Results tables often sit several pages after the
  interpreting text.
- Notes bilingual: 中文 TL;DR, English technical content.
- **Do not invent translations.** Keep the English original unless
  `INSTRUCTIONS.md` names a glossary and the term is in it.
- OCR artifacts: record what is reliable, note the corruption in
  `problems`, do not fabricate.
- Do not edit `_catalog.md`, `VOCAB.md`, or files of other papers.
- Do not open an xreview / ai-review round. Verification is the calling
  session's job.

## Driver

Follow WORKFLOW §A-4. The current session handles ingestion unless the user
explicitly delegates this task. Only then use the selected runner in `scripts/`.
Capture and recheck the exact source version per `meta/QUALITY.md`. Finishing
step 7 means digested, not integrated; leave completion receipts to the caller.
