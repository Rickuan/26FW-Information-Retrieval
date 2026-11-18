# P8a 程式修復與輸出產物實作計畫 (Code & Output Patch)

## 1. 任務範疇與負責檔案
- 核心程式碼：`HW2/src/rank.py`、`HW2/src/search.py`
- 單元測試：`HW2/tests/t6.test.py`、`HW2/tests/t7.test.py`、`HW2/tests/t2_bonus.test.py`
- 產物目錄：`HW2/output/`（本地生成不入版控，打包交付使用）

## 2. 前置技術決策與改動設計

### A1. 同分排序依 6 位輸出精度 (`rank.py`)
- **問題**：原採 `(-score, doc)`，浮點數微差（1e-16）導致印出 6 位小數時呈現 docID 逆序（範例 query 共 803 處逆序）。
- **解法**：`hits.sort(key=lambda x: (-round(x[1], 6), x[0]))`。
- **效果**：保證輸出精度下嚴格依 docID 遞增，消除跨平台/硬體之 1e-14 浮點微差。

### A2. CLI 缺檔友善提示 (`search.py`)
- **問題**：`--scheme lnc.ltc` 缺 norm 檔或 `--champion-r 10` 缺檔時拋出 traceback。
- **解法**：在 `main()` 執行 `search_query` 處捕捉 `FileNotFoundError`，於 `sys.stderr` 輸出 `Error: {e}` 並附帶重建提示（若為 norms 提示 `build_norms.py`，若為 champions 提示 `build_champions.py`），以狀態碼 1 退出。

### A3. 拼字建議時機移至 top-k 截斷前 (`search.py`)
- **問題**：`search_query` 內部先截斷 `hits[:top_k]`，導致外部 `len(hits) < 20` 只要在 `top_k < 20` 時必觸發拼字檢查（多花 1.6s）。
- **解法**：
  - `search_query` 改為可選擇性回傳或由呼叫端掌控全量結果；或在 `search.py` 中於截斷前取得全量召回數判定是否觸發建議，再取前 top_k 筆格式化。

### A5. 測試套件跨平台容差 (`t2_bonus.test.py`)
- **問題**：`core_sha == sha_default` 比對二進位 hash，因不同 OS `libm` 浮點捨入可能差 1 ulp 導致失敗。
- **解法**：與 index 檔案比對放寬為 `abs(val1 - val2) < 1e-12` 數值比對。

---

## 3. 子工項 Checklist 與 Commit 規劃

- [ ] **Step 1: 修正同分排序精度 (A1)**
  - 修改 `HW2/src/rank.py` 排序鍵為 `(-round(x[1], 6), x[0])`。
  - 同步更新 `HW2/tests/t6.test.py` 斷言（驗證 6 位精度同分時以 docID 升冪排序）。
  - *Commit 建議*：`✨ feat(rank): sort tie-breaking by 6-decimal rounded precision`

- [ ] **Step 2: 修正 CLI 缺檔防呆與拼字時機 (A2, A3)**
  - 修改 `HW2/src/search.py`：
    - `main()` 捕捉 `FileNotFoundError`，印出清晰建置指令與退出碼 1。
    - 拼字建議門檻評估改依全量 hits 數量（`< 20`）而非截斷後數量。
  - 同步更新 `HW2/tests/t7.test.py` 測試。
  - *Commit 建議*：`🐛 fix(cli): handle missing files gracefully and fix spell check trigger timing`

- [ ] **Step 3: 調整測試跨平台容差與全量驗證 (A5)**
  - 修改 `HW2/tests/t2_bonus.test.py` 核心檔案核對為 1e-12 數值誤差。
  - 執行 `uv run python -m unittest HW2/tests/*.py` 確認全數通過。
  - *Commit 建議*：`🧪 test: add float tolerance for cross-machine tests and verify test suite`

- [ ] **Step 4: 重新產生輸出 ranked lists (A4)**
  - 執行 `uv run python HW2/src/search.py --queries HW2/queries.txt --output-dir HW2/output`。
  - 撰寫驗證腳本抽查 4 筆 query，確保 6 位小數同分時 docID 嚴格遞增（803 處逆序歸零）。
  - *Commit 建議*：`📝 chore(output): regenerate sample query ranked lists with strictly ascending ties`

- [ ] **Step 5: 工項驗收與歸檔**
  - 規劃檔改名為 `HW2/plans/.done.P8a-code-and-output-patch.md` 作為分支最後 commit。

