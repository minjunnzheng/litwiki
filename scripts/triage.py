#!/usr/bin/env python3
"""Triage map.json into the digestion work list.

- Groups duplicate Zotero items by normalized title; picks one canonical
  citekey per paper (most annotations > largest fulltext > shortest key).
- Excludes non-research items (magazine/web pages) via EXCLUDE list.
- Output: meta/digest_list.json
    {canonical: {title, year, pdf, fulltext_bytes, annotations, aliases[]},
     "excluded": [...], "no_fulltext": [...]}
"""
import json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP = json.load(open(os.path.join(ROOT, "meta", "map.json")))

EXCLUDE = {
    "GoogleNotebookLMNote", "zotero-item-318",
    "billingsNASAsPerseveranceRover", "kutaHowWatchPerseids",
    "kutaTheseRemoteVolcanic", "molinekThisWorldWar", "mundt100YearsSanta",
    "schultzRestorations1990sMore", "sullivanAncientEgyptiansMay",
}

norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())[:60]

groups = {}
for k, v in MAP.items():
    if k in EXCLUDE:
        continue
    groups.setdefault(norm(v["title"]) or k, []).append(k)

def ft_bytes(k):
    p = os.path.join(ROOT, "fulltext", k + ".txt")
    return os.path.getsize(p) if os.path.exists(p) else 0

out, aliases_total = {}, 0
for _, keys in groups.items():
    keys.sort(key=lambda k: (-len(MAP[k]["annotations"]), -ft_bytes(k), len(k), k))
    canon = keys[0]
    # merge annotations from all copies
    anns = []
    for k in keys:
        anns.extend(MAP[k]["annotations"])
    v = MAP[canon]
    out[canon] = {"title": v["title"], "authors": v["authors"],
                  "year": v["year"], "journal": v["journal"], "doi": v["doi"],
                  "pdf": v["pdf"], "fulltext_bytes": ft_bytes(canon),
                  "annotations": anns, "aliases": keys[1:]}
    aliases_total += len(keys) - 1

digest = {k: v for k, v in out.items() if v["fulltext_bytes"] > 5000}
pdf_only = {k: v for k, v in out.items()
            if v["fulltext_bytes"] <= 5000 and v["pdf"]}
stub = {k: v for k, v in out.items()
        if v["fulltext_bytes"] <= 5000 and not v["pdf"]}

result = {"digest": digest, "pdf_only": pdf_only, "stub": stub,
          "excluded": sorted(EXCLUDE)}
with open(os.path.join(ROOT, "meta", "digest_list.json"), "w") as fh:
    json.dump(result, fh, ensure_ascii=False, indent=1)
print(f"unique papers: {len(out)} (merged {aliases_total} duplicates)")
print(f"digest via fulltext: {len(digest)}")
print(f"digest via PDF-read (no text layer): {list(pdf_only)}")
print(f"metadata-only stubs: {sorted(stub)}")
