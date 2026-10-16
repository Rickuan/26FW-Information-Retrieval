# Module 4：Index Writer & Reader — 實作計畫
> **檔案**：`HW1/src/writer.py` | **狀態**：⬜ 待實作  
> **上游**：M3 `Indexer`（+ M5 Skip pointer，可選）| **輸出**：`HW1/output/`

---

## 1. 磁碟佈局

```
HW1/output/
├── metadata.json     # N, vocab_size, avg_doc_len, preprocessor config, build_time
├── doc_map.json      # doc_num → {trec_id, doc_len, url}
├── lexicon.tsv       # term TAB df TAB byte_offset TAB byte_length  （字典序）
├── postings.bin      # VByte + Delta 壓縮二進制 postings
└── index_dump.txt    # （可選）人類可讀除錯版
```

---

## 2. 工項與 AC

### Step 4-A：Text Format（不依賴 M5，優先實作）
**工項**
- [ ] `write_text_format(indexer, path)` — 每行 `<term> (df=N): doc/tf doc/tf ...`，按字典序

**AC**
- 可 `grep "^information " index_dump.txt` 找到該詞
- 任意 5 term 的 df 與 `len(indexer.index[term])` 一致

---

### Step 4-B：`metadata.json` + `doc_map.json`
**工項**
- [ ] `write_metadata(indexer, config, output_dir)`：包含 N, vocab_size, total_tokens, avg_doc_len, created_at, preprocessor dict
- [ ] `write_doc_map(doc_map, output_dir)`：key 為字串化 doc_num

**AC**
- `json.load()` 正常，schema 完整
- `len(doc_map_json) == stats['N']`

---

### Step 4-C：VByte 壓縮工具
**工項**
- [ ] `encode_vbyte(n: int) -> bytes`
- [ ] `decode_vbyte(data: bytes, offset: int) -> (int, int)`（值 + 新 offset）

**AC**
- `encode_vbyte(300)` == `b'\xac\x02`（標準 VByte 驗算）
- `decode(encode(x)) == x` 對 0, 1, 127, 128, 300, 16383, 16384 均成立

---

### Step 4-D：Binary Format — `postings.bin` + `lexicon.tsv`

**Block 格式**（每個 term）：
```
[df: uint32][Δdoc_num: VByte][tf: VByte][n_pos: VByte][Δpos...: VByte]...
```

**工項**
- [ ] `encode_postings_block(postings: list[Posting]) -> bytes`（Delta + VByte）
- [ ] `write_binary_format(indexer, output_dir)`：按字典序寫 postings.bin，同步產生 lexicon.tsv

**AC**
- round-trip：`decode(encode(postings)) == original`
- `postings.bin` 大小 < 未壓縮版（4 bytes/doc_num）的 60%
- `lexicon.tsv` 行數 == vocab_size

---

### Step 4-E：`IndexReader`（讀取驗證）
**工項**
- [ ] `IndexReader(output_dir)`：lazy-load lexicon.tsv 為 `dict[str, (offset, len)]`
- [ ] `get_postings(term) -> list[Posting]`：seek + decode
- [ ] `get_doc(doc_num) -> DocEntry`

**AC**
- `reader.get_postings("information")` 與原 `indexer.index["information"]` 完全一致
- 讀取 1000 個 term 的 postings < 1s

---

## 3. 對外介面

```python
class IndexWriter:
    def write_text_format(self, indexer: Indexer) -> None: ...
    def write_binary_format(self, indexer: Indexer) -> None: ...
    def write_metadata(self, indexer: Indexer, config: dict) -> None: ...

class IndexReader:
    def get_postings(self, term: str) -> list[Posting]: ...
    def get_doc(self, doc_num: int) -> DocEntry: ...
```

> **注意**：Step 4-A 獨立於 M5，可立即在 M3 完成後執行驗證。Binary 格式若 M5 已完成，block 格式需擴充 skip offset 欄位。
