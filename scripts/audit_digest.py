#!/usr/bin/env python3
"""audit_digest.py — 消化批次的機械稽核（零模型 token）。

    python3 scripts/audit_digest.py <worklist.txt|citekey ...> [--json out.json]

對每篇檢查：
  numbers   lit note「Key findings」＋「Parameters」表與 claims statement 裡的數字，
            是否逐字出現在 fulltext 所標頁碼（[[p.N]] 區段）。
            分三類：ok / off_page（全文有但不在該頁）/ not_found（全文沒有）。
  quotes    claims 的 Evidence 引文（前 50 字，正規化空白／連字號）是否在所標頁。
  tags      topics/methods/regions 是否都在 meta/VOCAB.md。
  links     ## Relevance 與全文的 [[wikilink]] 目標是否存在（lit/concepts/mocs/claims/qa）。
  terms     禁用自創中譯（剝露／剝蝕／分離面／擋墊／陶恩／窗 等，見 TERM_BAD）。
結果：stdout 摘要＋可選 JSON；flags 可直接餵 meta/XCHECK-TASK.md 給另一家模型裁決。
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
NUM = re.compile(r"(?<![\w.])[-−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])[-−]?\d+\.\d+|(?<![\w.\-])\d{2,}(?![\w.])")
PAGE = re.compile(r"p\.(\d+)")
TERM_BAD = ["剝露", "剝蝕", "分離面", "擋墊", "陶恩", "布倫納", "卡奇", "恩加丁", "萊蓬廷", "因蘇布里亞"]
SKIP_NUM = {"2026", "2025"}  # digested_date 類雜訊


def norm(s: str) -> str:
    for a, b in (("−", "-"), ("–", "-"), ("—", "-"), ("⫺", "-"), ("­", ""), ("ﬁ", "fi"), ("ﬂ", "fl"),
                 ("ﬀ", "ff"), ("ﬃ", "ffi"), ("◦", "°"), ("º", "°"), ("\u2009", " "), ("\u202f", " "), ("\xa0", " ")):
        s = s.replace(a, b)
    s = re.sub(r"-\s*\n\s*", "", s)        # 斷字
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"(?<![\w)])- (?=\d)", "-", s)   # "− 28.2" → "-28.2"
    s = re.sub(r"(\d) ?([°‰%])", r"\1\2", s)  # "338 °c" → "338°c"
    s = re.sub(r"(\d) , (\d)", r"\1,\2", s)
    s = re.sub(r"°\s*c\b", "°c", s, flags=re.I)
    return s.lower()


def pages_of(ft: str) -> dict[int, str]:
    parts = re.split(r"\[\[p\.(\d+)\]\]", ft)
    out = {}
    for i in range(1, len(parts), 2):
        out[int(parts[i])] = norm(parts[i + 1])
    return out


def num_variants(n: str) -> list[str]:
    n = n.replace("−", "-")
    v = {n, n.replace(",", ""), n.replace(",", " ")}
    if "." in n:
        v.add(n.rstrip("0").rstrip("."))
    if re.fullmatch(r"-?\d{4,}", n):
        v.add(f"{int(n):,}")
    return [x for x in v if x]


def find_num(n: str, pages: dict[int, str], cited: list[int]) -> str:
    vs = num_variants(n)
    for p in cited:
        txt = pages.get(p, "")
        if any(v in txt for v in vs):
            return "ok"
    allt = " ".join(pages.values())
    return "off_page" if any(v in allt for v in vs) else "not_found"


def audit(ck: str, vocab: set[str], targets: set[str]) -> dict:
    r = {"citekey": ck, "numbers_checked": 0, "ok": 0, "off_page": [], "not_found": [],
         "bad_quotes": [], "bad_tags": [], "dead_links": [], "bad_terms": [], "errors": []}
    lit = VAULT / "lit" / f"{ck}.md"
    ftp = VAULT / "fulltext" / f"{ck}.txt"
    if not lit.exists() or not ftp.exists():
        r["errors"].append("missing lit or fulltext"); return r
    text = lit.read_text(encoding="utf-8")
    pages = pages_of(ftp.read_text(encoding="utf-8", errors="replace"))

    # tags
    fm = text.split("---", 2)[1]
    for key in ():
        m = re.search(rf"^{key}: \[(.*)\]", fm, re.M)
        if m:
            for t in [x.strip() for x in m.group(1).split(",") if x.strip()]:
                if t not in vocab:
                    r["bad_tags"].append(t)

    # numbers in Key findings (one finding per line) and Parameters rows
    def check_line(line: str, where: str):
        cited = [int(p) for p in PAGE.findall(line)]
        if not cited:
            return
        body = PAGE.sub("", line)
        body = norm(re.sub(r"\[\[[^\]]+\]\]", "", body))
        for n in NUM.findall(body):
            if n in SKIP_NUM:
                continue
            r["numbers_checked"] += 1
            v = find_num(n, pages, cited)
            if v == "ok":
                r["ok"] += 1
            else:
                r[v].append({"where": where, "value": n, "cited_pages": cited})

    sec = {}
    for m in re.finditer(r"^## (.+?)\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        sec[m.group(1).strip()] = m.group(2)
    for i, line in enumerate(sec.get("Key findings", "").splitlines()):
        if line.strip():
            check_line(line, f"lit:finding:{line.strip()[:40]}")
    for line in sec.get("Parameters", "").splitlines():
        if line.startswith("|") and "---" not in line and "parameter" not in line.lower():
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 4:
                check_line(f"{cells[1]} {cells[3]}", f"lit:param:{cells[0][:40]}")

    # claims
    for cp in sorted((VAULT / "claims").glob(f"clm-{ck}-*.md")):
        ct = cp.read_text(encoding="utf-8")
        st = re.search(r'^statement: "(.*)"', ct, re.M)
        pg = re.search(r"pages: \[([\d, ]*)\]", ct)
        cited = [int(x) for x in pg.group(1).split(",") if x.strip()] if pg else []
        if st and cited:
            check_line(st.group(1) + " " + " ".join(f"p.{p}" for p in cited), f"claim:{cp.stem}")
        for q in re.finditer(r'^> "(.+?)" \(\[\[([^\]]+)\]\] p\.(\d+)\)', ct, re.M):
            src = q.group(2)
            if src != ck:
                other = VAULT / "fulltext" / f"{src}.txt"
                if not other.exists():
                    continue
                pg_src = pages_of(other.read_text(encoding="utf-8", errors="replace"))
            else:
                pg_src = pages
            quote = norm(q.group(1))[:50]
            quote = re.sub(r"\s*(…|\.\.\.)\s*.*$", "", quote)  # 截到第一個省略號
            if len(quote) < 15:
                continue
            if quote not in pg_src.get(int(q.group(3)), ""):
                r["bad_quotes"].append({"claim": cp.stem, "src": src, "page": int(q.group(3)), "quote": quote})
        for t in TERM_BAD:
            if t in ct:
                r["bad_terms"].append(f"{cp.stem}:{t}")

    # links
    for l in set(re.findall(r"\[\[([^\]|#]+)", text)):
        if l not in targets and l != ck:
            r["dead_links"].append(l)
    for t in TERM_BAD:
        if t in text:
            r["bad_terms"].append(f"lit:{t}")
    return r


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = None
    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
        args = [a for a in args if a != out]
    cks = []
    for a in args:
        p = Path(a)
        if p.exists():
            cks += [l.strip() for l in p.read_text().splitlines() if l.strip() and not l.startswith("#")]
        else:
            cks.append(a)
    vocab = set(re.findall(r"^- `?([a-z0-9\-]+)`?", (VAULT / "meta/VOCAB.md").read_text(), re.M))
    vocab |= set(re.findall(r"`([a-z0-9\-]+)`", (VAULT / "meta/VOCAB.md").read_text()))
    targets = set()
    for d in ("lit", "concepts", "mocs", "claims", "qa"):
        targets |= {p.stem for p in (VAULT / d).glob("*.md")}
    targets |= set(re.findall(r"^- (\S+) → \[\[", (VAULT / "_catalog.md").read_text(), re.M))
    res = [audit(ck, vocab, targets) for ck in cks]
    tot = sum(r["numbers_checked"] for r in res); ok = sum(r["ok"] for r in res)
    print(f"{len(res)} papers · numbers {ok}/{tot} ok · off_page {sum(len(r['off_page']) for r in res)} · not_found {sum(len(r['not_found']) for r in res)} · bad_quotes {sum(len(r['bad_quotes']) for r in res)} · bad_tags {sum(len(r['bad_tags']) for r in res)} · dead_links {sum(len(r['dead_links']) for r in res)} · bad_terms {sum(len(r['bad_terms']) for r in res)}")
    for r in res:
        flags = len(r["off_page"]) + len(r["not_found"]) + len(r["bad_quotes"]) + len(r["bad_tags"]) + len(r["dead_links"]) + len(r["bad_terms"])
        if flags or r["errors"]:
            print(f"  {r['citekey']}: {r['ok']}/{r['numbers_checked']} ok, off_page {len(r['off_page'])}, not_found {len(r['not_found'])}, quotes {len(r['bad_quotes'])}, tags {r['bad_tags']}, links {r['dead_links']}, terms {r['bad_terms']} {r['errors']}")
    if out:
        Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print("→", out)


if __name__ == "__main__":
    main()
