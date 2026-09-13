# Source versions, integration receipts, and human evaluation

These checks answer different questions. `lit.status` describes digestion;
`claim.status` describes support/conflict; neither proves integration or human
verification. Run `python3 -B scripts/health.py status` to see operational status.

## Source versions

`meta/source-versions.json` maps each actual fulltext filename stem to its
SHA-256, capture date, and the mapped PDF path/hash when available. Source keys
are file identities, not automatically citable aliases. A first baseline records
the files observed today; it cannot reconstruct which version an old digest used.
An unavailable/unmapped PDF is reported separately from the fulltext hash.

Before reading a new or changed source, capture it to a new file outside the vault:

```bash
python3 -B scripts/health.py baseline --citekey <citekey> --output /path/outside/vault/source-versions.json
```

Inspect the proposed record, then include it with the digest and log in a
transaction. The command preserves other source records when a citekey is given.
Omit `--citekey` only when deliberately establishing a baseline for all files.
After digesting, recheck that the source still matches the captured hash. Never
refresh a changed baseline just to clear a warning: first recheck affected notes,
citations, and evaluation cases. Prior versions remain in Git history.

## Integration completion

`meta/integration.json` is the structured completion record. The status command
derives its queue from that file plus current catalog, note and link checks:

- `not-digested`: a stub; not ready for ordinary INTEGRATE.
- `pending`: explicitly recorded unfinished work, a missing catalog row, or a
  missing linked claim. A repaired catalog row alone does not clear the record.
- `unrecorded`: a legacy digest has no completion receipt. This does not mean it
  was never integrated. MOC and reciprocal-link flags are review leads only.
- `complete`: a complete receipt whose bound files still match.
- `stale-receipt`: a completion record is incomplete or its bound files changed.

For each paper, record the concepts, MOCs, backlinks and QA impact checks as
`done` or `not-applicable`, each with a reason. No arbitrary backlink quota is
required: only add links that the literature supports. Example receipt shape:

```json
{
  "<citekey>": {
    "status": "complete",
    "reviewer": "actual operator or model name",
    "checked_at": "ISO date/time",
    "checks": {
      "concepts": {"status": "done", "reason": "which concept was checked or updated"},
      "mocs": {"status": "done", "reason": "which MOC was checked or updated"},
      "backlinks": {"status": "not-applicable", "reason": "why none are supported"},
      "qa": {"status": "done", "reason": "queries used; affected QA or none"}
    },
    "files": {
      "lit/<citekey>.md": "SHA-256 of final note",
      "fulltext/<citekey>.txt": "SHA-256 of the source actually reviewed"
    }
  }
}
```

Bind at least the source and final lit note; additionally bind files whose exact
content the receipt depends on. The catalog row is checked live. Binding a shared
MOC means later edits to that file conservatively make this receipt stale. Prepare
the receipt with the other INTEGRATE replacements, using their final bytes, and
apply everything through `transaction.py`. A receipt records the operator's work,
not automatic scientific approval. Pending records can instead contain
`status: pending`, per-check reasons, and an `evidence` pointer to the observed debt.

## Human-reviewed question set

Keep private evaluation JSON outside the public workflow repo. Draft from existing
QA without promoting its verification labels:

```bash
python3 -B scripts/eval_human.py --draft-qa --output /path/outside/vault/cases.json
python3 -B scripts/eval_human.py --cases /path/outside/vault/cases.json
```

Every exported case starts `pending`, including QA formerly labelled `user`.
A person must check the question, expected answer, source file version, exact
quote, extraction page, units and conditions. Fill each `evidence` item with
`citekey`, integer `page`, `quote`, `source_sha256`. Set `kind` to `answerable`,
`conflict` (both sources required), or `not-in-kb`. A negative case needs the exact
answer `Not in knowledge base.`, the current reported `corpus_sha256`, and an
`absence_review` explaining search scope and alternatives tried. It expires when
the evidence corpus changes. This is a corpus-scoped judgement, not a universal
claim that no literature exists.

Only then fill `review` with `status: approved`, `reviewer_kind: human`, the
actual person's `reviewer` name, and `reviewed_at: YYYY-MM-DD`. AI operators must
never fill these fields on a person's behalf without their explicit review.
The fields are an attestation, not identity authentication. Pending cases are
excluded; approved cases with changed sources, wrong pages or unmatched quotes
are blocked and listed. Zero eligible cases produces null metrics, not a pass.

To assess a model answer, supply a JSON list via `--predictions`:

```json
[{"id":"case-id","answer":"candidate answer","citations":[
  {"citekey":"source-key","page":1,"quote":"exact source wording"}
]}]
```

The result separately reports retrieval Hit/MRR/source Recall (QA excluded),
citation-location recall, literal citation errors, and negative-case abstention.
These mechanical measurements do not prove that an answer follows from evidence.
No model is called by this evaluator.

For semantic grading, a person supplies a JSON list via `--reviews`, matching the
reported `case_sha256` and `prediction_sha256` so edits invalidate old grades:

```json
[{
  "id":"case-id","status":"approved","reviewer_kind":"human",
  "reviewer":"actual person","reviewed_at":"YYYY-MM-DD",
  "case_sha256":"from result","prediction_sha256":"from result",
  "checks":{"accuracy":true,"units":true,"conditions":true,"conflicts":null,"abstention":null}
}]
```

Use `true`/`false` for each applicable criterion and `null` only when irrelevant;
accuracy must be graded. Report denominators per criterion. Include wrong-page,
wrong-unit, missing-condition, conflicting-source and absent-answer cases in the
review set. Split development cases from held-out cases before tuning retrieval;
do not report this small regression set as a general research benchmark.

### Grading coexisting interpretations

`expected_answer` is a reviewed reference, not the only acceptable conclusion or
wording. Grade whether an answer faithfully represents the evidence and answers
the question within its stated scope. Apply this rubric to human grading and AI
review commentary; AI commentary still does not count as a human score.

- A transcription, unit, citation or attribution error is correctable. Report
  citation-location errors separately from the scientific interpretation.
- Different regions, periods, definitions, methods or assumptions can explain
  different results. State those conditions; do not force a contradiction.
- Competing interpretations of the same question may remain unresolved. Present
  each relevant position with its source, evidence, assumptions and limitations.
  A justified preference is allowed if its basis is explicit and alternatives
  are represented fairly. Preserving alternatives does not require equal weight.
- Model agreement, a majority vote, publication recency or a difference from the
  reference answer alone cannot establish that another interpretation is wrong.
  Do not set a claim to `refuted` without an explicit, source-grounded reason.

For `checks`, `accuracy` means faithful attribution and evidence-supported
statements, including honest uncertainty; it does not require settling the
scientific debate. `conditions` checks applicable scope and assumptions.
`conflicts` checks fair presentation of relevant competing positions and the
limits of any preference, not convergence to one answer. An unresolved debate
can pass these checks. If the reviewer cannot assess a required check, leave the
review pending; `null` means irrelevant, not uncertain.

Before grading, record the question's scope, required perspectives and applicable
criteria in the case's `review_notes`; these are bound by `case_sha256`. Review
changes before approving the case again. A paper-specific question need not
survey every competing paper; a cross-literature comparison must not omit a
relevant alternative merely because the reference favours another position.

Source/location recall measures overlap with the chosen reference evidence,
not scientific correctness or exhaustive coverage. If an answer brings valid
additional evidence, verify it and reconsider the reference; do not penalise the
answer solely for that difference. Recheck affected cases when new literature is
integrated, even when previously cited files have not changed.

`examples/demo/` contains synthetic teaching material. `scripts/demo.py` exercises
the pipeline and simulated approvals in temporary storage, not real human gold.
