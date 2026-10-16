# Module 5：Skip Builder & AND Query — 實作計畫
> **檔案**：`HW1/src/skip_builder.py` | **狀態**：⬜ 待實作  
> **上游**：M3 `Indexer.index` | **下游**：M4 Writer（binary format）

---

## 1. 資料結構

```python
@dataclass(slots=True)
class SkipPointer:
    target_doc_num: int   # 跳躍目標的 doc_num（用於比較）
    target_index: int     # 跳躍目標在 list 中的 index

@dataclass(slots=True)
class PostingWithSkip:
    doc_num: int
    tf: int
    positions: list[int]
    skip: SkipPointer | None   # None = 無 skip pointer
```

**間隔策略**：`L = floor(sqrt(P))`；`P < MIN_SKIP_LEN = 9` 不建立

---

## 2. 工項與 AC

### Step 5-A：`build_skip_list`
**工項**
- [ ] `build_skip_list(postings: list[Posting]) -> list[PostingWithSkip]`
  - `P < 9` → 全部 `skip=None`
  - 否則對 index `0, L, 2L, ...` 設 skip，指向 `index + L`（需 bound check）

**AC**
- 帶 skip 的節點數 == `floor(P / L)`
- `result[i].skip.target_doc_num == result[i + L].doc_num`
- `P < 9` 時所有節點 `skip is None`

---

### Step 5-B：`SkipBuilder.build(indexer)`
**工項**
- [ ] 遍歷 `indexer.index`，對每個 term 呼叫 `build_skip_list`
- [ ] 回傳新的 `dict[str, list[PostingWithSkip]]`（不修改原始 Indexer）
- [ ] 印出統計：有 skip 的 term 數、平均 skip interval

**AC**
- 有 skip 的 term 數 == df ≥ 9 的 term 數
- 35K 文件完整索引處理 < 30s

---

### Step 5-C：`intersect_with_skips` 演算法
**工項**
- [ ] `intersect_basic(p1, p2) -> (list[int], int)`：線性掃描，計比較次數
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

**AC**
- `intersect_basic` 與 `intersect_with_skips` 結果集完全相同
- skip 版本比較次數 ≤ basic 版本（對所有測試 pair）
- 高頻詞 pair（如 "game" AND "play"）比較次數減少 > 20%

---

### Step 5-D：效能評測腳本 `skip_builder.test.py`
**工項**
- [ ] 測試 5 組 term pair（長+短、高頻+高頻、無交集、df<9）
- [ ] 輸出格式：
  ```
  "game" (df=X) AND "play" (df=Y) → result=Z, basic=N1, skip=N2, speedup=N1/N2x
  ```

**AC**
- 5 組結果均正確（兩演算法輸出一致）
- 表格可直接貼入作業報告

---

## 3. 對外介面

```python
class SkipBuilder:
    MIN_SKIP_LEN: int = 9
    def build(self, indexer: Indexer) -> dict[str, list[PostingWithSkip]]: ...

def intersect_with_skips(
    p1: list[PostingWithSkip],
    p2: list[PostingWithSkip],
) -> tuple[list[int], int]: ...   # (matched_doc_nums, n_comparisons)
```

> **注意**：`target_index` 是 Python list index（記憶體用）；M4 binary 格式改存 byte offset。  
> 「比較次數」定義：每次 `doc_num` 大小比較算一次（兩演算法統一口徑）。
