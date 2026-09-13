#!/usr/bin/env python3
"""Build the citekey <-> PDF <-> metadata map for litwiki.

Sources:
  - meta/library.bib   (Better BibTeX auto-export; authoritative citekeys)
  - a read-only COPY of ~/Zotero/zotero.sqlite (annotations, item keys)

Outputs:
  - meta/map.json      citekey -> {title, year, doi, pdf, itemKey, annotations[]}
  - _catalog.md        skeleton (one line per paper; one_liner/topics filled later)

Usage:
  python3 scripts/zotero_map.py            # full rebuild
  python3 scripts/zotero_map.py --citekey X  # report one entry (after rebuild)
"""
import json, os, re, shutil, sqlite3, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _pick_bib():
    p = os.path.join(ROOT, "meta", "library.bib")
    if not os.path.exists(p):
        raise SystemExit("no bibliography found (expected meta/library.bib)")
    return p


BIB = _pick_bib()
MAP = os.path.join(ROOT, "meta", "map.json")
CATALOG = os.path.join(ROOT, "_catalog.md")
ZOTERO_DB = os.path.expanduser("~/Zotero/zotero.sqlite")
ZOTERO_DIR = os.path.expanduser("~/Zotero")


def parse_bib(path):
    """Minimal .bib parser: good enough for BBT biblatex output."""
    text = open(path, encoding="utf-8").read()
    entries = {}
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        typ, key = m.group(1).lower(), m.group(2)
        if typ in ("comment", "preamble", "string"):
            continue
        # slice from entry start to the next @entry (or EOF)
        start = m.end()
        nxt = re.search(r"\n@\w+\s*\{", text[start:])
        body = text[start:start + nxt.start()] if nxt else text[start:]
        fields = {}
        for fm in re.finditer(r"(\w+)\s*=\s*\{", body):
            fname = fm.group(1).lower()
            i, depth = fm.end(), 1
            while i < len(body) and depth:
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                i += 1
            fields[fname] = re.sub(r"\s+", " ", body[fm.end():i - 1]).strip()
        entries[key] = fields
    return entries


def unlatex(s):
    """Strip BibTeX/LaTeX markup from field values for clean display/grep."""
    s = re.sub(r"\\(mkbibemph|emph|textbf|textit|mkbibquote)", "", s)
    s = re.sub(r"\\text(subscript|superscript)", "", s)
    s = re.sub(r"\\['`^\"~=.uvHtcdb]\s*", "", s)   # accents
    s = s.replace("\\&", "&").replace("\\%", "%").replace("\\_", "_")
    s = s.replace("{", "").replace("}", "")
    s = s.replace("’", "'").replace("‐", "-")
    return re.sub(r"\s+", " ", s).strip()


def pdf_from_file_field(filefield):
    """BBT file field: 'desc:path:type;...' or plain path; pick first PDF."""
    if not filefield:
        return None
    for part in re.split(r"(?<!\\);", filefield):
        chunks = part.split(":")
        cand = [c for c in chunks if c.lower().endswith(".pdf")]
        if cand:
            p = cand[0].replace("\\:", ":").replace("\\;", ";")
            if not os.path.isabs(p):
                p = os.path.join(ZOTERO_DIR, p)
            return p
    return None


def storage_key(pdf_path):
    m = re.search(r"/storage/([A-Z0-9]{8})/", pdf_path or "")
    return m.group(1) if m else None


def load_zotero():
    """Read-only copy -> {attachmentStorageKey: {'itemKey':parentKey,
    'annotations':[{'page','text','comment','color'}]}}"""
    if not os.path.isfile(ZOTERO_DB):
        raise SystemExit(f"Zotero database not found: {ZOTERO_DB}. "
                         "For a PDF without Zotero, see docs/install.md.")
    with tempfile.TemporaryDirectory(prefix="litwiki-zotero-") as tmpdir:
        tmp = os.path.join(tmpdir, "zotero.sqlite")
        shutil.copy(ZOTERO_DB, tmp)
        for suffix in ("-wal", "-shm", "-journal"):
            src = ZOTERO_DB + suffix
            if os.path.exists(src):
                shutil.copy(src, tmp + suffix)
        con = sqlite3.connect(tmp)
        try:
            cur = con.cursor()
            out = {}
            # attachment storage key -> parent item key
            for att_id, att_key, parent_key in cur.execute("""
                SELECT ia.itemID, i.key, pi.key
                FROM itemAttachments ia
                JOIN items i  ON ia.itemID = i.itemID
                LEFT JOIN items pi ON ia.parentItemID = pi.itemID
                WHERE ia.contentType='application/pdf'"""):
                out[att_key] = {"attachmentID": att_id, "itemKey": parent_key,
                                "annotations": []}
            by_att_id = {v["attachmentID"]: v for v in out.values()}
            try:
                for parent_att, text, comment, page, color in cur.execute("""
                    SELECT parentItemID, text, comment, pageLabel, color
                    FROM itemAnnotations"""):
                    if parent_att in by_att_id:
                        by_att_id[parent_att]["annotations"].append(
                            {"page": page, "text": text or "", "comment": comment or "",
                             "color": color or ""})
            except sqlite3.OperationalError:
                print("WARN: itemAnnotations table not found; skipping annotations")
            return out
        finally:
            con.close()

def main():
    if not os.path.exists(BIB):
        sys.exit(f"ERROR: {BIB} not found. Set up the Better BibTeX "
                 "auto-export first (see meta/WORKFLOW.md D).")
    entries = parse_bib(BIB)
    zot = load_zotero()
    mapping, missing_pdf = {}, []
    for key, f in sorted(entries.items()):
        pdf = pdf_from_file_field(f.get("file"))
        skey = storage_key(pdf) if pdf else None
        zinfo = zot.get(skey, {}) if skey else {}
        if not (pdf and os.path.exists(pdf)):
            missing_pdf.append(key)
        mapping[key] = {
            "title": unlatex(f.get("title", "")),
            "authors": unlatex(f.get("author", "")),
            "year": f.get("date", f.get("year", ""))[:4],
            "journal": unlatex(f.get("journaltitle", f.get("journal", ""))),
            "doi": f.get("doi", ""),
            "pdf": pdf or "",
            "itemKey": zinfo.get("itemKey") or "",
            "annotations": zinfo.get("annotations", []),
        }
    with open(MAP, "w", encoding="utf-8") as fh:
        json.dump(mapping, fh, ensure_ascii=False, indent=1)
    print(f"map.json: {len(mapping)} entries "
          f"({len(mapping) - len(missing_pdf)} with PDF)")
    if missing_pdf:
        print("no PDF:", ", ".join(missing_pdf))

    if not os.path.exists(CATALOG) or "| citekey |" not in open(CATALOG).read():
        rows = ["---", "type: meta", "name: catalog",
                "description: One line per paper. First stop for routing.",
                "---", "", "# _catalog — 全庫目錄", "",
                "| citekey | year | first author | title | topics | one-liner |",
                "|---|---|---|---|---|---|"]
        for key, v in sorted(mapping.items(),
                             key=lambda kv: (kv[1]["year"], kv[0])):
            fa = v["authors"].split(" and ")[0].strip()
            title = v["title"][:80]
            rows.append(f"| [[{key}]] | {v['year']} | {fa} | {title} |  |  |")
        open(CATALOG, "w", encoding="utf-8").write("\n".join(rows) + "\n")
        print(f"_catalog.md skeleton written ({len(mapping)} rows)")
    else:
        print("_catalog.md exists — not overwritten")

    if "--citekey" in sys.argv:
        ck = sys.argv[sys.argv.index("--citekey") + 1]
        print(json.dumps(mapping.get(ck, "NOT FOUND"),
                         ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
