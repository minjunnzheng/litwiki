#!/usr/bin/env python3
"""litwiki schema linter. Run after every batch of note writes.

Checks: frontmatter schema per note type, filename conventions, controlled
vocabulary, wiki-link resolution, page anchors vs fulltext, duplicate claim
IDs, orphan claims, stale qa (cites contested/refuted/missing claims),
_catalog <-> lit/ sync, orphan concepts, unused VOCAB tags, concept alias
collisions. Exit code 1 if any ERROR (warnings don't fail).
"""
import glob, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ERRORS, WARNINGS = [], []
err = lambda f, m: ERRORS.append(f"ERROR {os.path.relpath(f, ROOT)}: {m}")
warn = lambda f, m: WARNINGS.append(f"WARN  {os.path.relpath(f, ROOT)}: {m}")


def frontmatter(path):
    """Tiny YAML-subset parser: scalars, [inline, lists], one level of
    '- key: val' item lists (enough for SCHEMA.md structures)."""
    text = open(path, encoding="utf-8").read()
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    if not m:
        return None, text
    fm, cur_list, cur_item = {}, None, None
    for line in m.group(1).splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        mm = re.match(r"^(\w+):\s*(.*)$", line)
        if mm:
            k, v = mm.group(1), mm.group(2).strip()
            cur_item = None
            if v == "":
                fm[k] = []          # assume block list (or empty scalar)
                cur_list = fm[k]
            else:
                cur_list = None
                if v.startswith("[") and v.endswith("]"):
                    inner = v[1:-1].strip()
                    fm[k] = [x.strip().strip("'\"") for x in inner.split(",")
                             if x.strip()] if inner else []
                else:
                    fm[k] = v.strip("'\"")
        elif re.match(r"^\s+-\s", line) and cur_list is not None:
            item = line.strip()[1:].strip()
            mm2 = re.match(r"^(\w+):\s*(.*)$", item)
            if mm2:
                cur_item = {mm2.group(1): mm2.group(2).strip().strip("'\"")}
                cur_list.append(cur_item)
            else:
                cur_list.append(item.strip("'\""))
                cur_item = None
        elif re.match(r"^\s+\w+:", line) and cur_item is not None:
            k2, v2 = line.strip().split(":", 1)
            v2 = v2.strip()
            if v2.startswith("[") and v2.endswith("]"):
                inner = v2[1:-1].strip()
                cur_item[k2] = [x.strip().strip("'\"")
                                for x in inner.split(",") if x.strip()]
            else:
                cur_item[k2] = v2.strip("'\"")
    return fm, text


def vocab_tags():
    tags = set()
    p = os.path.join(ROOT, "meta", "VOCAB.md")
    if os.path.exists(p):
        for m in re.finditer(r"^\|\s*([a-z0-9][a-z0-9-]*)\s*\|",
                             open(p).read(), re.M):
            if m.group(1) != "tag":
                tags.add(m.group(1))
    return tags


def main():
    tags = vocab_tags()
    notes = {}   # link target name -> path
    files = {t: sorted(glob.glob(os.path.join(ROOT, d, "*.md")))
             for t, d in [("lit", "lit"), ("claim", "claims"),
                          ("concept", "concepts"), ("moc", "mocs"),
                          ("qa", "qa")]}
    fm_all = {}
    for t, fl in files.items():
        for f in fl:
            fm, text = frontmatter(f)
            name = os.path.splitext(os.path.basename(f))[0]
            if fm is None:
                err(f, "no YAML frontmatter"); continue
            fm_all[f] = (t, fm, text)
            notes[name] = f
            if fm.get("type") != t:
                err(f, f"type '{fm.get('type')}' != folder type '{t}'")
    for extra in ("AI-GUIDE", "SCHEMA", "VOCAB", "WORKFLOW", "TRANSACTIONS", "HOME",
                  "_catalog", "EXTRACTION-PROMPT", "LINT", "INSTRUCTIONS",
                  "log", "AGENT-TASK", "TO-FIND"):
        notes[extra] = extra

    claim_ids = {}
    lit_claim_links = {}   # citekey -> set of claim ids linked in its lit note
    lit_names = {os.path.splitext(os.path.basename(f))[0]
                 for f, (t, _, _) in fm_all.items() if t == "lit"}

    for f, (t, fm, text) in fm_all.items():
        name = os.path.splitext(os.path.basename(f))[0]
        if t == "lit":
            for k in ("citekey", "title", "year", "status"):
                if not fm.get(k):
                    err(f, f"missing field '{k}'")
            if fm.get("citekey") and fm["citekey"] != name:
                err(f, f"citekey '{fm['citekey']}' != filename")
            if fm.get("status") not in ("stub", "digested", "verified",
                                        "reference"):
                err(f, f"bad status '{fm.get('status')}'")
            for field in ("topics", "methods", "regions"):
                for tag in fm.get(field, []) or []:
                    if isinstance(tag, str) and tag not in tags:
                        err(f, f"tag '{tag}' not in VOCAB.md")
            ft = os.path.join(ROOT, "fulltext", name + ".txt")
            if fm.get("status") != "stub" and not os.path.exists(ft):
                warn(f, "no fulltext file")
            if os.path.exists(ft):
                # Page anchors for this paper only: `[[<own citekey>]] p.N`, or a
                # bare p.N on a line with no other paper citation.
                have = set(re.findall(r"\[\[p\.(\d+)\]\]", open(ft).read()))
                body = text[text.find("\n---", 3) + 4:]
                link = r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]"   # [[target|alias]]
                for line in body.splitlines():
                    others = {t.strip() for t in re.findall(link, line)
                              if not re.fullmatch(r"p\.\d+", t.strip())} - {name}
                    other_papers = {t for t in others
                                    if t in lit_names or t not in notes}
                    for m in re.finditer(r"(" + link + r"\s*)?(?<![A-Za-z])"
                                         r"pp?\.(\d+)(?:[-–](\d+))?", line):
                        if m.group(2) and m.group(2).strip() in other_papers:
                            continue
                        if not m.group(2) and other_papers:
                            continue
                        for p in filter(None, (m.group(3), m.group(4))):
                            if p not in have:
                                err(f, f"cites p.{p} but fulltext has no [[p.{p}]] marker")
            if fm.get("status") == "reference":
                for sec in ("## TL;DR", "## Chapter map"):
                    if sec not in text:
                        err(f, f"missing section '{sec}' (reference note)")
            elif fm.get("status") != "stub":
                for sec in ("## TL;DR", "## Key findings", "## Methods",
                            "## Parameters", "## Claims", "## Relevance"):
                    if sec not in text:
                        err(f, f"missing section '{sec}'")
            lit_claim_links[name] = set(
                re.findall(r"\[\[(clm-[A-Za-z0-9-]+)\]\]", text))
        elif t == "claim":
            if fm.get("id") != name:
                err(f, f"id '{fm.get('id')}' != filename")
            claim_ids.setdefault(fm.get("id"), []).append(f)
            if not fm.get("statement"):
                err(f, "missing statement")
            if fm.get("status") not in ("supported", "contested", "refuted"):
                err(f, f"bad status '{fm.get('status')}'")
            if fm.get("provenance") not in ("paper", "user"):
                err(f, f"bad provenance '{fm.get('provenance')}'")
            srcs = [s for s in (fm.get("sources") or []) if isinstance(s, dict)]
            if fm.get("provenance") == "paper" and not srcs:
                err(f, "paper claim with no sources")
            for s in srcs:
                ck = s.get("citekey", "")
                if ck and ck not in notes:
                    err(f, f"source citekey '{ck}' has no lit note")
                pages = s.get("pages") or []
                if not pages:
                    warn(f, f"source '{ck}' has no pages")
                ft = os.path.join(ROOT, "fulltext", ck + ".txt")
                if pages and os.path.exists(ft):
                    have = set(re.findall(r"\[\[p\.(\d+)\]\]", open(ft).read()))
                    for p in pages:
                        if str(p) not in have:
                            err(f, f"p.{p} beyond fulltext markers of {ck}")
            if fm.get("status") == "contested" and "## Counter-evidence\nnone" in text:
                warn(f, "contested claim but Counter-evidence is 'none'")
        elif t == "concept":
            if fm.get("slug") != name:
                err(f, f"slug '{fm.get('slug')}' != filename")
        elif t == "qa":
            if not fm.get("question"):
                err(f, "missing question")

        for target in re.findall(r"\[\[([^\]|#]+?)\]\]", text):
            target = target.strip()
            if re.fullmatch(r"p\.\d+", target):
                continue
            if target not in notes:
                warn(f, f"broken link [[{target}]]")

    for cid, fl in claim_ids.items():
        if len(fl) > 1:
            err(fl[1], f"duplicate claim id '{cid}'")
    for f, (t, fm, _) in fm_all.items():
        if t != "claim":
            continue
        cid = fm.get("id", "")
        srcs = [s.get("citekey") for s in (fm.get("sources") or [])
                if isinstance(s, dict)]
        if not any(cid in lit_claim_links.get(ck, ()) for ck in srcs):
            warn(f, "orphan claim (not linked from any source lit note)")

    # ---- stale qa: cached answer citing missing/contested/refuted claims --
    claim_status = {fm.get("id"): fm.get("status")
                    for _, (t, fm, _) in fm_all.items() if t == "claim"}
    for f, (t, fm, text) in fm_all.items():
        if t != "qa":
            continue
        for ck in fm.get("sources") or []:
            if isinstance(ck, str) and ck not in notes:
                err(f, f"qa source '{ck}' has no lit note (stale qa?)")
        acknowledges = bool(re.search(r"contested|爭議", text, re.I))
        for cid in sorted(set(re.findall(r"\[\[(clm-[A-Za-z0-9-]+)\]\]", text))):
            st = claim_status.get(cid)
            if st is None:
                err(f, f"qa cites missing claim [[{cid}]] — stale, re-verify or delete")
            elif st == "refuted":
                err(f, f"qa cites refuted claim [[{cid}]] — stale, re-verify or delete")
            elif st == "contested" and not acknowledges:
                err(f, f"qa cites contested claim [[{cid}]] without presenting "
                       "both sides — re-verify or mark contested")

    # ---- _catalog.md <-> lit/ sync ----------------------------------------
    cat_path = os.path.join(ROOT, "_catalog.md")
    if os.path.exists(cat_path):
        cat = open(cat_path, encoding="utf-8").read()
        cat_keys = set(re.findall(r"^\|\s*\[\[([^\]]+)\]\]", cat, re.M))
        lit_keys = {os.path.splitext(os.path.basename(f))[0]
                    for f, (t, _, _) in fm_all.items() if t == "lit"}
        for ck in sorted(lit_keys - cat_keys):
            err(cat_path, f"lit note '{ck}' has no row in _catalog.md")
        for ck in sorted(cat_keys - lit_keys):
            err(cat_path, f"catalog row '{ck}' has no lit note")
        m = re.search(r"(\d+)\s+unique papers", cat)
        if m and int(m.group(1)) != len(cat_keys):
            err(cat_path, f"header says {m.group(1)} papers but table has "
                          f"{len(cat_keys)} rows")

    # ---- orphan concepts: no inbound link from any other note -------------
    links_to = {}   # link target -> set of source files
    for f, (t, fm, text) in fm_all.items():
        for target in re.findall(r"\[\[([^\]|#]+?)\]\]", text):
            links_to.setdefault(target.strip(), set()).add(f)
    for f, (t, fm, _) in fm_all.items():
        if t != "concept":
            continue
        slug = os.path.splitext(os.path.basename(f))[0]
        if not (links_to.get(slug, set()) - {f}):
            warn(f, "orphan concept (no inbound links from lit/claims/mocs/qa)")

    # ---- unused VOCAB tags -------------------------------------------------
    used_tags = set()
    for f, (t, fm, _) in fm_all.items():
        for field in ("topics", "methods", "regions"):
            for tag in fm.get(field) or []:
                if isinstance(tag, str):
                    used_tags.add(tag)
    vocab_path = os.path.join(ROOT, "meta", "VOCAB.md")
    for tag in sorted(tags - used_tags):
        warn(vocab_path, f"tag '{tag}' is used by no note")

    # ---- concept alias collisions ------------------------------------------
    slugs = {os.path.splitext(os.path.basename(f))[0]
             for f, (t, _, _) in fm_all.items() if t == "concept"}
    alias_owner = {}
    for f, (t, fm, _) in sorted(fm_all.items()):
        if t != "concept":
            continue
        slug = os.path.splitext(os.path.basename(f))[0]
        for a in fm.get("aliases") or []:
            if not isinstance(a, str) or not a.strip():
                continue
            a_n = a.strip().lower()
            if a_n in {s.lower() for s in slugs - {slug}}:
                err(f, f"alias '{a}' collides with another concept's slug")
            elif a_n in alias_owner and alias_owner[a_n] != slug:
                err(f, f"alias '{a}' also claimed by concept "
                       f"'{alias_owner[a_n]}'")
            alias_owner.setdefault(a_n, slug)

    for line in ERRORS + WARNINGS:
        print(line)
    n_notes = len(fm_all)
    print(f"\n{n_notes} notes checked: {len(ERRORS)} errors, "
          f"{len(WARNINGS)} warnings")
    sys.exit(1 if ERRORS else 0)


if __name__ == "__main__":
    main()
