# Phase 3：職缺保存、通知預覽與 Telegram 恢復

Phase 3 讓職缺與通知紀錄保留到下次執行。預設 `run` 只取得、初篩及保存職缺；明確加上 `--notify` 才會建立待送紀錄並嘗試 Telegram 發送。

整體資料流見 [Phase 3 架構圖](architecture.md#phase-3職缺保存通知佇列與可恢復發送)。本章說明操作與恢復，不代表真實來源或 Telegram 已完成 live 驗收。

## 1. 先分清楚四種操作

| 操作 | 保存職缺觀察 | 新增 outbox | 發送 Telegram | 呼叫 Apify |
|---|---|---|---|---|
| `run --fixture ...` | 是，標示 fixture | 否 | 否 | 否 |
| `run --live` | 是，標示 live | 否 | 否 | 是，可能計費 |
| `run ... --dry-run` | 是 | 否，既有 outbox 列也不修改 | 否 | 僅 `--live` 時會 |
| `run --live --notify` | 是 | 依候選與去重結果建立 | 嘗試發送 | 是，可能計費 |
| `deliver --send` | 不重新取得職缺 | 不重新產生通知 | 處理已保存的待送紀錄 | 否 |

`resume --live` 同樣支援 `--dry-run`／`--notify`，但讀取既有 Apify run，不另開付費 Actor。`--dry-run` 和 `--notify` 不能同時使用；fixture 禁止 `--notify`。

`dry-run` 不是整個資料庫的唯讀模式：它會更新職缺與 Profile 觀察，只是不排隊、不發送、不消耗既有待送紀錄。最新觀察仍可能影響舊通知之後是否符合發送條件。

普通 `run` 也不會新增通知；若觀察到新版本，原本尚未發送的舊版本可能標成 `superseded`，避免日後送出過時內容。

## 2. 先做免費離線預覽

以下在專案根目錄的 Git Bash 執行，使用獨立練習資料夾：

```bash
source venv/Scripts/activate
python -m nz_job_radar run \
  --profile auckland-cafe-service \
  --fixture tests/fixtures/phase2/seek-synthetic.json \
  --dry-run --state-dir data/phase3-demo
python -m nz_job_radar outbox --state-dir data/phase3-demo
```

這會顯示標記為「合成測試資料」的通知文字，保存合成職缺，但不讀 `.env`、不連線、不建立 outbox。全新的練習資料夾會看到空的 outbox。

預覽可加 `--chat-id 123456789`；這裡的數字只是本機去重範圍，不會真的送訊息。省略時使用 `preview` 預覽目的地，不套用任何真實 Chat 的送達紀錄。

fixture 與 live 的識別範圍分開。即使合成 ID、Chat ID 與真實資料相同，fixture 預覽也不會冒用真實通知的去重結果。

重複預覽仍可能列出同一則訊息，因為預覽從未把它排隊或標成已送達。對指定 live Chat，既有同版本 `pending`／`retryable` 也可列出預覽；尚在退避或目的地冷卻中則列為暫緩。已送、失敗或人工 skip 的同版本不重新列成待送。

## 3. 真實發送前提與指令

以下 live 範例只在來源使用許可已釐清、費用上限已確認，而且確定要傳送到所設定 Chat 時使用。旗標不會代替資料使用許可。

實際發送從 `.env` 或環境變數讀取 `TELEGRAM_BOT_TOKEN` 與數字 `TELEGRAM_CHAT_ID`；環境變數優先。還需 `SOURCE_ACCESS_CONFIRMED=true`。`run --live` 另需 Apify Token、費用與 timeout 設定，詳見 [來源接入說明](source-access.md)及 [README](../README.md)。

Bot 必須能在目的地發言。目的地只接受非零數字 ID，不接受 `@username`；正負號與前導零會正規化後用於去重。實際發送不接受用 `--chat-id` 覆蓋 `.env`，該參數只供 dry-run。

先取得與預覽，再由明確指令發送：

```bash
# 仍會取得 live 資料並可能產生 Apify 費用；不發 Telegram。
# 將數字換成實際 Chat ID，才會套用該目的地的本機去重紀錄。
python -m nz_job_radar run --profile auckland-cafe-service \
  --live --dry-run --chat-id 123456789

# 讀取同一個 run，保存、建立候選待送紀錄並最多處理 3 則通知。
python -m nz_job_radar resume --profile auckland-cafe-service \
  --run-id '實際RUN_ID' --live --notify --notify-limit 3
```

將 `實際RUN_ID` 換成第一行回傳的 run ID。預覽不建立待送紀錄；第二行以 `resume` 讀取同一份結果，不另開付費 Actor，仍須通過原 Profile／run 驗證。要重新搜尋新職缺時才使用新的 `run --live`，並重新承擔該次抓取費用。

Phase 4 新增 `run`／`resume` 的 `--notify-limit`，有效範圍 1～100、預設 20。它限制這次命令處理的通知筆數；若仍有待送，保留於 outbox 並回傳 exit code 2。它不是跨命令的累積發送額度。

`--notify` 先驗證 Telegram 與 Apify 設定，再啟動可能計費的工作，避免抓完才發現缺少通知設定。

已經建立 outbox 後，可只處理通知，不再取得職缺：

```bash
python -m nz_job_radar outbox
python -m nz_job_radar deliver --send
python -m nz_job_radar deliver --send --outbox-id '實際OUTBOX_ID' --limit 1
```

`deliver` 預設最多處理 20 筆，`--limit` 可設 1～100。它不讀取 Apify dataset、不啟動 Actor，也不需要 Apify Token；仍會檢查來源許可旗標、Telegram 設定與目前的 Profiles。

同一實際目的地應持續使用同一個 `--state-dir`。不同資料夾有不同的去重、冷卻與程序鎖紀錄，不能互相防止重送。

## 4. 保存什麼，以及如何判斷「已通知過」

預設共用 `data/runs.sqlite3`。原本 `journal.py` 的 `runs` 保存執行摘要；新增 `store.py` 保存職缺觀察、重要版本、Profile 匹配、outbox 與嘗試紀錄。

| 資料 | 用途 |
|---|---|
| canonical SEEK ID | 從受驗證的 SEEK 職缺網址取出數字 ID；不同 Actor ID 不會把同一網址拆成兩份職缺 |
| 重要版本 hash | 比較有意義的職缺內容與分類，決定是不是更新 |
| destination key | 將正規化 Chat ID 加上 Telegram 範圍後計算 hash，用來區分通知目的地 |
| Profile 匹配與 fingerprint | 記錄這筆版本為何符合搜尋／通知設定，並供發送前核對 |
| `Notice`／`NotificationPlan` | 準備好的訊息，以及保存、更新、排隊、去重與暫緩數量 |
| outbox 與 attempt history | 已提交的待送文字、狀態、次數、下次可嘗試時間及已確認的 message ID |

去重範圍是 **模式＋SEEK ID＋重要版本＋目的地**。同一職缺跨 Profile 命中可保存多個匹配，卻不會為同一目的地再建立同版本通知。`sent` 表示已確認 Telegram API 接受，不代表使用者已閱讀。

重要版本包含職稱、雇主、地點、國別、聘僱類型、薪資、正規化內文，以及 WHV 標籤、聘期結果／起訖日、規則版本與過期狀態。純 HTML／空白／大小寫整理、刊登日、廣告截止日、觀察時間或單純查核日期字串改變，不會單獨造成重送。規則更新若真的改變分類或規則版本，則可能形成新版本。

資料庫保存不含完整內文的職缺快照、必要證據／評估、內文 hash 和已產生的通知文字。完整職缺內文只在本次處理中參與判斷與 hash，不直接存入職缺快照；不保存原始 provider payload、Bot Token 或原始 Chat ID。目的地 hash 是去重鍵，不是加密憑證保管。

不因這次搜尋沒有找到某筆職缺，就推測它已下架或刪除舊紀錄。本版也不提供自動清理或完整歷史瀏覽介面。

## 5. 為什麼先保存，再送 Telegram？

`JobStore.record()` 用同一個 SQLite 交易保存職缺／版本／匹配及可選的 outbox，交易提交後才允許發送。

發送器先重新檢查目前版本、最新可通知的 Profile、設定 fingerprint、規則查核日期、目的地與冷卻時間；符合後才用 `claim()` 把狀態改成 `sending`、增加嘗試次數並提交。接著才呼叫 Telegram，最後保存已確認結果。

outbox 的文字與查核日期是保存當時的快照，不會在 `deliver` 時依新設定重寫。Profile 被停用、設定 fingerprint 改變、職缺版本已過時或規則超過 90 天未查核時，舊訊息會暫緩。先重新觀察與預覽；沒有 `force` 參數可繞過檢查。

有一個明確的更新途徑：再次使用 `--notify` 取得仍符合資格的同一重要版本，且規則查核日期確實較新時，可刷新現有 `pending`／`retryable` 訊息的文字與查核日期，不新增重複通知，也不重置嘗試次數、退避或冷卻。dry-run 可顯示預計刷新的文字，但不修改 outbox；已送、失敗、結果不明或人工 skip 的紀錄不因此自動恢復。

## 6. 狀態、有限重試與冷卻

| 狀態 | 意思與後續 |
|---|---|
| `pending` | 已保存，尚未取得發送權 |
| `sending` | 已取得本次發送權；不能據此斷言遠端已收到 |
| `retryable` | 確定可重試，但須等待保存的期限並保留次數上限 |
| `sent` | 回覆含有效 message ID，且 Chat ID 與目的地一致 |
| `failed` | 明確拒絕或自動嘗試次數已用完；先修正原因再人工決定 |
| `delivery_unknown` | 可能已送達，禁止自動重送，需人工核對 |
| `superseded` | 尚未送出的舊版本已被新觀察取代 |
| `dismissed` | 人工選擇 skip，紀錄保留 |

每筆通知自動最多嘗試 3 次，次數存入 SQLite，重新執行 `deliver` 不會重置。明確尚未送出的連線失敗，發送器短暫等待 1／2 秒再試；HTTP client 每次 `send()` 只送一次，不在內部重試。

確認為 Telegram 429 且帶有效 `retry_after` 時，保存該目的地的冷卻期限並結束當批，之後手動執行 `deliver` 才會再檢查。冷卻適用同一 Chat 的其他待送列，也跨程序重啟保留；不長時間 sleep、不把過長或格式錯誤的值縮短後提早重送。

發送器另採同目的地程序鎖與短間隔：正數 Chat ID 約 1.1 秒、負數 Chat ID 約 3.1 秒。這是本機保守節流，不是 Telegram 保證的可用額度；伺服器回覆的冷卻仍優先。

Read／Write timeout、協定錯誤、5xx、格式錯誤的成功回覆或缺乏可靠資訊的 429 都可能發生在送出之後，因此記為 `delivery_unknown`。當次發送批次會停止；同職缺、同目的地的其他版本也暫緩，直到原結果處理完。

發送中斷後，`deliver` 或人工處理前會檢查遺留的 `sending`；到期的紀錄（預設約 300 秒）轉成 `delivery_unknown`，不直接回到待送。如果 Telegram 已收到，但本機保存 `sent` 失敗，也沿用這個保守恢復方式，不再盲目呼叫 HTTP。

## 7. 人工處理失敗或結果不明

先執行 `outbox`，取得正確 `id`、狀態、錯誤碼及嘗試歷史，再到 Telegram 核對。`outbox` 是讀取清單，不發訊息。

以下將 placeholder 換成實際 ID；`resolve-notification` 只更新本機決定，本身不會送 Telegram。只有 `failed`／`delivery_unknown` 可使用這些處理方式。

```bash
# 已核對確實送達：填入該則真實訊息的正整數 message ID，不可猜填。
python -m nz_job_radar resolve-notification \
  --id '實際OUTBOX_ID' --action sent --message-id 123

# 決定放棄這一則通知，但保留紀錄。
python -m nz_job_radar resolve-notification --id '實際OUTBOX_ID' --action skip

# failed：修正原因後重新開啟有限嘗試預算。
python -m nz_job_radar resolve-notification --id '實際OUTBOX_ID' --action retry

# delivery_unknown：即使人工核對，也仍可能重複；必須明確認知後才選擇 retry。
python -m nz_job_radar resolve-notification \
  --id '實際OUTBOX_ID' --action retry --acknowledge-duplicate-risk

# retry 只改成 pending；仍需另行明確發送。
python -m nz_job_radar deliver --send --outbox-id '實際OUTBOX_ID' --limit 1
```

人工 retry 會另開一組有限嘗試預算並保留舊歷史；不會繞過目的地冷卻、目前 Profile／版本／規則檢查。這套流程降低重複風險，但不宣稱端到端 exactly-once。

## 8. 常見結果怎麼讀

| 英文狀態／錯誤碼 | 處理方向 |
|---|---|
| `connection_unavailable` | 尚未連上；依已保存的次數與期限有限重試 |
| `rate_limited` | 等待目的地冷卻期限，之後再執行 `deliver` |
| `access_denied` | 檢查 Token、Chat 與 Bot 發言權限，勿在終端貼出 Token |
| `request_rejected` | API 已明確拒絕；確認目的地與訊息設定 |
| `chat_migration_required` | 目的 Chat 需人工確認更新，不自動跟隨移轉 ID |
| `invalid_response`／`delivery_unknown`／`stale_sending` | 先核對 Telegram 與 outbox，不自行認定未送達 |
| `skipped` 增加 | 當前設定或規則檢查未通過；保留原紀錄，重新觀察／預覽 |
| `remaining` 大於 0 | 選定範圍仍有待送、失敗或未知結果，不是全部完成 |

一般完成回傳 exit code `0`；資料不完整、設定錯誤或選定發送範圍仍有未完成紀錄時回傳 `2`；人工中斷為 `130`。在 Git Bash 可於上一行命令結束後用 `echo $?` 查看。

Telegram 通知是一則 plain text，沒有 Markdown／HTML parse mode，關閉連結預覽。文字包含職缺、WHV 標籤、理由、確認問題、少量證據、來源連結、規則查核日期及免責說明；按 UTF-16 單位保守限制為 4096，清除控制字元，完整連結不被長職稱截掉。完整內文不整份貼到訊息。

錯誤採本機固定文字，不輸出 provider 回覆正文、Token 或帶 Token 的請求 URL；client 直接使用 HTTP transport，避免 HTTPX Client 的 INFO request log 帶出 Token 路徑。

## 官方 API 參考

- [sendMessage](https://core.telegram.org/bots/api#sendmessage)：本程式使用文字訊息 API，成功後確認回傳的訊息識別碼與目的 Chat。
- [ResponseParameters](https://core.telegram.org/bots/api#responseparameters)：限流時的 `retry_after` 是重新嘗試前需等待的秒數；目的地移轉由使用者人工確認。
- [Bots FAQ：傳送頻率](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this)：同一 Chat 與群組有傳送速率考量，本機節流仍須服從伺服器回覆。

離線驗證涵蓋 mock HTTP、交易／去重／恢復、CLI 與訊息長度。Phase 4 使用者已確認來源許可並完成限額測試：咖啡通知已人工核對，滑雪場缺少符合條件的真實通知樣本；詳見 [驗證紀錄](phase4-verification.md)。未來執行仍須確認當時的來源許可與費用範圍。
