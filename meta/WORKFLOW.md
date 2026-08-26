---
type: meta
name: WORKFLOW
description: Standard operating procedures — adding a new paper, caching verified answers, validation, and Zotero-side setup.
---

# WORKFLOW — 日常維護 SOP

## A. 新論文入庫（每篇 ~5 分鐘人工 + 一次 AI 消化）

1. 論文照常進 Zotero（拖 PDF / 瀏覽器外掛）。
2. `meta/library.bib` 是 Better BibTeX auto-export（Keep updated），會自動
   更新，citekey 以它為準。
3. 在終端機（litwiki/ 目錄下）跑：
   ```bash
   python3 scripts/zotero_map.py --citekey <新citekey>   # 找 PDF、更新對照
   bash scripts/extract_fulltext.sh <新citekey>          # 產 fulltext/<citekey>.txt
   ```
4. 叫 AI 消化（模型可換，程序不可換）：

   | 走哪條 | 指令 | 用在 |
   |---|---|---|
   | **預設** | `bash scripts/grok_one.sh <citekey>` | 一般論文（grok-4.6） |
   | 難篇 | `bash scripts/codex_one.sh <citekey>` | OCR 差、圖說與正文互相矛盾、引用標籤混亂的老論文（gpt-5.6-sol） |
   | Claude | > 依照 `meta/EXTRACTION-PROMPT.md` 消化 `<citekey>`。 | 手邊已開 session 時 |

   兩支腳本內部都強制走 `meta/CODEX-TASK.md`。品質由架構保證：EXTRACTION-PROMPT
   定程序、SCHEMA 定格式、validate.py 硬驗證，所以換模型讀，成品仍是同一規格。
   絕不讓 AI「自由發揮」讀論文。
   （消化 agent 只寫 `lit/`+`claims/`——平行安全；回寫既有頁面是下一步的事。）

   **注意：Codex 若載入了「寫入信任庫前先跨模型審查」之類的全域規則，會為每篇
   多開一輪審查。** `codex_one.sh` 的 prompt 已明寫此步不需送審；批次跑之前
   別把那句拿掉。
5. **INTEGRATE 回寫**（消化完成後，由主 session 依消化回傳的 JSON 執行；
   這步讓既有頁面「知道」新論文存在，缺了它庫會單向生長）：
   1. `_catalog.md` 加一行（表頭論文數 +1）。
   2. `concept_candidates` 併入 `concepts/`；新論文有提供數值的既有 concept，
      把值補進其 Typical values 表（附 [[citekey]] 或 claim 連結）。
   3. 加進相關 `mocs/`（一句話導讀）。
   4. **反向連結**：依新 lit 筆記的 `## Relevance`，打開被連到的 3–5 篇既有
      `lit/` 筆記，在各自 `## Relevance` 加一行
      `[[新citekey]] — <延伸/反駁/使用了它的什麼>`。
   5. **qa 影響檢查**：`grep -ril "<相關關鍵詞>" qa/`，新論文推翻或明顯補充
      某 qa 的答案 → 修正或刪除該 qa（修正後仍須符合 tpl-qa）。
   6. **把完整變更做成 transaction**：所有目標檔先寫到 vault 外的 session
      scratch；`meta/log.md` 的 `INGEST`／`INTEGRATE` 行也放進同一批 replacement。
      Spec 格式與安全契約見 `meta/TRANSACTIONS.md`。正式 vault 不可逐檔直接改。
   7. Preview、一次套用、驗證：
      ```bash
      python3 scripts/transaction.py prepare /private/tmp/<operation>/spec.json \
        --bundle /private/tmp/<operation>/bundle.json
      python3 scripts/transaction.py inspect /private/tmp/<operation>/bundle.json
      python3 scripts/transaction.py apply /private/tmp/<operation>/bundle.json \
        --approved-plan-sha256 <inspect 輸出的 hash>
      python3 scripts/validate.py
      ```
      只有 `validate.py` 0 errors 才完成。若驗證失敗，先跑只讀的
      `transaction.py rollback <operation_id>` 看完整計畫；套用 rollback 前依
      `TRANSACTIONS.md` 列出所有絕對路徑並取得使用者明確同意。
6. obsidian-git 自動 commit（或手動 commit）。

## A-R. 教科書/專著入庫（reference tier；不走 A-4 全文消化）

教科書全文消化＝數十萬 token 燒在讀入，且產出形狀不對（書是按章查閱的）。
改走輕量流程：

1. PDF 照常進 Zotero（book 條目，pin citekey）——同 A-1〜A-3
   （zotero_map ＋ extract_fulltext；fulltext 全量抽取免費）。
2. AI **只讀目錄頁**（約 8–12 頁），寫 `lit/<citekey>.md`：
   `status: reference`，段落只要 `## TL;DR`（這是什麼書、對本庫用途）＋
   `## Chapter map`（章名 → 頁碼範圍 → 一句話涵蓋什麼）。
3. **claims 隨用隨萃**：日後查閱時（章節地圖定位 → grep fulltext → 只讀
   命中頁），被使用者確認的事實才寫 `clm-<citekey>-NN`（含頁碼），慢慢累積。
4. `_catalog.md` 加一行（標 ※ref）、`python3 scripts/validate.py`、log 記
   `INGEST <citekey>（reference tier）`。

成本：建檔每本 ~1–2 萬 token；之後每次查閱 ~2–4 千。

## B. qa/ 快取（讓知識庫越用越聰明）

任何 AI 回答被你確認正確且日後可能再問，就叫它：
> 把剛才這個問答依 `tpl-qa` 存進 `qa/`。
弱 AI 之後會最先命中這裡（路由 Step 1）。答案後來被推翻就直接刪檔或修正。
新增/修正/刪除 qa 後在 `meta/log.md` 追加一行 `QA ...`。

## C. 驗證

```bash
python3 scripts/validate.py          # schema、斷鏈、頁碼錨點、孤兒 claim、
                                     # 過期 qa、catalog 同步、孤兒 concept、
                                     # 未用 tag、concept alias 互撞
```
每次批次寫入後必跑；紅字全修完才算完成。

## D. Zotero 端設定（一次性）

1. **Better BibTeX auto-export**：My Library 右鍵 → Export Library →
   格式 Better BibLaTeX、勾 **Keep updated** → 存到
   `meta/library.bib`（本庫根目錄下）。
2. citekey 公式建議（BBT Preferences → Citation keys）：
   `auth.lower + year`（衝突自動加後綴），與本庫檔名慣例一致。
   改公式後：全選 → 右鍵 → Better BibTeX → Refresh citation keys；
   已入庫的論文 citekey 請 Pin（右鍵 → Pin citation key）避免日後漂移。
3. Obsidian **Zotero Integration** 插件：Import format 指到
   `meta/zotero-import.md` 模板，Note path 設 `lit`。
   （這條路線給「手動快速帶入 metadata+註記」用；完整消化仍走 A 流程。）

## E. 批次重跑（架構升級時）

SCHEMA/EXTRACTION-PROMPT 若大改版，舊筆記不必手改：對目標 citekey 重跑
A-4（消化步驟）即可覆寫。`fulltext/` 與 `library.bib` 是不變的原料層。

## F. 語意 lint（定期健檢；手動觸發）

每累積 **~10 篇新論文**或**每季一次**，開 session 說：
> 跑 litwiki lint

AI 依 `meta/LINT.md` 執行四個 pass（claims 矛盾掃描、概念去重、缺口偵測、
qa 語意過期抽查），產出 `meta/lint-reports/YYYY-MM-DD.md`。**它只診斷**：
所有修復建議逐項給你確認後才執行，完成後追加 `meta/log.md` 一行 `LINT ...`。

## G. INSTRUCTIONS.md 更新（研究方向變動時）

`meta/INSTRUCTIONS.md` 是你的研究優先序檔（extraction 加密與 lint 缺口偵測
的基準），**由你擁有**。開新研究線（例如新造山帶）、或 lint 提醒範圍外論文
成群時，AI 只能**提出修改草案（diff）給你確認**，確認後代筆寫入並更新
`updated:` 日期＋log 一行 `SCHEMA ...`。AI 不得未經確認修改此檔。
