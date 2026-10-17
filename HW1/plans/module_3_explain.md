# M3 Indexer — 完整說明

> 檔案：`HW1/src/indexer.py`、`HW1/src/trie.py`
> 測試：`HW1/src/indexer.test.py`、`HW1/src/indexer_features.test.py`
> 狀態：✅ 3-A / 3-B / 3-C / 3-D 完成，全量 04.warc 驗證通過

---

## 0. 一句話總結

M3 把 M1（Loader）與 M2（Preprocessor）的輸出建成「詞 → postings（docID、tf、positions）」的位置型倒排索引。
提供兩種建置模式（全記憶體 / SPIMI）與三種讀取介面（逐詞走訪 / 精確查詢 / 前綴查詢）。

**下游使用規則：**

| 工作 | 用什麼 | 模式 |
|---|---|---|
| 產生交給 TA 的索引檔（M4 text / binary / lexicon） | `idx.iter_postings()` | 兩種都可以 |
| 建 skip pointer（M5 `SkipBuilder.build`） | `idx.iter_postings()` | 全記憶體 |
| 查特定詞（M5 AND 查詢、M4 `IndexReader` 驗證） | `idx.get_postings(term)` 或 `idx.index[term]` | 全記憶體 |
| 前綴查詢展示 | `idx.prefix_search(prefix)` | 全記憶體 |
| `doc_map`、`stats` | `idx.doc_map`、`idx.stats` | 兩種都可以 |

---

## 1. 在整條管線中的位置

```
04.warc
 → M1 iter_documents()        Document(doc_num, trec_id, url, kind, text)
 → M2 Preprocessor.process()  [(pos, term), ...]
 → M3 Indexer.build()         index / doc_map / stats        ← 本模組
 → M5 SkipBuilder             skip pointers + AND 查詢
 → M4 IndexWriter             輸出檔案
```

`Indexer.build()` 內部會自己呼叫 M1、M2，所以 M4 和 M5 **不需要**自己讀 WARC 或斷詞。
但有兩個例外：
- M4 的 `metadata.json` 要記錄 Preprocessor 的設定（`casefold`、`stopword`、`stem`）。
- M5 的查詢詞必須用**同一個 Preprocessor** 處理（見第 8 節）。

---

## 2. 資料結構

```python
@dataclass(slots=True)
class Posting:
    doc_num: int        # docID
    tf: int             # 詞在這份文件出現的次數
    positions: array    # array('I')，詞在文件中的位置

@dataclass
class DocEntry:
    trec_id: str        # e.g. clueweb09-en0000-04-00123
    doc_len: int        # 這份文件進入索引的 token 數
    url: str
```

| 欄位 | 定義 | 為何這樣設計 |
|---|---|---|
| `doc_num` | TREC-ID 尾碼整數（0–34785），**不重新編號** | 可直接推回 TREC-ID；已驗證連續、無缺號、無重複 |
| `tf` | `== len(positions)` | 計畫要求保留此欄位；測試會檢查兩者一致 |
| `positions` | 從 1 起算，**嚴格遞增** | 片語查詢 / 鄰近查詢需要；`array('I')` 比 list 省 15% 記憶體 |
| `doc_len` | `len(terms)`，**不含被移除的停用詞** | 依原計畫的 AC 定義 |
| postings 順序 | 依 `doc_num` 嚴格遞增 | 文件依序加入，直接 append 即可，不需排序；`add_document` 會 assert 檢查 |

**位置規則**（說明文件要寫）：
- 標點、附著詞（`'s`）、超過 64 字元的 token：**不佔位置**
- 停用詞（開啟移除時）：**佔位置但不建 postings**，所以 positions 可能跳號（1, 2, 4），片語查詢的距離才會正確

---

## 3. 兩種建置模式

### 3.1 全記憶體模式（預設）

```python
idx = Indexer().build("HW1/dataset/04.warc", Preprocessor())
```

- 整個索引保存在 `idx.index`（`dict[str, list[Posting]]`）
- 全量：Peak RSS 3,167 MB，約 6 分鐘
- **所有讀取介面都能用**，M4 / M5 的完整功能都在此模式下執行

### 3.2 SPIMI 模式

```python
idx = Indexer(spimi=True, flush_every=3_000_000, tmp_dir="spimi_tmp").build(
    "HW1/dataset/04.warc", Preprocessor())
for term, plist in idx.iter_postings():
    ...
idx.cleanup()
```

運作方式：
1. 每累積 `flush_every` 個位置，把記憶體中的索引**依詞排序後逐筆寫出** `partial_NNN.pkl`，清空記憶體
2. 全部文件處理完，用 `heapq.merge` 多路歸併所有 partial → `merged.pkl`
3. 同一個詞在不同 partial 的 postings 直接串接（partial 依文件順序產生，docID 自然遞增）
4. `iter_postings()` 從 `merged.pkl` 逐筆串流讀出

全量：Peak RSS **855 MB（−73%）**，412 秒（+14%）。產生的索引與全記憶體模式**逐詞完全一致**。

**用途：**
1. **報告特色**：證明索引可在記憶體受限下建構（「huge corpus」）
2. **TA 執行環境的備案**：若 TA 的機器記憶體不足 3.2 GB，可加 `--spimi` 照樣產生正確的索引檔
   → 前提是 M4 必須用 `iter_postings()` 讀取（見第 5 節）

**限制：**
- 建完後 `idx.index` 為空
- `get_postings()` 會丟出 RuntimeError
- `prefix_search()` 只回傳 `(term, df)`，不含 postings
- 每次呼叫 `iter_postings()` 都會重讀一次 `merged.pkl`（數十秒）→ 盡量一次走訪就做完所有輸出
- `cleanup()` 必須在讀完後才呼叫
- 需要約 1 GB 暫存磁碟空間

**為何預設不開？** 全記憶體只需 3.2 GB，而且 M5 的查詢需要隨機存取。SPIMI 是備案與展示用途，不是主流程。

---

## 4. 三種讀取介面

### 4.1 `iter_postings()` — 依字典序走訪全部詞

```python
for term, plist in idx.iter_postings():
    df = len(plist)
    for p in plist:
        p.doc_num, p.tf, p.positions
```

- 輸出順序：Python 字串排序（Unicode code point），與 `dictionary` 檔要求的「排序後詞彙」一致
- **兩種模式都能用，輸出完全相同**
- 適合：要處理「所有詞」的工作（寫檔、建 skip pointer）
- 不適合：查特定詞（必須從頭掃過 64 萬個詞）

### 4.2 `get_postings(term)` / `idx.index[term]` — 精確查詢

```python
idx.get_postings("computer")   # 查無回傳 []
idx.index["computer"]          # 查無會 KeyError
```

- 用 dict，O(1)，100k 次查詢約 3 ms
- **只能在全記憶體模式下使用**
- 適合：AND 查詢、讀回驗證、抽查

### 4.3 `prefix_search(prefix, limit=None)` — 前綴查詢

```python
idx.prefix_search("comput", limit=10)
# [('comput', [...]), ('compute', [...]), ('computer', [...]), ...]
```

- 使用 Radix Trie（`trie.py`），第一次呼叫時才建立（1.8 秒，約 +80 MB）
- 64.5 萬詞只需 77 萬個節點（單一子節點的路徑合併成一條邊）
- trie 節點存的是 `idx.index` 中**同一個** postings 物件的參考，不會複製
- 精確查詢比 dict 慢 30 倍 → 精確查詢用 dict，前綴查詢才用 trie
- 為何需要：投影片 p.11 明列 trie 為加分項

---

## 5. 下游該用哪個介面，以及原因

### M4 Writer

| 工作 | 用什麼 | 原因 |
|---|---|---|
| `write_text_format` | `iter_postings()` | 已排序、兩種模式通用 → `--spimi` 時也能產生評分用的檔案 |
| `write_binary_format`（postings.bin + lexicon.tsv） | `iter_postings()` | 同上；SPIMI 模式下建議與 text format **在同一次走訪中一起寫**，避免重讀 merged 檔 |
| `write_metadata` / `write_doc_map` | `idx.stats`、`idx.doc_map` | 兩種模式都在記憶體中 |
| `IndexReader` 驗證 AC | `idx.get_postings(term)` | 需隨機存取，全記憶體模式 |

改寫方式（只改迴圈，內容不變）：

```python
# 原計畫寫法（只支援全記憶體模式）
for term in sorted(idx.index):
    plist = idx.index[term]
    ...

# 建議寫法（兩種模式都支援）
for term, plist in idx.iter_postings():
    ...
```

### M5 Skip Builder

| 工作 | 用什麼 | 原因 |
|---|---|---|
| `SkipBuilder.build` | `iter_postings()` 或 `idx.index` | 要處理所有詞；結果是記憶體中的 dict，所以本身就是全記憶體工作 |
| `intersect_*` / AND 查詢 | `idx.get_postings()` 或 SkipBuilder 的結果 dict | 需隨機存取 |

SPIMI 模式下，M5 直接略過即可（skip pointer 是加分展示，不影響評分用的索引檔）。

### 建議的 `main.py` 流程

```python
pre = Preprocessor(casefold=not args.no_casefold, stopword=args.stopword, stem=args.stem)
idx = Indexer(spimi=args.spimi).build(args.warc, pre)

writer = IndexWriter(args.out)
writer.write_metadata(idx, config)          # stats + preprocessor 設定
writer.write_doc_map(idx.doc_map)
writer.write_text_format(idx)               # 內部用 idx.iter_postings()
writer.write_binary_format(idx)             # 內部用 idx.iter_postings()

if not args.spimi:                          # 需要隨機存取的功能只在全記憶體模式執行
    skips = SkipBuilder().build(idx)
    ...

idx.cleanup()                               # SPIMI 模式刪暫存檔；全記憶體模式無作用
```

---

## 6. 實測結果（全量 04.warc，可直接用於報告）

| 項目 | 數值 |
|---|---|
| N / vocab_size / total_tokens | 34,786 / 644,523 / 27,549,214 |
| postings 數（term-doc pairs） | 11,834,013 |
| avg_doc_len | 791.96 |
| 速度（含擷取 + 斷詞） | 約 94 docs/s，全量約 6 分鐘 |

| 版本 | Peak RSS | 時間 |
|---|---|---|
| positions = `list[int]` | 3,712 MB | 368 s |
| positions = `array('I')` | 3,167 MB（−15%） | 362 s |
| array + SPIMI（10 partials） | 855 MB（−73%） | 412 s（merge 18 s） |

| Radix trie | 數值 |
|---|---|
| 詞 / 節點 | 644,523 / 770,227 |
| 建立時間 / 額外記憶體 | 1.8 s / 約 +80 MB |
| 100k 次精確查詢 | dict 3 ms / trie 90 ms |

| 前 2000 篇 | vocab_size | total_tokens |
|---|---|---|
| 預設（casefold） | 132,650 | 2,085,249 |
| + stopword + stem | 112,342 | 1,331,925 |

**正確性驗證：**
- `sum(tf) == total_tokens`；所有 postings 的 docID / positions 嚴格遞增、`tf == len(positions)`
- 空文件（doc 24621）有記錄、`doc_len == 0`、無任何 posting
- 全部停用詞的文件：`process()` 回傳空列表
- SPIMI 與全記憶體：前 2000 篇、11 個 partial，**全部 132,650 個詞逐筆一致**；全量 stats 一致

---

## 7. 與 planning file 的差異

| 項目 | 原計畫 | 實作 | 理由 |
|---|---|---|---|
| `positions` 型別 | `list[int]` | `array('I')` | 記憶體 −15% |
| SPIMI 觸發條件 | psutil RSS > 1500 MB，每 500 篇檢查 | 累積位置數 ≥ `flush_every` | Python 釋放記憶體後 RSS 不下降，第一次 flush 後會一直誤觸發 |
| partial 格式 | 序列化整個 index | 排序後逐筆 pickle | 整個 dict 一次載入的話，歸併時記憶體全部回來，SPIMI 失去意義 |
| SPIMI 預設 | 整合在 `build()` | 選擇性開啟，預設全記憶體 | 全記憶體只需 3.2 GB；M5 查詢需要隨機存取 |
| SPIMI AC | 200 MB 上限；抽查 5 個詞 | 實測 855 MB；全部詞比對 | 200 MB 低於 Python + spaCy + bs4 的基本用量；抽查 5 個詞驗證力不足 |
| 效能 AC | ≥ 500 docs/s | 約 94 docs/s | 上游擷取 + 斷詞本身約 96 docs/s，為瓶頸 |
| `doc_len` | 「加入索引的 token 總數」 | `len(terms)`，不含停用詞 | 原計畫的說明與 AC 不一致，依 AC |
| `build()` 參數 | `(warc_path, preprocessor)` | 多了 `limit=None`、`progress=5000` | 有預設值，原呼叫方式不受影響 |
| 新增介面 | — | `iter_postings`、`get_postings`、`prefix_search`、`build_trie`、`cleanup` | SPIMI 串流讀取 + trie 加分項 |
| 相依套件 | `psutil` | 不需要 | |

---

## 8. 給 M4 / M5 的注意事項

1. **`positions` 是 `array('I')`，不是 list**
   - 可以：`for x in p.positions`、`len()`、`", ".join(map(str, p.positions))`、切片
   - 不行：`p.positions == [1, 3]`（永遠 False）、`json.dump`（會失敗）→ 先 `list(p.positions)`
   - M4 round-trip AC（`decode(encode(p)) == original`）：decode 要產生 `array('I')`，或比較時兩邊都轉 list

2. **作業規定的輸出格式必須含 positions**（投影片 p.9）
```
   term, df: <docID, tf: <pos1, pos2, …>; docID, tf: <…>; …>
```
   M4 計畫 4-A 的 `<term> (df=N): doc/tf ...` 沒有 positions，**不符規定**。另外還需要一個「排序後詞彙、一行一個」的 dictionary 檔。

3. **查詢詞要先經過同一個 Preprocessor**
   開啟 stem 時，索引裡存的是 `game`；直接查 `"games"` 或 `"Game"` 會查不到。查詢前先用 `pre.process(query)`。

4. **M5 的 `PostingWithSkip` 會複製 positions**
   為每個 posting 建一個新物件並複製 positions，記憶體可能再增加數 GB。建議 `PostingWithSkip` 直接引用原本的 `Posting`，或只另外存 skip 資訊（`dict[str, list[(index, target_index)]]`）。

5. **SPIMI 模式下 `iter_postings()` 每次產生新的 `Posting` 物件**
   不要用 `is` 比較兩次讀出的結果；要比較內容。