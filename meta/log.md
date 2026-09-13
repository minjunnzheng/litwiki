---
type: meta
name: log
description: Append-only event log. One line per vault write.
---

# log

Format: `YYYY-MM-DD  KIND  one line`. KIND is `INGEST` / `INTEGRATE` /
`QA` / `SCHEMA` / `FIX` / `DATA`. Never edit old lines.

2026-08-27  SCHEMA     empty vault initialised from the public workflow template

2026-09-12  SCHEMA     Template candidate: explicit per-task model selection, page search, source/integration records, human-evaluation gates, synthetic demo, package CI and upgrade instructions. Personal papers and review data remain outside this package.
2026-09-13  SCHEMA     Clarified evidence-based grading in QUALITY: preserve competing interpretations, distinguish scope differences and citation errors, and bind case-specific criteria in review_notes; AI-GUIDE links to the rubric. No scientific claims, QA answers or human grades changed.
2026-09-13  SCHEMA     Routine ingestion and queries use source/content checks without fixed question sets or human-scoring gates. QA remains an optional cache; tool evaluation requires an explicit request, and ungraded drafts are not integration debt.
2026-09-13  FIX        Final system audit: made source verification override cached-note precedence, aligned ingestion draft/transaction boundaries and coexisting-view lint rules; health now reports broken/untracked note PDF links without refreshing source baselines. Legacy single-paper runners now preserve CLI failure status and never infer success from an old digest report.
2026-09-13  FIX        Final audit follow-up: explicit batch worklists no longer skip based solely on old reports; batch exits nonzero when an agent fails, and the legacy Codex entry delegates to the shared batch runner.
