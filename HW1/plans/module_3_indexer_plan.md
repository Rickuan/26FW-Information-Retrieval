# Module 3：Inverted Indexer (SPIMI) — 實作計畫
> **檔案**：`HW1/src/indexer.py`、`HW1/src/trie.py` | **狀態**：✅ 已完成  
> **測試**：`HW1/src/indexer.test.py`、`HW1/src/indexer_features.test.py`  
> **上游**：M1 `iter_documents()` + M2 `Preprocessor.process()` | **下游**：M4 Writer、M5 Skip Builder

---

## 0. 演進紀錄（實作過程與數據）

全量 04.warc（34,786 篇、644,523 詞、27,549,214 個位置、11,834,013 筆 posting），預設 Preprocessor（casefold only）。

| 版本 | 內部儲存 | 全記憶體 Peak RSS | 建置時間 | SPIMI Peak RSS | 紀錄 |
|---|---|---|---|---|---|
| v1 | `dict[str, list[Posting]]`，`positions: list[int]` | 3,712 MB | 368 s | — | `indexer.test.py` 全量輸出 |
| v2 | 同上，`positions: array('I')` | 3,167 MB（−15%） | 362 s | 855 MB（412 s，merge 18 s） | `logs/bench_memory.txt`、`logs/bench_spimi.txt` |
| v3（現行） | 欄式儲存：每詞 3 個 `array('I')`（docs / tfs / pos） | **1,110 MB（−70% vs v1）** | 375 s | **604 MB**（380 s，merge 6 s） | `logs/bench_memory_columnar.txt`、`logs/bench_spimi_columnar.txt` |

### v1 → v2：`list[int]` → `array('I')`
- **做法**：`Posting.positions` 由 list 改為 `array('I')`（每個位置 4 bytes）
- **結果**：只省 15%，低於預期
- **原因**：平均每筆 posting 僅約 2.3 個位置；array 物件本身的固定開銷（約 64–80 bytes）比小 list 大；Python 會快取 0–256 的小整數，list 原本只存 8 bytes 指標。真正吃記憶體的是「1,183 萬個 `Posting` 物件 + 1,183 萬個 array 物件」本身

### v2 → v3：欄式儲存
- **做法**：每個詞只存 3 個連續陣列，不再為每筆 posting 建立物件
```
  "computer" → docs = [12, 87, 301]
               tfs  = [2, 1, 4]
               pos  = [5, 40, 3, 1, 9, 22, 30]   # 依序串接；第 k 筆 = pos[sum(tfs[:k]) : sum(tfs[:k+1])]
```
  物件數由約 2,366 萬降為約 260 萬（詞彙數 × 4）
- **對外介面不變**：`iter_postings()` / `get_postings()` / `index[term]` 在讀取時才組回 `list[Posting]`
- **結果**：全記憶體 3,167 → 1,110 MB（−65%）；SPIMI 855 → 604 MB；SPIMI merge 18 → 6 s（pickle 連續 array 比大量 tuple 快）
- **代價（讀取端，見 `logs/bench_m4_read.txt`）**：

  | 工作（全量） | v2 | v3 | 差異 |
  |---|---|---|---|
  | 依作業格式產生全部文字（M4） | 12.51 s | 13.71 s | +1.2 s（+10%） |
  | 走訪全部 postings | 1.33 s | 3.50 s | +2.2 s |
  | 隨機查 1 萬個詞 | 0.01 s | 0.10 s | +0.09 s |
  | 查 df 最高 100 詞 × 10 次 | ≈ 0 s | 9.23 s | 每次約 9 ms（每次組出約 3 萬筆 Posting） |

  四項結果完全一致；作業格式輸出經 SHA-1 比對**逐 byte 相同**

### SPIMI
- **目的**：(1) 報告特色：證明可在記憶體受限下建構索引；(2) 備案：若 TA 機器記憶體不足，`--spimi` 仍能產生正確輸出（前提：M4 用 `iter_postings()`）
- **觀察**：v3 欄式儲存後，全記憶體模式已降到 1.1 GB，SPIMI 優勢縮小為約一半（604 MB）。兩者解決不同層次問題：欄式儲存降低「每筆資料的開銷」；SPIMI 讓「索引總大小不受記憶體限制」

### Radix Trie（加分項）
- 64.5 萬詞僅 77 萬節點（單一子節點路徑合併為一條邊，約 1.2 節點／詞）
- 建立 1.8–2.3 s；額外記憶體約 +46 MB（v3，只存 df）／+80 MB（v2，存 postings 參考）
- 100k 次精確查詢：dict 3 ms vs trie 90 ms（v2 量測）→ 精確查詢用 dict，前綴查詢用 trie

---

## 1. 與原計畫的差異

| 項目 | 原計畫 | 實作 | 理由 |
|---|---|---|---|
| 內部儲存 | `dict[str, list[Posting]]` | 欄式儲存（見 §0） | 記憶體 −70%；對外仍提供 `Posting` |
| `Posting.positions` | `list[int]` | `array('I')` | 讀取時由 pos 陣列切片產生 |
| `idx.index` | 真正的 dict | 唯讀 `Mapping` view，取值時才組出 `list[Posting]` | 相容原用法；**每次取值是新物件** |
| SPIMI 觸發 | psutil RSS > 1500 MB，每 500 篇 | 累積位置數 ≥ `flush_every`（預設 3,000,000） | Python 釋放記憶體後 RSS 不下降，會不斷誤觸發 |
| partial 格式 | 序列化整個 index | 依詞排序後逐筆 pickle `(term, docs, tfs, pos)` | 才能串流歸併 |
| SPIMI 預設 | 整合於 `build()` | `Indexer(spimi=True)` 選擇性開啟 | 全記憶體僅需 1.1 GB；M5 需隨機存取 |
| SPIMI AC | 200 MB；抽查 5 詞 | 實測 604 MB；全部詞比對 | 200 MB 低於 Python + spaCy + bs4 基本用量 |
| 效能 AC | ≥ 500 docs/s | ≥ 80 docs/s | 上游擷取 + 斷詞約 96 docs/s 為瓶頸 |
| `doc_len` | 「加入索引的 token 總數」 | `len(terms)`，不含被移除的停用詞 | 原說明與 AC 不一致，依 AC |
| `build()` 參數 | `(warc_path, preprocessor)` | 增加 `limit=None, progress=5000` | 有預設值，相容原呼叫 |
| 新增介面 | — | `iter_postings`、`get_postings`、`df`、`prefix_search`、`build_trie`、`cleanup` | SPIMI 串流、trie、欄式儲存 |
| 相依套件 | `psutil` | 不需要 | |

---

## 2. 資料結構

```python
@dataclass(slots=True)
class Posting:                 # 對外資料型別（讀取時組出）
    doc_num: int               # TREC-ID 尾碼（0–34785），同一 term 內嚴格遞增
    tf: int                    # == len(positions)
    positions: array           # array('I')，從 1 開始，嚴格遞增

@dataclass
class DocEntry:
    trec_id: str
    doc_len: int               # len(terms)，不含被移除的停用詞
    url: str

class _Columns:                # 內部儲存（每個詞一個）
    docs: array('I')
    tfs:  array('I')
    pos:  array('I')
```

**位置規則**
- 標點、附著詞（`'s`）、長度 > 64 的 token：不佔位置
- 停用詞（開啟移除時）：佔位置但不建 postings → positions 可能跳號，但仍嚴格遞增

---

## 3. 工項與 AC

### Step 3-A：`add_document` ✅
- [x] `Posting`, `DocEntry` dataclass
- [x] 模組層級 `add_document(index, doc_map, doc_num, trec_id, url, terms)`（原規格，保留作為正確性對照的參考實作）

**AC**
- [x] 同詞多次出現 → `tf` 累加、`positions` 升序
- [x] `doc_map[doc_num].doc_len == len(terms)`
- [x] `doc_num` 倒退時 AssertionError

### Step 3-B：`Indexer`（全記憶體）✅
- [x] `Indexer.add_document(doc, terms)`、`get_stats()`、`build(warc_path, preprocessor, limit, progress)`

**AC**
- [x] `limit=n` 時 `stats['N'] == n`
- [x] `sum(tf) == stats['total_tokens']`；`len(pos) == sum(tfs)`（每個詞）
- [x] 所有 postings：`doc_num` 嚴格遞增、`positions` 嚴格遞增、`tf == len(positions)`

### Step 3-C：SPIMI ✅
- [x] `Indexer(spimi=True, flush_every=3_000_000, tmp_dir="spimi_tmp")`
- [x] `_flush_partial()`：只在文件之間 flush；依詞排序後逐筆寫出
- [x] `_merge_partials()`：`heapq.merge` 多路歸併；同詞依 partial 順序串接（docID 自然遞增）
- [x] `iter_postings()` 從 `merged.pkl` 串流讀出；`cleanup()` 刪暫存檔

**AC**
- [x] 前 2000 篇、`flush_every=200_000`（11 partials）：SPIMI 與全記憶體 **全部 132,650 詞逐筆一致**
- [x] 全量兩模式 stats 一致
- [x] 全量 Peak RSS：SPIMI 604 MB < 全記憶體 1,110 MB

### Step 3-D：測試 ✅
- [x] `indexer.test.py`：單元測試、一致性檢查、全量執行、top-10 df
- [x] `indexer_features.test.py`：`compare`／`bench`／`m4`／`legacy` 指令
- [x] 邊界：空文件、全停用詞文件

**AC**
- [x] 空文件（doc 24621）在 `doc_map`、`doc_len == 0`、無 posting
- [x] 全停用詞文字 `process()` 回傳空列表
- [x] 速度 ≥ 80 docs/s（預設約 94；stopword + stem 約 71）

### Step 3-E：Radix Trie（加分項）✅
- [x] `trie.py`：`RadixTrie.insert / get / prefix_search / node_count`
- [x] `Indexer.build_trie()`（存 df）、`prefix_search(prefix, limit)`（第一次呼叫才建立）

**AC**
- [x] `len(trie) == vocab_size`；抽樣 1000 詞 `trie.get(t) == idx.df(t)`
- [x] `prefix_search` 依字典序，可處理 prefix 結束於邊中間
- [x] 全量：644,523 詞 / 770,227 節點

### Step 3-F：欄式儲存 ✅
- [x] `_Columns`（docs / tfs / pos 三個 `array('I')`）
- [x] `_PostingsView(Mapping)`：`idx.index` 相容原 dict 用法
- [x] SPIMI partial / merged 直接存 3 個 array

**AC**
- [x] 前 2000 篇：欄式儲存與參考實作（3-A `add_document`）全部詞逐筆一致、`doc_map` 相同
- [x] 全量：依作業格式輸出的內容與參考實作 SHA-1 相同
- [x] 全量 Peak RSS ≤ 參考實作的 50%（實測 1,110 vs 3,167 MB）
- [x] M4 依作業格式輸出時間增加 ≤ 20%（實測 +10%）

---

## 4. 對外介面（供 M4 / M5）

```python
class Indexer:
    index: Mapping[str, list[Posting]]  # 唯讀 view；SPIMI 模式建完後為空
    doc_map: dict[int, DocEntry]
    stats: dict                         # N, vocab_size, total_tokens, avg_doc_len

    def __init__(self, spimi=False, flush_every=3_000_000, tmp_dir="spimi_tmp"): ...
    def build(self, warc_path, preprocessor, limit=None, progress=5000) -> "Indexer": ...
    def get_stats(self) -> dict: ...

    def iter_postings(self) -> Iterator[tuple[str, list[Posting]]]: ...  # 依字典序
    def get_postings(self, term) -> list[Posting]: ...                   # 查無回傳 []
    def df(self, term) -> int: ...                                       # 不組 Posting，最快
    def prefix_search(self, prefix, limit=None) -> list[tuple]: ...
    def build_trie(self) -> RadixTrie: ...
    def cleanup(self) -> None: ...
```

| 介面 | 全記憶體 | SPIMI | 用途 |
|---|---|---|---|
| `iter_postings()` | ✅ | ✅（每次呼叫重讀 merged 檔） | 走訪全部詞：寫檔、建 skip |
| `index[term]` / `get_postings(term)` | ✅ | ❌ | 查特定詞 |
| `df(term)` | ✅ | ❌ | 只需 df 時（不組物件） |
| `prefix_search()` | ✅ 回傳 `(term, postings)` | ⚠️ 回傳 `(term, df)` | 前綴查詢 |
| `doc_map` / `stats` | ✅ | ✅ | metadata |

> **注意**
> - `doc_num` 來自 TREC-ID 尾碼，不重新賦號；Delta encoding 由 M4 負責
> - `positions` 是 `array('I')`：`== list` 永遠為 False、`json.dump` 會失敗 → 先 `list(p.positions)`
> - `idx.index[t]` / `get_postings(t)` **每次都產生新物件**：不要用 `is` 比較；高頻詞每次約 9 ms，不要在迴圈中反覆查同一個詞，請存起來重用
> - 查詢詞必須經過與建索引時相同的 `Preprocessor`

---

## 5. 測試指令

```zsh
uv run python HW1/src/indexer.test.py HW1/dataset/04.warc 200                      # 單元 + 一致性
uv run python HW1/src/indexer_features.test.py HW1/dataset/04.warc compare 2000     # 欄式 / SPIMI / trie 正確性
uv run python HW1/src/indexer_features.test.py HW1/dataset/04.warc bench memory     # 現行版記憶體
uv run python HW1/src/indexer_features.test.py HW1/dataset/04.warc bench spimi
uv run python HW1/src/indexer_features.test.py HW1/dataset/04.warc m4 0             # 讀取效能 v2 vs v3
uv run python HW1/src/indexer_features.test.py HW1/dataset/04.warc legacy array     # 重現 v2 記憶體
uv run python HW1/src/indexer_features.test.py HW1/dataset/04.warc legacy list      # 重現 v1 記憶體
```