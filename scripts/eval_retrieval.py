#!/usr/bin/env python3
"""Evaluate litwiki retrieval against verified QA source labels.

The benchmark uses each qa note's original question as the query and its
``sources`` citekeys as gold labels. All qa documents are excluded from the
index to prevent cached-answer leakage. The target vault is never written.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any


SCRIPT_VERSION = "1"
SENTINEL = "Not in knowledge base."
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


class BenchmarkError(RuntimeError):
    pass


def split_frontmatter(text: str, path: Path) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise BenchmarkError(f"{path}: missing YAML frontmatter")
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise BenchmarkError(f"{path}: unterminated YAML frontmatter") from exc
    return "\n".join(lines[1:end]), "\n".join(lines[end + 1 :])


def scalar(frontmatter: str, key: str, path: Path) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.*?)\s*$", frontmatter, re.M)
    if not match:
        raise BenchmarkError(f"{path}: missing {key}: field")
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if not value:
        raise BenchmarkError(f"{path}: empty {key}: field")
    return value


def flow_list(frontmatter: str, key: str, path: Path) -> list[str]:
    match = re.search(rf"^{re.escape(key)}:\s*\[(.*?)\]\s*$", frontmatter, re.M)
    if not match:
        raise BenchmarkError(f"{path}: {key}: must be an inline list")
    values = []
    for item in match.group(1).split(","):
        item = item.strip().strip("\"'")
        if item:
            values.append(item)
    return values


def parse_qa(path: Path) -> dict[str, Any]:
    frontmatter, body = split_frontmatter(path.read_text(encoding="utf-8"), path)
    sources = flow_list(frontmatter, "sources", path)
    if not sources:
        normalized_answer = body.replace("*", "").strip()
        if SENTINEL not in normalized_answer:
            raise BenchmarkError(
                f"{path}: sources is empty but answer does not contain {SENTINEL!r}"
            )
    return {
        "id": scalar(frontmatter, "id", path),
        "path": str(path),
        "question": scalar(frontmatter, "question", path),
        "verified_by": scalar(frontmatter, "verified_by", path),
        "gold_sources": sources,
        "negative": not sources,
    }


def parse_claim_sources(path: Path) -> list[str]:
    frontmatter, _ = split_frontmatter(path.read_text(encoding="utf-8"), path)
    lines = frontmatter.splitlines()
    in_sources = False
    sources: list[str] = []
    for line in lines:
        if line.startswith("sources:"):
            in_sources = True
            inline = line.split(":", 1)[1].strip()
            if inline.startswith("[") and inline.endswith("]"):
                for item in inline[1:-1].split(","):
                    item = item.strip().strip("\"'")
                    if item:
                        sources.append(item)
            continue
        if in_sources and line and not line[0].isspace():
            break
        if in_sources:
            match = re.match(r"^\s*-\s*citekey:\s*(.*?)\s*$", line)
            if match:
                value = match.group(1).split(" #", 1)[0].strip().strip("\"'")
                if value:
                    sources.append(value)
    return sources


def validate_claim_mappings(vault: Path) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    failures = []
    for path in sorted((vault / "claims").glob("*.md")):
        sources = parse_claim_sources(path)
        mapping[str(path.relative_to(vault))] = sources
        if not sources:
            failures.append(str(path))
    if failures:
        joined = "\n  ".join(failures)
        raise BenchmarkError(f"claim files with no mapped citekey:\n  {joined}")
    return mapping


def load_search_module(vault: Path) -> ModuleType:
    path = vault / "scripts" / "search.py"
    if not path.is_file():
        raise BenchmarkError(f"missing target search implementation: {path}")
    old_dont_write = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("_litwiki_target_search", path)
        if spec is None or spec.loader is None:
            raise BenchmarkError(f"cannot import target search implementation: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = old_dont_write
    if not hasattr(module, "compile_index"):
        raise BenchmarkError(f"{path}: compile_index() is required")
    return module


def catalog_metadata(vault: Path) -> dict[str, dict[str, str]]:
    path = vault / "_catalog.md"
    if not path.is_file():
        raise BenchmarkError(f"missing catalog: {path}")
    result: dict[str, dict[str, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("| citekey") or "---" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        match = WIKILINK_RE.search(cells[0]) if cells else None
        if not match:
            continue
        result[match.group(1)] = {
            "year": cells[1] if len(cells) > 1 else "",
            "author": cells[2] if len(cells) > 2 else "",
        }
    return result


def is_name_bearing(
    question: str,
    gold_sources: list[str],
    catalog: dict[str, dict[str, str]],
    search_module: ModuleType,
) -> bool:
    query_tokens = set(search_module.tokenize(question))
    for citekey in gold_sources:
        metadata = catalog.get(citekey, {})
        year = metadata.get("year", "").strip()
        if year and year in query_tokens:
            return True
        author_tokens = set(search_module.tokenize(metadata.get("author", "")))
        if author_tokens & query_tokens:
            return True
    return False


def hit_sources(
    hit: dict[str, Any], vault: Path, claim_mapping: dict[str, list[str]]
) -> list[str]:
    kind = hit["kind"]
    if kind == "catalog":
        match = WIKILINK_RE.search(hit.get("anchor", ""))
        return [match.group(1)] if match else []
    if kind == "lit":
        return [Path(hit["path"]).stem]
    if kind == "claim":
        return claim_mapping.get(hit["path"], [])
    return []


def score_case(
    case: dict[str, Any],
    hits: list[dict[str, Any]],
    vault: Path,
    claim_mapping: dict[str, list[str]],
    top: int,
) -> dict[str, Any]:
    seen: set[str] = set()
    duplicate_or_nonsource_slots = 0
    ranked_hits = []
    gold = set(case["gold_sources"])
    first_relevant_rank = None
    for rank, hit in enumerate(hits, 1):
        sources = set(hit_sources(hit, vault, claim_mapping))
        relevant = bool(sources & gold)
        if relevant and first_relevant_rank is None:
            first_relevant_rank = rank
        if not (sources - seen):
            duplicate_or_nonsource_slots += 1
        seen.update(sources)
        ranked_hits.append(
            {
                "rank": rank,
                "kind": hit["kind"],
                "path": hit["path"],
                "anchor": hit.get("anchor", ""),
                "score": hit["score"],
                "sources": sorted(sources),
                "relevant": relevant,
            }
        )
    found = sorted(gold & seen)
    result = {
        **case,
        "hits": ranked_hits,
        "distinct_sources_at_k": len(seen),
        "duplicate_or_nonsource_slots": duplicate_or_nonsource_slots,
        "capacity_warnings": [],
    }
    if case["negative"]:
        result.update(
            {
                "found_gold_sources": [],
                "first_relevant_rank": None,
                "reciprocal_rank": None,
                "source_recall_at_k": None,
            }
        )
        return result
    if len(gold) > top:
        result["capacity_warnings"].append(f"gold sources ({len(gold)}) exceed K ({top})")
    if len(gold) > len(seen):
        result["capacity_warnings"].append(
            f"gold sources ({len(gold)}) exceed realized distinct-source capacity ({len(seen)})"
        )
    result.update(
        {
            "found_gold_sources": found,
            "first_relevant_rank": first_relevant_rank,
            "reciprocal_rank": 1.0 / first_relevant_rank if first_relevant_rank else 0.0,
            "source_recall_at_k": len(found) / len(gold),
        }
    )
    return result


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    if not cases:
        return {
            "n": 0,
            "hit_at_k": None,
            "mrr_at_k": None,
            "macro_source_recall_at_k": None,
            "micro_source_recall_at_k": None,
            "found_gold_sources": 0,
            "gold_sources": 0,
        }
    found = sum(len(case["found_gold_sources"]) for case in cases)
    gold = sum(len(case["gold_sources"]) for case in cases)
    return {
        "n": len(cases),
        "hit_at_k": sum(case["first_relevant_rank"] is not None for case in cases) / len(cases),
        "mrr_at_k": sum(case["reciprocal_rank"] for case in cases) / len(cases),
        "macro_source_recall_at_k": sum(case["source_recall_at_k"] for case in cases) / len(cases),
        "micro_source_recall_at_k": found / gold,
        "found_gold_sources": found,
        "gold_sources": gold,
    }


def git_provenance(vault: Path) -> dict[str, Any]:
    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, cwd=vault, text=True, capture_output=True, check=False)

    head = run(["git", "rev-parse", "HEAD"])
    if head.returncode != 0:
        return {"head": None, "dirty": None, "label": "not-a-git-worktree"}
    status = run(["git", "status", "--porcelain", "--", "."])
    dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
    sha = head.stdout.strip()
    return {"head": sha, "dirty": dirty, "label": f"{sha}{'-dirty' if dirty else ''}"}


def run_benchmark(vault: Path, top: int | None = None) -> dict[str, Any]:
    vault = vault.expanduser().resolve()
    search_module = load_search_module(vault)
    if top is None:
        top = int(getattr(search_module, "DEFAULT_TOP", 12))
    if top < 1:
        raise BenchmarkError("--top must be at least 1")

    qa_paths = sorted((vault / "qa").glob("qa-*.md"))
    if not qa_paths:
        raise BenchmarkError(f"no qa/qa-*.md files found in {vault}")
    cases = [parse_qa(path) for path in qa_paths]
    ids = [case["id"] for case in cases]
    duplicate_ids = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicate_ids:
        raise BenchmarkError(f"duplicate QA ids: {', '.join(duplicate_ids)}")

    claim_mapping = validate_claim_mappings(vault)
    catalog = catalog_metadata(vault)
    docs, _ = search_module.collect_docs()
    benchmark_docs = [doc for doc in docs if doc["kind"] != "qa"]
    index = search_module.compile_index(benchmark_docs)
    kinds = tuple(kind for kind in search_module.KINDS if kind != "qa")
    doc_counts = Counter(doc["kind"] for doc in benchmark_docs)

    scored = []
    for case in cases:
        case["name_bearing"] = is_name_bearing(
            case["question"], case["gold_sources"], catalog, search_module
        )
        hits = search_module.query(index, case["question"], top, kinds)
        scored.append(score_case(case, hits, vault, claim_mapping, top))

    positives = [case for case in scored if not case["negative"]]
    negatives = [case for case in scored if case["negative"]]
    by_name_bearing = {
        str(flag).lower(): summarize([case for case in positives if case["name_bearing"] is flag])
        for flag in (True, False)
    }
    verification_groups = sorted({case["verified_by"] for case in positives})
    by_verified_by = {
        group: summarize([case for case in positives if case["verified_by"] == group])
        for group in verification_groups
    }
    eligible = [case for case in positives if len(case["gold_sources"]) <= top]
    return {
        "benchmark_version": SCRIPT_VERSION,
        "provenance": {
            "vault": str(vault),
            "git": git_provenance(vault),
            "k": top,
            "index_documents": {kind: doc_counts.get(kind, 0) for kind in kinds},
            "index_document_total": len(benchmark_docs),
            "positive_queries": len(positives),
            "negative_queries": len(negatives),
            "verification_counts": dict(Counter(case["verified_by"] for case in scored)),
        },
        "cases": scored,
        "aggregates": {
            "all_positive": summarize(positives),
            "by_name_bearing": by_name_bearing,
            "by_verified_by": by_verified_by,
            "capacity_eligible": {
                **summarize(eligible),
                "criterion": f"gold_source_count <= {top}",
            },
        },
    }


def metric(value: Any) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def summary_line(label: str, summary: dict[str, Any], top: int) -> str:
    return (
        f"{label}: n={summary['n']} hit@{top}={metric(summary['hit_at_k'])} "
        f"mrr@{top}={metric(summary['mrr_at_k'])} "
        f"macro-recall@{top}={metric(summary['macro_source_recall_at_k'])} "
        f"micro-recall@{top}={metric(summary['micro_source_recall_at_k'])} "
        f"sources={summary['found_gold_sources']}/{summary['gold_sources']}"
    )


def render_text(result: dict[str, Any]) -> str:
    provenance = result["provenance"]
    top = provenance["k"]
    counts = " ".join(f"{kind}={count}" for kind, count in provenance["index_documents"].items())
    verification = " ".join(
        f"{name}={count}" for name, count in sorted(provenance["verification_counts"].items())
    )
    lines = [
        f"litwiki retrieval benchmark v{result['benchmark_version']}",
        f"vault: {provenance['vault']}",
        f"git: {provenance['git']['label']}",
        f"K: {top}",
        f"index: total={provenance['index_document_total']} {counts}",
        (
            f"queries: positive={provenance['positive_queries']} "
            f"negative={provenance['negative_queries']} verified_by[{verification}]"
        ),
        "",
        "Cases",
    ]
    for case in result["cases"]:
        flags = [case["verified_by"]]
        if case["name_bearing"]:
            flags.append("name-bearing")
        if case["negative"]:
            flags.append("negative")
            lines.append(
                f"{case['id']} [{' '.join(flags)}] distinct-sources@{top}="
                f"{case['distinct_sources_at_k']} duplicate/non-source-slots="
                f"{case['duplicate_or_nonsource_slots']}"
            )
            for hit in case["hits"]:
                source_text = ",".join(hit["sources"]) or "-"
                lines.append(
                    f"  {hit['rank']:>2}. {hit['kind']} {hit['path']} sources={source_text}"
                )
            continue
        lines.append(
            f"{case['id']} [{' '.join(flags)}] first={case['first_relevant_rank'] or '-'} "
            f"rr={case['reciprocal_rank']:.4f} sources="
            f"{len(case['found_gold_sources'])}/{len(case['gold_sources'])} "
            f"recall@{top}={case['source_recall_at_k']:.4f} "
            f"distinct-sources@{top}={case['distinct_sources_at_k']} "
            f"duplicate/non-source-slots={case['duplicate_or_nonsource_slots']}"
        )
        lines.extend(f"  warning: {warning}" for warning in case["capacity_warnings"])

    aggregates = result["aggregates"]
    lines.extend(["", "Aggregates", summary_line("all-positive", aggregates["all_positive"], top)])
    for flag, summary in aggregates["by_name_bearing"].items():
        lines.append(summary_line(f"name-bearing={flag}", summary, top))
    for group, summary in aggregates["by_verified_by"].items():
        lines.append(summary_line(f"verified-by={group}", summary, top))
    lines.append(summary_line("capacity-eligible", aggregates["capacity_eligible"], top))
    lines.append(
        "Interpretation: model-verified groups measure self-consistency, not human ground truth."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vault",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="target litwiki vault (default: this script's repository)",
    )
    parser.add_argument("--top", type=int, help="retrieval cutoff K (default: target search.py default)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    try:
        result = run_benchmark(args.vault, args.top)
    except BenchmarkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
