# Install

## macOS / Linux

```bash
git clone https://github.com/minjunnzheng/litwiki.git
cd litwiki

# PDF extraction
#   macOS:  brew install poppler
#   Debian: sudo apt install poppler-utils

python3 scripts/validate.py
```

Optional: Zotero + the Better BibTeX plugin, auto-exporting My Library as
Better BibLaTeX to `meta/library.bib` (Keep updated). The automated
`zotero_map.py` command requires both. Citation key formula
`auth.lower + year` matches the filename convention. Pin keys of papers
already in the vault.

## Windows (WSL)

```bash
sudo apt update
sudo apt install -y git python3 poppler-utils
git clone https://github.com/minjunnzheng/litwiki.git
cd litwiki
python3 scripts/validate.py
```

All commands in this repo assume a Unix shell inside WSL, not PowerShell.

## Without Zotero

Create a private vault from this template before adding real sources. Choose a
stable citekey and add an entry to `meta/map.json` without removing existing
entries. Copy the title, authors, year, journal and DOI from the source or a
verified bibliography; leave `doi` empty if none is available. Use the PDF's
absolute path and an empty annotation list:

```json
{
  "paperkey": {
    "title": "<verified title>",
    "authors": "<verified authors>",
    "year": "<YYYY>",
    "journal": "<verified journal>",
    "doi": "",
    "pdf": "/absolute/path/to/paper.pdf",
    "itemKey": "",
    "annotations": []
  }
}
```

Replace `paperkey` and the placeholders, then run
`bash scripts/extract_fulltext.sh paperkey`. Use that same citekey for
`fulltext/paperkey.txt` and `lit/paperkey.md`. Do not run `zotero_map.py`
after adding manual entries: it rebuilds `meta/map.json` from the Zotero export.

The map entry and extraction are bootstrap steps: they run directly in the vault,
before the source baseline and digestion (`meta/WORKFLOW.md` §A). Do not log
them separately. Record them once, in the `INGEST` line of `meta/log.md` that goes
into the final ingest transaction together with the note, catalog row, source
version and integration receipt — for example
`INGEST paperkey: manual map.json entry, fulltext extracted, lit + N claims`.
If extraction fails (nonzero exit), stop; nothing is logged.

## Agent skills

```bash
mkdir -p ~/.claude/skills ~/.codex/skills ~/.agents/skills
cp -R skills/litwiki ~/.claude/skills/
cp -R skills/litwiki ~/.codex/skills/    # directory of real files
cp -R skills/litwiki ~/.agents/skills/
export LITWIKI_ROOT=/path/to/litwiki
```

The examples copy complete skill directories. If an entry already exists, inspect
it before copying; consult your agent’s current discovery rules for symlinks.

## Obsidian (optional)

Open this folder as a vault. `HOME.md` links to the catalog, topic maps
and workflow rules. Zotero Integration, if used, can load
`meta/zotero-import.md` as the import format, with note path `lit/`.
