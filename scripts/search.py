#!/usr/bin/env python3
"""search.py — litwiki 本機 BM25 檢索（零依賴、決定性）。

取代「整本讀 _catalog.md」的路由步驟：給關鍵字，回 top-N 候選（citekey／claim／concept／qa／
lit 段落）＋路徑＋片段，AI 再只開命中的檔。

    python3 scripts/search.py "Tauern Window exhumation rate"
    python3 scripts/search.py --kind claim --top 10 "closure temperature zircon"
    python3 scripts/search.py --json "décollement dip Taiwan"
    python3 scripts/search.py --rebuild            # 強制重建索引

索引檔：.cache/search-index.json（已加入 .gitignore）。任何被索引的檔 mtime 變新就自動重建。
索引範圍：_catalog.md 每列、lit/ 每個 ## 段、claims/、concepts/、qa/、mocs/。
**不索引 data/ 與 fulltext/**（data statement 欄未驗證；fulltext 用 grep -n 走 AI-GUIDE Step 5）。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
INDEX = VAULT / ".cache" / "search-index.json"
KINDS = ("catalog", "lit", "claim", "concept", "qa", "moc")
K1, B = 1.5, 0.75

_WORD = re.compile(r"[a-z0-9][a-z0-9\-\.]*[a-z0-9]|[a-z0-9]")
_STOP = set("the a an of in on and or to for with from by is are was were be as at that this these those it its we our their than then into over under between within which who whose not no".split())


def tokenize(text: str) -> list[str]:
    text = text.lower()
    # strip accents loosely so décollement == decollement
    text = (text.replace("é", "e").replace("è", "e").replace("ü", "u").replace("ö", "o").replace("ä", "a"))
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


def build() -> dict:
    docs, mtimes = collect_docs()
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
    idx = {"mtimes": mtimes, "docs": docs, "df": dict(df), "avgdl": avgdl, "postings": postings, "N": len(docs)}
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
    for t in set(toks):
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--kind", action="append", choices=KINDS, help="限定類型，可重複")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args(argv)
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
