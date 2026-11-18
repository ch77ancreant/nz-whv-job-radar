# Phase 4 離線端到端驗證

測試位於 [`tests/test_phase4_e2e.py`](../../test_phase4_e2e.py)，沿用 [Phase 2 的 12 筆合成職缺](../phase2/README.md)，不複製 JSON，也不使用真實職缺或憑證。

測試執行真實 CLI、設定解析、`collect_live()`、Apify HTTP client、正規化與 Profile／WHV 判斷、SQLite／outbox，以及 Telegram HTTP client。只在 HTTP 傳輸邊界使用 `httpx.MockTransport`；不以假 `collect_live()` 或假 `send()` 取代中間流程。

- 假設定檔只建立在 pytest 暫存目錄，設定解析停用工作站環境變數覆寫，不讀專案 `.env`。
- 時間固定從 `2026-09-23` 開始，等待只推進測試時鐘；既有 `conftest.py` 禁止實際 socket 連線。
- 驗證兩個實際 YAML Profile 的 Actor 請求、run／dataset 分頁、結果分類、交易後發送、resume 不再啟動與相同版本不重送。
- 涵蓋來源拒絕、啟動結果不明、遠端失敗、本機停止等待、成功零筆、部分資料恢復、Telegram 429 冷卻、發送結果不明、明確失敗與重要內容更新。
- 每個情境都檢查 stdout、stderr、API log 與 SQLite 中沒有假 Token 或原始 Chat ID；HTTP 失敗回應刻意夾帶假 Token，以驗證錯誤清理。
- `--notify-limit 3` 情境核對最多只有 3 個 Telegram HTTP POST，其餘符合條件的通知維持待送。

這些是完全離線的模擬端到端測試，不代表來源使用許可、真實 Apify 執行或 Telegram 實際送達已驗收。真實來源測試另由明確批准的受限流程執行與記錄。
