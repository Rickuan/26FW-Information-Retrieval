# Module 4：Index Writer & Reader — 實作計畫
> **檔案**：`HW1/src/writer.py` | **狀態**：⬜ 待實作  
> **上游**：M3 `Indexer`（+ M5 Skip pointer，可選）| **輸出**：`HW1/output/`

---

## 0. 變更紀錄（因應 M3 實作與作業規範）

| 項目 | 原計畫 | 修改後 | 理由 |
|---|---|---|---|
| 🔄 Step 4-A 文字格式 | `<term> (df=N): doc/tf ...`（無 positions） | 作業規定格式 `dictionary.txt` + `postings.txt`（含 positions） | 投影片 p.9 規定；評分依據為索引正確性 |
| 🔄 讀取索引 | `indexer.index[term]` | 寫檔用 `indexer.iter_postings()` | 已排序；全記憶體 / SPIMI 通用 |
| 🔄 positions 型別 | `list[int]` | `array('I')` | M3 實作；比較與 JSON 前需轉 list |
| 🔄 比較方式 | `== original` | 比較 `(doc_num, tf, list(positions))` | array 與 list 直接比較永遠為 False；`index[t]` 每次是新物件 |
| 🔄 VByte 說明 | — | 註明為 LEB128 變體 | `b'\xac\x02'` 與 IIR 課本 VB（`b'\x02\xac'`）不同 |
| 🆕 Step 4-F | — | `write_all()` 單次走訪寫出所有檔案 | SPIMI 模式下每次 `iter_postings()` 都重讀 merged 檔 |
| 🔄 metadata | preprocessor dict | `casefold`, `stopword`, `stem`, `spimi` | 查詢時需相同設定 |

**M3 已提供的效能參考**（全量，M3 v3 欄式儲存）：依作業格式產生全部 `postings.txt` 內容約 14 s；走訪全部 postings 約 3.5 s。

---

## 1. 磁碟佈局

```
HW1/output/
├── dictionary.txt    # 🆕 排序後詞彙，一行一個（作業規定）
├── postings.txt      # 🆕 作業規定格式 positional postings（作業規定）
├── metadata.json     # N, vocab_size, total_tokens, avg_doc_len, preprocessor, spimi, build_time
├── doc_map.json      # doc_num → {trec_id, doc_len, url}
├── lexicon.tsv       # term TAB df TAB byte_offset TAB byte_length（字典序）
└── postings.bin      # VByte + Delta 壓縮二進制 postings
```

---

## 2. 工項與 AC

### Step 4-A：作業規定格式（最優先，評分依據）🔄
**格式**（投影片 p.9，Fig. 2.11）：每個 term 一行
```
term, df: <docID, tf: <pos1, pos2, …>; docID, tf: <pos1, …>; …>
```
範例：
```
computer, 3: <12, 2: <5, 40>; 87, 1: <3>; 301, 4: <1, 9, 22, 30>>
```
參考實作（已在 M3 `bench_m4` 驗證）：
```python
def format_line(term, plist):
    body = "; ".join(f"{p.doc_num}, {p.tf}: <{', '.join(map(str, p.positions))}>" for p in plist)
    return f"{term}, {len(plist)}: <{body}>\n"
```

**工項**
- [ ] `write_dictionary(indexer, path)`：排序後詞彙一行一個
- [ ] `write_postings_text(indexer, path)`：依上述格式
- [ ] 使用 `for term, plist in indexer.iter_postings():`（已排序，不需 `sorted()`）

**AC**
- [ ] `dictionary.txt` 行數 == `stats['vocab_size']`，且已排序（Python 字串排序）
- [ ] `postings.txt` 第 i 行的 term == `dictionary.txt` 第 i 行
- [ ] 任意 5 term：解析出的 (docID, tf, positions) 與 `indexer.get_postings(term)` 一致（positions 轉 list）
- [ ] 每行 df == posting 數；每筆 tf == positions 數
- [ ] 可 `grep "^information, " postings.txt` 找到該詞

> 解析時以第一個 `", "` 切出 term：term 可能含逗號（`10,000`）或冒號（`7:30`），但不含空白。

---

### Step 4-B：`metadata.json` + `doc_map.json`
- [ ] `write_metadata(indexer, config, output_dir)`：N, vocab_size, total_tokens, avg_doc_len, created_at, 🔄 `preprocessor: {casefold, stopword, stem}`, `spimi`
- [ ] `write_doc_map(doc_map, output_dir)`：key 為字串化 doc_num

**AC**
- [ ] `json.load()` 正常，schema 完整
- [ ] `len(doc_map_json) == stats['N']`
- [ ] preprocessor 設定與建索引時一致

---

### Step 4-C：VByte 壓縮工具
- [ ] `encode_vbyte(n: int) -> bytes`
- [ ] `decode_vbyte(data: bytes, offset: int) -> (int, int)`

**AC**
- [ ] `encode_vbyte(300)` == `b'\xac\x02'`
- [ ] `decode(encode(x)) == x` 對 0, 1, 127, 128, 300, 16383, 16384 均成立

> 🔄 此為 LEB128 變體（低位在前、非最後 byte 設最高位）。IIR 課本 VB 為高位在前、最後 byte 設最高位（300 → `b'\x02\xac'`）。報告需註明採用何者。

---

### Step 4-D：Binary Format — `postings.bin` + `lexicon.tsv`
**Block 格式**：
```
[df: uint32][Δdoc_num: VByte][tf: VByte][n_pos: VByte][Δpos...: VByte]...
```
- 第一個 doc_num 的 Δ 以 0 為基準（doc_num 可能為 0）
- 每筆 posting 第一個 position 的 Δ 以 0 為基準

**工項**
- [ ] `encode_postings_block(postings) -> bytes`
- [ ] `decode_postings_block(data) -> list[Posting]`（positions 產生 `array('I')`）
- [ ] `write_binary_format(indexer, output_dir)`：以 `iter_postings()` 寫 postings.bin，同步產生 lexicon.tsv

**AC**
- [ ] round-trip：逐筆比對 `(doc_num, tf, list(positions))` 一致
- [ ] `postings.bin` < 未壓縮版（每整數 4 bytes）的 60%
- [ ] `lexicon.tsv` 行數 == vocab_size

---

### Step 4-E：`IndexReader`
- [ ] `IndexReader(output_dir)`：lazy-load lexicon.tsv 為 `dict[str, (offset, len)]`
- [ ] `get_postings(term) -> list[Posting]`：seek + decode
- [ ] `get_doc(doc_num) -> DocEntry`

**AC**
- [ ] `reader.get_postings("information")` 與 `indexer.get_postings("information")` 逐筆一致（全記憶體模式）
- [ ] 讀取 1000 個 term 的 postings < 1 s

---

### Step 4-F：單次走訪寫出所有檔案 🆕
- [ ] `write_all(indexer, output_dir)`：一次 `iter_postings()` 內同時寫 `dictionary.txt`、`postings.txt`、`postings.bin`、`lexicon.tsv`

**AC**
- [ ] 輸出與分別呼叫 4-A / 4-D 完全相同
- [ ] `Indexer(spimi=True)` 下可產生完整輸出，且與全記憶體模式逐 byte 相同

**呼叫 M3 的方式**

| 工作 | 用什麼 |
|---|---|
| 寫 dictionary / postings text / postings.bin / lexicon | `iter_postings()`（已排序，兩種模式通用；建議在同一個 pass 一起寫） |
| 寫 metadata / doc_map | `idx.stats`、`idx.doc_map`（兩種模式都在記憶體） |
| `IndexReader` 驗證 AC | `idx.get_postings(term)`（全記憶體模式） |

> 原本 `for term in sorted(idx.index)` 改為 `for term, plist in idx.iter_postings()`，兩種模式都支援且不必自行排序。

---

## 3. 對外介面

```python
class IndexWriter:
    def __init__(self, output_dir: str): ...
    def write_all(self, indexer: Indexer) -> None: ...            # 🆕 建議主程式使用
    def write_dictionary(self, indexer: Indexer) -> None: ...     # 🆕
    def write_postings_text(self, indexer: Indexer) -> None: ...  # 🔄 取代 write_text_format
    def write_binary_format(self, indexer: Indexer) -> None: ...
    def write_metadata(self, indexer: Indexer, config: dict) -> None: ...

class IndexReader:
    def get_postings(self, term: str) -> list[Posting]: ...
    def get_doc(self, doc_num: int) -> DocEntry: ...
```

> **注意**
> - 寫檔一律用 `indexer.iter_postings()`；驗證時用 `indexer.get_postings()`（全記憶體模式）
> - `p.positions` 是 `array('I')`：輸出用 `", ".join(map(str, p.positions))`；比較或 JSON 前 `list()`
> - `indexer.index[t]` 每次是新物件，不要用 `is` 比較
> - Step 4-A 獨立於 M5，可立即執行。Binary 格式若 M5 已完成，block 需擴充 skip offset 欄位