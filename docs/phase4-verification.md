# Phase 4：驗證與交付紀錄

日期：2026-09-23。依 [SEEK-only 規格](../NZ_WORKING_HOLIDAY_JOB_RADAR_SPEC.md)驗收；不包含 Trade Me、滑雪場官網、排程或 Dashboard。

## 結論

Phase 4 的程式補強、離線驗證及操作文件已完成。全套 **763 個測試通過**；咖啡 Profile 已完成真實取得 → WHV → Telegram，使用者確認收到且內容／連結正常。

滑雪場 Profile 的真實收集、篩選與零候選不發送已驗證，但本次有限樣本沒有符合條件的職缺，**尚未完成滑雪場真實職缺通知的正向驗收**。不能因此將完整 MVP 的兩個 Profile live 驗收全部勾選。

## 1. 本輪交付

- 新增 [24 個 HTTP 端到端測試](../tests/test_phase4_e2e.py)：真實 CLI、設定解析、Apify client、匹配／WHV、SQLite 與 Telegram client；只替換 HTTP 傳輸、時鐘與等待。
- 新增 `run`／`resume --notify-limit`（1～100，預設 20），本輪明確設 3；`deliver --limit` 也在參數解析階段驗證範圍。7 個候選的測試確認只發送 3 則，另 4 則保留 pending。
- 修正職缺正規化 ID：統一以受驗證 SEEK URL 的數字 ID 識別，避免 provider fallback ID 相同造成漏職缺，或同一 URL 不同 fallback ID 重複計數。
- 修正預算紀錄：以交易及 Decimal 保留歷次觀察費用的最高值，較低的後續回應不釋放既有預算。
- 新增 [Git Bash 驗收指南](acceptance-guide.md)，更新 [README](../README.md)、[通知恢復](notifications.md)與[架構文件](architecture.md)；保留 Phase 1／2／3 三張架構圖。

新增測試總計 52 個：24 個整條 HTTP 流程、19 個通知上限參數案例、9 個 ID／預算回歸案例。Phase 1–3 原有 711 個測試仍通過。

## 2. 離線檢查

使用本專案既有 Windows Python 3.12 venv，未新增依賴、重建環境或使用替代 Python。

| 檢查 | 結果 |
|---|---|
| `python -m pytest --tb=short` | 763 passed |
| `python -m ruff check .` | All checks passed |
| `python -m ruff format --check .` | 54 files already formatted（最終複驗） |
| `python -m mypy` | 16 個來源檔案通過 strict 型別檢查 |
| `python -m pip check` | No broken requirements found |

整合案例包含：兩份正式 YAML、啟動／輪詢／多頁下載、同 run 恢復不再 POST、明確新 run 不重送相同職缺、來源 401／403／啟動結果不明、遠端失敗與零筆成功區別、partial 恢復、429 跨命令冷卻、通知失敗／不明、重要更新及密鑰安全。

一般測試阻擋真實 socket，不讀真實 `.env`。測試用假密鑰比對 stdout、stderr、log 與資料庫均未洩漏。這些失敗／多頁案例是 mock 證據，不是假裝真實服務曾經發生。

另依文件實際執行免費 CLI 練習，使用 `data/phase4-verification-fixture`：咖啡 12 筆中符合 10、預覽 7 則；再次執行新增／重要更新均為 0、仍可預覽 7 則；滑雪場符合 2、預覽 2 則。三次均 `queued=0`，最後 outbox 為空，與未發送的預覽語意一致。

驗證的是既有 editable 安裝及 CLI，不包含 wheel／全新電腦重裝測試。此 venv 未安裝 setuptools／wheel／build，未為打包另行下載建置依賴。

## 3. 真實測試授權與界線

使用者本輪明確確認來源資料可用於蒐集、保存及通知，並同意最多 2 次新 Actor 啟動、每次 US$0.05、合計上限 US$0.10、每個 Profile 最多 3 則通知。這是使用者的來源許可確認，不代表本專案另行取得或獨立驗證法律授權文件。

- 實際新啟動 **2 次**；之後只 `resume` 已知 run，沒有第三次啟動。
- Actor `blackfalcondata/seek-scraper`，固定 build `0.4.57`；普通模式、NZ、details 開啟。
- 使用 `data/live-smoke-profiles/` 副本，僅把 `max_results` 改 3、`max_pages` 改 1；已程式比對其他設定與原檔一致。
- 沿用原 `data/runs.sqlite3`，不重設預算／去重，不改正式 `profiles/`、`.env` 或 Token 權限。
- 單次程序設定來源旗標為 true、每次 US$0.05、每日 US$0.10、timeout 120 秒；本地有效每日預設原為 US$0.50，本輪是降低，不是提高。
- `.env` 原本沒有來源許可旗標及費用欄位，本輪保持原樣。之後的 live 命令需依指南提供旗標，不能假定已永久啟用。

## 4. Live 結果

| 項目 | 咖啡服務 | 滑雪場 |
|---|---|---|
| Profile | `auckland-cafe-service` | `nz-ski-fields` |
| 本機 attempt ID |（已遮蔽） |（已遮蔽） |
| Apify run ID |（已遮蔽） |（已遮蔽） |
| Dataset ID |（已遮蔽） |（已遮蔽） |
| 本機啟動時間 UTC | 14:39:52 | 14:40:59 |
| 遠端／本機狀態 | SUCCEEDED／COMPLETE | SUCCEEDED／COMPLETE |
| 取得／完整讀取本次 dataset | 3／是 | 3／是 |
| Profile 符合／排除／待確認 | 2／1／0 | 0／3／0 |
| 無效／同批重複 | 0／0 | 0／0 |
| 符合者 WHV 綠／黃／紅 | 0／1／1 | 0／0／0 |
| 通知候選／實際發送 | 1／1 | 0／0 |
| 延後回讀 usageTotalUsd | US$0.016 | US$0.016 |
| 延後回讀計費 item 數 | 3 | 3 |

兩個 run 均回傳 `search_result_cap_possible`。完整讀完這 3 筆 dataset **不等於搜尋完整市場**；正式較大結果上限、本次未見職缺或市場覆蓋率都沒有因此通過驗收。

### 咖啡通知與重跑

- [Demi Chef & Kitchen Hand](https://nz.seek.com/job/94445727)，Sergeant Group，Auckland CBD, Auckland：黃色 `needs_confirmation`，聘期及非永久性證據不足，依原本綠／黃通知政策發送。
- [Cafe Assistant](https://nz.seek.com/job/94385433)，Atomic Coffee Roasters Ltd：符合 Profile，但文字含永久聘僱的硬性衝突，紅標且未通知。
- 另一筆未符合關鍵字，沒有通知。沒有放寬 Profile／WHV 規則以增加發送量。

Telegram 對第一筆回傳 message ID（已遮蔽）。本地 outbox ID（已遮蔽）、狀態 `sent`、發送嘗試 **1 次**；本機登記成功時間 `2026-09-23T14:41:20.316347+00:00`。

再次 `resume` 同 run、同版本並加 `--notify --notify-limit 3`，結果為 `deduplicated=1`、`queued=0`、`sent=0`、`remaining=0`；本機仍只有 1 筆 live outbox、1 次發送嘗試。沒有新增 Apify run。

使用者隨後明確回覆：「已收到，內容與連結正常」。因此咖啡情境同時具有 API 接受及人工收件證據，不只是一則純測試文字。

### 滑雪場零候選

這次上游回傳 tanker／hydro／crane operator 類工作，雇主為 SJ Allen Holdings／Smith Crane and Construction。3 筆均不符合設定的詞組及滑雪場雇主，正確排除。

對同 run 執行通知流程得到 `queued=0`、`sent=0`、`remaining=0`，沒有建立滑雪場 outbox。這驗證了不相干資料不發送，**沒有驗證滑雪場真實職缺訊息**，也不能推論 SEEK 目前完全沒有符合職缺。兩個 Profile 的正向通知路徑均另有 HTTP mock 證據。

### 費用

首次完成時各回報 US$0.010、計費 item 0；稍後同 run 回讀均更新為 US$0.016、3 items。截至本次最後 resume，合計回讀毛額 **US$0.032**，小於授權上限 US$0.10。

本機仍保留每次 US$0.05、共 US$0.10 的保守 UTC 日預算，不把差額當作本次追加啟動許可。這不是信用卡實際扣款、帳戶餘額或最終帳單；未擴權查帳務。此前 Phase 0 的費用不混入本輪合計。

## 5. 密鑰與資料保護

- `git check-ignore` 確認 `.env`、venv、smoke 副本與 SQLite 被忽略。
- 對 Git 可見檔案及本機 SQLite 以真實 Token／Chat ID 做只讀字串比對，未發現值；檢查本身只輸出是否命中。
- 實際執行輸出只保留安全摘要、短理由、職缺／run／通知識別碼，沒有另存原始 dataset、完整職缺正文或 Token。
- Git 未 stage／commit；既有工作檔保留。沒有設定排程、推送遠端、改全域 Git 信任或安裝新套件。

## 6. 剩餘驗收

- [x] 程式、離線端到端與品質檢查完成。
- [x] 兩個 Profile 的限額真實取得／列出／WHV／保存完成。
- [x] 咖啡職缺真實通知、人工收件與同 run 不重送完成。
- [x] 滑雪場零候選時不發送完成。
- [ ] 滑雪場取得至少一筆依既有規則可通知的真實職缺，完成通知與人工核對。

本輪授權的兩次啟動已用完，停在這裡，不追加費用、不改搜尋／分類條件來湊結果。若要補最後一項，需使用者另行決定下一輪搜尋的時間、樣本量與費用上限；這不是本次默認排程或額外開發工作。
