#!/usr/bin/env python3
"""Read-only source drift and integration audit; baseline writes only to a new output file."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from validate import frontmatter

ROOT = Path(__file__).resolve().parent.parent
CHECKS = ("concepts", "mocs", "backlinks", "qa")


def digest(path):
    with Path(path).open("rb") as handle:
        before = os.fstat(handle.fileno())
        result = hashlib.sha256()
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
        finished = os.fstat(handle.fileno())
    after = Path(path).stat()
    if len({(s.st_ino, s.st_size, s.st_mtime_ns) for s in (before, finished, after)}) != 1:
        raise ValueError(f"source changed while hashing: {path}")
    return result.hexdigest()


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def source_path(root, relative):
    """Keep source references inside the vault, including symlink resolution."""
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or Path(relative).is_absolute():
        raise ValueError(f"source path must stay inside vault: {relative}")
    return path


def capture(root, keys=None):
    mapping = read_json(root / "meta/map.json", {})
    records = {}
    for path in sorted((root / "fulltext").glob("*.txt")):
        if keys and path.stem not in keys:
            continue
        source_path(root, str(path.relative_to(root)))
        record = {"captured_at": now(), "basis": "observed-current-files",
                  "fulltext": {"path": str(path.relative_to(root)), "sha256": digest(path)},
                  "pdf": None}
        pdf = mapping.get(path.stem, {}).get("pdf")
        if pdf:
            file = Path(pdf).expanduser()
            if not file.is_absolute():
                file = root / file
            record["pdf"] = {"path": str(file.resolve()),
                             "sha256": digest(file) if file.is_file() else None}
        records[path.stem] = record
    if keys and set(keys) - records.keys():
        raise ValueError(f"missing fulltext: {sorted(set(keys) - records.keys())}")
    return records


def wiki_links(text):
    return set(re.findall(r"\[\[([^\]|#]+)(?:[^\]]*)\]\]", text))


def audit(root, versions=None, integrations=None):
    versions = versions if versions is not None else read_json(root / "meta/source-versions.json", {})
    integrations = integrations if integrations is not None else read_json(root / "meta/integration.json", {})
    current = capture(root)
    sources = []
    for key in sorted(versions.keys() | current.keys()):
        old, new = versions.get(key), current.get(key)
        changes = []
        if old is None:
            state = "untracked"
        elif new is None:
            state = "missing"
        else:
            for field in ("fulltext", "pdf"):
                if old.get(field) != new.get(field):
                    changes.append(field)
            state = "changed" if changes else "unchanged"
        sources.append({"source_key": key, "state": state, "changed": changes,
                        "pdf_available": bool(new and new.get("pdf") and new["pdf"].get("sha256")),
                        "baseline": old, "current": new})

    notes = {}
    for folder in ("lit", "claims", "concepts", "mocs", "qa"):
        for path in sorted((root / folder).glob("*.md")):
            fm, body = frontmatter(path)
            notes[path.stem] = (path, fm or {}, wiki_links(body), body)
    catalog_path = root / "_catalog.md"
    catalog = catalog_path.read_text() if catalog_path.exists() else ""
    catalog_keys = set(re.findall(r"^\|\s*\[\[([^\]|]+)\]\]", catalog, re.M))
    papers = []
    for key, (path, fm, links, body) in notes.items():
        if path.parent.name != "lit":
            continue
        receipt = integrations.get(key, {})
        missing = sorted(link for link in links if link.startswith("clm-") and link not in notes)
        mocs = sorted(name for name, (p, _, targets, _) in notes.items()
                      if p.parent.name == "mocs" and key in targets)
        reciprocal_missing = sorted(target for target in links if target in notes
                                    and notes[target][0].parent.name == "lit"
                                    and target != key and key not in notes[target][2])
        flags = []
        if key not in catalog_keys:
            flags.append("missing-catalog-row")
        if missing:
            flags.append("missing-claim-files")
        if not mocs:
            flags.append("no-moc-link-observed")
        if reciprocal_missing:
            flags.append("reciprocal-links-to-review")
        state = "unrecorded"
        if fm.get("status") == "stub":
            state = "not-digested"
        elif key not in catalog_keys or missing or receipt.get("status") == "pending":
            state = "pending"
        elif receipt.get("status") == "complete":
            checks = receipt.get("checks", {})
            valid = all(checks.get(c, {}).get("status") in ("done", "not-applicable")
                        and checks[c].get("reason", "").strip() for c in CHECKS)
            files = receipt.get("files", {})
            required = {f"lit/{key}.md", f"fulltext/{key}.txt"}
            valid = valid and bool(receipt.get("reviewer")) and bool(receipt.get("checked_at"))
            valid = valid and required.issubset(files)
            for relative, expected in files.items():
                file = source_path(root, relative)
                valid = valid and file.is_file() and digest(file) == expected
            state = "complete" if valid else "stale-receipt"
        papers.append({"citekey": key, "digest_status": fm.get("status"),
                       "integration_status": state, "flags": flags, "mocs": mocs,
                       "missing_claims": missing, "reciprocal_links_to_review": reciprocal_missing,
                       "record": receipt or None})
    return {"generated_at": now(), "vault": str(root.resolve()),
            "source_counts": dict(Counter(s["state"] for s in sources)),
            "integration_counts": dict(Counter(p["integration_status"] for p in papers)),
            "sources": sources, "papers": papers,
            "limitations": "An observed baseline does not identify the source version used by an old digest. "
                            "Unrecorded means no structured completion receipt; link flags require review, "
                            "not automatic edits. Hash equality is not scientific verification."}


def self_test():
    with tempfile.TemporaryDirectory(prefix="litwiki-health-") as folder:
        root = Path(folder)
        for name in ("fulltext", "lit", "claims", "meta"):
            (root / name).mkdir()
        source = root / "fulltext/demo.txt"
        source.write_text("[[p.1]]\nDemonstration only.\n")
        note = root / "lit/demo.md"
        note.write_text("---\ntype: lit\ncitekey: demo\nstatus: digested\n---\n")
        (root / "_catalog.md").write_text("| [[demo]] |\n")
        baseline = capture(root)
        assert audit(root, baseline)["source_counts"] == {"unchanged": 1}
        assert audit(root, baseline)["papers"][0]["integration_status"] == "unrecorded"
        pending = {"demo": {"status": "pending"}}
        assert audit(root, baseline, pending)["papers"][0]["integration_status"] == "pending"
        receipt = {"demo": {"status": "complete", "reviewer": "fixture", "checked_at": now(),
                            "checks": {c: {"status": "not-applicable", "reason": "fixture"} for c in CHECKS},
                            "files": {p: digest(root / p) for p in ("lit/demo.md", "fulltext/demo.txt", "_catalog.md")}}}
        assert audit(root, baseline, receipt)["papers"][0]["integration_status"] == "complete"
        source.write_text("[[p.2]]\nChanged source.\n")
        result = audit(root, baseline, receipt)
        assert result["source_counts"] == {"changed": 1}
        assert result["papers"][0]["integration_status"] == "stale-receipt"
        source.rename(root / "moved.txt")
        assert audit(root, baseline)["source_counts"] == {"missing": 1}
        try:
            source_path(root, "../outside.txt")
            raise AssertionError("escaping path accepted")
        except ValueError:
            pass
    print("health self-test: PASS")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("status", "baseline"), default="status")
    parser.add_argument("--vault", type=Path, default=ROOT)
    parser.add_argument("--citekey", action="append", help="baseline: capture only these sources; preserve other records")
    parser.add_argument("--output", type=Path, help="new file outside the vault; install via transaction after inspection")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    root = args.vault.expanduser().resolve()
    try:
        if not (root / "meta/AI-GUIDE.md").is_file():
            raise ValueError(f"not a litwiki vault: {root}")
        if args.command == "baseline":
            if not args.output:
                raise ValueError("baseline requires --output")
            result = read_json(root / "meta/source-versions.json", {})
            result.update(capture(root, args.citekey))
        else:
            if args.citekey:
                raise ValueError("--citekey is only for baseline")
            result = audit(root)
        payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            if args.output.resolve().is_relative_to(root):
                raise ValueError("--output must be outside the vault")
            with args.output.open("x") as handle:
                handle.write(payload)
            print(args.output.resolve())
        elif args.json:
            print(payload, end="")
        else:
            print("sources:", result["source_counts"])
            print("integration:", result["integration_counts"])
            for paper in result["papers"]:
                if paper["integration_status"] in ("pending", "stale-receipt"):
                    print(paper["integration_status"], paper["citekey"], ", ".join(paper["flags"]))
            print(result["limitations"])
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
