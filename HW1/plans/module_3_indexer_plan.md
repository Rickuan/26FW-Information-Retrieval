# Module 3：Inverted Indexer (SPIMI) — 實作計畫
> **檔案**：`HW1/src/indexer.py` | **狀態**：⬜ 待實作  
> **上游**：M1 `iter_documents()` + M2 `Preprocessor.process()` | **下游**：M4 Writer、M5 Skip Builder

---

## 1. 資料結構

```python
@dataclass(slots=True)
class Posting:
    doc_num: int        # TREC-ID 尾碼整數（嚴格遞增）
    tf: int             # Term Frequency
    positions: list[int]  # 詞位置（從 1 開始，升序）

@dataclass
class DocEntry:
    trec_id: str
    doc_len: int        # 加入索引的 token 總數
    url: str

# 主索引
InMemoryIndex = dict[str, list[Posting]]   # term → postings
```

---

## 2. 工項與 AC

### Step 3-A：`add_document` 純函式
**工項**
- [ ] 定義 `Posting`, `DocEntry` dataclass
- [ ] `add_document(index, doc_map, doc_num, trec_id, url, terms: [(pos, tok)])` 純函式
  - 同一文件的同一 term → 累加 tf，append pos
  - 新 doc_num → append 新 Posting

**AC**
- 同詞多次出現 → `tf` 正確累加，`positions` 升序
- `doc_map[doc_num].doc_len == len(terms)`

---

### Step 3-B：`Indexer` 類別（全量記憶體）
**工項**
- [ ] `Indexer.__init__`：封裝 `index: InMemoryIndex`、`doc_map`
- [ ] `Indexer.add_document(doc: Document, terms: list[tuple[int,str]])`
- [ ] `Indexer.get_stats()` → `{N, vocab_size, total_tokens, avg_doc_len}`

**AC**
- 100 篇測試文件，`stats['N'] == 100`
- `sum(e.doc_len for e in doc_map.values()) == stats['total_tokens']`

---

### Step 3-C：SPIMI（記憶體保護）
**工項**
- [ ] `memory_limit_mb: int = 1500` 參數；每 500 篇用 `psutil` 檢查 RSS
- [ ] `_flush_partial(tmp_dir)`：序列化 index 為 `partial_NNN.pkl`，清空記憶體
- [ ] `_merge_partials(tmp_dir)`：多路歸併（按 term 字典序），合併同 term 的 postings
- [ ] `Indexer.build(warc_path, preprocessor)` 整合流程

**AC**
- 記憶體上限 200 MB 下跑完整語料不 OOM
- 任意抽查 5 個 term，merge 後 df 與 postings 與全量一致

---

### Step 3-D：`indexer.test.py`
**工項**
- [ ] 前 200 篇驗證 stats 正確性
- [ ] 效能測試（target ≥ 500 docs/s）
- [ ] 邊界：空文件、全停用詞文件

**AC**
- 空文件在 `doc_map` 有記錄，`doc_len == 0`，不產生任何 posting
- 印出 top-10 df term

---

## 3. 對外介面（供 M4 / M5）

```python
class Indexer:
    index: dict[str, list[Posting]]
    doc_map: dict[int, DocEntry]
    stats: dict  # N, vocab_size, total_tokens, avg_doc_len

    def build(self, warc_path: str, preprocessor: Preprocessor) -> "Indexer": ...
    def get_stats(self) -> dict: ...
```

> **注意**：`doc_num` 來自 TREC-ID 尾碼整數，不重新賦號；Delta encoding 由 M4 負責。
