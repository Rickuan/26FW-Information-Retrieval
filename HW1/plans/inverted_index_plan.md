# Inverted Index System — Architecture Plan
> **Course**: 26FW Information Retrieval - HW1 | **Dataset**: `HW1/dataset/04.warc` (~1.05 GB ClueWeb09)

---

## 1. 系統架構與資料流

```
04.warc → [M1 Loader] → (doc_num, text) → [M2 Tokenizer] → (pos, tok)[]
        → [M3 Indexer] → Postings Lists → [M5 Skip Builder] → Skip Pointers
        → [M4 Writer] → lexicon.tsv + postings.bin + metadata.json
```

**五大模組**：

| # | 模組 | 檔案 | 狀態 |
|---|------|------|------|
| M1 | Loader & HTML Cleaner | `warc.py`, `extract.py`, `documents.py` | ✅ 完成 |
| M2 | Tokenizer & Normalizer | `tokenizer.py` | ✅ 完成 |
| M3 | Inverted Indexer (SPIMI) | `indexer.py` | ⬜ 待實作 |
| M4 | Index Writer & Reader | `writer.py` | ⬜ 待實作 |
| M5 | Skip Builder & AND Query | `skip_builder.py` | ⬜ 待實作 |

---

## 2. 模組規格摘要

### M1：Loader（已完成）
- 自製 WARC 0.18 parser（不用 warcio，避免 Content-Length 錯誤）
- `iter_documents(path)` → `Document(doc_num, trec_id, url, kind, text)`
- UnicodeDammit 解碼 + ftfy 修 Mojibake + BeautifulSoup/lxml 去標籤

### M2：Tokenizer（已完成）
- spaCy `blank("en")` 斷詞 + NLTK Porter Stemmer / stopwords
- `Preprocessor(casefold, stopword, stem).process(text)` → `[(pos, tok), ...]`

### M3：Indexer
- `Posting(doc_num, tf, positions)` + `DocEntry(trec_id, doc_len, url)`
- `Indexer.add_document()` + `get_stats()` → N, vocab_size, avg_doc_len
- SPIMI：記憶體超門檻 → flush partial → multi-way merge

### M4：Writer
- **Text format**：`index_dump.txt`（除錯用，可 grep）
- **Binary format**：`lexicon.tsv` + `postings.bin`（VByte Delta encoding）
- `metadata.json` + `doc_map.json`
- `IndexReader.get_postings(term)` 讀取驗證介面

### M5：Skip Builder
- 間隔 `L = floor(sqrt(P))`，P < 9 不建立
- `SkipPointer(target_doc_num, target_index)`
- `intersect_with_skips(p1, p2)` → `(doc_nums, n_comparisons)`
- 效能評測：與線性掃描比較次數

---

## 3. 目錄結構

```
HW1/
├── dataset/04.warc          # 原始語料
├── plans/                   # 本計畫文件
├── src/
│   ├── warc.py / extract.py / documents.py   # M1
│   ├── tokenizer.py                           # M2
│   ├── indexer.py                             # M3
│   ├── writer.py                              # M4
│   └── skip_builder.py                        # M5
├── output/                  # 索引輸出（.gitignore）
└── logs/                    # 執行日誌
```

---

## 4. 實作里程碑

| Phase | 目標 | 產出 |
|-------|------|------|
| Phase 3 | M3 Indexer + SPIMI | `indexer.py`, `indexer.test.py` |
| Phase 4A | M4 Text format + metadata | `index_dump.txt`, `metadata.json` |
| Phase 5 | M5 Skip Builder + AND query | `skip_builder.py`, 效能報告 |
| Phase 4B | M4 Binary format + Reader | `lexicon.tsv`, `postings.bin` |
| Phase 6 | 全量語料整合測試 | `main.py`, `output/*` |

---

## 5. 相依套件

`beautifulsoup4`, `lxml`, `ftfy`, `langdetect`, `spacy`, `nltk`, `tqdm`, `psutil`
