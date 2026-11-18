# Phase 0：資料來源接入調查

查核日期：2026-09-23。此份是縮小範圍前，依據[原完整版第 20 節](archive/NZ_WORKING_HOLIDAY_JOB_RADAR_SPEC_FULL.md)完成的調查紀錄，保留當時的證據與限制。

> Phase 4 後續更新（2026-09-23）：使用者已明確確認 SEEK 資料可用於本專案蒐集、保存與 Telegram 通知，並授權 2 次限額 live 測試。已執行，結果與費用見 [Phase 4 紀錄](phase4-verification.md)。這是使用者的許可確認，不代表另行獨立法律審查；下方 `blocked_permission_review` 與「未確認」均保留為 Phase 0 當時狀態，不是最新驗收進度。

> 範圍更新：目前以 [SEEK-only MVP 規格](../NZ_WORKING_HOLIDAY_JOB_RADAR_SPEC.md)及[新 Roadmap](../MVP_ROADMAP.md)為準。Trade Me、滑雪場官網監測及其 adapter 不再是 MVP 必做項目；其受阻狀態不影響新版驗收。SEEK 的使用許可缺口仍保留，普通模式＋本地 diff 已納入新版設計，上游增量修復延後。以下資料不是要求重新啟用所有來源。

## 1. 結論與交付

| 來源 | 技術證據 | 自動接入決策 | 解除條件 |
|---|---|---|---|
| SEEK／Apify | 普通模式成功取得 1 筆；增量模式失敗 | `blocked_permission_review`；普通模式僅技術可用 | 確認來源授權涵蓋蒐集、保存與通知；增量另須解決狀態存取 |
| NZSki | 官方頁連至 Dayforce；公開頁 HTTP 200，但初始 HTML 沒有職缺列表 | `blocked_access_and_schema_unverified` | 確認可用的自動接入方式、條款與限流；取得實際列表及詳情樣本 |
| Cardrona／Treble Cone | 官方頁連至 employment.cardrona.com；招聘站禁止一般爬蟲 | `blocked_robots_disallow` | 雇主提供許可、授權 feed／API，或可允許使用的替代入口 |
| Trade Me Jobs | 官方 API 文件已確認；未設定相關憑證 | `disabled_missing_approved_access` | 核准 API 用途、憑證，以及保存、跨來源整合與通知的資料使用權限 |

每個來源已有接入決策及樣本／受阻紀錄，符合當時 Phase 0 exit；不代表 MVP 已驗收。NZSki、Cardrona 原為完整版要求的來源，現已由使用者明確移出本版 MVP，不是未報告的缺漏。

- [樣本與證據索引](../tests/fixtures/phase0/README.md)
- [參考專案授權檢查](reference-licenses.md)
- [後續 Roadmap](../MVP_ROADMAP.md)

本次沒有修改 `.env`、Token 權限、排程或帳務設定，沒有安裝套件、建立應用程式或發送新的 Telegram 訊息。沒有繞過登入、CAPTCHA、403 或 robots 限制。

## 2. SEEK／Apify

### 介面與權限

- Actor：`blackfalcondata/seek-scraper`，ID `5BAoYcBhwvPuMtd0K`。
- 本次固定 build `0.4.57`／`CRzwHtgqdMgvEKwQa`，不能假定之後的 latest 有相同輸入或行為。
- 使用 `.env` 的 `APIFY_API_TOKEN`，以 Authorization Bearer header 傳送；不將 Token 放進 URL、文件或 log。
- 目前使用者提供的權限設定為 Account-level Actors: Run、Access default run storages 開啟、Run full-permission Actors 關閉。實測可啟動、讀取指定 run 及其 dataset。
- 列出 Actor 歷史 runs 回傳 403，不代表已知 run 不能讀取。程式需即時保存啟動回應的 run ID／dataset ID，不依賴帳號級列舉。
- canonical 啟動端點為 `POST /v2/actors/{actorId}/runs`；`/v2/acts` 是 deprecated alias，不是兩套權限機制。[官方 API 說明](https://docs.apify.com/api/v2)

執行流程：啟動 → 保存 run ID → 查詢 run 狀態 → 成功後分頁讀取 dataset。連線中斷或等待逾時不等於遠端執行失敗，不應直接重送啟動請求。本次中斷後只讀取原 run，沒有另外啟動。

### 輸入與輸出契約

固定版本的 OpenAPI 已讀取，節錄存於 [SEEK 執行證據](../tests/fixtures/phase0/seek-runs.json)。[OpenAPI 端點文件](https://docs.apify.com/api/v2/actor-openapi-json-get)

| 輸入 | 確認結果／專案規則 |
|---|---|
| `query` | string；同設定檔的多關鍵字使用 JSON 編碼後的陣列字串 |
| `country` | 預設 AU，專案必須明確送 NZ |
| `maxResults` | 此 build 預設 100，範圍 0～5000；測試明確設 1，不依賴預設 |
| `maxPages` | 預設 25，範圍 1～100；測試設 1，不能當作完整搜尋結果 |
| `includeDetails`／`descriptionFormat`／`compact` | 分別明確設 true／text／false |
| `includeApplicantInsights`／`skipReposts` | 皆設 false |
| `incrementalMode` | 預設 false；true 的本次實測失敗，見下節 |
| `stateKey` | string；未來每個 profile 使用穩定且版本化的值 |
| `emitUnchanged`／`emitExpired` | 此 build 皆預設 false；正常監控若啟用過期提示需明確設 true |

不加短期滾動 `dateRange`；不把 `maxResults=1`／`maxPages=1` 當正式監控設定。輸入更新以 pinned build 契約及實測為準，不僅依舊 README。[Actor input schema](https://apify.com/blackfalcondata/seek-scraper/input-schema)

本次普通模式樣本確認：

- `seekJobId`、`jobId`、`title`、`company`、`canonicalUrl`、`sourceUrl`、`applyUrl` 存在。
- 地點為字串及 `locationCountry`／`locationSuburb` 等平面欄位；薪資欄位可能為 null。
- `description` 為字串；`bulletPoints` 與 `screeningQuestions` 為陣列，本筆分別 3、5 項。
- 普通模式本筆沒有 `changeType`、`trackedHash`、`firstSeenAt`、`lastSeenAt`。adapter 必須允許缺少，使用本地觀察時間，不得杜撰上游事件。
- `validThrough` 是刊登有效時間，不是聘僱結束日；Full time 也不提供合約月數，不能據此判定 WHV 適合。
- fixture 僅保存欄位投影及 20 字描述片段；未保存聯絡人、電話、email、社群資料或完整職缺正文。詳見樣本說明。

### 實際執行與費用

兩次皆限制 `timeout=120`、`maxTotalChargeUsd=0.05`、最多 1 筆結果、1 頁，無通知設定。時間皆為 UTC。

| 模式 | run ID | 時間 | 狀態／輸出 | 回讀費用 USD |
|---|---|---|---|---|
| 增量 |（已遮蔽） | 06:17:36～06:17:39 | FAILED／0 筆，`SEK-4002` | 0.010 |
| 普通 |（已遮蔽） | 06:19:51～06:20:03 | SUCCEEDED／1 筆 | 0.012 |
| 合計 | 僅本次 Phase 0 的兩次 | 2026-09-23 | 不含先前連通測試 | 0.022 |

普通 run 的 dataset 為（已遮蔽）；失敗 run 為（已遮蔽）。終止狀態的初次回應仍顯示普通 run 為 0.010，稍後回讀已更新為 0.012；費用需延後對帳。

當日 Actor metadata 為 PAY_PER_EVENT：啟動事件每 GB 記憶體 US$0.01、最少 1 個計費單位；每輸出 item US$0.002。本次 256 MB 仍收 1 個啟動事件。上述為 `usageTotalUsd` 毛額，不是信用卡扣款，也未查得帳戶剩餘點數或整月帳單。[Actor 費率](https://apify.com/blackfalcondata/seek-scraper)

`maxTotalChargeUsd` 限制本次付費事件支出；不要把 API 的 `maxItems` 當 PAY_PER_EVENT Actor 的通用結果限制。程式仍須同時控制 Actor 輸入及本地每日預算。[執行 API](https://docs.apify.com/api/v2/actor-runs-post)

### 增量失敗的判斷

啟動 HTTP 201 只代表請求建立成功，不代表 Actor 執行成功。此 run 在開啟持久化狀態時停止，錯誤代碼 `SEK-4002`，dataset 為空；不能解讀成「目前沒有職缺」。

已知：普通模式可用、增量儲存路徑失敗；restricted Token 的 default storage 權限不等於跨 run 狀態一定可存取。尚不能確認是哪一個 named storage 的哪項權限不足，也不能排除 Actor 問題。未擅自擴大權限。

解除步驟：向 Actor 維護者提供失敗 run ID，確認所需狀態儲存及最小權限；由使用者核准調整後，以同一 `stateKey` 連續執行兩次確認。不可直接推薦開啟全部儲存／完整 Actor 權限，也尚未證明 resource-specific Run 失敗的確切原因。

### 使用條款與速率

SEEK 條款（更新日 2026-07-20）第 7(d)、9(b) 限制未經同意的自動蒐集。第三方 Actor 有售且技術上能執行，不等於本專案已獲 SEEK 的蒐集、保存或再利用許可；本次未取得這類授權證明。正式 live／排程先停用，需確認供應商或 SEEK 的授權涵蓋本用途。這是工程接入風險決策，不是法律定論。[SEEK 條款](https://nz.seek.com/terms)

Apify API 文件目前為一般資源預設每秒 60 次、run 等端點每資源每秒 400 次；實際以回應限流資訊為準。本專案在取得來源使用許可後，建議單來源序列執行、API 請求最多每秒 1 次、數秒以上輪詢，429 依 Retry-After／退避處理；這是本地保守設定，不是 SEEK 授權限額。[Apify 限流](https://docs.apify.com/api/v2)

## 3. NZSki：入口已確認，live adapter 仍受阻

官方 [NZSki Employment](https://www.nzski.com/employment) 連到 [Dayforce NZSki 招聘板](https://jobs.dayforcehcm.com/en-NZ/trojanholdings/NZSKI-EMPLOYMENT)。不再猜測或硬編碼過時 ATS。

- 招聘板 HTTP 200；Next.js 初始資料只有 `site-info`，`clientNamespace=trojanholdings`、`jobBoardCode=nzski-employment`、`jobBoardId=4`。
- 頁面附帶的公開 JS 表明職缺列表在客戶端載入。初始 HTML 無職缺，不可判為零職缺或將既有職缺標為過期。
- [Dayforce robots](https://jobs.dayforcehcm.com/robots.txt) 當日只有 Content-Signal 說明註解，沒有實際 User-agent／Disallow 指令；這不構成自動抓取或再利用的授權。
- NZSki 主站 robots 的本次直接 HTTP 請求得到 403 challenge，未繞過。[主站條款](https://www.nzski.com/terms-conditions) 未提供已確認的職缺資料自動取得授權；招聘板提供的 legal 入口也未成功讀取。
- 尚無可驗證的列表／詳情 response contract、穩定 ID／分頁／關閉訊號與來源公布的速率上限。保存的是入口與 shell 發現紀錄，不是假造的職缺樣本。

接入方案：先向雇主／ATS 確認允許方式；優先有授權的 feed/API，其次才是允許自動使用的公開 HTML／瀏覽器渲染。取得真實列表和詳情樣本後才定案 parser。無登入憑證需求的公開入口已找到，但不代表已驗證完整免登入資料流程。

暫時不排程。若獲准且未另定限流，提議最多每 6 小時一次、同 host 序列請求間隔至少 2 秒；須再依對方規範調整。一般職涯 FAQ 不是單一職缺的聘期證據。

## 4. Cardrona／Treble Cone：招聘站 robots 受阻

[官方 Employment](https://cardrona-treblecone.com/employment) → [Our Positions](https://cardrona-treblecone.com/employment/our-positions) → [招聘入口](https://employment.cardrona.com/search)。主站可讀，Our Positions 為職務類別介紹，不能當成目前開放職缺。

主站 [robots](https://cardrona-treblecone.com/robots.txt) 允許一般 crawler，但 [招聘站 robots](https://employment.cardrona.com/robots.txt) 的 wildcard group 是：

```text
User-agent: *
Disallow: /
Crawl-delay: 60
```

`Crawl-delay` 不是忽略 `Disallow` 的許可。未抓取 `/search`，也不冒用 Googlebot、不用瀏覽器或代理繞過。主站允許不會跨網域延伸至 ATS。

[RealNZ Careers](https://www.realnz.com/en/careers/) 的候選入口 `employment.realnz.com` 亦有相同 wildcard 禁止規則，不能當作可用備援。未取得招聘資料 schema，保存的是真實入口及 robots 節錄。[主站條款](https://cardrona-treblecone.com/terms-conditions) 亦不能當作 ATS 自動使用的授權。

解除需雇主許可／授權 feed；屆時再核對職缺 ID、場地、詳情、日期、分頁與關閉規則。現階段不安排任何 ATS polling。必要時人工查看原站，但人工流程不算自動來源驗收通過。

## 5. Trade Me Jobs：API 預設停用

- 文件端點為 `GET https://api.trademe.co.nz/v1/Search/Jobs.json`，Requires Authentication=Yes、Permission Required=None。後者不代表匿名可用。[Jobs search](https://developer.trademe.co.nz/api-reference/search-methods/jobs-search)
- OAuth 1.0a；至少需核准 application 的 Consumer Key／Secret。非會員資料請求與會員授權流程不同；access token／secret 是否另需，應依核准的操作確認，不先要求提供 Trade Me 密碼。[認證](https://developer.trademe.co.nz/api-overview/authorisation)
- 文件 shape：`TotalCount`、`TotalCountTruncated`、`Page`、`PageSize`、`List`；列表以 `ListingId` 識別，支援 `search_string`、`region`／`district`、`page`／`rows`。地區須使用官方 ID，不傳城市名冒充 ID。完整詳情還需確認對應讀取契約。
- 速率文件為 authenticated 預設每小時 1000 次（consumer／user 維度），實際核准額度可能不同；429 要退避。專案初始可採每秒不超過 1 次、每日執行，不代替官方限額。[限流](https://developer.trademe.co.nz/api-overview/rate-limiting)
- 本次只核對 `.env` 的 key 名稱，沒有 Trade Me 憑證；沒有送出職缺 API 請求、申請帳號或聯絡對方。

非 Catalogue API 要註冊且核准用途。條款第 31～33 項對重新使用、合併及保存資料有限制，因此 SQLite 歷史、跨來源去重、Telegram 通知與規格的保留期限都需在申請用途中確認，不能只拿到 key 就推定可做。[API 條款](https://developer.trademe.co.nz/terms-and-conditions)

原接入決策：取得核准之前禁用 live；若未來恢復此來源，可依文件獨立撰寫離線合成 fixture，必須標明 synthetic。本次只提供停用描述，不宣稱已取得真實 Trade Me 職缺；目前 SEEK-only MVP 不要求 Trade Me adapter／fixture tests。

## 6. 增量、本地紀錄與過期決策

1. **本地 SQLite 為唯一主要紀錄。** 即使上游增量恢復，仍保存來源 ID、內容 hash、版本、run／profile、觀察時間與通知待送狀態。
2. `stateKey` 只屬於上游追蹤狀態，不能取代本地去重或通知紀錄。變更搜尋語意須版本化，不能沿用造成錯誤消失訊號。
3. 原調查提出的備案是 `incrementalMode=false`＋本地 diff；範圍縮小後已納入新版設計，仍未實作或啟用。這取代原完整版第 9.1 節的增量推薦，普通模式重複輸出的成本須明確計算。
4. 普通模式可能每次重新輸出所有相同職缺，費用應按每次全部 emitted items 計算，不能套用僅新增／變動的增量成本假設。
5. 失敗、timeout、部分分頁、達到結果上限或 JS 空殼均不是可靠的完整快照，不能因缺席把職缺標為關閉。
6. Actor 的 `EXPIRED` 僅為離開其追蹤範圍的提示。原完整版設計會保留 `left_actor_tracking_universe` 並以可靠關閉證據確認；此過期處理已延後，不是 SEEK-only MVP 必做項目。刊登有效期不等於聘期的判斷仍適用。
7. Telegram 必須在本地正規化、WHV 判斷與 outbox 之後發送，不使用 Actor 直接推播取代這條流程。

## 7. 驗收清單與下一步

- [x] 各來源有入口、接入方案、權限／限流已知或未確認項目、解除條件。
- [x] SEEK 有普通 run、失敗 run、固定版本輸入契約與去識別欄位投影。
- [x] 其他來源保存 discovery／停用證據，明確不是完整 parser fixtures。
- [x] 本地 diff、上游狀態、失敗及過期的責任界線已記錄。
- [x] 參考 repository 授權盤點完成，未複製其程式碼。
- [x] 文件相對連結、JSON 可解析、敏感值未寫入及 Git 忽略規則已驗證。

下一階段依新 Roadmap 先完成 Profile、離線樣本與終端列表，再加入 WHV 及 Telegram。SEEK live 抓取仍須先解除來源權限問題；排程與 web UI 已延後。Phase 0 沒有執行不存在的單元／整合測試，文件檢查不等同端到端驗收。
