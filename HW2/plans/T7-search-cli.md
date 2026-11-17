# T7 CLI 查詢介面與輸出模組規劃

## 1. 目標
實作 `HW2/src/search.py` 之 CLI 入口與查詢函式 `search_query()`。
串接 Preprocessor、Parser (T4)、Boolean (T5)、VSM Rank (T6)，提供單一與批次查詢介面，輸出標準 `<doc#> <score>` 格式，並整合拼字建議 (T4c) 與錯誤處理防呆。

## 2. 上游依賴與接口
- **T1 `writer.py` / `tokenizer.py`**：
  - `IndexReader(index_dir)`：載入索引，提供 `reader.N`、`reader.get_metadata()`
  - `Preprocessor.from_config(metadata["preprocessor"])`：嚴格還原前處理設定
- **T4/T4b/T4c `parser.py` / `spelling.py`**：
  - `parse(query, pre) -> Node | None`：語法解析 AST，錯誤拋出 `ValueError`
  - `expand(node, reader) -> Node | None`：原字展開 Wildcard / Soundex
  - `query_terms(node) -> Counter[str]`：提取評分詞項與詞頻 $tf_{t,q}$
  - `query_words(query, pre) -> list[str]`、`did_you_mean(word, reader) -> list[str]`
- **T5 `boolean.py`**：`evaluate(node, reader) -> set[int] | None` 取得候選文件集合
- **T6 `rank.py`**：`rank(qtf, candidates, reader, scheme, champion_r) -> list[tuple[int, float]]`

## 3. CLI 規格與前置技術決策

### 3.1 命令行參數介面
```bash
uv run python HW2/src/search.py --index-dir HW2/index [--top-k K] [--queries FILE] [--scheme SCHEME] [--champion-r R] [query]
```
- `query`：位置參數，單一查詢字串（與 `--queries` 二擇一，兩者皆無時報錯退出）。
- `--index-dir`：索引目錄路徑，預設為 `HW2/index`（缺檔時印出錯誤訊息並以非 0 代碼退出）。
- `--top-k`：整數，截斷輸出排名前 K 筆結果；預設 `None` 輸出所有 `score > 0` 的文件。
- `--queries`：批次查詢檔案路徑，每行一個 query。
- `--scheme`：SMART 方案標記，預設 `ltc.ltc`。
- `--champion-r`：整數，開啟 Champion list 不精確 top-k（預設 `None` 關閉）。

### 3.2 查詢管線與輸出格式
1. **執行流程**：
   - 載入 `IndexReader` 與 `Preprocessor`。
   - `node = parse(query, pre)`：語法錯誤（未配對引號/括號等）捕獲並在 stderr 報錯，CLI exit code 為非 0（exit 1）。
   - `node = expand(node, reader)`：展開萬用字元與 Soundex 運算子。
   - `cands = evaluate(node, reader)`：Boolean 候選過濾（自由文字回傳 None）。
   - `qtf = query_terms(node)`：提取查詢詞頻；若 `qtf` 為空（如純 NOT 查詢）直接回傳空結果。
   - `hits = rank(qtf, cands, reader, scheme=scheme, champion_r=champion_r)`。
   - 若有 `--top-k` 參數，截斷 `hits = hits[:top_k]`。
2. **標準輸出 (stdout) 規範**：
   - 每行格式：`<doc#> <score:.6f>`（例如 `28281 0.185707`，以單一空白分隔，無表頭）。
   - 排序保證：T6 已保證依原始分數降冪、同分依 `<doc#>` 升冪。
   - 批次模式：若使用 `--queries`，依序印出各 query 結果，或支援 query 間隔格式。
3. **stderr 提示與拼字建議整合（加分 7）**：
   - 當單一查詢之 `len(hits) == 0` 時，呼叫 `spelling.did_you_mean(word, reader)` 檢驗 `query_words`。
   - 若有顯著候選建議詞，於 `stderr` 輸出 `Did you mean: <word> -> <suggestion>`，嚴格不污染 `stdout`。

## 4. 測試策略 (`HW2/tests/t7.test.py`)
- **參數解析與防呆**：
  - 缺少 query 與 `--queries` 時拋錯退出；非法 top-k 或 scheme 參數檢驗。
  - `--index-dir` 不存在時檢驗非 0 退出碼。
- **標準輸出格式檢驗**：
  - 單一詞查詢（`Microsoft`）輸出符合 `<doc#> <score>` 格式，小數點後精確至 6 位。
  - 同分破除驗證（同分時 docID 升冪）。
  - `--top-k` 截斷長度正確性。
- **批次查詢測試**：
  - 輸入多行 queries 檔案，檢驗逐行檢索與輸出。
- **異常與邊界測試**：
  - 語法錯誤（如 `"open source` 缺少結尾引號）捕獲並以 exit code != 0 退出。
  - 純 NOT 查詢（`NOT linux`）或無結果查詢，驗證輸出空（exit code 0）。
- **加分項串接**：
  - 驗證 stderr 輸出之 `did_you_mean` 拼字建議。
  - 驗證 `--scheme` 與 `--champion-r` 參數正確透傳至 T6。

## 5. 子工項與進度追蹤
- [x] **7.1 規劃建檔與分支切換**：建立 `HW2/plans/T7-search-cli.md`，確認依賴接口。
- [x] **7.2 核心查詢函式實作**：實作 `search_query()` 端到端整合查詢管線。
- [ ] **7.3 CLI 介面與參數解析**：實作 `HW2/src/search.py` 之 `main()` 與 argparse 設定。
- [ ] **7.4 拼字建議整合與防呆**：整合 stderr 拼字建議與語法/缺檔例外處理。
- [ ] **7.5 單元與端到端測試**：撰寫 `HW2/tests/t7.test.py`，覆蓋所有 CLI 參數、輸出格式與邊界。
- [ ] **7.6 範例 Query 產出**：執行 4 組作業範例 query，輸出至 `HW2/outputs/*.txt`。
- [ ] **7.7 驗收與歸檔**：同步更新 `ranked_retrieval_plan.md`，並將規劃檔歸檔為 `.done.T7-search-cli.md`。
