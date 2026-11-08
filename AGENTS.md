# AI 代理人協同開發指引 (AGENTS.md)

本文件定義 AI 代理人與協同開發者的工作規範與行為準則。全文分為兩大部分：
- Part I：通用規範，可抽象化複用至其他專案 repos 的協作與工程標準。
- Part II：本專案專屬規範，針對本儲存庫（26FW-Information-Retrieval）的特定環境、模組與路徑約定。

---

# Part I: 通用 AI 協作與工程規範

## 1. 藍圖規劃、工項拆解與分支管理

### 1.1 專案藍圖
專案或大版本啟動時，應具備一份頂層藍圖檔：`.BLUEPRINT.[專案名稱].md`（例如 `.BLUEPRINT.build-garden.md`），作為整體規格與架構的單一真實來源。藍圖中記錄整體架構、模組切分、各階段驗收標準，以及各工項的清單與相依性。

### 1.2 工項拆解與獨立分支
執行任何大任務前，必須根據藍圖拆解為具體、獨立的子工項。每個工項遵循「一工項、一分支、一規劃檔」原則：
- 每個工項對應獨立分支（如 `feat/plantAppleTree`）與一份專屬規劃檔（如 `plans/P1-plant-apple-tree.md`）。
- 嚴禁不同工項在同一分支混雜開發，確保多人或多代理人並行時不受版控干擾。

### 1.3 越界問題之即時開票機制
若在開發分支（如 `feat/plantAppleTree`）過程中，發現不在當前 scope 內的 bug 或新需求：
1. 嚴禁順手修改，切勿改動當前分支中與本次工項無關的程式碼。
2. 暫存當前工作（若有未提交變更，先執行 `git stash`）。
3. 從最新的 `main` 或 `dev` 切出獨立文件分支（例如 `docs/planToBuyAx`）。
4. 僅新增相應的 planning 檔案（例如 `plans/P2-buy-ax.md`），並將該工項同步登記回頂層 `.BLUEPRINT.[專案名稱].md` 中。
5. 提交並發起 PR 合併回 `main` 或 `dev` 完成建檔開票。
6. 切回原開發分支（若有暫存則執行 `git stash pop`），繼續完成原本範圍內的工作。

### 1.4 分支安全守則
- 每次 commit 前必須主動確認當前分支。
- 嚴禁直接在保護分支（如 `main`, `dev`, `prod`）上進行 commit 或 push。若處於保護分支，應立即切換或建立對應的 feature branch。
- 嚴禁未經使用者同意下達破壞性指令（如 `git push --force`, `git reset --hard`, `git clean -fd`）。

### 1.5 Pull Request 流程與主動提醒
- 進行中或尚未完全驗收的工項，一律建立 Draft PR。
- 每次完成 `git push` 後，AI 必須主動詢問使用者：是否需要為此分支開立指向目標分支（如 `main` 或 `dev`）的 Draft PR。
- PR 標題必須與 commit 格式完全一致，並附帶對應之 Gitmoji。

---

## 2. Planning 規劃檔案規範

每個工項開工前，必須與 AI 共同協作產出一份專屬的 planning 檔案：

1. 存放路徑與命名：存放於專案或子模組下的 `plans/` 資料夾（例如 `plans/[工項編號]-[名稱].md`，如 `plans/P1-plant-apple-tree.md`）。
2. 前置技術決策：規劃階段必須完成所有可預見的技術決策、架構設計與邊界考量，避免邊寫邊猜。
3. 高層抽象化描述：planning 檔案應以抽象化、架構化的方式描述邏輯流程、介面定義與資料流，不應出現大段具體程式碼。
4. 決策理由與落差記錄：簡要記錄技術選型與架構決策原因。若實作過程中與原計劃出現偏差，需記錄實作與計劃的差別，以及彌補方式或評估不需彌補的理由。
5. 子工項追蹤與 commit 粒度：提供 checklist 追蹤完成狀態。每個子工項的粒度應對應為 1 個或多個獨立的 commit。
6. 長度上限：每個 planning 檔案必須精簡在 130 行以內，聚焦重點架構與進度，維持人類最佳可讀性。
7. 工項完成與歸檔：當一個 feature 開發與驗收完畢，將該檔案重新命名加上 `.done.` 前綴（例如 `plans/P1-plant-apple-tree.md` → `plans/.done.P1-plant-apple-tree.md`），作為該分支的最後一次 commit。

---

## 3. 程式碼品質與單元測試

1. 單元測試全覆蓋慣例：除非特例，每個功能檔案與模組皆需撰寫對應的單元測試。測試檔案命名採鄰近原則：`[filename].test.[ext]`（例如 `buyApple.py` → `buyApple.test.py`、`parser.ts` → `parser.test.ts`）。
2. Commit 前強制驗證防呆：
   - 凡涉及程式碼邏輯變更的 commit，AI 必須在終端實際執行相應的測試套件並確認通過。
   - 嚴禁在未執行測試或測試失敗的狀態下建立 commit。
   - 純文件（如 planning 檔案、markdown）或純註解的變更可免除測試驗證。
3. 既有測試保護原則：
   - 遇到既有測試失敗時，應優先檢查並修正業務邏輯實作。
   - 嚴禁為了讓測試通過而擅自竄改或放寬既有測試的斷言條件。若因規格調整必須修改測試，需主動向使用者說明原因。
4. 註解保護：修改程式碼時，保留與變更無關之既有註解與 docstring，切勿隨意刪除。

---

## 4. Commit 規範與顆粒度限制

### 顆粒度限制
為了便於審查與歷史回溯，每個 commit 應維持小型原子化變更：
- 檔案數限制：單一 commit 變更檔案數建議在 5 個檔案以內。
- 行數限制：單一 commit 程式碼變更行數建議在 200 行以內。
- 豁免條件：自動生成的依賴 lockfile（如 `uv.lock`, `package-lock.json`）或二進位/大型資料檔，不受 200 行限制。

### 格式規範
```
[gitmoji] [分類：feat/doc/chore...][(optional: scope)]: [title]
```

- 範例：
  - `📝 doc(plan): add user slice planning for phase 6 main pipeline`
  - `✨ feat(skip): implement intersect_with_skips for postings`
  - `🐛 fix(indexer): handle edge case when term frequency is zero`
  - `🧪 test(writer): add round-trip validation for binary postings`
  - `⚡️ perf(tokenizer): optimize token normalization loop`
  - `🔧 chore(deps): add psutil to project dependencies`

### 分類 (Type)
- `feat`: 新增功能模組或演算法
- `fix`: 修復程式錯誤或邊界條件問題
- `doc`: 實作計畫文件、說明文件、註解調整
- `test`: 新增或調整單元測試、整合測試
- `perf`: 效能優化（記憶體減少、執行加速）
- `refactor`: 重構程式碼（不改變外部功能行為）
- `chore`: 設定檔調整、依賴管理、環境配置

### 常用 Gitmoji 對照表
| Gitmoji | 簡碼 (Shortcode) | 適用分類 | 說明 |
|---|---|---|---|
| 📝 | `:memo:` | `doc` | 撰寫文件、規格、註解 |
| ✨ | `:sparkles:` | `feat` | 新增功能 |
| 🐛 | `:bug:` | `fix` | 修復 bug |
| 🧪 | `:test_tube:` | `test` | 增加或修復測試 |
| ⚡️ | `:zap:` | `perf` | 提升效能、減少記憶體 |
| ♻️ | `:recycle:` | `refactor` | 重構程式碼 |
| 🔧 | `:wrench:` | `chore` | 修改設定檔或環境 |
| 🚚 | `:truck:` | `refactor` / `chore` | 移動或重新命名檔案 |

---

## 5. 依賴套件管理紀律

1. 嚴禁未經確認新增第三方套件：優先評估使用標準函式庫或現有依賴。若有新增必要，必須先向使用者說明原因與替代方案，取得同意後再安裝。
2. 使用指定套件管理器：安裝套件必須使用專案規定的管理工具（例如 `uv add`、`npm install`），並確保 lockfile 一併提交版控。
3. 保持藍圖乾淨：藍圖檔案僅記錄功能規格與工項，不混入底層套件宣告。

---

## 6. 停步諮詢與資源防耗守則

1. 歧義與衝突停步：當需求規格不明確、與既有架構產生衝突、或有多種方案各有顯著優缺點時，AI 必須停下來向使用者提出條列式選項與評估，嚴禁擅自通靈或盲猜實作。
2. 長時與高消耗任務前置確認：若自動化驗證、腳本執行或測試套件預期執行時間長、消耗大量運算資源或燒費大量 token，執行前必須主動告知預估成本與耗時，取得確認後再執行。

---

# Part II: 本專案專屬規範

> 專案名稱：26FW Information Retrieval (`26FW-Information-Retrieval`)  
> 作業目標：HW1 Inverted Index & Skip Pointers Pipeline

### 1. 開發環境與依賴管理
- Python 版本：Python 3.12+
- 套件管理工具：全面使用 `uv` 進行管理。
  - 執行指令：`uv run python ...`
  - 依賴安裝：`uv add [package]`
  - 測試指令：`uv run python -m unittest HW1/src/*.test.py` 或執行指定測試檔
  - 虛擬環境啟動：`.venv`

### 2. 目錄結構與規劃檔位置
- 作業主目錄：`HW1/`
  - 核心程式碼：`HW1/src/`
  - 單元測試：`HW1/src/*.test.py`（與被測模組同目錄）
  - 規劃檔案位置：`HW1/plans/`（例如 `HW1/plans/inverted_index_plan.md`）
  - 完成規劃檔封存：`HW1/plans/.done.*.md`

### 3. 模組階段與驗收驗證 (M1 ~ M5)
作業依照流水線切分為五大核心模組：
- M1: Loader / Warc Extractor (`warc.py`, `extract.py`)
- M2: Tokenizer & Preprocessor (`tokenizer.py`)
- M3: Indexer & SPIMI Engine (`indexer.py`, `documents.py`)
- M4: Binary Postings Writer & Lexicon (`writer.py`, `trie.py`)
- M5: Skip List Builder & Intersect (`skip_builder.py`)

每個模組均有對應之驗收條件，提交各工項前須確保對應之單元測試與端對端驗證全數通過。
