---
type: meta
name: LINT
description: Semantic lint protocol — periodic AI health check of the whole vault (contradictions, stale qa, duplicate concepts, coverage gaps). Diagnoses only; fixes need user approval.
---

# LINT — 語意巡檢協定（AI 定期健檢）

> 觸發：使用者說「跑 litwiki lint」。頻率建議：每累積 ~10 篇新論文、或每季一次。
> 本協定**只診斷不動刀**：產出報告，所有修復動作列成建議，經使用者確認才執行。
> 結構層問題（格式/斷鏈/頁碼）不歸這裡——那是 `scripts/validate.py` 的事，
> lint 開始前先跑它並確認 0 errors，語意巡檢建立在結構乾淨的前提上。

Vault root: the directory that contains `meta/`。執行者：任何有檔案存取的 AI agent
（可平行分工，四個 pass 互相獨立）。

## Pass 1 — 矛盾掃描（claims）

目的：找出「兩條 claims 對同一物理量/同一對象給出不相容陳述，卻沒有互列 contested」。
注意語意：「矛盾」在本庫＝**未互列的並立結果**（不同方法/資料的 competing
estimates）。修復目標是互列＋查詢時並陳各方方法，**不是判定誰對誰錯**
（SCHEMA 的 contested 定義）。

1. 讀全部 `claims/*.md` 的 `statement` + `topics`（一行一條，量少可全讀）。
2. 按 topic/region 分組，組內兩兩比對：同一物理量（速率、深度、溫度、年齡、
   幾何）或同一因果解釋，數值/方向不相容？
3. 排除合法情況：不同研究區、不同時間窗、不同定義（例如不同熱定年系統的
   封閉溫度本來就不同）——不確定就標「疑似」讓使用者裁決。
4. 每個發現記：兩條 claim id、各自 statement、為何不相容、建議
   （互改 `status: contested` + 互列 `counter_sources`）。

## Pass 2 — 概念去重（entity resolution）

目的：防止同一概念長出兩張卡（例如 detachment vs decollement）。

1. 讀全部 `concepts/*.md` 的 slug、aliases、Definition 首段。
2. 找語意重複或高度重疊的卡；也檢查「某 alias 其實該是獨立概念」的反向情況。
3. 建議：合併方向（誰併入誰）、保留哪個 slug、aliases 怎麼併。

## Pass 3 — 缺口偵測（coverage gaps）

目的：找「該有而沒有」。基準 = `meta/INSTRUCTIONS.md` 的焦點主題。

1. 統計 `_catalog.md` 各 topic 的論文數。
2. 焦點主題：論文 ≥3 篇但無對應 `concepts/` 卡或 `mocs/` 導讀 → 報缺口。
3. 一般主題：論文 ≥5 篇才報。
4. 反向檢查：庫裡是否累積了 INSTRUCTIONS「範圍外」主題的論文 → 提醒使用者
   （可能是誤入庫，也可能是研究方向變了該更新 INSTRUCTIONS——由使用者判斷）。
5. lit 筆記的 `## Open questions` 中反覆出現、但庫內無任何論文回答的問題
   → 列為「文獻缺口」（建議使用者找論文，不是建筆記）。

## Pass 4 — qa 抽查（語意過期）

目的：validate.py 只能抓「qa 引用的 claim 變了」；這裡抓「qa 的結論被
*之後入庫的論文*語意上推翻/削弱，但沒有任何連結變動」。

1. 對每個 `qa/*.md`：取其結論關鍵詞，grep `claims/` 與 `_catalog.md` 中
   *晚於該 qa `date:`* 入庫的相關論文。
2. 新證據支持、矛盾、還是無關？矛盾 → 建議改寫或刪除該 qa。
3. 順帶檢查 qa 的 `sources` 論文是否已被 PURGE（validate 會抓檔案缺失，
   這裡確認語意上是否還站得住）。

## 報告格式

寫入 `meta/lint-reports/YYYY-MM-DD.md`（當天日期）：

```markdown
---
type: meta
name: lint-report-YYYY-MM-DD
description: Semantic lint findings of YYYY-MM-DD (N findings, M fixed).
---

# Lint report YYYY-MM-DD

掃描範圍：N lit / N claims / N concepts / N mocs / N qa。validate.py：0 errors。

## Findings

### L1 [矛盾|重複概念|缺口|過期qa] <一行標題>
- 涉及：[[...]]、[[...]]
- 說明：<為什麼是問題，含證據引用>
- 建議修復：<具體動作>
- 處置：pending → （使用者確認後改 fixed / rejected + 一句話）

## 統計
矛盾 N、重複概念 N、缺口 N、過期 qa N。
```

## 收尾（強制）

1. 報告寫完先給使用者看 findings 摘要，逐項要確認。
2. 使用者核准的修復才執行；執行後把該 finding 的處置改 fixed，
   跑 `python3 scripts/validate.py` 確認 0 errors。
3. `meta/log.md` 追加一行：
   `YYYY-MM-DD  LINT  第N輪語意巡檢：發現X項（矛盾a/重複b/缺口c/過期d），修復y項，報告 meta/lint-reports/YYYY-MM-DD.md`
