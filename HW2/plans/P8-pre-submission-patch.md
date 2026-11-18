# P8 交件前修正與報告校正規劃 (Pre-submission Patch)

## 目標與技術決策

針對交件前之程式實作與報告進行盤點修訂。採雙軌平行架構，檔案邊界完全隔離：
- **Track 1 (Code & Output)**：專注 `src/`、`tests/` 與 `output/`，修復排序精度與 CLI 防呆。
- **Track 2 (Report & Doc)**：專注 `README.md`，修訂 TA 執行指引、事實數據與演算法描述。
- **Track 3 (Release)**：雙軌合流後執行交付驗收與 ZIP 打包。

### 核心技術決策
1. **同分排序鍵（A1）**：改為 `(-round(score, 6), doc)`。消除不同平台浮點計算 1e-14 微差，確保輸出 6 位小數時 docID 嚴格遞增。
2. **CLI 缺檔優雅提示（A2）**：`main()` 捕捉 `FileNotFoundError`，友善提示對應建置指令並以 code 1 退出，避免 bare traceback。
3. **拼字更正時機（A3）**：罕見結果判斷（`< 20` 筆）移至 `--top-k` 截斷前，避免合法小 top-k 查詢額外耗損 1.6s。
4. **報告數據據實校正（C1~C3）**：更新 Champion 實測數值（Exact Top-1 為 20949，Champion 為 9554）；修正原字 df（1 與 81）。

---

## 雙人分工與工作流 Checklist

### 👨‍💻 Track 1: 程式修復與輸出產物 (分支: `patch/HW2-feature-patch`，見 `.done.P8a-code-and-output-patch.md`)
- [x] **A1. 排序鍵精度修正** (`HW2/src/rank.py`)：排序鍵改為 `(-round(score, 6), doc)`，消滅 4 筆 query 的 803 處逆序。
- [x] **A2. CLI 缺檔防呆** (`HW2/src/search.py`)：`main()` 捕捉 `FileNotFoundError` 並提示重建指令。
- [x] **A3. 拼字建議時機優化** (`HW2/src/search.py`)：`len(all_hits) < FEW_RESULTS_THRESHOLD` 移至 `top_k` 截斷前評估。
- [x] **A5. 跨機器測試容差** (`HW2/tests/t2_bonus.test.py`)：`core_sha` 比對改為 1e-12 數值誤差容忍。
- [x] **單元測試驗證**：全量 12 套測試皆全數通過。
- [x] **A4. 重新產出範例輸出** (`HW2/output/`)：執行 `--queries HW2/queries.txt --output-dir HW2/output`，驗證同分 docID 嚴格遞增（0 逆序）。

### 📝 Track 2: 報告校正與 TA 執行防呆 (分支: `docs/readme-correction`)
- [ ] **B1. 索引檔案清單校正** (`HW2/README.md`)：補上 `doc_norms.bin`、`champions.r50.*`，移除 `dictionary.txt`，註明請直接使用附檔。
- [ ] **B2. 重建指令參數修復**：`build_norms` 加入 `--index-dir`；`build_champions` 改為 `--r 50`。
- [ ] **B3. 環境描述**：改為「需 Python ≥ 3.12、uv；數據在 Python 3.12 環境量測」。
- [ ] **B4. 權重方案前提**：補充說明非 ltc 需先建 norm 檔、champion 僅預建 r=50 之限制。
- [ ] **B5. 同分排序描述更新**：說明 6 位精度同分 docID 遞增，同步改寫困難 #5 之解法。
- [ ] **C1. 實驗三 Champion 數據**：更新為真實數據（精確 Top-1 20949 vs Champion 9554，重疊 2 篇）或精簡刪除。
- [ ] **C2. 實驗二 Skip 數據**：更新實際比對數據（密集串列 +1.1%）或刪除，修飾 96 行「超過 90%」。
- [ ] **C3. 拼字建議數據**：修正為原字 df（retreival 1 / retrieval 81），補齊 `df == 0` 與 `≥ 10x` 觸發條件。
- [ ] **D1~D8 & E 功能精準化與文字微調**：
  - [ ] D1. 萬用字元：補充 substring wildcard 支援任意位置 `*`（如 `co*tion`）。
  - [ ] D2. 布林運算：釐清多詞 Term（隱含 AND）用 skip pointer，顯式 And 採集合交集。
  - [ ] D3. Proximity：改為兩側區間間隔 ≤ k，不分先後，重疊不算。
  - [ ] D4. 效能分析：修正為單次 `get_doc_tf` 呼叫加速 3.5 倍（非整體檢索）。
  - [ ] D5. 移除「mmap 與記憶體映射」冗詞。
  - [ ] D6. 註明 LRU 快取為 API 選項，CLI 預設關閉。
  - [ ] D7. 說明 Champion List 依 tf 選取前 50 名，結果不精確。
  - [ ] D8. 說明批次查詢 `--output-dir` 與 stdout 行為。
  - [ ] E. 文字修飾（公式在 weighting 實作一次、無查詢向量短路、修正「重覆」、精確語料命名）。

### 🤝 Track 3: 最終合流與交件打包 (Release Track)
- [ ] **分支合併**：發起 PR 並確認兩軌無衝突合併至主分支。
- [ ] **F. 打包檢查清單**：
  - [ ] 確認 ZIP 包含 `HW2/index/`（含 norms、champions、surface）、`HW2/src/`、`HW2/output/`、設定檔與報告。
  - [ ] 確認報告含組員姓名與學號。
  - [ ] 確認 ZIP 檔案大小符合 iSchool+ 限制。
  - [ ] 於乾淨目錄解壓縮，依 README 指令實測端到端檢索。

