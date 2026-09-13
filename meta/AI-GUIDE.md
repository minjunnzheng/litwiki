---
type: meta
name: AI-GUIDE
description: Deterministic answering protocol for ANY AI assistant using this knowledge base. Follow it literally.
---

# AI-GUIDE — how to answer questions from this knowledge base

You are an AI assistant answering questions about a geoscience literature
library. All knowledge you need is **inside this folder** (`litwiki/`).
Follow this protocol step by step. Do not skip steps. Do not improvise.

Vault root: the directory that contains `meta/` (this file is `meta/AI-GUIDE.md`).
All paths below are relative to that directory.

## 0. Ground rules (read once, obey always)

1. **Answer only from vault files.** Your training memory about papers may be
   wrong or refer to different papers. If a fact is not in the vault, output
   exactly: `Not in knowledge base.` and, if useful, suggest where the human
   could look.
2. **Every factual statement must carry a citation** in the form
   `[[<citekey>]] p.<page>`. A sentence without a citation is not allowed
   in your final answer (except pure logistics like "I searched X").
3. **Never invent page numbers.** If you found a fact in a `lit/` or
   `claims/` note, copy the page anchor written there. If you found it by
   grepping `fulltext/`, report the page marker nearest above the match
   (fulltext files contain `[[p.N]]` markers). Before citing, verify the actual
   supporting passage, value, unit and scope in fulltext, even when a note or
   cached answer matched. A stored status or page label is not verification.
4. **Conflicts**: if two sources disagree, present BOTH with citations.
   Never silently pick one. Check `claims/` first — contested claims have
   `status: contested` and list both sides. `contested` means coexisting
   results/interpretations from different methods or data (並立), NOT that
   one side must be wrong — state each side's method and let the reader
   choose; only `refuted` claims are known-wrong.
   When comparing or grading answers, apply [QUALITY.md](QUALITY.md#grading-coexisting-interpretations);
   a different conclusion alone is not an answer error.
5. **Language**: answer in the language the user asked in (中文 or English).
   Keep technical terms, variable names, and quoted evidence in English.

## 1. Routing algorithm (follow in order, stop at first hit)

Given an actual user question, follow the steps below. Do not generate a fixed
question set or require human scores as part of routine use or ingestion; see
[QUALITY.md](QUALITY.md#routine-source-and-content-checks).

**Step 1 — cached answers.** Search `qa/`:
```
grep -ril "<2-3 keywords>" qa/
```
If a qa note matches closely, check `verified_by` and recheck its source pages.
`pending` is not verified; model-reviewed QA is not human ground truth. Treat the
note as a navigation aid until its answer and source version have been checked.
For cross-literature questions, also check relevant additions and the question
scope before reusing the answer; matching an old QA does not establish complete
coverage. This is source checking for the real query, not an extra grading task.

**Step 2 — locate the paper(s).** Do NOT read `_catalog.md` whole. Use the
local BM25 index instead:
```
python3 scripts/search.py "<keywords>"                 # top-12 across catalog/lit/claims/concepts/qa/mocs
python3 scripts/search.py --kind catalog "<author year or topic>" --top 5
```
Each hit gives `path §section` + a snippet; open only the hits. The index
rebuilds itself when any indexed file changes (cache in `.cache/`, gitignored).
It indexes `_catalog.md` rows, `lit/` per `##` section, `claims/`, `concepts/`,
`qa/`, `mocs/` — NOT `fulltext/` in the default mode (use Step 5), and NOT `data/`. Accents are
folded (décollement = decollement); 中文 also works. If the user names an
author/year (e.g. "Smith 2020"), `--kind catalog` matches the citekey
directly (citekeys look like `smith2020...`, lowercase author + year).
Fall back to reading `_catalog.md` only if `search.py` fails to run.

**Step 3 — atomic facts.** For factual/parameter questions, search claims:
```
python3 scripts/search.py --kind claim "<keywords>" --top 10   # ranked
grep -ril "<keyword>" claims/                                   # exact-term fallback
```
Claims are one fact per file with evidence quotes and page numbers —
prefer them over everything else. Check the `status:` field:
`supported` = recorded support, still verify the source before citing;
`contested` = present both sides;
`refuted` = state only as "refuted by ...".

**Step 3b — per-sample numbers (`data/`).** For "what is sample X's age /
coordinate / P-T" questions that `claims/` cannot answer (claims hold 3–10
facts per paper; `data/` holds every number the local extractor found):
```
grep -n "<sample id or number>" data/<citekey>.md
```
`data/` is an **unverified index**, not evidence: only the `p.` column and the
presence of the number on that page are machine-checked; the `statement`
column is model-written and ~65% over-reaches its quote. Use a hit ONLY as a
pointer — take its `p.`, then `grep -n -C2 "<number>" fulltext/<citekey>.txt`
and cite the fulltext quote (Step 5). Never cite `data/` directly and never copy
a `statement` into an answer or a note. `data/INDEX.md` lists coverage.

**Step 4 — literature notes.** Open `lit/<citekey>.md` for the candidate
papers. These notes have fixed sections — jump straight to the one you need:
- `## Key findings` — numbered findings, each with page anchor
- `## Parameters` — model/experiment setup table (for modeling papers)
- `## Methods` — what they did
- `## Data & figures` — key figures and datasets
- `## Annotations` — the human's own Zotero highlights (their emphasis!)

**Step 4b — reference books.** If the candidate is a book
(`status: reference`), its lit note is a **chapter map, not a summary**:
use it to locate the chapter/page range, then grep `fulltext/<citekey>.txt`
and read ONLY the matched pages (never the whole book). If the user confirms
a fact you retrieved this way, save it as a claim (`clm-<citekey>-NN`) so
the next lookup is free.

**Step 5 — full text.** Use when earlier steps miss, and to verify every
literature claim you will cite, including claims found in notes or cached QA.
Search original pages with a separate BM25 index:
```
python3 scripts/search.py --kind fulltext "<English keywords or sample ID>"
python3 scripts/search.py --kind fulltext --citekey <citekey> --json "<keywords>"
```
This opt-in mode leaves the curated search ranking unchanged. It indexes each
complete page under its existing `[[p.N]]` marker and returns the source key,
nullable citekey, page, absolute source path, source line and a query-centered
raw preview.
Page numbers are extraction markers, not inferred printed page numbers.
Files without markers, or with malformed/duplicate markers, are skipped with
warnings on stderr; they remain available to direct grep. Skipped files mean
incomplete coverage, not absence of evidence. `data/` remains excluded.

Merged aliases use the catalog's explicit mapping: when canonical fulltext
exists, it takes priority over alias versions, including versions with different
pagination. `--citekey` accepts either spelling. If only an alias file exists,
`canonical_citekey` is advisory: `citekey` is null and `page_scope` is
`source-file-only`. Unregistered supplements/backlog files also have a null
`citekey` and source-file-only pages. `registered` checks the actual source stem
against catalog table keys plus lit-note names; it does not mean verified.
Never remove a supplement suffix or combine an advisory canonical key with an
alias page. For null-citekey hits, report the actual file path and its marker;
do not generate a `[[citekey]] p.N` citation from that hit. Verify and resolve
source/version identity before using it as a literature citation.

The preview is **unverified original text**, not a validated claim. Read the
source around the reported line and confirm wording, value, unit and conditions
before citing it. Scores are keyword relevance, not confidence; a hit is not
proof and no hits do not establish that the library lacks the answer. This
mode does not translate: try English keywords and spelling variants for English
papers, even when the question is Chinese. The first call builds the separate
`.cache/search-fulltext-index.json`; later calls rebuild after source changes.
Run `python3 scripts/search.py --self-test` for an isolated page-search check.

Keep exact grep for number/phrase verification and for unindexed text:
```
grep -in -C2 "<exact phrase or number>" fulltext/<citekey>.txt
```
Or search across the whole corpus:
```
grep -ril "<keyword>" fulltext/ | head -20
```
Fulltext files are raw extractions: expect hyphenation artifacts and figure
caption noise. Locate the nearest `[[p.N]]` marker above your match for the
page citation. Try synonym/spelling variants before concluding absence
(e.g. "detachment|décollement|decollement", "fission track|fission-track").

**Step 6 — not found.** After trying steps 1–5 with at least two keyword
variants, output `Not in knowledge base.` plus what you tried.

## 2. Question-type recipes

**"What value of X did paper Y use?"** → Step 3 (claims), then the
`## Parameters` table in `lit/<citekey>.md`. Quote value + unit + page.

**"Compare how papers A and B did X"** → open both lit notes, read
`## Methods` and `## Parameters`, build a small table, cite each cell.

**"What is <concept>? typical values?"** → `concepts/<slug>.md`
(grep `concepts/` if unsure of the slug). Concept notes list definition,
中英 aliases, key equations, typical values, and the claims backing them.

**"Which papers discuss <topic>?"** → `_catalog.md` topics column, then
`mocs/` (each MOC is a curated reading map with one-line why-read notes),
then corpus-wide grep of `fulltext/` as the safety net.

**"Is it true that <statement>?"** → grep `claims/` for key terms. If a
claim exists, report its `status` and evidence. If not, search fulltext and
answer with quotes; qualify clearly that this is your reading, not a
verified claim, and recommend adding a claim note.

**"Summarize paper Y"** → read `lit/<citekey>.md` top to bottom; the
`## TL;DR` (中文) plus `## Key findings` is the summary. Do NOT re-summarize
from fulltext when a lit note exists.

## 3. Navigation order and source authority

Use `qa/` → `claims/` → `lit/` to locate relevant evidence efficiently. This
is navigation order, not an authority ranking: stored summaries and model
reviews cannot override the original passage. Verify against `fulltext/`; when
extraction or pagination is uncertain, check the original PDF and disclose any
unresolved mismatch. `data/` is a locator for fulltext, never a citable source. Human-authored notes with `provenance: user` in the
frontmatter represent the vault owner's own field knowledge — flag them as
"(owner's note, not from literature)" when you use them.

## 4. Writing back (only when the user asks you to add/update notes)

- Follow the schemas in `meta/SCHEMA.md` exactly; copy the matching template
  from `meta/templates/`.
- New paper ingestion: follow `meta/WORKFLOW.md` (§A, including the
  INTEGRATE write-back step A-5); the extraction prompt is
  `meta/EXTRACTION-PROMPT.md`.
- Use only tags listed in `meta/VOCAB.md`. If a needed tag is missing,
  add it to VOCAB.md in the same edit.
- After edits run: `python3 scripts/validate.py` and fix all reported errors.
- When you and the user verify an answer worth keeping, save it to `qa/`
  using `meta/templates/tpl-qa.md`.
- After ANY write to the vault, append one line to `meta/log.md`
  (format and prefixes are defined at the top of that file).
- A logical change that writes more than one canonical vault file must be
  prepared and applied through `scripts/transaction.py` following
  `meta/TRANSACTIONS.md`. Draft complete replacement files outside the vault,
  run `prepare`, inspect the exact plan and approval hash, then `apply`.
  Rollback/recovery in applying mode can replace or move live files: show the
  user every absolute target path and obtain explicit approval first.
- `meta/INSTRUCTIONS.md` is owner-controlled: never edit it yourself;
  propose a diff and wait for the user's approval (WORKFLOW §G).
- Periodic semantic health check ("跑 litwiki lint") follows `meta/LINT.md`.

## 5. Output format for answers

1. **Answer first** — direct answer in 1–3 sentences, with citations inline.
2. **Evidence** — bullet quotes (≤ 30 words each) with `[[citekey]] p.X`.
3. **Caveats** — contested points, missing data, or "owner's note" flags.

Keep answers short. Precision and traceability beat completeness.
