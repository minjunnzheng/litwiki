#!/usr/bin/env python3
"""Check the tracked distribution file allowlist and empty private-data slots."""
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def main():
    manifest = ROOT / ".github/package-files.txt"
    allowed = set(manifest.read_text().splitlines())
    tracked = set(subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().strip("\0").split("\0"))
    errors = []
    if tracked != allowed:
        errors.append(f"tracked file allowlist differs: extra={sorted(tracked-allowed)}, missing={sorted(allowed-tracked)}")
    for folder in ("fulltext", "lit", "claims", "concepts", "mocs", "qa", "data",
                   "meta/digest-reports", "meta/lint-reports"):
        paths = [p for p in (ROOT / folder).rglob("*") if p.is_file() and p.name != ".gitkeep"]
        if paths:
            errors.append(f"private data present in {folder}")
    for name in ("map.json", "source-versions.json", "integration.json"):
        if json.loads((ROOT / "meta" / name).read_text()) != {}:
            errors.append(f"meta/{name} must be empty in the package")
    if re.search(r"^\s*@\w+\s*[{(]", (ROOT / "meta/library.bib").read_text(), re.M):
        errors.append("bibliography entries in public package")
    for name in tracked:
        path = ROOT / name
        if path.is_symlink():
            if name != "AGENTS.md" or path.readlink() != Path("CLAUDE.md"):
                errors.append(f"unexpected symlink: {name}")
        elif path.is_file() and (b"/" + b"Users/") in path.read_bytes():
            errors.append(f"local user path in {name}")
    # Empty-vault unused vocabulary is expected; all other warnings remain visible.
    result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/validate.py")], capture_output=True, text=True)
    expected = [line for line in result.stdout.splitlines()
                if line.startswith("WARN  meta/VOCAB.md:") and line.endswith("is used by no note")]
    unexpected = [line for line in result.stdout.splitlines()
                  if line.startswith(("ERROR", "WARN")) and line not in expected]
    if result.returncode or unexpected:
        errors.append(result.stdout + result.stderr)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"template: PASS ({len(tracked)} allowlisted files; {len(expected)} expected unused-vocabulary notices)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
