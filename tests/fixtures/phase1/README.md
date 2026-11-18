# Phase 1 合成職缺樣本

`seek-synthetic.json` 是完全合成的離線資料，供 Phase 1 正規化與 Profile 匹配示範使用。頂層的 `fixtureKind` 明確標示為 `synthetic_phase1_dataset`，`items` 內含 8 筆 Actor-shaped 記錄。

## 來源與使用界線

- 這不是 Apify 實際執行結果，也不是真實 SEEK 職缺；沒有透過網路抓取任何資料。
- 欄位名稱沿用專案已觀察的 Actor 欄位，以少量白名單欄位表達測試情境，並非 Actor 完整 raw schema。
- 職稱、描述、日期、薪資及多數公司名稱均為人工合成。`NZSki`、`Cardrona` 是為了測試雇主匹配而使用的真實名稱，內容不代表它們的招募、聘僱條件或聲明。
- `990000001` 至 `990000008` 是合成識別碼；SEEK 格式連結只是 URL 結構示例，不代表存在對應職缺。不要開啟它們尋找或申請工作，也不要將它們發送為真實求職通知。
- `null` 表示該欄位未知，不應轉成空字串、零薪資或自行補上日期。`validThrough` 表示廣告截止時間，不是任職期間。
- 描述保留少量任期、工作許可或未知條件的情境，僅供未來 WHV 篩選測試擴充；本階段沒有 WHV 適合度標籤，也不能把 Profile 匹配當作 WHV 適合度判定。
- 本檔不包含 API Token、Telegram 資料、聯絡方式或其他個人資料。

## 情境索引

| 合成 SEEK ID | 情境 | 檢查目的 |
| --- | --- | --- |
| `990000001` | Auckland／Front of House Assistant／Fictional Harbour Cafe | 基本職稱與地區匹配。 |
| `990000002` | Auckland／Barista，描述含 `front of house` | 確認僅描述含字詞時，不會被當成符合職稱條件。 |
| `990000003` | Wellington／Kitchen Hand | 確認職稱吻合但地區不符的情境。 |
| `990000004` | Auckland／Cafe Assistant | 另一個職稱候選，並示範薪資及日期未知。 |
| `990000005` | Queenstown／Guest Services Assistant／NZSki | 測試滑雪場雇主名稱條件；並非 NZSki 真實廣告。 |
| `990000006` | Wānaka／Rentals Assistant／Cardrona | 測試滑雪場雇主條件及帶長音符號的地名；並非 Cardrona 真實廣告。 |
| `990000007` | Queenstown／Rentals Assistant／Fictional Vehicle Rentals | 避免僅因職稱及地區相符，就把租車工作視為雪場工作。 |
| `990000008` | Methven／Guest Services Assistant／公司未知 | 雇主缺失時保留待確認情境，不能僅以雪場附近地區推定雇主。 |

實際匹配結果由 Profile 設定與測試驗證；這份索引不預先宣告匹配總數。
