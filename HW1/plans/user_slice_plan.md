# Phase 6：整合管線與 CLI 入口 (main.py) — 實作計畫
> **檔案**：`HW1/src/main.py` | **狀態**：⬜ 待實作  
> **上游**：M1 Loader、M2 Tokenizer、M3 Indexer、M4 Writer、M5 SkipBuilder  
> **產出**：`HW1/output/*`（6 個作業產物）、執行日誌與效能報表

---

## 0. 系統定位與目標

本模組為整個倒排索引系統的**統一入口點（User Slice / CLI Entrypoint）**。
串聯 M1 至 M5，提供單一指令執行全流程，並確保作業評分產物與報告數據能一鍵生成。

```
04.warc 
  ↓ [M1 Documents]
Documents (doc_num, trec_id, url, text)
  ↓ [M2 Preprocessor]
Tokens [(pos, term), ...]
  ↓ [M3 Indexer (Memory / SPIMI)]
Inverted Index & DocMap
  ├── [M4 IndexWriter] ───────→ HW1/output/ (6 個索引檔)
  └── [M5 SkipBuilder] ───────→ Skip List & AND Query 效能評測報表
```

---

## 1. CLI 命令列介面規格

使用 Python 內建 `argparse`，支援三個主要模式（Subcommands）：

### 1.1 `build`：全流程建置索引（作業繳交核心指令）

```bash
# 全量建置（預設全記憶體模式）
python HW1/src/main.py build --input HW1/dataset/04.warc --output HW1/output/

# 快速測試（限制 1,000 篇文件，並同時執行 M5 Skip 評測）
python HW1/src/main.py build --limit 1000 --eval-skips

# SPIMI 模式建置
python HW1/src/main.py build --mode spimi --block-size-mb 100
```

**參數支援**：
- `--input`：WARC 檔案路徑（預設 `HW1/dataset/04.warc`）
- `--output`：輸出目錄（預設 `HW1/output/`）
- `--limit`：處理最大文件數（預設 `None`，處理全量）
- `--mode`：`memory`（全記憶體）或 `spimi`（外排序合併），預設 `memory`
- `--block-size-mb`：SPIMI 記憶體門檻（MB），預設 `150`
- `--no-stem`：關閉 Porter Stemmer
- `--no-stopword`：關閉停用詞過濾
- `--eval-skips`：建置完成後是否自動執行 M5 Skip Pointer 評測（僅 memory 模式有效）

---

### 1.2 `query`：布林 AND 檢索（User Slice 互動/查詢介面）

```bash
# 基本查詢（從磁碟或記憶體讀取索引）
python HW1/src/main.py query "game" "play"

# 顯示匹配文件的詳細資訊（trec_id, URL）
python HW1/src/main.py query "information" "retrieval" --show-docs 5
```

**參數支援**：
- `terms`：查詢詞（支援 2 個或多個詞的 AND 查詢）
- `--index-dir`：索引所在目錄（預設 `HW1/output/`）
- `--show-docs`：顯示前 K 篇匹配文件的 TREC ID 與 URL（預設 `10`）
- `--no-skips`：強制使用 Basic 遍歷比較（便於比對）

---

### 1.3 `eval-skips`：M5 Skip 效能評測與報告產出

```bash
python HW1/src/main.py eval-skips --limit 1000
```
- 自動執行 5 組代表性 query pair（長+短、高頻+高頻、稀疏+密集、無交集、df < 9）
- 終端機格式化輸出 Markdown 表格（包含 Basic 次數、Skip 次數、減少比例、加速比），可直接貼入作業報告。

---

## 2. 磁碟輸出驗證規範（HW1 評分交付物）

`build` 執行完畢後，必須在指定 `--output` 目錄下產出完整 6 個檔案：

| 檔案名稱 | 格式 | 說明 |
|---|---|---|
| `dictionary.txt` | 純文字 | 嚴格字典序，一行一個詞彙（作業評分標準） |
| `postings.txt` | 純文字 | 作業指定格式（Fig. 2.11），包含 doc_num, tf, positions |
| `metadata.json` | JSON | 包含 N, vocab_size, total_tokens, avg_doc_len, preprocessor 設定 |
| `doc_map.json` | JSON | doc_num 映射至 trec_id, doc_len, url |
| `lexicon.tsv` | TSV | term \t df \t offset \t length（二進制索引目錄） |
| `postings.bin` | Binary | VByte + Delta 壓縮之二進制 postings |

---

## 3. 工項與驗收標準 (AC)

### Step 6-A：CLI 參數解析與配置管理
- [ ] 於 `HW1/src/main.py` 實作 `argparse` 架構與子命令（`build`, `query`, `eval-skips`）
- [ ] 支援路徑合法性檢查（WARC 是否存在、output 目錄自動建立）
- [ ] 支援 Preprocessor 設定傳遞（casefold, stopword, stem）

**AC**：
- [ ] `python HW1/src/main.py --help` 正確顯示使用說明
- [ ] 非法路徑或未知命令會輸出清楚的錯誤提示而非 traceback

---

### Step 6-B：端到端索引建置管線 (`run_build`)
- [ ] 串接 M1 `iter_documents()`、M2 `Preprocessor`、M3 `Indexer`
- [ ] 使用 `tqdm` 呈現文件處理進度、吞吐量（docs/s, tokens/s）
- [ ] 呼叫 M4 `IndexWriter.write_all()` 一次性產出 6 項產物
- [ ] 監控與記錄：總耗時、分段耗時（讀取/斷詞/索引/寫檔）、Peak RSS（psutil）

**AC**：
- [ ] 執行 `--limit 100` 時，6 個輸出檔案皆正確生成且內容齊全
- [ ] 輸出摘要日誌（Summary），列出 N、Vocab 大小、各階段耗時與 Peak RAM

---

### Step 6-C：M5 Skip 評測與報表模組 (`run_eval_skips`)
- [ ] 在記憶體建置完成後（或載入已建立的索引），建置 Skip List
- [ ] 測試至少 5 組具代表性的查詢詞對：
  1. 高頻詞 + 高頻詞（交集大）
  2. 高頻詞 + 低頻詞（長度差異顯著，Skip 發揮最大優勢）
  3. 中頻詞 + 中頻詞
  4. 完全無交集的詞對
  5. 包含 df < 9 的詞對（驗證邊界條件）
- [ ] 輸出 Markdown 格式的比較表格至終端機與 `HW1/logs/skip_eval_report.md`

**AC**：
- [ ] 產生之 Markdown 表格欄位包含：Query Pair、df(q1)、df(q2)、Intersection Size、Basic Comparisons、Skip Comparisons、Reduction (%)
- [ ] Skip 比較次數在所有測試案例中均 $\le$ Basic 次數

---

### Step 6-D：檢索展示介面 (`run_query`)
- [ ] 支援從磁碟索引（`IndexReader` + `doc_map.json`）執行查詢
- [ ] 查詢詞經同一個 Preprocessor 正規化
- [ ] 輸出結果：匹配總篇數、檢索耗時、前 K 篇的 TREC ID、URL 與文件長度

**AC**：
- [ ] 查詢 `"game" "play"` 能正確回傳符合的文件清單
- [ ] 若查詢詞不存在或被停用詞過濾，能有友善提示

---

### Step 6-E：全量語料 (04.warc) 整合測試
- [ ] 執行全量 `04.warc`（約 3.5 萬篇文件、1.05 GB）
- [ ] 驗證輸出檔案完整性與雜湊值
- [ ] 記錄整體建置報告於 `HW1/logs/full_pipeline_run.log`

**AC**：
- [ ] 全量執行無例外錯誤、順利完成
- [ ] `postings.bin` 壓縮比低於原始二進制的 60%
- [ ] `dictionary.txt` 與 `postings.txt` 行數精確等於詞彙量（Vocab Size）

---

## 4. 模組架構圖與呼叫關係

```python
# HW1/src/main.py 主要調度流程偽代碼：

def run_build(args):
    preprocessor = Preprocessor(stem=not args.no_stem, stopword=not args.no_stopword)
    indexer = Indexer(preprocessor=preprocessor, spimi=args.mode == "spimi")
    
    # M1 + M2 + M3
    for doc in tqdm(iter_documents(args.input, limit=args.limit)):
        tokens = preprocessor.process(doc.text)
        indexer.add_document(doc.doc_num, doc.trec_id, doc.url, tokens)
    
    # M4
    writer = IndexWriter(args.output)
    writer.write_all(indexer)
    
    # M5 (選用)
    if args.eval_skips and args.mode == "memory":
        run_eval_skips(indexer)

def run_query(args):
    reader = IndexReader(args.index_dir)
    # 讀取查詢詞、求交集並印出結果
```
