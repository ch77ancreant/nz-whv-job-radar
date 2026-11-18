# Phase 3 開發與驗證紀錄

日期：2026-09-23。範圍為 [Roadmap](../MVP_ROADMAP.md) 的 Telegram、職缺保存、通知去重與安全恢復，不含排程或其他資料來源。

## 結果與界線

**Phase 3 程式與離線驗證完成**，包含通知預覽及 mock 發送流程；本版使用合成資料和 HTTP mock 驗證，不等於已完成真實 Telegram 收件或整條 live MVP 驗收。

本次沒有讀取／修改使用者 `.env`、沒有啟動 Apify Actor、沒有真實 Telegram 發送或 Token 權限調整。沒有新增套件，使用既有 Python 3.12 venv。
一般測試由原本的 autouse fixture 阻擋真實 socket；Telegram client 測試注入 `httpx.MockTransport`，不使用真實 Token。

## 已交付

| 模組／介面 | 完成內容 |
|---|---|
| `store.py` | 同一 SQLite 附加職缺、重要版本、Profile 匹配、outbox、嘗試歷史及目的地冷卻，保留既有 runs |
| `messages.py` | 單則純文字通知、長度限制、必要欄位、理由／證據／問題、完整連結與免責 |
| `telegram.py` | 單次 HTTPS，嚴格確認成功、Chat／message ID；錯誤與 log 不帶 Token URL 或回覆正文 |
| `delivery.py` | 提交後才發送、最多三次的可確認安全重試、429 跨次冷卻、結果不明禁止自動重送 |
| `locking.py` | 同一 state 目錄的 Profile／目的地非阻塞程序鎖，作業系統釋放，檔案本身不刪除 |
| CLI／設定 | 預設保存不發送；`--dry-run`、live `--notify`、`outbox`、`deliver --send`、`resolve-notification` |
| 文件 | [操作與恢復](notifications.md)、[新增 Phase 3 架構圖](architecture.md)、README、規格及 Roadmap |

通知識別為模式＋canonical SEEK ID＋重要版本＋Chat 雜湊鍵，不含 Profile ID。
SQLite 保存最小快照、必要證據與內文 hash，不直接保存完整職缺正文、raw dataset 或 Bot Token。
fixture／live 分離；缺席不推測下架；沒有自動資料清理，保留期限須依來源授權另行確定。

## 實際離線檢查

| 檢查 | 結果 |
|---|---|
| `python -m pytest --tb=short` | **711 passed**，包含 Phase 1／2 回歸 |
| `python -m ruff check .` | 通過 |
| `python -m ruff format --check .` | 通過 |
| `python -m mypy src` | 16 個 source files，strict 型別檢查通過 |
| `git check-ignore` | `.env`、venv、驗證 SQLite 及 `data/locks` 類型路徑均被忽略 |
| 文件檢查 | 本機 Markdown 連結無失效；架構文件保留三個階段各一張 Mermaid |

實際 CLI 使用 `data/phase3-verification`，不改用戶原本的 `data/runs.sqlite3`：

```bash
python -m nz_job_radar run --profile auckland-cafe-service --fixture tests/fixtures/phase2/seek-synthetic.json --dry-run --state-dir data/phase3-verification --format json
python -m nz_job_radar run --profile auckland-cafe-service --fixture tests/fixtures/phase2/seek-synthetic.json --dry-run --state-dir data/phase3-verification --format json
python -m nz_job_radar run --profile nz-ski-fields --fixture tests/fixtures/phase2/seek-synthetic.json --dry-run --state-dir data/phase3-verification --format json
python -m nz_job_radar outbox --state-dir data/phase3-verification
```

| 實際執行 | 保存觀察 | 新職缺 | 重要更新 | 符合 Profile | 預覽訊息 | 新增待送 |
|---|---:|---:|---:|---:|---:|---:|
| 咖啡，首次 | 12 | 12 | 0 | 10 | 7 | 0 |
| 咖啡，原樣重跑 | 12 | 0 | 0 | 10 | 7 | 0 |
| 滑雪場，同一批樣本 | 12 | 0 | 0 | 2 | 2 | 0 |

四行皆 exit code 0；最後 outbox 為 `[]`。重複預覽不會誤標已送，所以第二次仍有七則預覽。每批保存所有有效職缺，Profile 是否匹配另記錄，不只保存綠標或通知候選。
另重跑滑雪場文字格式，確認兩則預覽的合成標示、WHV 理由、完整網址與免責文字可讀。
這三筆 run 為合成資料、費用 0，沒有可應徵的真實職缺。

## 關鍵回歸覆蓋

- 原有 Phase 1／2 測試保留；調整目前 CLI 的 Phase 3 狀態文字，不移除成本、來源閘門或 WHV 保護。
- 相同資料／跨 Profile／Actor ID 別名使用 canonical SEEK ID 去重；不同 Chat、模式與重要版本分開。
- 純空白／HTML／大小寫／刊登日期／觀察時間不新增版本，薪資或分類等重要內容改變才更新。
- 已確認送達版本不再排隊；未送出的 A → B → A 可恢復同一筆通知而不產生重複列。
- 同交易保存職缺、匹配及 outbox；製作訊息失敗會 rollback；兩個資料庫連線不能重複 claim 同一通知。
- 預覽可以重複，既有 pending／retryable 不消耗，沒有寫入 sent；fixture 禁止真實排隊。
- 明確成功、拒絕、錯誤 Chat、畸形成功、5xx、HTTP／Unicode 邊界、連線／讀寫 timeout 皆有 mock 測試。
- 429 的目的地冷卻跨重新開啟資料庫、其他職缺及人工 retry 保留，不能跳到同 Chat 的下一筆躲過等待。
- 最大自動嘗試次數跨命令保留；人工 retry 留歷史、明確重開有限額度，不繞過冷卻。
- 中斷／遺留 sending 保守轉結果不明；不偷取仍在進行的 claim，不自動重送未知結果。
- Profile 設定改變、非目前版本、規則查核過期、錯誤目的地都擋住發送。
- 新查核日期不單獨觸發新通知；符合條件的明確重新觀察可刷新未送訊息，不重置嘗試次數或退避。
- 明確失敗／結果不明的人工 sent、retry、skip 不直接發送；未知重試須額外風險旗標。
- 超長／特殊 Unicode 訊息仍保留來源與免責；輸出、例外及 request log 不暴露 synthetic Token。

## 尚待完成

1. [來源使用許可](source-access.md)仍待確認，相關旗標預設關閉；沒有用工程測試取代授權確認。
2. 本版尚未以真實 Apify 回傳資料，完成收集 → WHV → 保存 → Telegram 實際收件。Phase 0 的舊連通測試不取代此項。
3. Phase 4 的限額 live smoke 需由使用者在許可／費用確認後明確啟用；不可拿合成職缺發送成真實求職通知。
4. Telegram 已收到但本機回覆／保存失敗時，無法保證 exactly-once；`delivery_unknown` 是保守停送機制，不是送達證明。
5. 沒有跨裝置／不同 state 目錄的去重與費用協調；沒有排程、背景 worker、Web UI、其他來源或個人簽證資格保證。

API 契約參照 [Telegram sendMessage](https://core.telegram.org/bots/api#sendmessage)、[retry_after](https://core.telegram.org/bots/api#responseparameters)及[官方頻率說明](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this)，查核日為 2026-09-23；單次 transport 與較保守的錯誤分類是本專案選擇。
