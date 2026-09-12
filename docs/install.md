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
Better BibLaTeX to `meta/library.bib` (Keep updated). Citation key formula
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

## Agent skills

```bash
cp -R skills/litwiki ~/.claude/skills/
cp -R skills/litwiki ~/.codex/skills/    # directory of real files
cp -R skills/litwiki ~/.agents/skills/
export LITWIKI_ROOT=/path/to/litwiki
```

The examples copy complete skill directories. If an entry already exists, inspect
it before copying; consult your agent’s current discovery rules for symlinks.

## Obsidian (optional)

Open this folder as a vault. Dataview queries in `HOME.md` need the
Dataview plugin. Zotero Integration can use `meta/zotero-import.md` as
the import format, with note path `lit/`.
