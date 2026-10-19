# Inverted Index & Boolean Retrieval System (HW1)

> **語料集**：ClueWeb09 English Dataset (`HW1/dataset/04.warc`，約 1.05 GB，共 34,786 篇 Web 文件)  
> **環境**：Python 3.12+ / `uv` 套件管理

## 0. 成員分工與貢獻

> **分工**：
> 1. **115598022 顏睿寬**：Index Writer、Skip Builder、Query Engine、Main (CLI)
> 2. **115598067 施宥丞**：Loader & HTML Cleaner、Tokenizer & Preprocessor、Inverted Indexer (SPIMI)
> 3. **共同負責**：實驗設計與分析、報告撰寫、程式整合
> 4. **GitHub repo**: https://github.com/Rickuan/26FW-Information-Retrieval

---

## 1. 系統簡介

本系統專為大型 Web 語料（ClueWeb09）設計，提供高效能倒排索引與布林檢索功能，處理管線如下：
1. **Loader & Cleaner**：串流解析 WARC 0.18 格式，修復編碼並過濾 HTML 標籤。
2. **Tokenizer & Preprocessor**：字元清洗、縮寫/否定詞保護、位置保真停用詞過濾、大小寫折疊與字幹提取。
3. **Inverted Indexer**：自製欄式整數陣列（`array('I')`），支援全記憶體與 SPIMI 外部排序分塊索引。
4. **Index Writer**：同步寫出作業規範文字檔（`dictionary.txt`, `postings.txt`）與二進制索引檔（`lexicon.tsv`, `postings.bin`）。
5. **Skip Builder & Query Engine**：動態建立 Skip 指標（$L = \lfloor\sqrt{P}\rfloor$），提供跳躍加速布林 AND 檢索。

---

## 2. 環境相依與快速上手

需 Python 3.12+，於專案根目錄透過 `uv` 安裝相依套件：
```bash
uv sync
```
主要套件包含：`spacy`, `nltk`, `beautifulsoup4`, `lxml`, `ftfy`, `psutil`, `tqdm`。請確認語料位於 `HW1/dataset/04.warc`。

---

## 3. 命令列介面與執行指令

以 `HW1/src/main.py` 為統一入口點：

```bash
# 1. 一鍵全量建置（產物輸出至 HW1/output/；可選 --mode spimi、--no-casefold、--no-stopword、--no-stem、--lemma、--limit N）
uv run python HW1/src/main.py build

# 2. 布林 AND 檢索（預設啟用 Skip 指標加速；加上 --no-skips 可切換為線性比對驗證）
uv run python HW1/src/main.py query "information" "retrieval" --show-docs 5
```

---

## 4. 系統主要特色

- **巨量語料支援與低記憶體架構**：
  - **Columnar 欄式陣列**：以連續 `array('I')` 存放倒排表，記憶體峰值自 3.7 GB 降至 1.1 GB（減少 70% 記憶體）。
  - **SPIMI 外部排序歸併**：支援記憶體閾值自動分塊與多路串流歸併，在極限 604 MB 記憶體下穩定完成全量建置。
- **極低儲存開銷與壓縮技術**：
  - **VByte + Delta Gap (d-gap)**：二進制倒排表由 177+ MB 壓縮至 62.97 MB（壓縮率 35.5%，節省 64.5% 空間）。
  - **隨機尋道**：支援基於 `lexicon.tsv` 偏移量之快速查詢，1,000 次隨機詞彙檢索僅耗時 0.03 秒。
- **Skip Pointer 查詢加速**：
  - 動態跳躍間隔 $L = \lfloor\sqrt{P}\rfloor$（$P \ge 9$），長短串列比對次數大幅減少 94.8%（加速比達 19.14x），密集交集時平滑退化為線性比對。
- **文字前處理管線 (Preprocessor Pipeline)**：
  - **字元清洗**：清除不可見及控制字元並轉空格；多種編碼引號統一映射為 ASCII 單引號 `'`。
  - **語意保護與細緻斷詞**：保留否定後綴（`n't`）；縮寫去除點號聚合（`U.S.A.` $\to$ `USA`）；完整保留網域與 Email；智慧切分斜線複合詞（`client/server`）；剝除頭尾非英數雜訊；過濾附著詞素（`'s`, `'ve` 等）；限制 `MAX_LEN = 64` 剔除無意義超長雜訊。
  - **形態學與位置保真**：標記每個 Token 之絕對位置；過濾停用詞時嚴格保留 position 序號不遞減（如 "lord of the rings" 中 "lord" 為 pos 1，"rings" 為 pos 4），真實維護詞距以提高片語檢索精度；徹底大小寫折疊；純字母保護字幹提取與詞元還原。
- **輔助前綴檢索與多重產物格式**：
  - **Radix Trie 前綴檢索**：支援萬筆詞彙 0.01 秒高速前綴檢索（Prefix Search）。
  - **多重產物格式**：單次走訪同步產出符合作業規範之文字檔（`dictionary.txt`, `postings.txt`）與二進制檔（`lexicon.tsv`, `postings.bin`）。

---

## 5. 核心實驗與消融分析

### 實驗一：前處理規則消融分析 (前 5,000 篇基準)

| 實驗組別 | 參數設定 | 詞彙量 ($Vocab$) | 總 Tokens 數 | 索引大小 (`postings.bin`) | 效益與影響分析 |
|---|---|---|---|---|---|
| **基準對照組** | **預設全開** | **94,820** | **2,410,812** | **6.81 MB** | **最佳組態 (詞彙最精簡、儲存開銷最低)** |
| 關閉 Case folding | `--no-casefold` | 124,310 (+31.1%) | 2,410,812 | 7.92 MB (+16.3%) | 大小寫未合併，字典規模顯著膨脹 |
| 關閉 Stopwords | `--no-stopword` | 94,999 (+0.2%) | 3,921,405 (+62.7%) | 11.95 MB (+75.5%) | 高頻虛詞全數建表，倒排表體積激增 75.5% |
| 關閉 Stemming | `--no-stem` | 124,131 (+30.9%) | 2,410,812 | 7.92 MB (+16.3%) | 衍生詞形未歸納（如 `retrieval` vs `retrieving`） |
| 啟用 Lemmatization | `--lemma` | 108,450 (+14.4%) | 2,410,812 | 7.35 MB (+7.9%) | 保留詞形語意且不破壞詞根，詞彙量介於兩者之間 |

### 實驗二：Skip Pointer 查詢加速對比 (全量 34,786 篇)

| 測試情境 | 查詢詞組 (q1 AND q2) | Basic 比較次數 | Skip 比較次數 | 比較減少率 (%) | 加速倍率 |
|---|---|---|---|---|---|
| **長短串列 (長度懸殊)** | `home` AND `hallyday` | 19,145 | **1,000** | **-94.8%** | **19.14x** |
| **典型同現詞組** | `game` AND `play` | 9,225 | **8,399** | **-9.0%** | **1.10x** |
| **高頻密集交集** | `home` AND `new` | 27,946 | 27,946 | 0.0% (平滑退化) | 1.00x |

> **結論**：長短串列因短串列稀疏，Skip 連續跳躍減少 94.8% 比對次數；密集交集自動平滑退化為線性比對，無額外判斷負擔。

---

## 6. 重大困難與解決方案

1. **WARC 標頭瑕疵與捨棄 `warcio`**：部分標頭 `Content-Length` 誤差導致第三方庫偏移錯位；改以自製串流解析器依邊界標記 `b"WARC/0.18"` 精準切割。
2. **HTML 編碼衝突與無聲截斷**：HTTP 宣告與內文編碼不符導致 `lxml` 截斷；改以 `UnicodeDammit` 先解碼轉字串再傳入，搭配 `ftfy` 修復 Mojibake，截斷數降至 1 篇。
3. **巨量語料之記憶體爆炸**：原生 Python 物件造成 Peak RSS 高達 3.7 GB；自製欄式連續陣列 `array('I')` 降至 1.1 GB（-70%），並以 SPIMI 外部歸併在 604 MB 預算下完成建置。
4. **Skip Pointer 統計公平性與邊界**：連續跳躍若未計入條件比較會低估開銷且短串列有額外負擔；嚴格將跳躍比對計入統計，並設定 $P < 9$ 短串列不建 Skip 指標以平滑退化。
5. **數字年份保真與網址截斷保護**：年份具重要時序語意，嚴格限制純字母才執行 Stemming 避免數值破壞；網址與具主題辨識價值，透過 `MAX_LEN = 64` 保留核心網域並剔除 Base64 未解析冗長參數。
