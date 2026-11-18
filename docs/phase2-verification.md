# Phase 2 開發與驗證紀錄

日期：2026-09-23。範圍依 [SEEK-only Roadmap](../MVP_ROADMAP.md) 的 Phase 2。

## 結果

**Phase 2 程式與離線驗證完成**：Profile 結果已接上 WHV 初篩，提供標籤、分數、信心、理由、原文證據及待確認問題。
這不是完整 MVP 或真實來源的端到端驗收；Telegram、職缺持久化與跨次通知防重複仍屬 Phase 3。

本次未讀取或修改 `.env`、未呼叫 Apify／Telegram，也沒有啟動付費 Actor、擴大 Token 權限或新增套件依賴。
使用既有 Python 3.12 venv；若已完成 Phase 1 安裝，不需為 Phase 2 額外安裝套件。

## 已交付

| 部分 | 內容 |
|---|---|
| 聘期解析 | `tenure.py`：明示任職期間、起訖日、三個日曆月、月底／閏年及邊界判斷 |
| WHV 初篩 | `whv.py`：綠／黃／紅標、硬性衝突優先、保守必要條件、可回看的原文證據 |
| Pipeline | 有效且同批去重後的 Job 均評估；Profile 匹配與 WHV 結果分開保存於本次 Report |
| CLI | 文字與 JSON 顯示評估、規則來源／日期、免責說明；紅標仍可查看 |
| 通知政策 | 依 Profile 的 `notification_labels` 計算候選與抑制筆數，沒有建立佇列或發送訊息 |
| 執行摘要 | SQLite 增加分類數、規則資訊與候選計數；不保存逐筆職缺、評估或證據 |
| 文件 | [WHV 規則](whv-rules.md)、[Phase 2 架構圖](architecture.md)、[合成樣本說明](../tests/fixtures/phase2/README.md)；保留 Phase 1 架構圖 |

規則所依據的 [INZ 台灣打工度假官方頁面](https://www.immigration.govt.nz/visas/taiwan-working-holiday-visa/) 已於上述日期查核。
專案評分、信心及日期邊界是工程判斷，不是官方核准機率；綠標不保證使用者有資格接受工作。

## 實際執行的檢查

以下命令均在專案根目錄、既有 venv 中執行：

| 命令 | 結果 |
|---|---|
| `python -m pytest --tb=short` | **515 passed**，包含 Phase 1 回歸測試 |
| `python -m ruff check .` | 通過 |
| `python -m ruff format --check .` | 通過 |
| `python -m mypy src` | 11 個 source files，strict 型別檢查通過 |
| `git check-ignore` | `.env`、`venv/Scripts/python.exe`、`data/phase2-verification/runs.sqlite3` 均被忽略 |

pytest 由既有 autouse fixture 阻擋真實 socket，API 路徑使用 mock；不把 mock 測試視為外部服務驗收。

另以實際 CLI 重跑兩個 Profile，兩次均 exit code 0、費用 0：

```bash
python -m nz_job_radar run --profile auckland-cafe-service --fixture tests/fixtures/phase2/seek-synthetic.json --state-dir data/phase2-verification --format json
python -m nz_job_radar run --profile nz-ski-fields --fixture tests/fixtures/phase2/seek-synthetic.json --state-dir data/phase2-verification --format json
```

| Profile | 取得 | 符合 Profile | 排除 | 綠 | 黃 | 紅 | 通知候選／抑制 |
|---|---:|---:|---:|---:|---:|---:|---|
| `auckland-cafe-service` | 12 | 10 | 2 | 2 | 5 | 3 | 7／3 |
| `nz-ski-fields` | 12 | 2 | 10 | 1 | 1 | 0 | 2／0 |

兩者的 Profile 待確認、無效及重複筆數均為 0。表中的綠／黃／紅只計 Profile 符合者；全批 12 筆均評估，兩個 Profile 的全批統計皆為綠 3、黃 6、紅 3。
執行紀錄留在獨立、Git 忽略的 `data/phase2-verification/runs.sqlite3`，不覆寫使用者原本的 `data/runs.sqlite3`。
所有職缺都是合成資料，不可拿來應徵或當成真實招募通知。

## 重要回歸情境

- 永久工作、要求超過三個月及明確排除 WHV／限定公民居民，不能被歡迎 WHV 等正向分數抵銷。
- `Full time` 不推定永久；`Casual/Vacation`、`Contract/Temp` 可提供非永久類型證據，但不能單憑類型變綠。
- 不提供 sponsorship 不直接判紅；永久／不受限制工作權要求需確認，不誤作永久職缺。
- 明示兩個月、超期最低承諾、三個月邊界、日／週／月／年、月底與閏年、錯誤／極端日期。
- 過往工作經驗、過往聘僱、否定日期、刊登／截止日、試用期及訓練期不當作本職缺聘期；同文仍可辨識明確目前契約日期。
- 缺少雇主、國別或正文，不以高分補成綠標；替代、延長或矛盾條件保留待確認。
- 規則查核第 90／91 天的邊界、零筆結果的過期警告、過期規則停止給綠標，但不抹除硬性衝突。
- 證據保留來源欄位的原文短片段；通知標籤只改候選計數、不隱藏紅標；JSON／文字及 SQLite 彙總結果一致。
- 原 Phase 1 的 API 恢復、成本限制、來源許可閘門、資料正規化及離線不讀密鑰等測試持續通過。

## 未驗證與限制

1. 尚未用真實 Actor 資料驗收本版；[來源許可缺口](source-access.md)仍待確認，不能以 Phase 0 的連通紀錄取代。
2. 規則式解析只涵蓋已測試的常見英文措辭，不保證辨識所有寫法；未偵測到衝突不等於已證明相容。
3. 不驗證個人簽證、過往同雇主任職時間、全部法規條件或職缺是否仍有效。實際接受工作前仍須人工確認。
4. 規則版本為 `tw-whv-1.0`，查核日期 `2026-09-23`；超過 90 天需重新查核，不會自動連網更新。
5. 沒有職缺資料庫、跨次差異比較、通知 outbox、Telegram 發送／通知 dry-run、排程或 Web UI。

下一個開發階段為 Phase 3；本次沒有提前實作。
