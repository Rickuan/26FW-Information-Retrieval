# Module 3：倒排索引構建器 (Indexer) — 詳細實作計畫

> **對應檔案**：`HW1/src/indexer.py`  
> **前置模組**：M1 (`documents.iter_documents`) + M2 (`tokenizer.Preprocessor`)  
> **輸出給**：M4 (Writer)、M5 (Skip Builder)

---

## 0. 上游介面（已固定）

```python
# 從 documents.py 取得
Document(doc_num: int, trec_id: str, url: str, kind: str, text: str)

# 從 tokenizer.py 取得
Preprocessor(casefold, stopword, stem).process(text)
# → [(pos: int, tok: str), ...]   (pos 從 1 開始)
```

---

## 1. 資料結構設計

### 1.1 Posting

```python
@dataclass(slots=True)
class Posting:
    doc_num: int        # 整數 docID（TREC-ID 尾碼）
    tf: int             # Term Frequency（該詞在此文件出現次數）
    positions: list[int]  # 詞位置清單（pos 從 1 開始）
```

> **為何保留 positions**：後續若要支援 phrase query 可直接使用；記憶體開銷在 SPIMI 分段寫入下可接受。

### 1.2 In-Memory Lexicon

```python
# term -> [Posting, ...]
# Postings 在同一段記憶體索引內按 doc_num 遞增排列
InMemoryIndex = dict[str, list[Posting]]
```

### 1.3 DocMap

```python
@dataclass
class DocEntry:
    trec_id: str
    doc_len: int        # 此文件的 token 總數（加入索引的，扣除停用詞後）
    url: str
```

---

## 2. 工項清單

### Step 3-A：基本資料結構

**工項**
- [ ] 定義 `Posting` dataclass（`doc_num`, `tf`, `positions`）
- [ ] 定義 `DocEntry` dataclass（`trec_id`, `doc_len`, `url`）
- [ ] 撰寫 `add_document(index, doc_map, doc_num, trec_id, url, terms)` 純函式
  - `terms` 格式為 `[(pos, tok), ...]`
  - 若 term 不存在則建立新的 `list[Posting]`
  - 若 term 已存在且最後一筆 `doc_num` 相同，則累加 `tf` 並 append `pos`
  - 若 `doc_num` 是新的，append 新 `Posting`

**AC**
- `add_document` 對同一篇文件多次出現的詞，`tf` 正確累加
- `Posting.positions` 按位置升序排列（因 Preprocessor 輸出就是順序的）
- `doc_map[doc_num].doc_len` 等於 `len(terms)`

---

### Step 3-B：全量記憶體索引（Batch Mode）

**工項**
- [ ] 定義 `Indexer` 類別，封裝 `InMemoryIndex` + `dict[int, DocEntry]`
- [ ] 實作 `Indexer.add_document(doc: Document, terms: list[tuple[int,str]])`
- [ ] 實作 `Indexer.get_stats() -> dict`，回傳：
  - `N`：總文件數
  - `total_tokens`：所有文件的 token 總數
  - `vocab_size`：詞彙表大小 `|V|`
  - `avg_doc_len`：平均文件長度

**AC**
- 對 100 篇測試文件，`stats['N'] == 100`
- `stats['vocab_size']` 與手動計算的 unique token 數一致
- `sum(e.doc_len for e in doc_map.values()) == stats['total_tokens']`

---

### Step 3-C：SPIMI 分段策略（記憶體保護）

> **背景**：全量語料約 35K 文件，純文字展開後可能超出可用記憶體。  
> 策略：設定記憶體門檻，超過時把目前的 partial index 寫到磁碟暫存，最終 merge。

**工項**
- [ ] 新增 `memory_limit_mb: int = 1500` 參數到 `Indexer.__init__`
- [ ] 每處理 `check_interval=500` 篇文件後，用 `psutil` 檢查 RSS
- [ ] 超過門檻時，呼叫 `_flush_partial(tmp_dir)` 將當前 `InMemoryIndex` 序列化為臨時檔（`partial_000.pkl`），並清空記憶體索引
- [ ] 實作 `_merge_partials(tmp_dir) -> InMemoryIndex`：讀入所有 partial，多路歸併（按 term 字典排序），合併相同 term 的 Postings List
- [ ] `Indexer.build(warc_path, preprocessor)` 整合以上流程，回傳 self

**AC**
- 在記憶體上限設 200MB 的條件下，對完整語料執行不 OOM
- merge 後，任意抽查 5 個 term，其 `df` 與 Postings 內容與全量索引一致
- flush 的 partial 檔案在 `output/tmp/` 下產生並最終被清除

---

### Step 3-D：整合測試腳本 (`indexer.test.py`)

**工項**
- [ ] 小語料測試（前 200 篇）：驗證 stats、抽查 term 的 df 與 postings
- [ ] 效能測試：計算每秒處理文件數（target ≥ 500 docs/s）
- [ ] 邊界測試：空文件（text=""）、單一 token 文件、全停用詞文件

**AC**
- 空文件不產生任何 posting，但 `doc_map` 有記錄且 `doc_len == 0`
- 測試輸出印出 top-10 最高 df 的 term（應為常見英文詞）

---

## 3. 對外介面（供 M4 / M5 使用）

```python
class Indexer:
    index: dict[str, list[Posting]]    # term -> postings（按 doc_num 排序）
    doc_map: dict[int, DocEntry]       # doc_num -> DocEntry
    stats: dict                        # N, vocab_size, total_tokens, avg_doc_len

    def build(self, warc_path: str, preprocessor: Preprocessor) -> "Indexer": ...
    def get_stats(self) -> dict: ...
```

---

## 4. 注意事項

- Postings List 內的 `doc_num` **必須嚴格遞增**（WARC 串流順序保證，SPIMI merge 時需重新確認）
- `doc_num` 來自 TREC-ID 尾碼整數（`warc.py` 的 `WarcResponse.doc_num`），不重新賦號
- `Indexer` 不負責壓縮（Delta encoding 交給 M4 Writer 在序列化時處理）
