# NZ WHV Job Radar

SEEK-only 求職工具：YAML Profile → Apify／SEEK → 正規化／匹配 → WHV 初篩 → 保存／列表 → 明確啟用 Telegram 通知。
WHV 提供可解釋的保守標籤，不保證簽證資格。預設只保存與列出，不發送；必須加 `--notify` 才會排隊並嘗試發送。
Phase 4 開發、文件及 763 個離線測試完成。咖啡 Profile 已通過真實職缺通知與人工收件；滑雪場本次 3 筆均被排除，尚缺真實職缺通知的正向樣本。詳見 [Phase 4 驗證紀錄](docs/phase4-verification.md)，不把有限測試當完整市場覆蓋。

## 安裝（Windows Git Bash）

在專案資料夾執行；既有 `.env` 與 `venv` 不要覆蓋：

```bash
source venv/Scripts/activate
python --version
python -m pip install -e ".[dev]"
```

若還沒有 venv，先執行 `python -m venv venv`。需 Python 3.12 以上。

## 免費離線練習

```bash
python -m nz_job_radar profiles
python -m nz_job_radar run --profile auckland-cafe-service --fixture tests/fixtures/phase1/seek-synthetic.json --show-excluded
python -m nz_job_radar run --profile nz-ski-fields --fixture tests/fixtures/phase1/seek-synthetic.json --show-excluded
python -m nz_job_radar runs
```

Fixture 模式不讀 `.env`、不呼叫網路、不發送 Telegram。樣本完全合成，不代表真實職缺；不要將示例 SEEK 連結當作應徵機會。

咖啡範例：8 筆 → 符合 2、排除 6。滑雪場範例：8 筆 → 符合 2、排除 5、雇主待確認 1。
加入 `--format json` 可取得結構化輸出；`--show-excluded` 可查看排除與 Profile 待確認項目。
`runs` 以 JSON 顯示最近 30 筆本機執行紀錄與統計，不列帳號內其他 Apify runs。

### Phase 2：查看 WHV 分類與證據

原本四行仍可用，現在多出 WHV 結果。下列新樣本刻意涵蓋永久工作、超期、工作權衝突、日期邊界與資訊不足：

```bash
python -m nz_job_radar run --profile auckland-cafe-service --fixture tests/fixtures/phase2/seek-synthetic.json
python -m nz_job_radar run --profile nz-ski-fields --fixture tests/fixtures/phase2/seek-synthetic.json --format json
```

輸出包含 `likely_suitable`／`needs_confirmation`／`likely_incompatible`、規則分數、證據信心、原文片段、聘期與待確認事項。
紅標仍顯示；`--show-excluded` 另外顯示 Profile 排除與待確認者。
`notification_policy` 只統計符合 Profile 及通知標籤設定的候選，不是待送／已送數。實際儲存、排隊、去重及發送結果另見 `notifications`。
規則超過 90 天未查核時顯示警告並保守停止給綠標。詳細邊界見 [WHV 規則說明](docs/whv-rules.md)。

### Phase 3：免費預覽通知、重跑與保存

已安裝 Phase 1 開發套件者不需再安裝依賴。在 Git Bash 執行：

```bash
python -m nz_job_radar run --profile auckland-cafe-service --fixture tests/fixtures/phase2/seek-synthetic.json --dry-run --state-dir data/practice
python -m nz_job_radar run --profile auckland-cafe-service --fixture tests/fixtures/phase2/seek-synthetic.json --dry-run --state-dir data/practice
python -m nz_job_radar run --profile nz-ski-fields --fixture tests/fixtures/phase2/seek-synthetic.json --dry-run --state-dir data/practice
python -m nz_job_radar outbox --state-dir data/practice
```

預期咖啡每次預覽 7 則、滑雪場 2 則；咖啡第二次的新職缺／重要更新為 0，但仍可預覽，因為預覽沒有標記已送。最後 outbox 為空清單。

- `--dry-run` 保存本次職缺觀察，但不建立、消耗或標記任何通知紀錄；不是完全不寫資料庫。
- 不提供 Chat ID 時使用獨立預覽目的地；可加 `--chat-id 123456789` 指定數字目的地，檢查同模式本機紀錄。這不會讀 `.env` 或送出訊息。
- fixture 與 live 的資料分開識別；合成職缺不會污染真實通知去重。`--fixture --notify` 會直接拒絕。
- 實際成功送達後，相同 SEEK ID＋重要版本＋Chat 跨次及跨 Profile 不再重送；只變抓取／刊登日期或排版不算重要更新。

詳細狀態與恢復方法見 [通知、去重與安全恢復](docs/notifications.md)。

## 修改 Profile

編輯 `profiles/auckland-cafe-service.yaml` 或 `profiles/nz-ski-fields.yaml`，也可複製並換成唯一 `id`。
每個 YAML 檔放一個 Profile，範例內的欄位都要保留；未知欄位、重複 key、錯誤型別會阻止執行。

| 設定 | 目前行為 |
|---|---|
| `enabled`、`country` | 只有啟用且 `NZ` 的 Profile 可執行 |
| `locations` | 非空清單；地點命中任一設定，才視為符合地區 |
| `keywords` | 非空清單；職稱或正文命中任一詞組 |
| `exclude_title` | 只排除職稱，不排除正文的咖啡訓練描述；可空清單 |
| `employers` | 有設定時，雇主必須符合；缺雇主為待確認，已知不符則排除；可空清單 |
| `max_results`、`max_pages` | 上游搜尋上限，各為 1–5000、1–100，不保證完整市場覆蓋 |
| `notification_labels` | 三種 WHV 標籤的清單，影響候選、預覽與明確啟用時的排隊，不影響職缺是否列出；可空清單 |

本地匹配忽略大小寫、重音與標點，採詞組邊界及有限的英文 `s` 複數處理，不做任意子字串比對。
關鍵字／地點送上游搜尋，再用相同設定在本地複核；不宣稱完全重現 SEEK 的搜尋語義。
地點、國別或受限制的雇主缺失時列 `needs_profile_confirmation`，不是 WHV 黃標。
滑雪場採明確品牌／場地名稱，不用大型旅遊母公司名稱涵蓋其所有工作；可自行增補真實刊登別名。

## Live：只在來源使用許可確認後

既有 `.env` 不需重建，也不要用 `.env.example` 覆蓋已填的 key。後者只提供欄位參考。
許可未確認時保留 `SOURCE_ACCESS_CONFIRMED=false`；這個旗標只是使用者確認，不會取得來源授權。

```dotenv
APIFY_API_TOKEN=你的既有Token
SOURCE_ACCESS_CONFIRMED=false
APIFY_MAX_CHARGE_USD=0.05
APIFY_DAILY_BUDGET_USD=0.50
APIFY_TIMEOUT_SECONDS=120
```

Telegram 的既有設定只在 `--notify` 或 `deliver --send` 使用，預覽不需要；系統環境變數優先於 `.env`。
取得來源許可並明確將旗標改為 `true` 後，以下命令才會啟動可能計費的抓取：

```bash
python -m nz_job_radar run --profile auckland-cafe-service --live
```

取得來源許可後，可先預覽，再使用同一個 run 明確發送。`run --live` **每次都可能產生 Apify 費用**；`--dry-run` 只禁止 Telegram，不禁止付費抓取：

```bash
python -m nz_job_radar run --profile auckland-cafe-service --live --dry-run --chat-id YOUR_NUMERIC_CHAT_ID
python -m nz_job_radar resume --profile auckland-cafe-service --run-id YOUR_RUN_ID --live --notify --notify-limit 3
```

`YOUR_NUMERIC_CHAT_ID` 要換成實際數字（群組通常為負數）；實際發送則從 `.env` 讀 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`，不能用預覽參數改收件人。
`YOUR_RUN_ID` 要換成上一行回傳的 run ID；兩行使用同一份 Profile 與資料庫。
不要為了發送同一份結果再啟動新 run：已有 run ID 時，改用 `resume --live --run-id ... --profile ... --notify`，只讀既有 dataset。

固定 Actor `blackfalcondata/seek-scraper`（ID `5BAoYcBhwvPuMtd0K`）、build `0.4.57`，使用普通模式 `incrementalMode=false`。
關鍵字與多地點依已確認 schema 編碼，不使用 Actor 的持久增量狀態。
若供應商版本／schema 改變，應先另行查核；不要以擴大 Token 權限解決所有錯誤。

### 費用與上限

- 啟動前，以 SQLite 交易預留整筆每次上限；UTC 同一天所有 Profile 共用本地每日預算。
- 成功、失敗、明確拒絕或啟動結果不明，都不自動釋出當天預留額。計入預留額與歷次已觀察費用的較高者；後續回應較低也不回收額度。
- 這是保守的本機防呆，不是帳戶餘額或全帳戶消費控制；其他電腦、其他 state 目錄及手動 Console 執行不在統計內。不要刪除資料庫來繞過限制。
- 回讀 `usageTotalUsd` 與已回傳的計費筆數；尚未回傳就顯示未知，不假裝免費。費用可能延後更新，並非最終帳單或信用卡扣款。
- `maxResults`／`maxPages`／費用上限可能讓搜尋不完整；完整讀完某次 dataset，也不等於完整抓完市場。頁數是否截斷無法獨立確認，不推測職缺已下架。
- 即使本地排除或同批去重，上游已輸出的資料仍可能計費。普通模式重跑不等於只對新增資料付費。

### 斷線與恢復

程式先顯示本機 `attempt ID`，收到啟動回應後立即顯示並保存 `run ID`。
POST 啟動不自動重試；讀取 GET 才做有限重試。`--wait-seconds` 預設 180，僅限制本機輪詢等待，正在進行的 HTTP 請求／重試可能多花一些時間。
停止本機等待或按 Ctrl+C 不會取消遠端 run；遠端仍受啟動時的 timeout／費用設定限制。

已知 run 恢復（只讀既有 run，不重新啟動 Actor）：

```bash
python -m nz_job_radar runs
python -m nz_job_radar resume --profile auckland-cafe-service --run-id YOUR_RUN_ID --live
```

恢復時需使用同一份 Profile 設定與本機資料庫。若是 `START_UNKNOWN` 或尚未記下 run ID 的 `STARTING`，
先去 Apify Console 核對是否已啟動，確認對應的 run ID 後才能手動連結：

```bash
python -m nz_job_radar resume --profile auckland-cafe-service --run-id VERIFIED_RUN_ID --attempt-id LOCAL_ATTEMPT_ID --live
```

找不到對應 run 時先人工釐清，不盲目重跑。未完成／結果不明的同一 Profile 會擋住新啟動。
Dataset 下載中斷時，可先看到已完整收到的頁面與 partial 警告；resume 從第一頁重新讀取並計算，不把半份資料當完整成功。

### Telegram 待送與恢復

`--notify` 只處理這次 Profile 的通知候選，預設單次最多處理 20 筆；可用 `--notify-limit 3` 限為 3 筆（有效範圍 1～100）。未完成的留在本地 outbox，exit code 2。這是單次命令上限，不是多次命令的累積額度。
先檢查，再決定是否發送既有待送訊息；`deliver` 不呼叫 Apify：

```bash
python -m nz_job_radar outbox
python -m nz_job_radar deliver --send
```

可用 `deliver --send --outbox-id ID` 限定一筆，或 `--limit 1` 限制本次處理筆數。仍須有效 Telegram 設定與來源許可確認。
已送達、明確失敗或 `delivery_unknown` 不會被此命令自動重送。有限重試耗盡／設定錯誤會保留為 `failed`；結果不明必須先到 Telegram 核對。

修正問題後，`resolve-notification --id ID --action retry` 可為明確失敗重新開啟有限重試額度，**本命令本身不發送**。
若狀態是 `delivery_unknown`，重試還須 `--acknowledge-duplicate-risk`；不要在尚未核對時使用。
人工確認已收到可用 `--action sent --message-id MESSAGE_ID`；決定放棄可用 `--action skip`。完整範例見[安全恢復文件](docs/notifications.md)。

## 儲存與錯誤

本地 `data/runs.sqlite3` 保留原有 run／成本紀錄，Phase 3 以附加資料表保存職缺最新欄位、重要版本、Profile 匹配、WHV 理由／必要證據及 outbox／發送紀錄。舊 run 摘要不回填，也不刪除。
不保存 raw dataset 或完整正文；正文只用於正規化 hash 與必要短證據。目的 Chat 保存雜湊鍵、不保存 Bot Token；實際目的地只在明確發送時由設定提供。
目前沒有自動資料清理；保留期限須依來源授權決定。刪除本機歷史會失去預算及已送去重依據，不能當作一般重試方式。
SQLite 檔及其 WAL、`.env`、venv 與快取已列入 `.gitignore`。`--state-dir` 可選測試資料夾，但應固定使用同一目錄管理 live 預算。
`data/locks` 的小型 lock 檔由作業系統管理同 Profile／同目的地並行；檔案留著不代表仍鎖定，不需手動刪除。
JSON 輸出只含白名單職缺欄位，正文的聯絡資訊採 best-effort 遮蔽；不保證能識別所有自由文字個資。
刊登有效期不是聘期。沒有從這次搜尋結果出現，不會推定職缺關閉。

| 情況 | 行為 |
|---|---|
| 確認成功且 dataset 為 0 筆 | 成功摘要，exit code 0 |
| 有資料但全部被 Profile 排除 | 顯示原因統計，exit code 0 |
| Dataset 下載失敗／缺失、無效項目 | 顯示 partial／錯誤或無效數，exit code 2 |
| Actor 失敗、權限不足、啟動結果不明 | 清楚報錯，exit code 2；不當成零筆結果 |
| 要求通知但仍有待送、失敗、結果不明或安全條件未通過 | 保留職缺與通知狀態，exit code 2；先查 outbox |
| Ctrl+C | exit code 130；保留已寫入的執行紀錄 |

即使 exit code 0，也不代表搜尋完整或保證 WHV 資格；沒有要求通知時更不代表已送。完全免費練習請用 `--fixture --dry-run`。
WHV 紅標／黃標是正常的分類結果，不是程式執行失敗，因此不會單憑標籤改成非零 exit code。

## 測試

```bash
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy
```

一般測試阻擋真實 socket 連線，只使用 fixture 和 HTTP mock，不會啟動付費 Actor。
Phase 4 加上只替換 HTTP 傳輸層的整條 CLI 測試，保留真實設定解析、來源 client、篩選、SQLite 與通知 client。
完整操作順序與驗收界線見 [Phase 4 驗收指南](docs/acceptance-guide.md)。

## 規格與參考

- [程式架構與資料流（Phase 1／2／3 圖及 Phase 4 驗證流程）](docs/architecture.md)
- [Phase 4 驗收指南](docs/acceptance-guide.md)
- [Phase 4 實際結果與剩餘驗收](docs/phase4-verification.md)
- [通知、去重與安全恢復](docs/notifications.md)
- [WHV 規則、證據與限制](docs/whv-rules.md)
- [目前 MVP 規格](NZ_WORKING_HOLIDAY_JOB_RADAR_SPEC.md)
- [Roadmap](MVP_ROADMAP.md)
- [SEEK 接入限制](docs/source-access.md)
- [17 個滑雪場官方入口](docs/ski-resort-directory.md)

本輪使用者已確認來源許可並授權限額 live 測試；`.env` 保持原樣，未永久啟用許可旗標。後續操作依[驗收指南](docs/acceptance-guide.md)，本次的 2 次啟動額度不代表可自動追加或定時執行。
