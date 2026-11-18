# Phase 1 開發與驗證紀錄

日期：2026-09-23。範圍依 [SEEK-only Roadmap](../MVP_ROADMAP.md)，不含 Phase 2–4。

## 結果

Phase 1 程式與離線流程完成；**未執行本版真實 Apify 抓取，不宣稱 live 驗收完成**。
這次沒有啟動付費 Actor、沒有呼叫 Telegram，沒有修改既有 `.env` 或擴大 Token 權限。
安裝依賴使用既有 Python 3.12 venv。操作方式見 [README](../README.md)。

## 已交付

| 部分 | 內容 |
|---|---|
| 專案入口 | `pyproject.toml`、`python -m nz_job_radar`、`nz-job-radar`、無密鑰 `.env.example` |
| Profile | 嚴格 YAML 欄位／型別／唯一 ID 檢查；咖啡、滑雪場兩個範例 |
| Apify | 固定已調查 Actor/build、普通模式、費用／timeout 限制、輪詢、分頁與已知 run 恢復 |
| 安全重試 | 啟動 POST 不重試；GET 有限重試，尊重 bounded Retry-After；啟動不明先人工核對 |
| 資料處理 | 白名單欄位、SEEK URL／ID 正規化、同批去重、正文清理與聯絡資訊 best-effort 遮蔽 |
| 本地匹配 | 地點、關鍵字、職稱排除、雇主限制；未知資訊不自動當符合 |
| 結果 | 終端列表／JSON、排除原因、待確認、無效項目、部分結果、搜尋上限與費用狀態 |
| 執行紀錄 | SQLite 保存 run／dataset／狀態／成本／統計；原子預留每日預算，同 Profile 未解決時擋住新 run |

執行紀錄提前使用 SQLite 是恢復讀取與費用控制所需，不代表已完成 Phase 3 的職缺資料庫／通知 outbox。

## 實際執行的離線檢查

| 命令 | 結果 |
|---|---|
| `python -m pytest` | **264 passed** |
| `python -m ruff check .` | 通過 |
| `python -m ruff format --check .` | 當時 26 個檔案格式通過（包含 Markdown 程式碼區塊） |
| `python -m mypy` | 9 個 source files，strict 型別檢查通過 |
| `git check-ignore` | `.env`、`venv/Scripts/python.exe`、`data/runs.sqlite3` 均被忽略 |

一般 pytest 透過 autouse fixture 阻擋真實 socket 連線；使用合成資料、暫存 SQLite 與 `httpx.MockTransport`。
「mock live」是測試 API 契約及控制流程，不等於外部服務驗證。

另以實際 CLI、預設本地 `data/runs.sqlite3` 執行兩個 fixture 命令，均 exit code 0：

| Profile | 取得 | 符合 | 排除 | Profile 待確認 | 無效 |
|---|---:|---:|---:|---:|---:|
| `auckland-cafe-service` | 8 | 2 | 6 | 0 | 0 |
| `nz-ski-fields` | 8 | 2 | 5 | 1 | 0 |

兩筆 fixture 紀錄留在本機，費用為 0，不進 Git。全部職缺是[合成測試資料](../tests/fixtures/phase1/README.md)，不是可應徵的真實刊登。

## 重要測試與修正

- Profile 缺欄位、未知欄位、重複 key／ID、錯誤型別、不合理上限與停用狀態。
- 標題 barista 排除；正文咖啡訓練不誤排；Wānaka 重音、詞組邊界、雇主缺失與不相關租車雇主。
- 刊登有效日不當聘期；電話遮蔽保留 ISO／斜線日期範圍及薪資範圍，相鄰電話仍遮蔽。
- POST 成功不代表 run 成功；401／403、429、5xx、timeout、redirect、畸形回應與 unknown start。
- 多頁 dataset、缺 total header、offset／total 不一致、空頁、部分下載與缺 dataset。
- 真正成功零筆與 Actor 失敗分開；resume 只 GET，不再次 POST；更改 Profile／錯誤 run 綁定被拒絕。
- 每日跨 Profile 預算、同 Profile 重疊阻擋、失敗或啟動不明不釋出預留、fixture 不花 live 預算。
- 成功恢復清除舊錯誤；partial 保存當前錯誤與統計；run ID 在本機紀錄寫入失敗前先輸出供恢復。
- `.env` 設定優先序、live 許可閘門、無效金額／timeout；離線 CLI 不讀 `.env` 或建立 API client。

## 未驗證與限制

1. 來源資料使用許可仍待確認，見 [Phase 0 調查](source-access.md)。旗標不取代實際授權。
2. 本版真實 Actor/build、目前服務回應與最終費用，未經 live smoke 複驗。Phase 0 的既有連通證據不能代替新程式驗收。
3. 結果／頁數／費用上限可能造成搜尋不完整；下載完整 dataset 不是完整市場覆蓋。不推測下架，不保證每個滑雪場都有 SEEK 結果。
4. 本地預算只涵蓋同一資料庫、按啟動日 UTC 計算的 run 預留與已回讀費用；不代表帳戶餘額、跨裝置消費控制或最終帳單保證。
5. 目前只保存執行摘要；沒有跨次職缺差異比較、WHV 判斷、Telegram、通知 dry-run、排程或 Web UI。
6. 文字匹配與聯絡資訊遮蔽是保守規則，不保證自然語言理解或個資辨識完全正確。

下一階段是 Phase 2 WHV filter。是否進行 live smoke 需先解除來源許可缺口，再明確設定費用上限執行。
