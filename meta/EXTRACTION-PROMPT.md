---
type: meta
name: EXTRACTION-PROMPT
description: The exact prompt given to a strong AI to digest one paper into lit + claim notes. Used for the initial batch and for every future ingestion.
---

# EXTRACTION-PROMPT — digest one paper

> Usage: give a strong AI this whole prompt with the placeholders filled.
> One paper per agent/session. 未來新增論文也用這份，品質才一致。

---

You are digesting one scientific paper into a structured knowledge base so
that a much weaker AI can later answer questions about it *without reading
the paper*. Whatever you do not write down is lost — extract accordingly.

**Inputs**
- citekey: `{{citekey}}`
- metadata (from library.bib): `{{title / authors / year / journal / doi}}`
- full text: `litwiki/fulltext/{{citekey}}.txt` (contains `[[p.N]]` page markers)
- PDF (for figures, only if needed): `{{pdf_path}}`
- Zotero annotations (may be empty): `{{annotations}}`
- schema: read `litwiki/meta/SCHEMA.md` and follow it exactly
- allowed tags: `litwiki/meta/VOCAB.md`
- owner priorities: read `litwiki/meta/INSTRUCTIONS.md`. If the paper falls
  under a 焦點主題, extract DENSER: aim for the upper end of the findings
  (12) and claims (10) ranges, and make the Parameters table exhaustive.
  The 「抽取時永遠優先」 items there apply to every paper regardless of topic.

**Tasks**

1. Read the ENTIRE fulltext. Do not stop at the abstract.

2. Write `litwiki/lit/{{citekey}}.md` following the `lit` schema exactly:
   - TL;DR：中文 3–5 句。
   - Key findings: 5–12 numbered findings. Each one sentence, each with a
     page anchor. Include the *quantitative* result, not just the direction
     ("shortening rate 15 mm/yr", not "fast shortening").
   - Parameters: for modeling/experimental papers, extract EVERY setup
     value you can find (domain, resolution, rheology, boundary conditions,
     rates, temperatures, material properties, erosion laws...). This table
     is the single most-queried part of the note.
   - Data & figures: list the 3–6 figures a reader would actually need, and
     any datasets/repositories with identifiers.
   - Annotations: paste the provided Zotero annotations verbatim with pages.
   - Relevance: link other citekeys from `_catalog.md` that this paper
     extends, contradicts, or uses. Only link papers actually in the catalog.

3. Extract 3–10 **claims** into `litwiki/claims/` (schema `claim`):
   - Atomic: one falsifiable statement each, numbers verbatim, with a ≤40-word
     supporting quote and page.
   - Choose the claims a researcher would want to *cite or check*: headline
     results, key parameter values, disputed interpretations.
   - File/id naming: `clm-{{citekey}}-01`, `clm-{{citekey}}-02`, ... —
     scoped to this paper, so parallel ingestion never collides.
   - If a new claim contradicts an existing one in `claims/`, set both to
     `status: contested` and cross-list in `counter_sources`.

4. Return (as your final output) a JSON object:
   ```json
   {
     "citekey": "...",
     "one_liner": "一句話中文摘要（給 _catalog.md 用）",
     "topics": ["..."], "methods": ["..."], "regions": ["..."],
     "new_tag_proposals": ["..."],
     "claims_written": ["clm-...-001"],
     "concept_candidates": [
       {"slug": "...", "why": "...", "key_values": "..."}
     ],
     "problems": ["fulltext truncated at p.12", ...]
   }
   ```

**Rules**
- Every number you write must exist in the fulltext — copy, never estimate.
- Every page anchor must correspond to a real `[[p.N]]` marker location.
- Prefer VOCAB.md tags; propose new ones in `new_tag_proposals`, don't invent
  silently.
- If the fulltext is corrupt/truncated, extract what you can and report it
  in `problems`.
- Write nothing outside `lit/` and `claims/`.
