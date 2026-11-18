# NZ WHV Job Radar — SEEK-only MVP Roadmap

更新：2026-09-23。依[目前規格](NZ_WORKING_HOLIDAY_JOB_RADAR_SPEC.md)縮小範圍；本版階段定義取代先前的多來源／Dashboard Roadmap。

核心流程：**Profile → Apify／SEEK → 列出結果 → WHV filter → Telegram 通知**。

## 目前進度

- [x] Python 3.12.10、pip 與專案 venv 已確認可用。
- [x] Git 已初始化，`.env` 與 `venv` 已忽略。
- [x] 既有 Apify 普通模式、dataset 讀取及 Telegram 發送連通測試成功。
- [x] Phase 0：來源可行性調查及限制已記錄。
- [x] 滑雪場官方網站整理成[獨立參考目錄](docs/ski-resort-directory.md)。
- [x] MVP 收斂為 SEEK-only，原完整版已[保留為歷史參考](docs/archive/NZ_WORKING_HOLIDAY_JOB_RADAR_SPEC_FULL.md)。
- [x] Phase 1：Profile → SEEK → 結果列表；Phase 4 已補兩個 Profile 的限額 live 收集。
- [x] Phase 2：WHV filter、可解釋的標籤與離線測試。
- [x] Phase 3：Telegram、職缺保存與本地防重複；Phase 4 已補咖啡真實通知與重跑驗證。
- [ ] Phase 4：程式補強、763 個離線測試及文件已完成；滑雪場真實職缺通知仍缺正向樣本。

Phase 1 已有可執行 CLI、兩個 YAML Profile、Apify client、結果列表及本地 run／費用紀錄。
Phase 2 新增聘期／日曆月解析、WHV 分類、理由／證據／信心及通知政策候選統計。
Phase 3 新增職缺／版本保存、交易式 outbox、通知預覽、跨 Profile／版本／Chat 去重與明確啟用的 Telegram 發送。
詳見 [Phase 1 驗證紀錄](docs/phase1-verification.md)、[Phase 2 驗證紀錄](docs/phase2-verification.md)及 [Git Bash 操作說明](README.md)。
Phase 3 的命令與安全恢復見 [通知文件](docs/notifications.md)；[驗證紀錄](docs/phase3-verification.md)記錄 711 個測試及實際離線 CLI 結果。
Phase 4 使用者已確認來源許可與限額：實際 2 次啟動，合計回讀 US$0.032。咖啡送出 1 則並經使用者確認收到，滑雪場 3 筆皆被排除、未發送。詳見 [Phase 4 驗證紀錄](docs/phase4-verification.md)與[驗收指南](docs/acceptance-guide.md)；完整兩情境 live 驗收尚差滑雪場正向通知。

## Phase 0：已完成的調查

保留 [Phase 0 接入調查](docs/source-access.md)、[樣本](tests/fixtures/phase0/README.md)與[授權盤點](docs/reference-licenses.md)。

- 普通 SEEK 模式技術可用；增量模式因 `SEK-4002` 未通過。
- 本版先採普通模式＋本地差異比較，上游增量不再是 MVP 必要條件。
- Phase 0 當時 SEEK 資料使用許可待確認；Phase 4 使用者已確認蒐集、保存與通知用途並授權限額測試，並非另行獨立法律審查。
- Trade Me、NZSki、Cardrona／Treble Cone 及其他官網限制留作歷史／未來參考，不再是本版 MVP 的待解除障礙。

## Phase 1：定義 Profile、取得與列出結果

- 建立最小 Python 專案、依賴、設定驗證、CLI 與無密鑰的 `.env.example`。
- 定義 YAML profile，支援地點、關鍵字、職稱排除、雇主限制與結果上限。
- 提供咖啡服務與滑雪場兩個 SEEK 搜尋情境；新職缺類別以設定擴充。
- 先補完整合成 fixture，再實作正規化、Profile 匹配與終端列表。
- 接入 Apify 普通模式，保存 run ID、dataset ID，追蹤執行並分頁讀取結果。
- 限制結果、分頁、執行時間與預算；可從已知 run 恢復讀取，不盲目重啟付費 run。
- 顯示總數、Profile 排除原因、資料截斷、錯誤與費用；取得來源許可後才執行 live smoke。

完成判定：指定 profile 能列出符合條件的 SEEK 結果、原始連結及執行摘要；離線流程可獨立驗證。未做 live 的部分明確標示未驗證。

2026-09-23 實作狀態：上述程式已完成，普通模式啟動／輪詢／分頁／恢復透過離線 mock 測試。
僅提前建立 Phase 1 必需的 SQLite run／成本紀錄；職缺持久化、跨次差異與 outbox 仍屬 Phase 3。

## Phase 2：WHV filter

- 加入聘僱類型、聘期／日期與工作權文字的規則式抽取。
- 實作 likely_suitable／needs_confirmation／likely_incompatible、理由、證據與信心程度。
- 永久工作、明確超期與工作權衝突優先；seasonal／casual 期限不明不得變綠。
- 保留日曆月比較、邊界不明需確認、Full time 不等於 Permanent、刊登截止日不等於聘期。
- 顯示篩選前後統計，被排除通知的職缺仍可在終端查看。
- 測試日期邊界、資料缺失、硬性衝突及不誤傷咖啡訓練描述的服務職缺。

完成判定：每筆職缺都有可解釋的初步標籤，不把資料缺失當成符合資格；離線測試覆蓋正反例及邊界。

2026-09-23 實作狀態：有效且同批去重後的職缺均有評估，預設顯示 Profile 符合者；其他項目可用 `--show-excluded` 查看。
紅標仍保留於列表；通知政策僅計數，沒有 outbox／實際通知。新增 [WHV 規則文件](docs/whv-rules.md)及[獨立 Phase 2 架構圖](docs/architecture.md)，保留 Phase 1 圖。

## Phase 3：Telegram 與防重複

- SQLite 保存 run、職缺、Profile 匹配、重要版本與通知紀錄。
- 預設只推播綠／黃標；依 Profile 設定決定通知範圍。
- 同一 SEEK 職缺去重；已確認送達的相同版本跨 Profile 不再重送。
- 重要欄位或分類改變才建立更新通知，忽略抓取時間／排版變更。
- 使用交易式 outbox，加入有限重試及 delivery_unknown 的保守處理。
- 提供不發送 Telegram 的 dry-run；fixture 模式才保證完全不呼叫付費來源。

完成判定：重跑相同結果不重送已確認的通知；可預覽訊息、復原明確失敗；不承諾 Telegram 回應遺失時仍能保證 exactly-once。

2026-09-23 實作：預設只保存與列出，`--dry-run` 預覽，`--notify` 才在 live 模式建立待送紀錄並嘗試發送。
已保留原 run／成本資料，fixture 與 live 的 job key 分離；依 canonical SEEK ID＋重要版本＋目的 Chat 去重。
提供 `outbox`、`deliver --send`、`resolve-notification`，處理明確失敗、429 冷卻期限與 delivery_unknown 人工決策。
Phase 3 當時所有發送測試使用 mock；後續咖啡真實 Telegram 收件證據見 Phase 4 紀錄。
Phase 1–3 全套 711 個離線測試、Ruff、格式與 strict mypy 檢查通過。

## Phase 4：驗證與交付

- 兩個主要 Profile 都跑完結果列表 → WHV → Telegram。
- 加入設定錯誤、來源失敗、斷線恢復、部分結果及通知失敗的整合測試。
- 格式、lint、型別、單元與 fixture 測試通過。
- 來源許可確認後，做限額、明確啟用的端到端 live smoke；確認收到的是經 filter 的 Telegram 訊息，不是單純測試文字。
- 文件說明 Git Bash／Python venv 安裝、Profile 設定、手動執行、dry-run、重跑與錯誤排查。
- 驗證密鑰不進 Git／log，區分費用毛額、實際回讀資訊與未知的帳戶餘額。

完成判定：使用者可依文件在本機手動完成整條流程，重跑安全、判斷可理解、失敗可察覺。只通過離線測試不能宣稱 live MVP 完成。

2026-09-23 交付狀態：

- [x] 24 個只替換 HTTP 傳輸層的端到端案例，兩份 Profile 的正向流程與主要失敗／恢復分支皆覆蓋。
- [x] 新增通知上限，修正 canonical ID 去重及費用最高觀察值；全套 763 tests、Ruff、格式、strict mypy、pip check 通過。
- [x] Git Bash 操作、驗收步驟、架構說明與實際證據已更新，真實密鑰未出現在 Git 可見檔案／SQLite。
- [x] 兩次 live 收集均完整讀取本次 3 筆 dataset，保存 run／費用；不宣稱搜尋完整市場。
- [x] 咖啡 1 筆黃標通知、使用者收件核對、再次 resume 不重送。
- [x] 滑雪場 0 候選時不建立或發送通知。
- [ ] 滑雪場至少 1 筆符合條件的真實職缺 → Telegram → 人工收件；本輪不追加第 3 次啟動。

## 不納入本次驗收

Trade Me（連預設停用 adapter 也不做）、滑雪場／雇主官網監測、跨來源整合、Web Dashboard、收藏／申請狀態、定時排程、常駐服務、上游增量修復、推測過期、每日摘要與 LLM。

這些項目若日後需要再另排 Roadmap，不延續舊 Phase 3／4 成為隱含必做工作。滑雪場目錄是人工參考文件，不是 scraper 設定。
