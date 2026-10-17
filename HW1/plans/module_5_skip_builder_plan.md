# Module 5：Skip Builder & AND Query — 實作計畫
> **檔案**：`HW1/src/skip_builder.py` | **狀態**：⬜ 待實作  
> **上游**：M3 `Indexer`（全記憶體模式） | **下游**：M4 Writer（binary format）

---

## 0. 變更紀錄（因應 M3 實作）

| 項目 | 原計畫 | 修改後 | 理由 |
|---|---|---|---|
| 🔄 執行模式 | — | 僅全記憶體模式；SPIMI 模式略過 | AND 查詢需隨機存取；SPIMI 建完後 `index` 為空 |
| 🔄 讀取索引 | 遍歷 `indexer.index` | `iter_postings()`（建 skip）、`get_postings()`（查詢） | 與 M3 介面一致 |
| 🔄 `PostingWithSkip.positions` | `list[int]`（複製） | 引用 `Posting.positions`（`array('I')`），不複製 | 1,183 萬筆 posting，複製會再增加數 GB |
| 🔄 skip 節點數 AC | `floor(P / L)` | `floor((P - 1) / L)` | P = 9、L = 3 時只有 index 0、3 可建（6 + 3 超界） |
| 🆕 查詢詞正規化 | — | 查詢前經過同一個 `Preprocessor` | casefold / stem 開啟時 `"Games"` → `game` |
| 🆕 重複查詢 | — | 不要在迴圈中對同一詞反覆呼叫 `get_postings()` | M3 欄式儲存每次取值都重新組出 Posting；高頻詞每次約 9 ms |
| 🆕 記憶體 AC | — | 量測 SkipBuilder 前後 Peak RSS | 確認可在一般機器執行 |

**M3 已提供的效能參考**（全量）：走訪全部 postings 約 3.5 s；`get_postings` 高頻詞（df 約 3 萬）每次約 9 ms、隨機詞約 0.01 ms。

---

## 1. 資料結構

```python
@dataclass(slots=True)
class SkipPointer:
    target_doc_num: int
    target_index: int

@dataclass(slots=True)
class PostingWithSkip:
    doc_num: int
    tf: int
    positions: array            # 🔄 引用 Posting.positions（array('I')），不複製
    skip: SkipPointer | None
```

**間隔策略**：`L = floor(sqrt(P))`；`P < MIN_SKIP_LEN = 9` 不建立  
**skip 位置**：index `0, L, 2L, ...`，且僅在 `i + L < P` 時建立

---

## 2. 工項與 AC

### Step 5-A：`build_skip_list`
- [ ] `build_skip_list(postings: list[Posting]) -> list[PostingWithSkip]`
  - `P < 9` → 全部 `skip=None`
  - 否則 index `0, L, 2L, ...` 且 `i + L < P` 設 skip 指向 `i + L`
  - 🔄 `positions=p.positions`（不要 `list(p.positions)`）

**AC**
- [ ] 🔄 帶 skip 的節點數 == `floor((P - 1) / L)`（P ≥ 9）
- [ ] `result[i].skip.target_doc_num == result[i + L].doc_num`
- [ ] `P < 9` 時所有節點 `skip is None`
- [ ] 🆕 `result[i].positions is postings[i].positions`（同一次 `get_postings` 結果內，確認未複製）

---

### Step 5-B：`SkipBuilder.build(indexer)`
- [ ] 🔄 `for term, plist in indexer.iter_postings():` 對每個 term 呼叫 `build_skip_list`
- [ ] 回傳 `dict[str, list[PostingWithSkip]]`（不修改 Indexer）
- [ ] 印出：有 skip 的 term 數、平均 skip interval
- [ ] 🆕 `indexer.spimi` 為 True 時印提示並回傳空 dict

**AC**
- [ ] 有 skip 的 term 數 == df ≥ 9 的 term 數（可用 `indexer.df(t)` 計算，不需組 Posting）
- [ ] 35K 文件完整索引處理 < 30 s
- [ ] 🆕 印出 build 前後 Peak RSS，增加量記錄於報告

**呼叫 M3 的方式**

| 工作 | 用什麼 |
|---|---|
| `SkipBuilder.build` — 走訪所有詞 | `iter_postings()`（全記憶體模式；SPIMI 模式直接略過） |
| 統計 df ≥ 9 的詞數 | `idx.df(term)`（不需組 Posting） |
| `intersect_*` / AND 查詢 | SkipBuilder 建好的結果 dict（不要每次查詢都呼叫 `get_postings()`） |

---

### Step 5-C：`intersect_with_skips`
- [ ] `intersect_basic(p1, p2) -> (list[int], int)`
- [ ] `intersect_with_skips(p1, p2) -> (list[int], int)`：
```
  i, j = 0, 0
  while i < len(p1) and j < len(p2):
      if p1[i].doc_num == p2[j].doc_num:
          result.append(p1[i].doc_num); i++; j++
      elif p1[i].doc_num < p2[j].doc_num:
          if p1[i].skip and p1[i].skip.target_doc_num <= p2[j].doc_num:
              i = p1[i].skip.target_index
          else: i++
      else:
          if p2[j].skip and p2[j].skip.target_doc_num <= p1[i].doc_num:
              j = p2[j].skip.target_index
          else: j++
```
- [ ] 🆕 `and_query(skips, preprocessor, q1, q2)`：查詢詞先經 `preprocessor.process()`；被停用詞移除時回傳空結果並提示；postings 一律從 `skips` dict 取（已建好，不重複呼叫 `get_postings`）

**AC**
- [ ] 兩演算法結果集完全相同
- [ ] skip 版比較次數 ≤ basic 版
- [ ] 高頻詞 pair（如 "game" AND "play"）比較次數減少 > 20%
- [ ] 🆕 casefold + stem 開啟時 `and_query(..., "Games", "play")` 與 `"game" AND "play"` 結果相同

---

### Step 5-D：`skip_builder.test.py`
- [ ] 5 組 term pair（長+短、高頻+高頻、無交集、df < 9）
- [ ] 輸出：`"game" (df=X) AND "play" (df=Y) → result=Z, basic=N1, skip=N2, speedup=N1/N2x`

**AC**
- [ ] 5 組結果均正確
- [ ] 表格可直接貼入報告
- [ ] 🆕 註明 Preprocessor 設定

---

## 3. 對外介面

```python
class SkipBuilder:
    MIN_SKIP_LEN: int = 9
    def build(self, indexer: Indexer) -> dict[str, list[PostingWithSkip]]: ...

def intersect_with_skips(p1, p2) -> tuple[list[int], int]: ...

def and_query(skips, preprocessor, q1: str, q2: str) -> tuple[list[int], int]: ...  # 🆕
```

> **注意**
> - 僅全記憶體模式；SPIMI 模式下略過，不影響 M4 評分輸出
> - `target_index` 為 list index；M4 binary 格式改存 byte offset
> - 「比較次數」：每次 `doc_num` 大小比較算一次
> - `get_postings()` 每次都重新組出物件：建好 `skips` 後一律從 dict 取用