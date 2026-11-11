# T6 VSM 排序引擎規劃

## 1. 目標
實作 `HW2/src/rank.py` 之 `rank(qtf, candidates, reader, scheme="ltc.ltc", champion_r=None) -> list[tuple[int, float]]`。
以向量空間模型（VSM）計算 query 與候選文件之餘弦相似度（Cosine Similarity），回傳依 `(-score, doc_num)` 嚴格排序的結果清單。

## 2. 上游依賴與接口
- **W `weighting.py`**：`weight(tf, df, N, scheme)` 計算 doc 與 query 各詞項權重。
- **T1/T3 `writer.py`**：
  - `reader.N`、`reader.df(term)`
  - `reader.get_doc_tf(term) -> (docs, tfs)`
  - `reader.get_norms(scheme) -> array('d')`
  - `reader.get_champions(term, r) -> (docs, tfs)`
- **T4 `parser.py`**：`query_terms(node) -> Counter[str]` 提供詞頻 $tf_{t,q}$。
- **T5 `boolean.py`**：`evaluate(node, reader) -> set[int] | None` 提供候選文件集合。

## 3. 前置技術決策與核心演算法

### 3.1 權重方案解析與邊界防呆
- **Scheme 解析**：輸入 `scheme` 格式為 `<doc_scheme>.<query_scheme>`（例如 `"ltc.ltc"`、`"lnc.ltc"`）。
  - 前後各自為 3 碼 SMART 標記；由 `doc_scheme` 與 `query_scheme` 分別呼叫 `weighting.weight`。
- **提早 Short-circuit 判定**：
  - 若 `candidates is not None and len(candidates) == 0`，直接回傳 `[]`。
  - 若 `qtf` 為空（如純 NOT 查詢無評分詞），直接回傳 `[]`。

### 3.2 Query 向量計算與長度正規化
1. 逐評分詞 $t \in \text{qtf}$，透過 `weight(qtf[t], reader.df(t), reader.N, query_scheme)` 計算 $w_{t,q}$。
2. 若 $df(t) == 0$ 或 $w_{t,q} == 0$，該詞不參與評分。
3. 計算 query 向量長度 $|q| = \sqrt{\sum_{t} w_{t,q}^2}$（若 query scheme 之 normalization 為 `'n'` 則 $|q| = 1.0$）。
4. 若全部詞項權重皆為 0 或 $|q| == 0$，直接回傳 `[]`。

### 3.3 Term-at-a-time (TAAT) 分子累加器
1. 初始化累加器 `acc: dict[int, float] = defaultdict(float)`。
2. 逐一走訪有效評分詞 $t$：
   - 資料來源：若 `champion_r` 有設定則呼叫 `reader.get_champions(t, r=champion_r)`；否則呼叫 `reader.get_doc_tf(t)`。
   - 走訪各篇命中文件 $(d, tf)$：
     - 若 `candidates is not None and d not in candidates` 則略過。
     - 計算 $w_{t,d} = \text{weight}(tf, reader.df(t), reader.N, doc_scheme)$。
     - 累加內積：`acc[d] += w_td * w_tq`。

### 3.4 餘弦相似度計算與同分排序
1. 透過 `reader.get_norms(doc_scheme)` 取得預存之全量文件長度陣列 `norms`。
2. 對所有累加命中之文件 $d$：
   - 若 $norms[d] <= 0$，略過。
   - $\text{score} = \frac{\text{acc}[d]}{norms[d] \times |q|}$。
   - 僅保留 $\text{score} > 0$ 者。
3. 依 `(-score, doc_num)` 排序（分數高者在前；分數完全相同時，依 `doc_num` 由小到大嚴格遞增）。

## 4. 測試策略 (`HW2/tests/t6.test.py`)
- **手算小語料 Mock 測試**：
  - 構造 3 篇文件微型索引，精準對照手算 cosine 分數至小數點後 6 位。
- **排序與同分 Tie-breaking 驗證**：
  - 構造相同分數之文件，驗證嚴格依 `doc_num` 遞增排序。
- **候選過濾（T5 整合）驗證**：
  - 對照 `candidates=None`（全域自由召回）與 `candidates={...}`（布林嚴格過濾）之召回文件子集。
- **加分項驗證**：
  - SMART scheme 切換（`ltc.ltc` vs `lnc.ltc`）。
  - `champion_r=50` 不精確 top-k 召回與評分流程。
- **真實 HW2 索引端到端測試**：
  - 執行作業範例查詢（`Microsoft`、`open source AND Linux`），驗證輸出非空、分數介於 (0, 1] 且嚴格遞減。

## 5. 子工項與進度追蹤
- [x] **5.1 規劃建檔**：建立 `HW2/plans/T6-vsm-rank.md`。
- [ ] **5.2 核心實作**：實作 `HW2/src/rank.py` 之 `rank()` 與 SMART scheme、TAAT 累加、cosine 正規化。
- [ ] **5.3 單元測試**：撰寫 `HW2/tests/t6.test.py`，覆蓋手算對照、同分排序、布林候選過濾、加分項與真實索引。
- [ ] **5.4 驗收歸檔**：測試全數通過後，同步更新 `ranked_retrieval_plan.md`，並將規劃檔歸檔為 `.done.T6-vsm-rank.md`。
