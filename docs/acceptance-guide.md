# Phase 4：離線驗證與限額 live 驗收

這份指南說明如何取得驗收證據，不預先宣告測試或完整 MVP 已通過。實際結果、run ID、費用、通知 message ID 與未完成項目，見 [Phase 4 驗證紀錄](phase4-verification.md)。

## 1. 先分清楚四種證據

| 層級 | 能確認什麼 | 不能單憑它宣稱什麼 |
|---|---|---|
| 離線 fixture | 設定、解析、匹配、WHV、保存、預覽與去重流程 | 真實 SEEK 結果或 Telegram 連通 |
| 完整 HTTP mock | 可控制的成功／失敗、分頁、恢復、429、結果不明等分支 | 現在外部服務一定正常 |
| 限額 live smoke | 這次真實 run 的有限資料是否通過流程；API 是否接受通知 | 全市場覆蓋、長期穩定、使用者已閱讀 |
| 人工收件核對 | 指定 Chat 是否真的看到對應職缺訊息，內容是否可理解 | 所有職缺與個人簽證條件均適用 |

`sendMessage` 回覆與本機 `sent` 紀錄是 API 接受證據；使用者在 Telegram 看到訊息是另一項人工證據。兩者分開記錄，不把「有 message ID」寫成「使用者已讀」。

## 2. 本次授權與共同前提

本次使用者已明確確認來源資料使用許可，並授權最多 **2 次新 Actor 啟動、每次上限 US$0.05、合計上限 US$0.10，以及每個 Profile 最多 3 則通知**。這是本次驗收的界線，不是日後自動延續的額度，也不是已發生費用。

未來使用者需自行確認來源許可涵蓋取得、必要保存與通知，再設定 `SOURCE_ACCESS_CONFIRMED=true`；這個旗標只是使用者確認，不會取得授權，也不是程式替你完成法律審查。

開始前：

- 保留既有 `.env`、`venv` 與 `data/runs.sqlite3`；不要用範例覆寫設定，也不要在終端印出 Token。
- 本次 live 固定用 `--state-dir data`，沿用既有預算、未解決 run、去重與冷卻紀錄。不能改用新資料夾或刪除資料庫，藉此取得新的預算／重送額度。
- 檢查既有 Apify 費用／時間上限及 Telegram 目的地設定；不為了讓命令通過就提高每日預算或擴大 Token 權限。
- Bot 必須能在預定 Chat 發言；通知上限是每個 Profile 在本次驗收的累積上限，不能藉由重複命令再多送 3 則。
- 若已有未解決的同 Profile live attempt，先處理原 run，不改 Profile ID 或資料庫繞過它。

本輪已核對原每日上限為 US$0.50，因此以下命令前綴暫時將該次 Python 程序的每日上限降低為 US$0.10，並將每次啟動上限設為 US$0.05，不改寫 `.env`。仍從原本 `data/runs.sqlite3` 計算當日已用／預留金額；若剩餘額度不足就停止。

這個 US$0.10 前綴只適用已核對原每日上限不低於 US$0.10 的本次設定。未來若原設定更低，應沿用較低值，不能直接複製前綴提高預算。

## 3. 第一關：只做離線驗證

在專案根目錄的 Git Bash 啟用現有 venv。若缺少依賴，先依 [README 安裝說明](../README.md)處理，不要為驗收自動重建環境。

```bash
source venv/Scripts/activate
python --version
python -m pip check
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy
```

逐項確認命令結果；有失敗先釐清，不用 live 操作取代失敗的離線檢查。一般測試以 mock／fixture 執行並阻擋真實 socket 連線。

再用獨立的 fixture 資料夾練習兩個 Profile：

```bash
python -m nz_job_radar run --profile auckland-cafe-service \
  --fixture tests/fixtures/phase2/seek-synthetic.json \
  --dry-run --state-dir data/verification-fixture
python -m nz_job_radar run --profile nz-ski-fields \
  --fixture tests/fixtures/phase2/seek-synthetic.json \
  --dry-run --state-dir data/verification-fixture
python -m nz_job_radar outbox --state-dir data/verification-fixture
```

確認輸出有 WHV 標籤、理由、證據、確認事項及合成資料標記，且沒有建立真實待送通知。重跑可驗證跨次保存；dry-run 仍可重複預覽，不能因此認為已發送或去重失效。

## 4. 第二關：準備限額 Profile 副本

保留正式 `profiles/` 設定，將兩份 YAML 複製到本機 smoke 目錄。`cp -n` 不覆寫已有副本：

```bash
mkdir -p data/live-smoke-profiles
cp -n profiles/auckland-cafe-service.yaml data/live-smoke-profiles/
cp -n profiles/nz-ski-fields.yaml data/live-smoke-profiles/
```

用編輯器開啟這兩份副本，只將以下上限設為：

```yaml
max_results: 3
max_pages: 1
```

保留原 `id`、關鍵字、地區、雇主、排除條件與通知標籤。這樣仍在驗證原本兩個搜尋情境，只縮小取得量。不要用處理 `.env` 的 shell 指令順手改設定，也不要擴大搜尋條件以湊出可通知結果。

檢查副本與既有執行紀錄：

```bash
python -m nz_job_radar profiles --profiles-dir data/live-smoke-profiles
python -m nz_job_radar runs --state-dir data
python -m nz_job_radar outbox --state-dir data
```

`--profiles-dir` 只換 Profile 的讀取位置，`--state-dir data` 仍指向原本 live 資料庫。每次 Actor 啟動後，不再修改這份副本；`resume` 必須有相同 Profile ID 與完整 fingerprint。若是恢復更早的 run，則需還原該 run 當時的設定，不能套用新縮小的上限。

## 5. 第三關：一個 Profile 只啟動一次，先預覽再 resume 發送

以下咖啡 Profile 範例會啟動一次可能計費的 Actor，取得最多設定範圍內的結果，再做通知預覽；它不發 Telegram：

```bash
SOURCE_ACCESS_CONFIRMED=true APIFY_MAX_CHARGE_USD=0.05 APIFY_DAILY_BUDGET_USD=0.10 \
python -m nz_job_radar run --profile auckland-cafe-service \
  --profiles-dir data/live-smoke-profiles --state-dir data \
  --live --dry-run --show-excluded
```

立即保留輸出的本機 attempt ID、Apify run ID 與 dataset ID，再檢查：

- Dataset 是否完整、有無無效資料或讀取失敗。
- Profile 符合／排除／待確認數量，以及每筆 WHV 標籤、理由與證據是否合理。
- 候選是否有可通知的真實職缺；預覽文字與目的地是否正確。
- 回讀費用、設定上限與可能截斷警告。`max_results=3`／`max_pages=1` 不代表已搜尋完整市場。

省略 `--chat-id` 的預覽使用獨立 `preview` 範圍；若要套用實際目的地的本機去重紀錄，可在 dry-run 加上該數字 Chat ID。預覽不呼叫 Telegram，也不新增 outbox。

確認有適合依目前通知政策傳送的候選後，以**同一個 run** 執行下列命令。將 placeholder 換成剛才記下的實際 run ID：

```bash
SOURCE_ACCESS_CONFIRMED=true APIFY_MAX_CHARGE_USD=0.05 APIFY_DAILY_BUDGET_USD=0.10 \
python -m nz_job_radar resume --profile auckland-cafe-service \
  --profiles-dir data/live-smoke-profiles --state-dir data \
  --run-id '剛才的咖啡RUN_ID' --live --notify --notify-limit 3
```

`resume` 重新讀取原 run／dataset，不另開 Actor。不要改成第二次 `run --live --notify`，那會是新的付費啟動。

滑雪場使用同一順序，把 Profile 改成 `nz-ski-fields`，並保存它自己的 run ID；resume 也必須填它自己的 ID。這是本次第 2 次、也是最後一次允許的新啟動。任一 Profile 沒有候選時如實記錄，不加開 run 或放寬分類來湊通知。

`--notify-limit` 用於 `run`／`resume` 的通知處理上限，預設 20、有效範圍 1～100，會在啟動前驗證；本次明確設 3。它不改搜尋量，也不是整個本次授權的自動累積計數器。若還有待送紀錄，本次不要繼續整批 `deliver` 以超過每 Profile 3 則的授權。

## 6. 第四關：保存能對得上的證據

讀取目前執行與 outbox：

```bash
python -m nz_job_radar runs --state-dir data
python -m nz_job_radar outbox --state-dir data
```

每個 Profile 至少記錄以下結果；不包含 Token、原始 `.env` 或完整職缺正文：

| 證據 | 要能回答的問題 |
|---|---|
| Profile ID、限定設定、attempt ID | 跑的是哪個情境？有沒有超出授權啟動次數？ |
| run ID、dataset ID、遠端與本機狀態 | 預覽與 notify 是否確實使用同一個 run？ |
| 費用上限、回讀 usage 與查詢時間 | 花費目前已知多少？哪些仍未知／可能延後更新？ |
| 取得、有效、匹配、WHV 與候選數 | 職缺是否經過 Profile 與 WHV 篩選？ |
| outbox ID、SEEK ID、重要版本、目的地 key | 這則通知對應哪一筆已保存職缺？ |
| `sent`、message ID 與嘗試歷史 | API 是否確認接受？是否出現 retry／未知結果？ |
| 人工收件核對 | 使用者是否在預定 Chat 看到對應職缺、標籤與連結？ |

不要另外傳純測試文字，然後把它當成「真實職缺 → WHV → Telegram」的驗收證據。真實通知應能從 run、職缺、評估與 outbox 一路對到 message ID。

成功取得零筆、零候選、達搜尋上限或部分資料，本身都不是通知端到端完成的證據。達上限時可以證明有界收集的行為，但仍需另外有有效職缺與通知證據；partial 需先處理缺失。若只完成其中一個 Profile，就記錄哪一個完成及另一個缺什麼，不把完整 MVP 一併勾選。

## 7. 失敗時從已知狀態繼續

| 情況 | 本次處理方式 |
|---|---|
| `start_unknown`／啟動回應遺失 | 可能已建立付費 run；先核對 Apify 的對應 run ID，不再 POST。這次嘗試仍計入本次啟動／費用保留範圍 |
| `wait_timeout`／本機中斷／dataset partial | 保留 ID，用同 Profile 副本、同 state-dir 的 `resume --live --dry-run` 讀取原 run；不新啟動 |
| `actor_failed` | 記錄真正失敗，不把 0 筆當「沒有職缺」，不自動多開一次超出本次上限 |
| 費用尚未回報 | 記錄未知，不能寫 US$0；保留本機預算預留，稍後只核對已知 run |
| Telegram `rate_limited` | 保留目的地冷卻，到期後才考慮剩餘授權內的指定 outbox，不縮短等待 |
| Telegram `failed` | 先修正明確原因，再依[人工恢復流程](notifications.md#7-人工處理失敗或結果不明)決定是否 retry |
| `delivery_unknown`／遺留 `sending` | 先核對 Telegram 與 outbox；可能已送達，不因缺少本機 sent 就重送 |

恢復來源時若當時沒有保存到 run ID，但已人工找到正確遠端 run，可加上原 `--attempt-id` 連結；仍須通過原設定驗證。不要使用別人的 run 或猜測對應 ID。

若只剩單筆確定可重試的通知，在本次剩餘授權內可用指定 ID 的 `deliver`；它不呼叫 Apify：

```bash
SOURCE_ACCESS_CONFIRMED=true APIFY_DAILY_BUDGET_USD=0.10 \
python -m nz_job_radar deliver --send \
  --profiles-dir data/live-smoke-profiles --state-dir data \
  --outbox-id '已核對的OUTBOX_ID' --limit 1
```

`failed`／`delivery_unknown` 不會直接被 deliver 重送。人工 retry 仍要先使用 `resolve-notification`，未知結果還需明確接受可能重複的風險；方法見[通知文件](notifications.md)。`--notify-limit` 與 `deliver --limit` 不是相同參數。

## 8. 驗收結論怎麼寫

最後逐項記錄：離線檢查結果、兩個 Profile 的有限真實收集、經 filter 的通知 API 證據、人工收件核對、總啟動次數／回讀費用，以及剩餘限制。

離線／mock 全過但尚未 live，就只能寫離線流程通過；API 已接受而人工尚未核對，就把人工核對保留為待完成。零候選、來源失敗、partial、費用未知或通知不明，都應出現在結論中。

只有上述必要證據齊全，才能依 [MVP 規格](../NZ_WORKING_HOLIDAY_JOB_RADAR_SPEC.md)判定本次手動流程驗收；即使通過，也不擴張為完整市場涵蓋、長期可靠性或個人 WHV 合法適用的保證。
