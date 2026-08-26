---
type: meta
name: HOME
description: Human entry point — dashboard and directory of the knowledge base.
---

# litwiki — literature knowledge base

> AI: read [[AI-GUIDE]] first. Humans: start from a MOC or [[_catalog]].

## For humans

- **Browse a topic** → the matching MOC, or [[_catalog]].
- **Known paper** → open by citekey. Filenames are citekeys; do not rename them.
- Each `lit/` note can carry a local PDF preview link and a Zotero reader
  link once you have wired Zotero (WORKFLOW §D).

## For asking the AI

Root a session in this directory and say:

> Follow the litwiki protocol: <your question>

The AI routes `qa → claims → lit → fulltext` per [[AI-GUIDE]]. Every
factual sentence carries `[[citekey]] p.X`. If it is not in the vault the
reply is `Not in knowledge base.`

Useful shapes:

- Parameter: "What shortening rate does paper X's preferred model use?"
- Compare: "How do papers X and Y treat the dip of fault Z?"
- Concept: "What is critical taper? Typical values?"
- Scan: "Which papers use ZFT on this orogen?"

Save a good answer with "store this Q&A as tpl-qa in qa/". New papers go
through [[WORKFLOW]] §A.

## Index

- [[_catalog]] — one line per paper
- [[SCHEMA]] / [[VOCAB]] / [[WORKFLOW]] — spec and SOP
- [[TRANSACTIONS]] — preview, apply, rollback
- [[INSTRUCTIONS]] — your priorities (you own this file)
- [[log]] — append-only event log
- [[TO-FIND]] — gap list
- [[EXTRACTION-PROMPT]] — the only ingest prompt
- [[CODEX-TASK]] — hand-off for an external CLI agent
- [[LINT]] — periodic semantic check; reports land in `meta/lint-reports/`
