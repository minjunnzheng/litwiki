#!/usr/bin/env python3
"""Evaluate human-reviewed cases; lexical matches never count as semantic approval."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

import eval_retrieval as retrieval
from health import digest, source_path
from search import fulltext_pages

ROOT = Path(__file__).resolve().parent.parent
SENTINEL = "Not in knowledge base."
CRITERIA = ("accuracy", "units", "conditions", "conflicts", "abstention")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def corpus_hash(root):
    # Same evidence layers as retrieval; QA is deliberately excluded.
    files = [root / "_catalog.md"]
    for folder, suffix in (("fulltext", "txt"), ("lit", "md"), ("claims", "md"),
                           ("concepts", "md"), ("mocs", "md")):
        files.extend(sorted((root / folder).glob(f"*.{suffix}")))
    return fingerprint({str(p.relative_to(root)): digest(p) for p in files if p.is_file()})


def human_review(record):
    if record.get("status") != "approved" or record.get("reviewer_kind") != "human":
        return False
    if not str(record.get("reviewer", "")).strip():
        return False
    try:
        date.fromisoformat(record.get("reviewed_at", ""))
    except (TypeError, ValueError):
        return False
    return True


def evidence_errors(root, evidence):
    errors = []
    for e in evidence:
        key = e.get("citekey", "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", key):
            errors.append("invalid citekey")
            continue
        path = source_path(root, f"fulltext/{key}.txt")
        if not (root / "lit" / f"{key}.md").is_file() or not path.is_file():
            errors.append(f"{key}: missing registered source")
            continue
        if e.get("source_sha256") != digest(path):
            errors.append(f"{key}: source changed or no source hash")
            continue
        text = path.read_text()
        lines = text.split("\n")
        pages = {page: "\n".join(lines[start + 1:end]) for start, end, page in fulltext_pages(text)}
        page, quote = e.get("page"), e.get("quote", "")
        if type(page) is not int or page not in pages:
            errors.append(f"{key}: missing page marker {page}")
        elif not isinstance(quote, str) or not quote.strip() or quote not in pages[page]:
            errors.append(f"{key} p.{page}: quote not found verbatim")
    return errors


def case_errors(root, case, corpus):
    errors = []
    if not case.get("question") or not case.get("expected_answer"):
        errors.append("missing question or expected answer")
    if case.get("kind") not in ("answerable", "conflict", "not-in-kb"):
        errors.append("unknown case kind")
    evidence = case.get("evidence", [])
    if case.get("kind") == "not-in-kb":
        if evidence or case.get("expected_answer") != SENTINEL:
            errors.append("negative case must use the exact sentinel and no positive evidence")
        if case.get("corpus_sha256") != corpus or not case.get("absence_review"):
            errors.append("negative case needs a current corpus hash and human search-scope explanation")
    else:
        if not evidence:
            errors.append("positive case needs evidence")
        errors.extend(evidence_errors(root, evidence))
        if case.get("kind") == "conflict" and len({e.get("citekey") for e in evidence}) < 2:
            errors.append("conflict case needs both sources")
    return errors


def draft_qa(root):
    cases = []
    corpus = corpus_hash(root)
    for path in sorted((root / "qa").glob("qa-*.md")):
        parsed = retrieval.parse_qa(path)
        _, body = retrieval.split_frontmatter(path.read_text(), path)
        answer = body.partition("## Answer")[2].strip()
        cases.append({"id": parsed["id"], "question": parsed["question"],
                      "kind": "not-in-kb" if parsed["negative"] else "answerable",
                      "expected_answer": answer, "evidence": [],
                      "candidate_sources": parsed["gold_sources"], "corpus_sha256": corpus,
                      "absence_review": "", "origin": str(path),
                      "previous_verified_by": parsed["verified_by"],
                      "review": {"status": "pending", "reviewer_kind": "", "reviewer": "", "reviewed_at": ""}})
    return {"schema": "litwiki.human-eval.v1", "cases": cases}


def keyed(records, label):
    result = {}
    for record in records:
        key = record.get("id")
        if not isinstance(key, str) or not key or key in result:
            raise ValueError(f"{label}: missing or duplicate id {key!r}")
        result[key] = record
    return result


def evaluate(root, dataset, predictions=None, reviews=None, top=None):
    if dataset.get("schema") != "litwiki.human-eval.v1":
        raise ValueError("unsupported dataset schema")
    cases = keyed(dataset["cases"], "cases")
    predictions = keyed(predictions or [], "predictions")
    reviews = keyed(reviews or [], "reviews")
    if predictions.keys() - cases.keys() or reviews.keys() - predictions.keys():
        raise ValueError("prediction/review IDs must match supplied cases/predictions")
    corpus = corpus_hash(root)
    eligible, blocked, pending = [], [], []
    for case in cases.values():
        if not human_review(case.get("review", {})):
            pending.append(case["id"])
            continue
        errors = case_errors(root, case, corpus)
        if errors:
            blocked.append({"id": case["id"], "errors": errors})
        else:
            eligible.append(case)
    search = retrieval.load_search_module(root)
    top = top or search.DEFAULT_TOP
    if top < 1:
        raise ValueError("top must be positive")
    docs, _ = search.collect_docs()
    index = search.compile_index([d for d in docs if d["kind"] != "qa"])
    kinds = tuple(k for k in search.KINDS if k != "qa")
    mapping = retrieval.validate_claim_mappings(root) if eligible else {}
    rows, retrieval_scores = [], []
    for case in eligible:
        key = case["id"]
        row = {"id": key, "case_sha256": fingerprint(case)}
        negative = case["kind"] == "not-in-kb"
        if not negative:
            labels = {"id": key, "gold_sources": sorted({e["citekey"] for e in case["evidence"]}), "negative": False}
            hits = search.query(index, case["question"], top, kinds)
            score = retrieval.score_case(labels, hits, root, mapping, top)
            retrieval_scores.append(score)
            row["retrieval"] = score
        prediction = predictions.get(key)
        row["prediction_present"] = prediction is not None
        row["human_checks"] = None
        if prediction is not None:
            row["prediction_sha256"] = fingerprint(prediction)
            if not isinstance(prediction.get("answer"), str):
                raise ValueError(f"{key}: prediction answer must be text")
            citations = prediction.get("citations", [])
            if not isinstance(citations, list) or not all(isinstance(c, dict) for c in citations):
                raise ValueError(f"{key}: citations must be a list of objects")
            expected = {(e["citekey"], e["page"]) for e in case["evidence"]}
            observed = {(e.get("citekey"), e.get("page")) for e in citations}
            row["citation_location_recall"] = len(expected & observed) / len(expected) if expected else None
            # Freeze citations to the current source solely to check printed location/quote.
            checked_citations = []
            for e in citations:
                e = dict(e)
                path = source_path(root, f"fulltext/{e.get('citekey', '')}.txt")
                e["source_sha256"] = digest(path) if path.is_file() else None
                checked_citations.append(e)
            row["citation_errors"] = evidence_errors(root, checked_citations)
            row["exact_abstention"] = prediction.get("answer", "").strip() == SENTINEL if negative else None
            review = reviews.get(key, {})
            checks = review.get("checks", {})
            if (human_review(review) and review.get("case_sha256") == row["case_sha256"]
                    and review.get("prediction_sha256") == row["prediction_sha256"]
                    and set(checks) == set(CRITERIA)
                    and all(type(v) is bool or v is None for v in checks.values())
                    and type(checks.get("accuracy")) is bool
                    and (case["kind"] != "conflict" or type(checks.get("conflicts")) is bool)
                    and (not negative or type(checks.get("abstention")) is bool)):
                row["human_checks"] = checks
            elif review:
                row["review_error"] = "incomplete, non-human, or stale case/answer review"
        rows.append(row)
    human = {}
    for criterion in CRITERIA:
        values = [r["human_checks"][criterion] for r in rows
                  if r["human_checks"] is not None and r["human_checks"][criterion] is not None]
        human[criterion] = {"n": len(values), "pass_rate": sum(values) / len(values) if values else None}
    return {"schema": "litwiki.human-eval-result.v1", "vault": str(root.resolve()),
            "corpus_sha256": corpus, "dataset_sha256": fingerprint(dataset),
            "git": retrieval.git_provenance(root), "k": top,
            "eligible_human_cases": len(eligible), "pending_cases": pending, "blocked_cases": blocked,
            "retrieval": retrieval.summarize(retrieval_scores), "human_answer_checks": human, "cases": rows,
            "limitations": "Human review is an explicit attestation, not identity authentication. "
                            "Exact quotes and page matches do not establish semantic support. "
                            "No human-reviewed cases means no measured human-grounded performance."}


def self_test():
    with tempfile.TemporaryDirectory(prefix="litwiki-eval-") as folder:
        root = Path(folder)
        (root / "fulltext").mkdir(); (root / "lit").mkdir()
        source = root / "fulltext/demo.txt"
        source.write_text("[[p.1]]\nThe demonstration uses blue tokens.\n[[p.2]]\nOther text.\n")
        (root / "lit/demo.md").write_text("fixture")
        evidence = {"citekey": "demo", "page": 1, "quote": "blue tokens", "source_sha256": digest(source)}
        assert not evidence_errors(root, [evidence])
        assert evidence_errors(root, [{**evidence, "page": 2}])
        assert evidence_errors(root, [{**evidence, "quote": "red tokens"}])
        assert not human_review({"status": "approved", "reviewer_kind": "model", "reviewer": "AI", "reviewed_at": "2026-09-12"})
        assert human_review({"status": "approved", "reviewer_kind": "human", "reviewer": "fixture", "reviewed_at": "2026-09-12"})
        case = {"question": "demo?", "kind": "not-in-kb", "expected_answer": SENTINEL,
                "evidence": [], "absence_review": "fixture only", "corpus_sha256": corpus_hash(root)}
        assert not case_errors(root, case, corpus_hash(root))
        source.write_text(source.read_text() + "Changed.\n")
        assert case_errors(root, case, corpus_hash(root)) and evidence_errors(root, [evidence])
        assert fingerprint({"answer": "one"}) != fingerprint({"answer": "two"})
    print("human-eval self-test: PASS")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=ROOT)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--draft-qa", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--top", type=int)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    try:
        root = args.vault.expanduser().resolve()
        if args.top is not None and args.top < 1:
            raise ValueError("top must be positive")
        if args.draft_qa:
            if args.cases or args.predictions or args.reviews:
                raise ValueError("--draft-qa cannot score input files")
            result = draft_qa(root)
        else:
            if not args.cases:
                raise ValueError("provide --cases or --draft-qa")
            read = lambda path: json.loads(path.read_text()) if path else None
            result = evaluate(root, read(args.cases), read(args.predictions), read(args.reviews), args.top)
        payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            if args.output.resolve().is_relative_to(root):
                raise ValueError("--output must be outside the vault")
            with args.output.open("x") as handle:
                handle.write(payload)
            print(args.output.resolve())
        else:
            print(payload, end="")
        return 0
    except (OSError, ValueError, TypeError, KeyError, retrieval.BenchmarkError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
