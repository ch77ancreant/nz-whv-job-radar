# Phase 0 樣本與證據

查核日期：2026-09-23。這些是接入調查素材，不代表 adapter 或測試套件已實作。

範圍更新：目前僅開發 [SEEK-only MVP](../../../NZ_WORKING_HOLIDAY_JOB_RADAR_SPEC.md)。NZSki、Cardrona、Trade Me 的 discovery／停用檔案僅保留為歷史證據，不代表本版要建立其 adapter 或完成 fixture tests。

| 檔案 | 性質 | 能驗證什麼／不能驗證什麼 |
|---|---|---|
| [seek-runs.json](seek-runs.json) | 真實 run metadata 投影、實際輸入、固定 build 的 schema 節錄 | 成功／失敗、成本、API contract；不是完整帳單或增量成功證據 |
| seek-item-projection.json（公開版已移除） | 真實 dataset item 的白名單欄位投影 | 含第三方職缺內容，未確認再利用權限前不公開；欄位結構摘要見[來源接入調查](../../../docs/source-access.md) |
| [nzski-discovery.json](nzski-discovery.json) | 真實官方連結與 Dayforce 初始頁欄位投影 | 確認 ATS 入口、只有 site-info 的 shell；不是職缺列表 |
| [cardrona-discovery.json](cardrona-discovery.json) | 真實招聘入口、robots wildcard group 節錄 | 保存停用依據；沒有讀取受禁止 ATS 的職缺列表 |
| [trademe-disabled.json](trademe-disabled.json) | 本地停用狀態與官方文件契約摘要 | 缺少核准存取的交接資訊；不是 API response，也不是合成職缺 |

## 使用邊界

- 所有 JSON 都有 provenance／資料性質。projection 表示已刪除欄位，不能當作完整原始回應；不可把省略欄位誤當上游從未存在。
- SEEK item 的 `item` 保留選定原始值；`descriptionExcerpt` 與 `observedShape` 是本地整理的 metadata，不是 Actor 的新欄位。描述僅取最前 20 個空白分隔字，沒有完整複製刊登正文。
- 原始 `contentHash` 是完整上游內容的提示，不能用此刪減樣本重算後要求相等。本地 hash 規則將在 Phase 1 定義。
- 原始日期與職缺連結保留用於 schema 稽核；公開版已將 Apify run／dataset／key-value store ID 換成 `Synthetic…` 假值；這不是目前仍開放職缺的保證。`validThrough` 不代表聘僱期限。
- 未保存 Token、Chat ID、Authorization header、cookie、Dayforce session、求職者資料、聯絡人、電話、email 或社群欄位值。
- 這些第三方資料節錄僅作本地調查。公開發布 repository 前仍應核對內容再利用權限；未授權時改用明確標示 synthetic 的樣本。
- 後續需另加完整的合成描述、screeningQuestions、空結果、部分結果及來源錯誤案例。不能用此一筆投影假稱已涵蓋正規化及 WHV 判定。重刊與上游增量事件測試隨相關功能延後。
- NZSki／Cardrona／Trade Me 以規格允許的 blocked／disabled 路徑結束 Phase 0，沒有用一般 FAQ 或空陣列冒充真實職缺 fixture。

更多決策見[來源接入調查](../../../docs/source-access.md)。一般測試不得觸發付費 Actor；未來 live smoke 需明確啟用、限制預算並保存 run ID。
