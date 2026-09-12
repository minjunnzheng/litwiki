#!/usr/bin/env python3
"""Run the synthetic workflow example in temporary storage; never certify human gold."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import eval_human
import health
import search

ROOT = Path(__file__).resolve().parent.parent


def main():
    with tempfile.TemporaryDirectory(prefix="litwiki-demo-") as folder:
        vault = Path(folder) / "vault"
        shutil.copytree(ROOT / "examples/demo", vault)
        shutil.copytree(ROOT / "scripts", vault / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(ROOT / "meta/AI-GUIDE.md", vault / "meta/AI-GUIDE.md")
        result = subprocess.run([sys.executable, "-B", str(vault / "scripts/validate.py")],
                                text=True, capture_output=True, check=True)
        assert "0 errors, 0 warnings" in result.stdout, result.stdout
        idx = search.load_fulltext(root=vault)
        hit = search.query_fulltext(idx, "room temperature", 1, "tokens")[0]
        assert hit["page"] == 1 and hit["citekey"] == "tokens"
        baseline = health.capture(vault)
        assert health.audit(vault, baseline)["source_counts"] == {"unchanged": 2}
        pending = {"tokens": {"status": "pending", "reason": "synthetic unfinished integration"}}
        assert health.audit(vault, baseline, pending)["integration_counts"]["pending"] == 1
        dataset = json.loads((vault / "cases.json").read_text())
        report = eval_human.evaluate(vault, dataset)
        assert report["eligible_human_cases"] == 0 and report["retrieval"]["hit_at_k"] is None
        # Simulated approvals for the test only; never written back to examples or real QA.
        for case in dataset["cases"]:
            case["review"] = {"status": "approved", "reviewer_kind": "human",
                              "reviewer": "synthetic-test-only", "reviewed_at": "2026-09-12"}
            if case["kind"] == "not-in-kb":
                case["corpus_sha256"] = eval_human.corpus_hash(vault)
                case["absence_review"] = "Synthetic corpus: searched all documents; no mass measurement."
        predictions = [{"id": c["id"], "answer": c["expected_answer"],
                        "citations": [{k: e[k] for k in ("citekey", "page", "quote")} for e in c["evidence"]]}
                       for c in dataset["cases"]]
        report = eval_human.evaluate(vault, dataset, predictions)
        assert report["eligible_human_cases"] == 3 and not report["blocked_cases"]
        assert all(r["human_checks"] is None for r in report["cases"])
        assert all(not r["citation_errors"] for r in report["cases"])
        assert report["cases"][2]["exact_abstention"] is True
        reviews = [{"id": r["id"], "status": "approved", "reviewer_kind": "human",
                    "reviewer": "synthetic-test-only", "reviewed_at": "2026-09-12",
                    "case_sha256": r["case_sha256"], "prediction_sha256": r["prediction_sha256"],
                    "checks": {c: True for c in eval_human.CRITERIA}} for r in report["cases"]]
        assert eval_human.evaluate(vault, dataset, predictions, reviews)["human_answer_checks"]["accuracy"]["n"] == 3
        wrong = copy.deepcopy(predictions)
        wrong[0]["answer"] = "8 cm"
        wrong[0]["citations"][0]["page"] = 2
        changed = eval_human.evaluate(vault, dataset, wrong, reviews)
        assert changed["cases"][0]["citation_errors"]
        assert changed["cases"][0]["human_checks"] is None
        assert changed["human_answer_checks"]["accuracy"]["n"] == 2
        (vault / "fulltext/tokens.txt").write_text("[[p.1]]\nSource replaced.\n")
        assert health.audit(vault, baseline)["source_counts"]["changed"] == 1
        stale = eval_human.evaluate(vault, dataset)
        assert stale["eligible_human_cases"] == 0 and len(stale["blocked_cases"]) == 3
        print("demo: PASS (schema, page search, drift, pending integration, human gate, stale grades)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
