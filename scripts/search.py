#!/usr/bin/env python3
"""search.py — litwiki 本機 BM25 檢索（零依賴、決定性）。

取代「整本讀 _catalog.md」的路由步驟：給關鍵字，回 top-N 候選（citekey／claim／concept／qa／
lit 段落）＋路徑＋片段，AI 再只開命中的檔。

    python3 scripts/search.py "Tauern Window exhumation rate"
    python3 scripts/search.py --kind claim --top 10 "closure temperature zircon"
    python3 scripts/search.py --json "décollement dip Taiwan"
    python3 scripts/search.py --rebuild            # 強制重建索引
    python3 scripts/search.py --kind fulltext --citekey Dahlen1990 "critical taper"
    python3 scripts/search.py --self-test          # 隔離的原文搜尋檢查

索引檔：.cache/search-index.json（已加入 .gitignore）。任何被索引的檔 mtime 變新就自動重建。
索引範圍：_catalog.md 每列、lit/ 每個 ## 段、claims/、concepts/、qa/、mocs/。
預設不索引 data/ 與 fulltext/；--kind fulltext 使用獨立的逐頁索引，仍須核對原文。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
INDEX = VAULT / ".cache" / "search-index.json"
KINDS = ("catalog", "lit", "claim", "concept", "qa", "moc")
K1, B = 1.5, 0.75
DEFAULT_TOP = 12

_WORD = re.compile(r"[a-z0-9][a-z0-9\-\.]*[a-z0-9]|[a-z0-9]")
_STOP = set("the a an of in on and or to for with from by is are was were be as at that this these those it its we our their than then into over under between within which who whose not no".split())


def fold(text: str) -> str:
    text = text.lower()
    # strip accents loosely so décollement == decollement
    return text.replace("é", "e").replace("è", "e").replace("ü", "u").replace("ö", "o").replace("ä", "a")


def tokenize(text: str) -> list[str]:
    text = fold(text)
    toks = [t for t in _WORD.findall(text) if t not in _STOP and len(t) > 1]
    # CJK: unigram + bigram
    runs = re.findall(r"[一-鿿]+", text)
    for run in runs:
        toks.extend(run)
        toks.extend(run[i:i + 2] for i in range(len(run) - 1))
    return toks


def frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"')
    return fm, text[end + 4:]


def collect_docs() -> tuple[list[dict], dict[str, float]]:
    docs: list[dict] = []
    mtimes: dict[str, float] = {}

    def add(kind, path, anchor, title, text, snippet=None):
        docs.append({"kind": kind, "path": str(path.relative_to(VAULT)), "anchor": anchor,
                     "title": title, "text": text[:4000],
                     "snippet": re.sub(r"\s+", " ", (snippet or text).strip())[:220]})

    cat = VAULT / "_catalog.md"
    if cat.exists():
        mtimes[str(cat)] = cat.stat().st_mtime
        for line in cat.read_text(encoding="utf-8").splitlines():
            if line.startswith("| ") and not line.startswith("| citekey") and "---" not in line:
                cells = [c.strip() for c in line.strip("|").split("|")]
                if cells and cells[0]:
                    add("catalog", cat, cells[0], cells[0], " ".join(cells), " · ".join(cells[1:]))

    for d, kind in (("lit", "lit"), ("claims", "claim"), ("concepts", "concept"), ("qa", "qa"), ("mocs", "moc")):
        for p in sorted((VAULT / d).glob("*.md")):
            mtimes[str(p)] = p.stat().st_mtime
            fm, body = frontmatter(p.read_text(encoding="utf-8", errors="replace"))
            title = fm.get("name") or fm.get("id") or p.stem
            head = " ".join(f"{k} {v}" for k, v in fm.items() if k in ("name", "id", "description", "statement", "topics", "aliases", "title", "status"))
            if kind == "lit":
                # one doc per ## section so hits point at the right part of a long note
                parts = re.split(r"^(?=## )", body, flags=re.M)
                add(kind, p, "", title, head + " " + parts[0], fm.get("title", "") + " " + parts[0])
                for sec in parts[1:]:
                    h = sec.splitlines()[0].lstrip("# ").strip()
                    add(kind, p, h, title, f"{title} {h} {sec}", "\n".join(sec.splitlines()[1:]))
            else:
                add(kind, p, "", title, head + " " + body, fm.get("statement") or fm.get("description") or body)
    return docs, mtimes


def compile_index(docs: list[dict], mtimes: dict[str, float] | None = None) -> dict:
    """Compile search documents into an in-memory BM25 index without writing files."""
    docs = [dict(d) for d in docs]
    df: Counter = Counter()
    tf_list = []
    for d in docs:
        toks = tokenize(d["title"] + " " + d["text"])
        tf = Counter(toks)
        tf_list.append(tf)
        df.update(tf.keys())
        d["len"] = len(toks)
        del d["text"]
    avgdl = sum(d["len"] for d in docs) / max(1, len(docs))
    postings: dict[str, list] = defaultdict(list)
    for i, tf in enumerate(tf_list):
        for t, n in tf.items():
            postings[t].append([i, n])
    return {
        "mtimes": mtimes or {},
        "docs": docs,
        "df": dict(df),
        "avgdl": avgdl,
        "postings": postings,
        "N": len(docs),
    }


def build() -> dict:
    docs, mtimes = collect_docs()
    idx = compile_index(docs, mtimes)
    INDEX.parent.mkdir(exist_ok=True)
    INDEX.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    return idx



def load(rebuild=False) -> dict:
    if not rebuild and INDEX.exists():
        idx = json.loads(INDEX.read_text(encoding="utf-8"))
        # cheap staleness check: file set + mtimes
        cur: dict[str, float] = {}
        for d in ("lit", "claims", "concepts", "qa", "mocs"):
            for p in (VAULT / d).glob("*.md"):
                cur[str(p)] = p.stat().st_mtime
        cat = VAULT / "_catalog.md"
        if cat.exists():
            cur[str(cat)] = cat.stat().st_mtime
        if cur == idx.get("mtimes"):
            return idx
    return build()


def query(idx: dict, q: str, top: int, kinds: tuple[str, ...]) -> list[dict]:
    toks = tokenize(q)
    N, avgdl = idx["N"], idx["avgdl"]
    scores: dict[int, float] = defaultdict(float)
    for t in sorted(set(toks)):
        plist = idx["postings"].get(t)
        if not plist:
            continue
        df = idx["df"][t]
        idf = math.log(1 + (N - df + 0.5) / (df + 0.5))
        for i, n in plist:
            dl = idx["docs"][i]["len"]
            scores[i] += idf * n * (K1 + 1) / (n + K1 * (1 - B + B * dl / avgdl))
    hits = []
    for i, s in scores.items():
        d = idx["docs"][i]
        if d["kind"] in kinds:
            hits.append({**d, "score": round(s, 3)})
    hits.sort(key=lambda h: (-h["score"], h["path"], h["anchor"]))
    return hits[:top]


def fulltext_state(root: Path) -> dict:
    paths = sorted((root / "fulltext").glob("*.txt"))
    catalog = root / "_catalog.md"
    if catalog.exists():
        paths.append(catalog)
    files = {}
    for p in paths:
        stat = p.stat()
        files[str(p.resolve())] = [stat.st_mtime_ns, stat.st_size]
    return {"files": files, "lit_keys": sorted(p.stem for p in (root / "lit").glob("*.md"))}


def fulltext_registry(root: Path, lit_keys: list[str]) -> tuple[set[str], dict[str, str]]:
    catalog = root / "_catalog.md"
    text = catalog.read_text(encoding="utf-8") if catalog.exists() else ""
    registered = set(lit_keys) | set(re.findall(r"^\|\s*\[\[([^\]|]+)\]\]", text, re.M))
    section = re.search(r"^## Merged duplicate citekeys[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    aliases = {}
    for line in section[1].splitlines() if section else []:
        if not line.startswith("- "):
            continue
        match = re.fullmatch(r"- ([\w.-]+) → \[\[([\w.-]+)\]\]", line.strip())
        if not match or any(k in (".", "..") for k in match.groups()):
            raise ValueError(f"{catalog}: invalid merged alias: {line}")
        alias, target = match.groups()
        if alias in aliases and aliases[alias] != target:
            raise ValueError(f"{catalog}: conflicting alias {alias}")
        aliases[alias] = target
    resolved = {}
    for alias in aliases:
        key, seen = alias, set()
        while key in aliases:
            if key in seen:
                raise ValueError(f"{catalog}: alias cycle at {key}")
            seen.add(key)
            key = aliases[key]
        resolved[alias] = key
    return registered, resolved


def fulltext_pages(text: str) -> list[tuple[int, int, int]]:
    """Return (marker-line index, exclusive next-marker index, exact page)."""
    lines = text.split("\n")
    markers, seen = [], set()
    for i, line in enumerate(lines):
        if not line.strip().startswith("[[p."):
            continue
        match = re.fullmatch(r"\[\[p\.([1-9][0-9]*)\]\]", line.strip())
        if not match or int(match[1]) in seen:
            raise ValueError(f"invalid or duplicate page marker at line {i + 1}")
        page = int(match[1])
        seen.add(page)
        markers.append((i, page))
    if not markers:
        raise ValueError("no page markers")
    return [(i, markers[n + 1][0] if n + 1 < len(markers) else len(lines), page)
            for n, (i, page) in enumerate(markers)]


def load_fulltext(*, root: Path | None = None, index_path: Path | None = None, rebuild=False) -> dict:
    root = (root or VAULT).resolve()
    index_path = index_path or root / ".cache" / "search-fulltext-index.json"
    state = fulltext_state(root)
    if not rebuild and index_path.exists():
        try:
            idx = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(idx, dict) and idx.get("fulltext_version") == 1 and idx.get("source_state") == state:
                return idx
        except (ValueError, OSError):
            pass  # A disposable cache can be rebuilt after an interrupted/corrupt write.
    print("building fulltext index (complete marked pages)…", file=sys.stderr)
    registered, aliases = fulltext_registry(root, state["lit_keys"])
    docs, warnings, skipped = [], [], []
    for path in sorted((root / "fulltext").glob("*.txt")):
        source_key = path.stem
        canonical = aliases.get(source_key, source_key)
        if canonical != source_key and (root / "fulltext" / f"{canonical}.txt").is_file():
            skipped.append(str(path))
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            pages = fulltext_pages(text)
        except ValueError as exc:
            warnings.append(f"{path}: skipped ({exc})")
            continue
        direct = source_key in registered and canonical == source_key
        if not direct:
            warnings.append(f"{path}: source-file-only pages; citekey is null")
        lines = text.split("\n")
        for start, end, page in pages:
            body = "\n".join(lines[start + 1:end])
            if not body.strip():
                continue
            docs.append({"kind": "fulltext", "path": str(path.relative_to(root)),
                         "source_path": str(path.resolve()), "anchor": f"p.{page}",
                         "source_citekey": source_key, "citekey": source_key if direct else None,
                         "canonical_citekey": canonical if canonical != source_key or canonical in registered else None,
                         "registered": source_key in registered,
                         "page_scope": "canonical-fulltext" if direct else "source-file-only",
                         "page": page, "line": start + 1, "end_line": end + 1,
                         "title": source_key, "text": body, "snippet": ""})
    idx = compile_index(docs)
    idx.update(fulltext_version=1, source_state=state, aliases=aliases,
               warnings=warnings, skipped_aliases=skipped)
    if fulltext_state(root) != state:
        raise ValueError("fulltext sources changed while indexing; rerun the query")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=index_path.parent,
                                     prefix=".fulltext-", delete=False) as handle:
        json.dump(idx, handle, ensure_ascii=False, separators=(",", ":"))
        temporary = Path(handle.name)
    os.replace(temporary, index_path)
    return idx


def query_fulltext(idx: dict, q: str, top: int, citekey: str | None = None) -> list[dict]:
    key = idx["aliases"].get(citekey, citekey)
    ranked = query(idx, q, idx["N"], ("fulltext",))
    hits = [h for h in ranked if key is None or key == (h["canonical_citekey"] or h["source_citekey"])][:top]
    tokens = sorted(set(tokenize(q)), key=lambda t: (idx["df"].get(t, idx["N"]), -len(t), t))
    source_lines = {}
    for hit in hits:
        path = Path(hit["source_path"])
        stat = path.stat()
        if [stat.st_mtime_ns, stat.st_size] != idx["source_state"]["files"][str(path)]:
            raise ValueError(f"{path}: changed since indexing; rerun the query")
        if path not in source_lines:
            source_lines[path] = path.read_text(encoding="utf-8", errors="replace").split("\n")
            stat = path.stat()
            if [stat.st_mtime_ns, stat.st_size] != idx["source_state"]["files"][str(path)]:
                raise ValueError(f"{path}: changed while reading; rerun the query")
        lines = source_lines[path]
        start, end = hit["line"], hit["end_line"] - 1
        line_no, position = start, 0
        # Prefer the rarest matching query token; previews stay within one source line.
        for token in tokens:
            match = next(((i, fold(lines[i]).find(token)) for i in range(start, end)
                          if token in tokenize(lines[i])), None)
            if match is not None:
                line_no, position = match
                break
        offset = max(0, position - 70)
        hit["snippet_line"] = line_no + 1
        hit["snippet"] = lines[line_no][offset:offset + 220]
    return hits


def self_test() -> None:
    """Small runnable check, using only this invocation's temporary fixtures."""
    with tempfile.TemporaryDirectory(prefix="litwiki-pages-") as directory:
        root = Path(directory)
        full = root / "fulltext"
        full.mkdir()
        (root / "lit").mkdir()
        catalog = root / "_catalog.md"
        catalog.write_text("| [[canon]] |\n## Merged duplicate citekeys\n- alias → [[canon]]\n")
        (full / "canon.txt").write_text("preamble\n[[p.2]]\n" + "filler " * 800 + "latefind décollement\n[[p.7]]\nsecondpage\n")
        (full / "alias.txt").write_text("[[p.30]]\naliasversion\n")
        (full / "supplement.txt").write_text("[[p.4]]\nsupplementonly\n")
        (full / "unmarked.txt").write_text("unmarkedonly")
        (full / "duplicate.txt").write_text("[[p.1]]\nx\n[[p.1]]\ny")
        (full / "invalid.txt").write_text("[[p.bad]]\nx")
        idx = load_fulltext(root=root)
        assert idx["N"] == 3 and len(idx["skipped_aliases"]) == 1
        hit = query_fulltext(idx, "latefind", 1, "alias")[0]
        assert (hit["citekey"], hit["page"], hit["line"], hit["snippet_line"]) == ("canon", 2, 2, 3)
        assert "latefind" in hit["snippet"] and "décollement" in query_fulltext(idx, "decollement", 1)[0]["snippet"]
        assert query_fulltext(idx, "secondpage", 1)[0]["page"] == 7
        assert not query_fulltext(idx, "aliasversion", 1)
        hit = query_fulltext(idx, "supplementonly", 1)[0]
        assert hit["citekey"] is None and not hit["registered"] and hit["page_scope"] == "source-file-only"
        assert not query_fulltext(idx, "unmarkedonly", 1)
        assert load_fulltext(root=root) == idx
        (full / "canon.txt").rename(full / "canon.saved")
        idx = load_fulltext(root=root)
        hit = query_fulltext(idx, "aliasversion", 1, "canon")[0]
        assert hit["citekey"] is None and hit["canonical_citekey"] == "canon" and hit["page"] == 30
        (root / "lit" / "supplement.md").write_text("registered fixture")
        assert query_fulltext(load_fulltext(root=root), "supplementonly", 1)[0]["citekey"] == "supplement"
        (root / "lit" / "supplement.md").rename(root / "lit" / "supplement.saved")
        assert query_fulltext(load_fulltext(root=root), "supplementonly", 1)[0]["citekey"] is None
        (full / "added.txt").write_text("[[p.1]]\nnewfileword\n")
        assert query_fulltext(load_fulltext(root=root), "newfileword", 1)
        (full / "added.txt").rename(full / "added.saved")
        assert not query_fulltext(load_fulltext(root=root), "newfileword", 1)
        (full / "supplement.txt").write_text("[[p.9]]\nreplacementword\n")
        try:
            query_fulltext(idx, "supplementonly", 1)
            raise AssertionError("stale source not detected")
        except ValueError:
            pass
        assert query_fulltext(load_fulltext(root=root), "replacementword", 1)[0]["page"] == 9
        catalog.write_text("| [[newcanon]] |\n## Merged duplicate citekeys\n- alias → [[newcanon]]\n")
        assert query_fulltext(load_fulltext(root=root), "aliasversion", 1)[0]["canonical_citekey"] == "newcanon"
        catalog.write_text("## Merged duplicate citekeys\n- a → [[b]]\n- b → [[a]]\n")
        try:
            load_fulltext(root=root)
            raise AssertionError("alias cycle accepted")
        except ValueError:
            pass
    print("page-search self-test: PASS")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--top", type=int, default=DEFAULT_TOP)
    ap.add_argument("--kind", action="append", choices=(*KINDS, "fulltext"), help="限定類型；fulltext 需單獨使用")
    ap.add_argument("--citekey", help="限定原文來源（僅 fulltext）")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args(argv)
    if a.top < 1:
        ap.error("--top must be at least 1")
    if a.self_test:
        self_test()
        return 0
    fulltext = bool(a.kind and "fulltext" in a.kind)
    if fulltext and a.kind != ["fulltext"]:
        ap.error("--kind fulltext must be used alone")
    if a.citekey and not fulltext:
        ap.error("--citekey requires --kind fulltext")
    if fulltext:
        try:
            idx = load_fulltext(rebuild=a.rebuild)
            for warning in idx["warnings"]:
                print(f"warning: {warning}", file=sys.stderr)
            if idx["skipped_aliases"]:
                print(f"fulltext: {len(idx['skipped_aliases'])} merged alias files skipped; canonical sources preferred", file=sys.stderr)
            if not a.query:
                summary = {"pages": idx["N"], "warnings": idx["warnings"], "skipped_aliases": idx["skipped_aliases"]}
                print(json.dumps(summary, ensure_ascii=False) if a.json else f"fulltext index: {idx['N']} pages")
                return 0
            hits = query_fulltext(idx, a.query, a.top, a.citekey)
        except (ValueError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if a.json:
            print(json.dumps(hits, ensure_ascii=False, indent=1))
            return 0
        if not hits:
            print("no fulltext hits — try English/spelling variants or grep original files")
            return 1
        for r, h in enumerate(hits, 1):
            key = h["citekey"] or "no citable key"
            print(f"{r:2d}. [fulltext; unverified] {h['score']:.2f}  {key}  p.{h['page']} ({h['page_scope']})")
            print(f"    {h['source_path']}:{h['line']}\n    L{h['snippet_line']}: {h['snippet']}")
        return 0
    idx = load(rebuild=a.rebuild)
    if not a.query:
        print(f"index: {idx['N']} docs, {len(idx['df'])} terms → {INDEX}")
        return 0
    kinds = tuple(a.kind) if a.kind else KINDS
    hits = query(idx, a.query, a.top, kinds)
    if a.json:
        print(json.dumps(hits, ensure_ascii=False, indent=1))
        return 0
    if not hits:
        print("no hits — try synonyms (detachment|décollement), or grep fulltext/ (AI-GUIDE Step 5)")
        return 1
    for r, h in enumerate(hits, 1):
        loc = h["path"] + (f"  §{h['anchor']}" if h["anchor"] else "")
        print(f"{r:2d}. [{h['kind']:7s}] {h['score']:6.2f}  {loc}\n      {h['snippet'][:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
