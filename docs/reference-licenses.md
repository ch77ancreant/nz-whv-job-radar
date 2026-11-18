# Phase 0：參考專案授權盤點

查核日期：2026-09-23。依規格第 26 節，透過 GitHub 公開 repository metadata／根目錄核對；這不是完整授權或安全稽核。本次沒有複製程式碼、加入依賴或套用任何 repository 的程式實作。

| 參考專案 | 本次觀察 | 決策 |
|---|---|---|
| [BlackFalconData-org/seek-scraper](https://github.com/BlackFalconData-org/seek-scraper) | GitHub license=null；根目錄僅 README | 視為 hosted Actor 的文件參考，不當作可自由複製的 scraper 原始碼 |
| [giussepe198/trademe-mcp](https://github.com/giussepe198/trademe-mcp) | license=null；根目錄未見 LICENSE，README License 仍為 placeholder | 不複製實作；未來依 Trade Me 官方 API 自行撰寫 |
| [dgtlmoon/changedetection.io](https://github.com/dgtlmoon/changedetection.io) | metadata 辨識 Apache-2.0，根目錄有 LICENSE | 暫不引入；確有需要時固定版本、逐檔確認授權並保留要求的聲明 |
| [GEOFAIRY/Seek-Job-Scraper](https://github.com/GEOFAIRY/Seek-Job-Scraper) | license=null，最後 push 為 2022-12-08 | 僅參考概念，不複製程式；年代久也不能證明仍能執行 |
| [ScottCoffin/Job_Scraper](https://github.com/ScottCoffin/Job_Scraper) | metadata 辨識 AGPL-3.0 | 不納入 MVP；若要衍生／整合，先審查 copyleft 與網路使用相關義務 |
| [speedyapply/JobSpy](https://github.com/speedyapply/JobSpy) | metadata 辨識 MIT | 非必要 NZ 來源，不納入；日後使用需核對實際版本 LICENSE 與來源條款 |
| [TheDevRo/Jobsmith](https://github.com/TheDevRo/Jobsmith) | metadata 辨識 AGPL-3.0 | 超出 MVP，不複製實作 |

`license=null` 只代表未確認可用授權，不等於沒有著作權或可任意使用。metadata 的 SPDX 標籤也不是逐檔授權保證；沒有固定 commit 和完整 LICENSE 審查前，不宣稱已核准複製。

程式授權、API 服務條款、職缺內容使用權是三件不同的事。MIT／Apache／AGPL 均不替本專案取得 SEEK、Trade Me 或雇主資料的存取許可。來源限制見[接入調查](source-access.md)。
