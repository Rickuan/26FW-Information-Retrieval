# Inverted Index System — Architecture Plan
> **Course**: 26FW Information Retrieval - HW1 | **Dataset**: `HW1/dataset/04.warc` (~1.05 GB ClueWeb09)

---

## 1. 系統架構與資料流

```
04.warc → [M1 Loader] → (doc_num, text) → [M2 Tokenizer] → (pos, tok)[]
        → [M3 Indexer] → Postings Lists → [M5 Skip Builder] → Skip Pointers
        → [M4 Writer] → dictionary.txt + postings.txt + lexicon.tsv + postings.bin
        → [Step 6 User Slice] → main.py (build / query / eval-skips)
```

**六大模組／階段**：

| # | 模組 | 檔案 | 狀態 | 計畫文件 |
|---|------|------|------|----------|
| M1 | Loader & HTML Cleaner | `warc.py`, `extract.py`, `documents.py` | ✅ 完成 | `.done.module_1_loader_plan.md` |
| M2 | Tokenizer & Normalizer | `tokenizer.py` | ✅ 完成 | （同 M1） |
| M3 | Inverted Indexer (SPIMI) | `indexer.py` | ✅ 完成 | `.done.module_3_indexer_plan.md` |
| M4 | Index Writer & Reader | `writer.py` | ✅ 完成 | `.done.module_4_writer_plan.md` |
| M5 | Skip Builder & AND Query | `skip_builder.py` | ✅ 完成 | `module_5_skip_builder_plan.md` |
| Step 6 | Integration Pipeline & User Slice | `main.py` | ⬜ 待實作 | `user_slice_plan.md` |

---

## 2. 模組規格摘要

### M1：Loader（✅ 已完成）
- 自製 WARC 0.18 parser（不用 warcio，避免 Content-Length 錯誤）
- `iter_documents(path)` → `Document(doc_num, trec_id, url, kind, text)`
- UnicodeDammit 解碼 + ftfy 修 Mojibake + BeautifulSoup/lxml 去標籤

### M2：Tokenizer（✅ 已完成）
- spaCy `blank("en")` 斷詞 + NLTK Porter Stemmer / stopwords
- `Preprocessor(casefold, stopword, stem).process(text)` → `[(pos, tok), ...]`

### M3：Indexer（✅ 已完成）
- `Posting(doc_num, tf, positions)` + `DocEntry(trec_id, doc_len, url)`
- 欄式儲存（columnar `array('I')`）記憶體優化，`iter_postings()` 串接走訪
- `Indexer.add_document()` + `get_stats()` → N, vocab_size, avg_doc_len
- SPIMI 外排序分塊輸出與 multi-way merge，單機低記憶體無上限索引

### M4：Writer & Reader（✅ 已完成）
- **Text format**：`dictionary.txt` + `postings.txt`（作業規定格式，評分依據）
- **Binary format**：`lexicon.tsv` + `postings.bin`（VByte + Delta 編碼，壓縮率 35.5%）
- `metadata.json` + `doc_map.json`
- `IndexWriter.write_all()` 單次走訪同步產出 6 項產物
- `IndexReader` 隨機存取驗證介面（seek + decode < 0.05s）

### M5：Skip Builder（⬜ 待實作）
- 間隔 `L = floor(sqrt(P))`，P < 9 不建立
- `SkipPointer(target_doc_num, target_index)`
- `intersect_with_skips(p1, p2)` → `(doc_nums, n_comparisons)`
- 效能評測：5 組 query pair 與線性掃描比較次數及加速比

### Step 6：User Slice / CLI 入口（⬜ 待實作）
- `HW1/src/main.py` 整合統一 CLI 入口
- `build`：一鍵執行 M1~M4 端到端流程，自動生成 6 個評分檔案
- `query`：命令列布林 AND 查詢展示（結合 `IndexReader`）
- `eval-skips`：自動執行 M5 測試組並印出 Markdown 格式比較報表

---

## 3. 目錄結構

```
HW1/
├── dataset/04.warc          # 原始語料
├── plans/                   # 各階段實作計畫文件
│   ├── .done.module_1_loader_plan.md
│   ├── .done.module_3_indexer_plan.md
│   ├── .done.module_4_writer_plan.md
│   ├── module_5_skip_builder_plan.md
│   └── user_slice_plan.md
├── src/
│   ├── warc.py / extract.py / documents.py   # M1
│   ├── tokenizer.py                           # M2
│   ├── indexer.py                             # M3
│   ├── writer.py                              # M4
│   ├── skip_builder.py                        # M5
│   └── main.py                                # Step 6 (User Slice)
├── output/                  # 索引輸出（.gitignore）
└── logs/                    # 執行日誌與評測報告
```

---

## 4. 實作里程碑

| Phase | 目標 | 產出 | 狀態 |
|-------|------|------|------|
| Phase 1 & 2 | M1 Loader + M2 Tokenizer | `warc.py`, `extract.py`, `tokenizer.py` | ✅ 完成 |
| Phase 3 | M3 Indexer + SPIMI | `indexer.py`, `indexer.test.py` | ✅ 完成 |
| Phase 4 | M4 Text & Binary Writer + Reader | `writer.py`, `writer.test.py` | ✅ 完成 |
| Phase 5 | M5 Skip Builder + AND query | `skip_builder.py`, `skip_builder.test.py` | ✅ 完成 |
| Phase 6 | Step 6 User Slice CLI + 全量整合測試 | `main.py`, `output/*`, 評測報表 | ⬜ 待實作 |

---

## 5. 相依套件

`beautifulsoup4`, `lxml`, `ftfy`, `langdetect`, `spacy`, `nltk`, `tqdm`, `psutil`

