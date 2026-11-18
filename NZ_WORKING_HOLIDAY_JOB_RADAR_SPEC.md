# NZ Working Holiday Job Radar — SEEK-only MVP 規格

> 狀態：目前開發與驗收依據；Phase 1–4 程式／離線檢查與文件完成，咖啡 live 通過；滑雪場真實職缺通知仍待正向樣本驗收。
> 範圍更新：2026-09-23，依使用者決定縮小為 SEEK 單一來源。
> 本文件取代原多來源 MVP；[原完整版](docs/archive/NZ_WORKING_HOLIDAY_JOB_RADAR_SPEC_FULL.md)只作歷史參考，不可套用其中的舊任務清單或 kickoff prompt。

## 1. 目標與核心流程

建立個人求職工具，讓使用者定義想找的職缺，透過 Apify 取得 SEEK NZ 結果，列出職缺、進行台灣 WHV 初步篩選，再發送 Telegram 通知。

```text
定義／選擇 YAML Profile
  → 呼叫 Apify SEEK Actor
  → 讀取 dataset、正規化、列出結果
  → WHV filter：標籤＋理由＋原文證據
  → 本地去重／通知待送紀錄
  → Telegram 通知
```

先以可重複執行的手動 CLI 完成流程。「列出結果」指終端列表，不要求 Web UI。SQLite 只支援結果保存、差異比較及通知復原，不擴充成多來源平台。

滑雪場仍是 SEEK 的搜尋情境；不讀取或監測滑雪場官方招募網站。官方網站另收錄於[滑雪場資料目錄](docs/ski-resort-directory.md)，供人工查看及未來評估。

## 2. 範圍邊界

| 保留在本 MVP | 移出本 MVP／延後 |
|---|---|
| YAML Profile、SEEK NZ／Apify、終端結果列表 | Trade Me API、adapter、憑證及停用 adapter 的 fixture 驗收 |
| 台灣 WHV 規則式判斷與證據 | 所有滑雪場／雇主官網與 ATS 的職缺監測 |
| Telegram、dry-run、本地防重複及有限重試 | 跨來源去重、官網變更偵測、通用多來源架構 |
| SQLite 最小持久化、run 與費用紀錄 | Web Dashboard、收藏／已申請／備註、分析報表 |
| 手動單次執行、離線測試、明確啟用的 live smoke | 定時排程、常駐服務、雲端部署與自動健康摘要 |
| 新職缺及影響篩選／通知的重要更新 | 上游增量模式、重刊辨識、推測過期、完整版本歷史介面 |

不做自動投遞、LLM 評分、多使用者、雇用歷史或個人累計同雇主工作時間追蹤。延後項目不是下一階段自動獲准開發的工作，需另行決定。

## 3. Profile：找什麼工作

保留兩個主要情境，來源均只有 SEEK：

- `auckland-cafe-service`：Auckland 的 cafe assistant、front of house、counter staff、kitchen hand 等；排除以 barista、coffee maker、cafe all-rounder、head barista 為主的職稱。
- `nz-ski-fields`：指定地區／雇主的滑雪場服務工作，例如 lift operator、guest services、rentals、food and beverage、housekeeping。只能看見被 SEEK／Actor 搜尋涵蓋的職缺，不保證涵蓋目錄中每一場地。

甜點烘焙、租車等可日後透過相同設定格式增加；不要求先完成四個 profile 才算 MVP。

設定示意（已建立於 `profiles/auckland-cafe-service.yaml`）：

```yaml
id: auckland-cafe-service
name: Auckland Cafe Service
enabled: true
country: NZ
locations: [Auckland]
keywords: [cafe assistant, front of house, counter staff, kitchen hand]
exclude_title: [barista, coffee maker, cafe all-rounder, head barista]
employers: []
max_results: 100
max_pages: 3
notification_labels: [likely_suitable, needs_confirmation]
```

- 驗證唯一 ID、必要關鍵字、NZ 國別、結果／分頁上限及允許的標籤。範例上限是搜尋預算，不是完整市場覆蓋保證。
- 地區為限制，keywords 任一命中；若指定 employers，作為額外雇主限制。雇主欄位缺失時記錄待確認，不擅自視為匹配。
- upstream 查詢與本地文字比對規則須在實作時一致並有 fixtures；供應商搜尋可能回傳不相關結果，不能直接視為 profile 命中。
- `exclude_title` 僅比對職稱，不因服務職缺的正文提到咖啡訓練就排除。
- 正職工時 Full time 不等於永久僱用 Permanent；不得混為一談。
- 密鑰只在 `.env`，不放 YAML。既有 `APIFY_API_TOKEN`、`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID` 沿用，不必申請 Trade Me 憑證。

## 4. Apify／SEEK 接入

Actor 為 `blackfalcondata/seek-scraper`。已查核的 build、欄位、費用及樣本見 [Phase 0 調查](docs/source-access.md)與[樣本索引](tests/fixtures/phase0/README.md)。

### 最小執行契約

1. 啟動前檢查設定、來源使用許可與本地預算；一般測試預設不連線。
2. 一個 profile 的關鍵字盡量批次送出；API 的 `query` 是 JSON 編碼陣列字串，不是原生陣列。
3. 明確送 `country=NZ`、`sortMode=date`、`includeDetails=true`、`descriptionFormat=text`、`compact=false`、`includeApplicantInsights=false`、`skipReposts=false`。
4. 本版先使用 `incrementalMode=false`，以本地資料庫比較結果；不依賴 `stateKey`。這是本次精簡設計採用的技術備案，不是增量模式已修好。
5. 明確限制 `maxResults`、`maxPages`、timeout 與 `maxTotalChargeUsd`；不設定短期滾動日期窗來推測職缺消失。
6. 啟動後立即記錄 run ID，再追蹤完成狀態與 dataset ID，分頁讀取結果。HTTP 201 不等於執行成功。
7. 支援以已知 run ID 恢復讀取；timeout、斷線或帳號級歷史列舉 403 不應觸發盲目重新啟動，避免重複計費。
8. 來源失敗、部分結果、達到上限分開顯示；本 MVP 不推測職缺過期，也不因未出現而刪除舊資料。

本地 SQLite 為主要紀錄。日後若恢復 Actor 增量，需另驗證最小儲存權限、連續兩次執行與費用，再決定升級；目前不要求修復 `SEK-4002` 才能進行離線開發。

### Live 啟用條件

普通模式技術測試成功不代表已取得 SEEK 的資料使用許可；縮小來源數量也不會代替 [SEEK 資料使用條款](https://nz.seek.com/terms)所需的確認。Phase 0 當時未確認；Phase 4 使用者已明確確認蒐集、保存與通知用途並授權限額測試，見[驗證紀錄](docs/phase4-verification.md)。旗標僅記錄使用者確認，不是程式代為取得授權；未來用途或條件變更需重新確認。

不繞過登入、CAPTCHA、robots、403 或來源限制，不擅自擴大 Token 權限。禁止 Actor 直接推播最終通知，所有結果須先經本地 filter。

## 5. 列出結果與最小資料

終端先列出 profile 相關結果，再附上 WHV 標籤及通知處理摘要。被判為不相容的職缺仍可查看，不因 filter 永久刪除。至少顯示：

- 職稱、雇主、地點、聘僱類型、薪資（未知則標未知）、SEEK 原始連結。
- 刊登時間，以及職缺中明示的聘期／起訖日；不能把刊登截止日 `validThrough` 當聘期。
- WHV 標籤、理由、證據片段、信心程度、規則查核日期與免責說明。
- 本次取得／符合 Profile／各標籤／待通知／已送／失敗筆數，以及 run ID、費用與截斷警告。

最小內部紀錄包含來源 ID、連結、正文或必要證據、地點、聘僱類型、薪資、聘期與工作權措辭、分類結果、本地內容 hash、首次／最近觀察時間。僅保存本用途所需內容，保留期限依來源許可設定；不沿用舊版 90 天正文保存作為無條件預設。

同一 SEEK 職缺優先以 `seekJobId` 識別，再以 Actor `jobId` 或正規網址回退。不同 profile 命中同一 ID 可保留多個匹配，但不重複建立職缺。原文聯絡人、email、電話、社群資料不保存。

## 6. WHV filter：初步篩選，不是簽證保證

依 [Immigration New Zealand 台灣 WHV 頁](https://www.immigration.govt.nz/visas/taiwan-working-holiday-visa/)，2026-09-23 查核仍列出臨時工作、同一雇主最多三個月及不得從事永久工作。僅就職缺廣告判斷，不檢查個人的全部簽證條件或過往任職時間。

| 標籤 | 判斷 |
|---|---|
| `likely_incompatible` | 明確永久工作、最低承諾／聘期超過三個月，或明確排除目前工作權；硬性衝突優先 |
| `needs_confirmation` | 聘期／雇主不明、日期含糊、資訊缺失，或證據不足；seasonal／casual 不可單憑名稱變綠 |
| `likely_suitable` | 沒有硬性衝突、雇主與相容聘期明確，且達到既有保守評分門檻；仍需向雇主確認 |

沿用原規則式評分作為實作基準：WHV 明示接受 +30、temporary／casual／fixed-term／contract +25、明確相容聘期 +35、具體非永久起訖日 +10；永久 -70、超期 -60、排除工作權 -70 且皆為硬性衝突。分數限制 0～100；綠標需至少 70 且符合上表必要條件，不能以高分抵銷硬性衝突。

工程上沿用三個日曆月比較，不直接換成 90 天；起訖包含日或邊界不明時標待確認。這是保守的實作判定，不能宣稱官方已定義所有邊界計算細節。住宿、交通及個人偏好不能增加法律適合程度。

每個結果都要保留判斷理由、原文片段、來源連結與查核日期；規則超過 90 天未查核時顯示警示。訊息附「僅供初步篩選，請確認現行簽證條件與聘僱契約」。未知資料不能補成有利條件。

Phase 2 實作另採保守措施：規則超過 90 天未查核時不給新的綠標。英文抽取範圍、日期邊界、例外與計數定義見 [WHV 規則說明](docs/whv-rules.md)；分數及信心是本專案規則，不是官方判定或核准機率。

## 7. Telegram 通知

- 預設通知 `likely_suitable` 與 `needs_confirmation`；`likely_incompatible` 留在結果列表，不預設推播。各 profile 可明確設定標籤清單。
- 新的符合條件職缺通知一次；重要欄位／分類改變時可重送更新，不因抓取時間或格式改變重送。
- 訊息包含職稱、雇主、地點、聘僱類型、薪資（若有）、標籤、理由、需向雇主確認的問題、原始連結與免責說明，不貼整份職缺正文。
- 已確認成功送達的相同 job／重要版本／目的 Chat 不再發送；同一職缺跨 profile 命中亦沿用此防重複規則。
- 先交易式寫入結果與通知待送紀錄，再呼叫 Telegram；失敗不得抹除職缺。
- Telegram 429／可明確重試的錯誤採有限退避。若請求可能已送達但回應遺失，記錄 delivery_unknown，預設不盲目重送，供人工決定；不宣稱端到端 exactly-once。
- 提供 dry-run：列出「將發送的訊息」，不發送 Telegram、不消耗待送佇列、不標記已送。若取得的是 live 資料，Apify 仍可能計費；完整免網路測試應使用 fixture 模式。

## 8. 最小可靠性與費用

- SQLite 保存搜尋 run、職缺最新資料／重要版本識別、profile 匹配、outbox 與發送紀錄。保留可重跑與復原能力；不要求舊版完整多來源資料表。
- 同一 profile 的執行避免重疊；單次手動執行完成後退出，不需要常駐 worker。
- 請求 timeout、bounded retry、限流、清楚的錯誤訊息與非成功 exit code。Secret 不出現在 log、fixture、追蹤網址或 Git。
- 保留 run ID、dataset ID、emitted items、回讀 usageTotalUsd 及估計毛額；費用可能延後更新，不等於信用卡扣款。
- 普通模式每次可能重複輸出相同職缺，預算要計算全部 emitted items，不套用舊版「只對新增／變動結果付費」的假設。
- 以使用者設定的每次／每日上限防止連續重跑超支；正常測試不啟動 Actor。餘額無法讀取時顯示未知，不擴權讀取帳務。
- 上游回傳成功但為零筆、資料被截斷及真正失敗必須分開，不用空陣列掩蓋錯誤。

## 9. 目前狀態與驗收

已完成環境、[Phase 0 調查](docs/source-access.md)、[Phase 1](docs/phase1-verification.md)及 [Phase 2 程式與離線驗證](docs/phase2-verification.md)。
另已完成 [Phase 3 程式與離線驗證](docs/phase3-verification.md)，Phase 1–3 全套 711 個測試通過。
目前可用 CLI 選擇 Profile、取得／正規化／列出結果及 WHV 初篩；Apify 普通模式啟動／分頁／恢復及費用紀錄已經 mock 測試。
Phase 3 已接上跨次職缺／版本保存、通知預覽、去重與明確啟用的 Telegram 發送；安全恢復見 [通知文件](docs/notifications.md)。
Phase 4 已新增端到端測試與安全補強，全套 763 個測試、Ruff、格式、strict mypy 與 pip check 通過。
使用者已確認來源許可並授權限額 live；兩次取得各 3 筆，合計回讀 US$0.032。咖啡有 1 筆黃標通知並經人工核對；滑雪場 0 候選、不發送，尚缺真實通知正向樣本。詳見 [Phase 4 紀錄](docs/phase4-verification.md)。其他來源的受阻狀態不再阻擋本版 MVP。

完成條件：

- [x] 編輯 YAML 可變更關鍵字、地點、雇主與通知標籤，不需要修改 Python 程式（離線驗證）。
- [ ] 咖啡服務與滑雪場兩個 SEEK profiles 均可獨立跑完取得 → 列表 → WHV → Telegram。
- [x] 可讀取完整本次 dataset，顯示結果上限並保存 run／dataset／費用（live 各 3 筆；多頁與失敗恢復另有 HTTP mock 驗證）。
- [x] 永久、超期、日期不明、casual 不明、明示接受 WHV、日曆月邊界等離線測試通過（Phase 2）。
- [x] 職稱排除不誤傷僅在正文提到咖啡訓練的服務職缺（Phase 1 離線測試）。
- [x] 相同結果重跑不重複新增職缺、不重送已確認的通知；重要更新才產生新版本通知（離線／mock 驗證）。
- [x] 來源失敗、斷線恢復讀取、Telegram 明確失敗／限流／delivery_unknown 及 dry-run 都有離線測試。
- [x] 格式、lint、型別、單元與 fixture 整合測試通過；fixture 不需要網路。
- [x] 取得使用者許可確認後執行明確啟用且限額的 live smoke；咖啡職缺經 filter 通知、人工收件及重跑不重送已確認。
- [ ] 滑雪場取得可通知的真實職缺並完成 Telegram 人工收件；本次只有零候選不發送證據，不把完整兩情境驗收勾選。
- [x] README 包含 Git Bash／Python 3.12 venv 的安裝、設定、首次執行、dry-run、重跑及常見失敗說明。

不再要求 Trade Me 停用 adapter、任何滑雪場官網 adapter、跨來源去重、Dashboard 或排程才能完成 MVP。

## 10. 實作方向與後續

維持 Python 3.12、YAML、SQLite、HTTP client、規則式文字／日期處理與 Telegram Bot API。套件版本與資料庫遷移方式在實作時確定，以能測試及恢復的最小方案為準；本版不需要 Node.js、FastAPI、Jinja2、HTMX、Playwright 或瀏覽器自動化。

步驟見 [MVP Roadmap](MVP_ROADMAP.md)及 [Phase 4 操作指南](docs/acceptance-guide.md)。程式、離線檢查與文件已交付；剩餘為滑雪場真實通知樣本驗收，額外新啟動需另行決定時間與預算。不要因歷史規格、舊 fixture 或滑雪場目錄存在，就自行恢復多來源範圍。

相關文件：

- [滑雪場官方網站與招募目錄](docs/ski-resort-directory.md)
- [Phase 0 接入調查與未解風險](docs/source-access.md)
- [Phase 0 樣本](tests/fixtures/phase0/README.md)
- [原多來源完整版（歷史）](docs/archive/NZ_WORKING_HOLIDAY_JOB_RADAR_SPEC_FULL.md)
