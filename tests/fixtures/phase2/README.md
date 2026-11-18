# Phase 2 合成職缺樣本

`seek-synthetic.json` 是 12 筆完全合成的 Actor-shaped SEEK 記錄，頂層 `fixtureKind` 為 `synthetic_phase2_dataset`。用來驗證 Profile 匹配後的 WHV 初步標籤、原文證據、通知資格統計與離線 CLI；不是簽證或真實招募資訊。

## 來源與使用界線

- 本檔由人工合成，沒有呼叫 Apify、SEEK 或 Telegram。所有職稱、描述、聘期、薪資、日期均為測試情境。
- `NZSki`、`Cardrona` 是測試既有滑雪場 Profile 雇主條件所需的真實名稱；相關內容不代表這兩家雇主的招聘、聘僱條件或聲明。其餘公司名稱均為虛構。
- `991000001` 至 `991000012` 是合成 ID。SEEK 格式網址僅用來測試來源識別與 URL 格式，不代表存在對應職缺，不應開啟應徵或當作真實求職通知發送。
- `validThrough` 是廣告截止日，不是聘期。正文中的明確任職日期才用於日期情境；日期早晚不代表真實廣告仍有效。
- `null` 表示未知，不可自行補成有利條件。本檔沒有 Token、聯絡人、電話、email 或其他個人資料。
- 標籤只依廣告文字作保守初篩；不計算使用者過往同一雇主任職時間，不保證簽證或契約適用。

## 情境與預期結果

| 合成 SEEK ID | Profile | 情境 | 預期 WHV 標籤 |
| --- | --- | --- | --- |
| `991000001` | 咖啡 | 雇主已知，臨時兩個月，明示接受 WHV | `likely_suitable` |
| `991000002` | 咖啡 | 永久工作同時歡迎 WHV；硬性衝突優先 | `likely_incompatible` |
| `991000003` | 咖啡 | 四個月定期契約，即使歡迎 WHV 仍超期 | `likely_incompatible` |
| `991000004` | 咖啡 | 臨時兩個月，但只接受 NZ 公民／居民 | `likely_incompatible` |
| `991000005` | 咖啡 | Casual，未明示聘期；不能單憑名稱變綠 | `needs_confirmation` |
| `991000006` | 咖啡 | Full time 每週 40 小時，聘期未知；不能誤判永久 | `needs_confirmation` |
| `991000007` | 咖啡 | 不提供 sponsorship，要求有效簽證，聘期未知；不能僅因不贊助變紅 | `needs_confirmation` |
| `991000008` | 咖啡 | `2026-01-01` 至 `2026-04-01` 恰在三個日曆月邊界，包含日不明 | `needs_confirmation` |
| `991000009` | 咖啡 | 兩個月並歡迎 WHV，但雇主缺失；分數不能補足必要資料 | `needs_confirmation` |
| `991000010` | 咖啡 | 非永久定期工作 `2026-01-01` 至 `2026-03-01`，未寫 WHV；明確日期與非永久條件達 70 分 | `likely_suitable` |
| `991000011` | 滑雪場 | Queenstown／NZSki，臨時兩個月並歡迎 WHV；完全虛構 | `likely_suitable` |
| `991000012` | 滑雪場 | Wānaka／Cardrona，Casual 聘期未知；完全虛構 | `needs_confirmation` |

預設 Profile 下，咖啡符合 10 筆（綠 2、黃 5、紅 3），排除 2 筆；滑雪場符合 2 筆（綠 1、黃 1），排除 10 筆。全部 12 筆仍會取得 WHV 評估，因此全批統計為綠 3、黃 6、紅 3。咖啡 Profile 沒有限制雇主清單，所以缺雇主的第 9 筆仍符合搜尋 Profile，但 WHV 必須待確認。

預設通知標籤為綠、黃；咖啡通知資格為 7 筆、抑制 3 筆，滑雪場通知資格為 2 筆、抑制 0 筆。這只是 Profile 匹配結果上的通知政策計數，不代表已建立待送佇列或已發送訊息。紅標仍保留在可查看的職缺列表。

`tests/test_phase2_integration.py` 使用本檔核對這些結果，並檢查 SQLite 僅保留執行欄位與 aggregate summary，不保存 Job、正文或個別證據。
