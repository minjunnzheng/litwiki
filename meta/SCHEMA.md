---
type: meta
name: SCHEMA
description: YAML frontmatter and section specifications for the five note types (lit, claim, concept, moc, qa).
---

# SCHEMA — note types and required structure

Five note types. `type:` in the frontmatter is mandatory everywhere and is
what Dataview/grep filters on. Field names are always English; free-text
values are bilingual (中文摘要 + English technical terms).

Enforced by `scripts/validate.py`. Templates live in `meta/templates/`.

## 1. `lit` — literature note (one per paper) — `lit/<citekey>.md`

Filename = Better BibTeX citekey, exactly as in `meta/library.bib`.

```yaml
---
type: lit
citekey: smith2020example            # = filename, = BibTeX key
title: "..."
authors: [Smith A., ...]             # "Last F." form, full list
year: 2020
journal: "..."
doi: 10.xxxx/xxxx
zotero: zotero://select/library/items/<ITEMKEY>
pdf: ~/Zotero/storage/<KEY>/paper.pdf   # or any absolute path to the PDF
fulltext: fulltext/smith2020example.txt
topics: [orogeny]                              # from meta/VOCAB.md only
methods: [numerical-modeling]                  # from meta/VOCAB.md only
regions: [global]                              # from meta/VOCAB.md only
status: digested                     # stub | digested | verified | reference
digested_by: claude-fable-5          # model that wrote this note
digested_date: 2026-07-07
---
```

`status: reference` = 教科書/專著（reference tier）。**不走全文消化**：
lit note 只含 `## TL;DR`（這是什麼書、對本庫的用途）＋ `## Chapter map`
（章名 → 頁碼範圍 → 一句話涵蓋什麼，來源=目錄頁）。claims **隨用隨萃**——
查閱時被使用者確認的事實才寫成 `clm-<citekey>-NN`（含頁碼），慢慢累積。
fulltext 照常全量抽取（免費、grep-able）。其餘筆記類型的必要段落如下：

Required sections, in this order (headings verbatim):

```markdown
# <citekey> — <short title>

## TL;DR
3–5 句中文摘要：這篇做了什麼、怎麼做、主要結論、為什麼重要。

## Key findings
1. <finding, English, one sentence> ([[<citekey>]] p.X)
2. ...          # every finding MUST end with a page anchor
                # 5–12 items; numbers/values verbatim from the paper

## Methods
簡述方法（modeling / analytical / field / synthesis...），關鍵假設與限制。

## Parameters
| parameter | value | unit | page |
|---|---|---|---|
（modeling/實驗論文必填：domain, resolution, rheology, BCs, rates, temps...；
 非 modeling 論文可寫 "n/a"）

## Data & figures
- Fig. 3: <what it shows and why it matters> (p.X)
- Dataset: <name, where to get it>

## Claims
- [[clm-<citekey>-01]]    # links to every claim extracted from this paper

## Relevance
與庫內其他文獻/主題的關係：延伸誰、反駁誰、被誰用。用 [[citekey]] 連結。

## Annotations
（Zotero 高亮/筆記原文，含顏色與頁碼；無則寫 "none"）

## Open questions
作者自承的限制、未解問題。
```

## 2. `claim` — atomic fact — `claims/clm-<citekey>-<nn>.md`

One falsifiable statement per file. Scoped to the *primary* source paper:
`<citekey>` = the paper the claim comes from, `<nn>` = 01, 02, ... within
that paper (e.g. `clm-tanMountainBuildingProcess2024-03`). Claims from the
owner's own knowledge use `clm-user-<nn>` with `provenance: user`.

```yaml
---
type: claim
id: clm-tanMountainBuildingProcess2024-03
statement: "..."                     # English, one sentence, verbatim numbers
status: supported                    # supported | contested | refuted
    # contested ≠ 有一方錯誤。它表示庫內存在方法/資料/假設不同的「並立」
    # 結果或詮釋（competing estimates/theories）——回答時必須並陳各方
    # 及其方法，不得表述成「其中一方必錯」。refuted 才是已被明確推翻。
confidence: high                     # high | medium | low
sources:
  - citekey: tanMountainBuildingProcess2024
    pages: [4, 7]
counter_sources: []                  # citekeys that dispute it (contested/refuted)
topics: [taiwan-orogeny]
provenance: paper                    # paper | user  (user = owner's field knowledge)
---

## Evidence
> "<verbatim quote ≤ 40 words>" ([[tanMountainBuildingProcess2024]] p.4)

## Counter-evidence
（status: contested/refuted 時必填，同格式；否則 "none"）

## Notes
（可選：換算、單位、與其他 claim 的關係 [[clm-...]]）
```

## 3. `concept` — concept/method/parameter card — `concepts/<slug>.md`

```yaml
---
type: concept
slug: closure-temperature
aliases: [封閉溫度, Tc]
topics: [thermochronology]
---

## Definition
一段定義（中文），關鍵術語附英文。

## Key equations
（有則列，LaTeX；無則 "none"）

## Typical values
| context | value | source |
|---|---|---|
| ZFT | ~240 °C | [[clm-thermochron-001]] |

## Related
- claims: [[clm-...]]
- papers: [[citekey]] — 一句話說明關係
- concepts: [[other-slug]]
```

## 4. `moc` — map of content — `mocs/moc-<slug>.md`

```yaml
---
type: moc
slug: taiwan-orogeny
topics: [taiwan-orogeny]
---

## Start here
按閱讀順序排列，每篇一句話導讀：
1. [[citekeyA]] — 為什麼先讀這篇
2. [[citekeyB]] — ...

## Sub-topics
- <sub-topic>: [[citekeyC]], [[citekeyD]]

## Key concepts
[[concept-slug]], ...

## Open debates
- <爭點>: [[clm-...-00x]] (contested)
```

## 5. `qa` — verified answer cache — `qa/qa-<nnn>.md`

```yaml
---
type: qa
id: qa-001
question: "..."                      # 原始問法（保留使用者語言）
verified_by: user                    # user | fable  (誰確認過答案)
date: 2026-07-07
sources: [tan2024mountain]
---

## Answer
（完整答案，含 [[citekey]] p.X 引用）
```

## Global rules

- Wiki-links between notes always use `[[target]]` (no path, no .md).
- Page anchors: `p.X` or `pp.X-Y`, matching `[[p.N]]` markers in fulltext.
- Tags in `topics/methods/regions` MUST exist in `meta/VOCAB.md`.
- Dates ISO `YYYY-MM-DD`. No relative dates anywhere.
