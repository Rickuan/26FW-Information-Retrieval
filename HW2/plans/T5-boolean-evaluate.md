# T5 Boolean 求值引擎規劃

## 1. 目標
實作 `HW2/src/boolean.py` 之 `evaluate(node: Node, reader: IndexReader) -> set[int] | None`，遞迴求值 AST 產生布林候選 docID 集合，供下游 T6 VSM 排序使用。自由文字不作過濾回傳 `None`，布林與複雜查詢回傳 `set[int]`。

## 2. 上游依賴與接口
- **T1/T3 `writer.py`**：`reader.N`（總文件數）、`reader.df(term)`、`reader.get_doc_tf(term) -> (docs, tfs)`
- **T4 `parser.py`**：AST dataclass 節點（`Term`, `Phrase`, `Near`, `Wildcard`, `Soundex`, `Not`, `And`, `Or`, `Node`）
- **T4b `positional.py`**：`position_match(node: Phrase | Near, reader) -> set[int]`
- **M5 `skip_builder.py`**：引入至 `HW2/src/`，提供 `build_skip_list` 與 `intersect_with_skips`

## 3. 前置技術決策與求值語意
- **根節點為 `Term`**：回傳 `None`，代表自由文字查詢（不過濾），由 T6 累加器依詞項自然召回。
- **內部節點 `Term(tokens)`**：
  - 多詞代表隱含 AND，回傳包含其全部 tokens 之 doc 集合。
  - 若 `tokens` 為空，回傳 `set()`。
  - 任一 token 之 df == 0 或無 postings 時，直接 short-circuit 回傳 `set()`。
  - 使用 `get_doc_tf` 取得 docs，依 doc 串列長度由小到大兩兩交集（支援 skip list 加速）。
- **`And(children)`**：
  - 遞迴求值所有子節點得到集合串列；若子節點為根層 Term 退化，則視為不過濾。
  - 依集合大小由小到大排序後依序取交集；若中途集合為空則提早 short-circuit。
- **`Or(children)`**：
  - 遞迴求值所有子節點，取所有候選集合之聯集（`set.union`）。若無子節點回傳 `set()`。
- **`Not(child)`**：
  - 遞迴求值 child 得到子集 $S$；以全集 `set(range(reader.N))` 扣除 $S$ 回傳差集。
- **`Phrase` 與 `Near`**：
  - 呼叫 `positional.position_match(node, reader)` 取得符合位置約束之 doc 集合。
- **防呆例外**：
  - 輸入必須經過 `expand`；若樹中仍有 `Wildcard` 或 `Soundex` 節點，直接拋出 `ValueError`。

## 4. 自包含架構決策
- 將 `HW1/src/skip_builder.py` 引入至 `HW2/src/skip_builder.py`，保持 HW2 模組獨立自包含，避免跨作業目錄 import 造成的環境脆化。
- 對於純整數 docID 串列，提供包裝函式建構 `PostingWithSkip` 結構以呼叫 `intersect_with_skips`，兼顧演算法重用與效能。

## 5. 測試策略 (`HW2/tests/t5.test.py`)
- **小語料 Mock Index**：建立輕量 `MockIndexReader`（N=10，設定各 term 之 postings），無需依賴大磁碟 index 即可高速跑完單元測試。
- **節點求值覆蓋**：
  1. 根節點 Term 回傳 None；內部 Term 回傳包含所有 token 的 doc 集合。
  2. And 多子節點交集、short-circuit 空集合判定。
  3. Or 多子節點聯集。
  4. Not 反向差集、純 NOT 查詢（如 `NOT linux`）。
  5. Phrase 與 Near 位置呼叫整合。
  6. 巢狀複雜布林運算（如 `(A OR B) AND (C OR NOT D)`）。
  7. 邊界與例外防呆（未 expand 的 Wildcard / Soundex 拋錯）。

## 6. 子工項與進度追蹤
- [ ] **6.1 規劃檔建置**：產出專屬規劃檔 `HW2/plans/T5-boolean-evaluate.md`。
- [ ] **6.2 模組導入**：將 `skip_builder.py` 引入 `HW2/src/` 並確認介面相容。
- [ ] **6.3 核心實作**：於 `HW2/src/boolean.py` 實作 `evaluate()` 完整遞迴求值與 skip pointer 加速。
- [ ] **6.4 單元測試**：建立 `HW2/tests/t5.test.py`，驗證各節點、巢狀運算、純 NOT 與邊界防呆。
- [ ] **6.5 驗收與歸檔**：確認測試全數通過後，重新命名歸檔為 `.done.T5-boolean-evaluate.md`。
