---
type: lit
citekey: {{citekey}}
title: "{{title}}"
authors: [{{#each creators}}{{lastName}} {{firstName}}{{#unless @last}}, {{/unless}}{{/each}}]
year: {{date | format("YYYY")}}
journal: "{{publicationTitle}}"
doi: {{DOI}}
zotero: zotero://select/library/items/{{itemKey}}
pdf: {{#if pdfAttachments}}{{pdfAttachments.[0].path}}{{/if}}
fulltext: fulltext/{{citekey}}.txt
topics: []
methods: []
regions: []
status: stub
digested_by:
digested_date:
---

# {{citekey}} — {{title}}

## TL;DR
（stub：尚未消化。依 meta/EXTRACTION-PROMPT.md 完成消化後改 status: digested）

## Key findings

## Methods

## Parameters
| parameter | value | unit | page |
|---|---|---|---|

## Data & figures

## Claims

## Relevance

## Annotations
{{#each annotations}}
> "{{annotatedText}}" (p.{{page}}){{#if comment}} — 註：{{comment}}{{/if}}
{{/each}}

## Open questions
