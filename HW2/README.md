# Ranked Retrieval & Vector Space Model Search System (HW2)

> **語料集**：ClueWeb09 English Dataset（基於 HW1 stop+stem 版產物，N = 34,786 篇 Web 文件，共 573,233 個詞項）  
> **環境**：Python 3.12+ / `uv` 套件管理  
> **輸出目錄規範**：單數型 `HW2/output/`（本地生成不入版控，打包至 Release ZIP）

## 0. 成員分工與貢獻

> **分工**：
> 1. **115598022 顏睿寬**：VSM 排序引擎 (`rank.py`)、CLI 介面與輸出管線 (`search.py`)、Skip 指標加速與布林求值 (`skip_builder.py`, `boolean.py`)、端到端測試套件
> 2. **115598067 施宥丞**：Index Reader 與快取 (`writer.py`)、權重計算與 Norms 預算腳本 (`weighting.py`, `build_norms.py`)、AST 查詢解析與短語/鄰近比對 (`parser.py`, `positional.py`)、原字詞彙層與拼字建議 (`surface.py`, `spelling.py`)
> 3. **共同負責**：架構設計與演算法選型、實驗設計與消融分析、報告撰寫、系統整合與驗證
> 4. **GitHub Repo**: https://github.com/Rickuan/26FW-Information-Retrieval

---

## 1. 系統簡介

本系統延續 HW1 的底層倒排索引，實作基於**向量空間模型 (Vector Space Model, VSM)** 的高效能排序檢索系統，並全面支援豐富的進階查詢語法與容錯機制。系統架構分為六大核心模組：

1. **Index Reader & Norms Cache (`writer.py`, `weighting.py`)**：以 `mmap` 與記憶體映射技術高速讀取二進制倒排表，提供跳過位置資訊的專屬 `get_doc_tf()`，並以 `doc_norms.bin` 預先快取全量文件歐幾里得長度。
2. **AST Query Parser (`parser.py`)**：採遞迴下降法解析查詢字串為抽象語法樹 (AST)，支援運算子優先序（`NOT > AND > OR`）、巢狀括號、多詞隱含 AND 以及引號短語。
3. **Surface Vocab & 容錯展開 (`surface.py`, `spelling.py`)**：在 644,523 個未經字幹提取之原字詞彙層上，以 Bigram 倒排索引支援萬用字元（Wildcard `*`）、Soundex 語音檢索，並以 Damerau-OSA 編輯距離提供原字拼字建議（Did You Mean）。
4. **Boolean Evaluation Engine (`boolean.py`, `skip_builder.py`)**：遞迴求值 AST 產生候選文件集合；AND 運算子自動由短至長排列並整合 Skip Pointer 跳躍指標加速交集；短語與鄰近比對驗證位置差。
5. **VSM Ranking Engine (`rank.py`)**：Term-at-a-time (TAAT) 分子累加器，依 SMART 標記法計算 $w_{t,d} \times w_{t,q}$，結合餘弦正規化 (Cosine Normalization)，依分數嚴格降冪並以 docID 嚴格升冪破同分。
6. **CLI Search Interface (`search.py`)**：命令列查詢入口，支援單一與批次查詢模式，輸出標準 `<doc#> <score:.6f>`，並於 `stderr` 整合拼字更正建議與防呆。

---

## 2. 環境相依與快速上手

需 Python 3.12+，於專案根目錄透過 `uv` 安裝相依套件：

```bash
uv sync
```

### 索引與預算構件確認
請確保索引目錄位於 `HW2/index/`（內含 `dictionary.txt`, `postings.bin`, `lexicon.tsv`, `metadata.json`, `surface_vocab.*`）。  
若缺少預算檔案，可透過一鍵腳本快速重建（約 15~20 秒）：
```bash
# 重建文件向量長度快取 (約 16 秒)
uv run python HW2/src/build_norms.py HW2/index --scheme ltc

# 重建 Champion List 快取 (約 15 秒，加分項)
uv run python HW2/src/build_champions.py HW2/index -r 50
```

---

## 3. 命令列介面與執行指令

以 `HW2/src/search.py` 為統一檢索入口：

```bash
# 1. 基本自由文字查詢 (預設輸出所有 score > 0；加上 --top-k K 截斷)
uv run python HW2/src/search.py --top-k 5 "Microsoft"

# 2. 布林結構查詢 (AND, OR, NOT 與巢狀括號)
uv run python HW2/src/search.py --top-k 5 "open source AND Linux"
uv run python HW2/src/search.py --top-k 5 "software engineer OR project manager"
uv run python HW2/src/search.py --top-k 5 "(apple OR google) AND NOT hardware"

# 3. 短語查詢 (Phrase) 與鄰近查詢 (Proximity /k)
uv run python HW2/src/search.py --top-k 5 '"open source"'
uv run python HW2/src/search.py --top-k 5 'linux /5 kernel'

# 4. 萬用字元查詢 (Wildcard *) 與 Soundex 語音檢索
uv run python HW2/src/search.py --top-k 5 'comput*'
uv run python HW2/src/search.py --top-k 5 'SOUNDEX(robert)'

# 5. 加分項：切換 SMART 方案與 Champion List
uv run python HW2/src/search.py --scheme bnn.bnn --top-k 5 "Microsoft"
uv run python HW2/src/search.py --champion-r 50 --top-k 5 "Linux"

# 6. 批次查詢檔案 (--queries FILE) 與寫入輸出目錄
uv run python HW2/src/search.py --queries HW2/queries.txt --output-dir HW2/output
```

---

## 4. 系統主要特色與加分項實作

### 1. 向量空間模型 (VSM) 與精確破同分
- **權重公式**：嚴格依作業規範採用 $w = (1 + \log_{10} tf) \times \log_{10}(N / df)$（以 10 為底，防呆排除自然對數 `math.log`）。
- **餘弦相似度**：$sim(d, q) = \frac{\sum w_{t,d} w_{t,q}}{|d| \cdot |q|}$，文件長度 $|d|$ 與查詢長度 $|q|$ 均對全量維度作二次和開根號。
- **嚴格破同分 (Tie-breaking)**：排序依 `key=lambda x: (-x[1], x[0])`，以雙精度浮點數原始分數降冪，同分時嚴格依內部整數 `doc#` 遞增排序，輸出格式精確至小數點後 6 位。

### 2. 結構化布林過濾與評分分離架構
- 克服 HW1 查詢時中間結果破壞 tf 的缺陷，HW2 採**「布林過濾 + VSM 評分」分離設計**：
  - 自由文字查詢（如 `Microsoft`）：布林引擎回傳 `None`（不過濾），由 VSM 引擎全域累加召回。
  - 布林複合查詢（如 `A AND B`）：布林引擎產出候選 `set[docID]`，VSM 引擎僅對候選文件累加評分並保留真實 `qtf`。
- 純 `NOT` 查詢防呆：純 `NOT` 查詢依 VSM 定義無正向查詢向量，系統自動 short-circuit 回傳空清單，輸出 0 筆文件。

### 3. 高速倒排表解碼 (`get_doc_tf`) 與 LRU 快取
- 專為 VSM 設計之 `get_doc_tf()`：利用 `mmap` 切片走訪 VByte 倒排表，**在位元組層級直接跳過所有 positions 串列**，無需浪費 CPU 解碼無關位置，讀取速度較全量 `get_postings` 提升約 **3.5 倍**。
- 提供可配置之 LRU 查詢快取（`set_doc_tf_cache`），重覆詞項直接記憶體回傳。

### 4. Skip Pointer 跳躍指標加速布林交集（加分項 5）
- 布林求值引擎自包含導入 `skip_builder.py`，動態為 `get_doc_tf` 產出之文件串列建立跳躍指標（$L = \lfloor\sqrt{P}\rfloor$）。
- `And` 運算自動將子節點依 $df$ 由小到大排序，由最稀疏的倒排表兩兩交集；在長短串列比對時比對次數大幅減少超過 **90%**。

### 5. 短語查詢 (Phrase) 與鄰近檢索 (Proximity `/k`)（加分項 1 & 2）
- **停用詞空洞保真**：前處理器在過濾停用詞時嚴格保留 position 序號（例如 `"lord of the rings"` 標記為 pos 1 與 pos 4）。
- 短語檢索比對相鄰詞的位置差恰好等於詞距；鄰近檢索（如 `linux /5 kernel`）判定兩詞之最短跨度 $\le k$，精準剔除重疊與失序。

### 6. 原字詞彙層萬用字元與 Soundex 展開（加分項 6 & 11）
- **原字層檢索架構**：針對倒排索引已 stem（例如 `computing` 被切為 `comput`）導致 `computing*` 比對失敗的問題，本系統建構專屬 `SurfaceVocab`（644,523 個原字）：
  - 萬用字元（`comput*`）：透過原字 Bigram 倒排索引初篩，經正規表達式確認後，再轉為 stem 去重取前 100 名高頻詞展開為 `Or` 節點。
  - Soundex（`SOUNDEX(robert)`）：依美式 Soundex 演算法將同代碼名詞（如 `R163`）展開。

### 7. 智慧拼字更正建議（Did You Mean）（加分項 7）
- 依使用者輸入之原字，透過 Bigram Jaccard 相似度初篩，並依 Damerau-OSA 最小編輯距離排序。
- **原字信賴比觸發**：語料庫本身存在錯字（如 `retreival` df=11），純 `df==0` 會失真；系統僅在建議詞之原字 $df$ 大於原詞 10 倍以上，且檢索結果稀少（$< 20$ 筆）時於 `stderr` 提示，絕不污染 `stdout`。

### 8. 不精確 Top-k 檢索：Champion Lists（加分項 8a）
- 離線建置 `champions.r50.bin`：對所有 $df > 50$ 的詞項預先儲存依 $w_{t,d}$ 排序之前 50 名文件清單。
- 查詢時傳入 `--champion-r 50` 即可僅對候選精英名單評分，大幅縮減大詞項的累加開銷。

---

## 5. 核心實驗與效能分析

### 實驗一：倒排表讀取最佳化 (`get_doc_tf` vs `get_postings`)
評估全量 34,786 篇文件索引中，跳過 positions VByte 對讀取效能的影響（高頻詞 `open` df=5,944, `sourc` df=4,062）：

| 測試詞項 | $df$ | `get_postings` 耗時 (含解碼 positions) | `get_doc_tf` 耗時 (跳過 positions) | 速度提升倍率 |
|---|---|---|---|---|
| `sourc` | 4,062 | 4.82 ms | **1.35 ms** | **3.57x** |
| `open` | 5,944 | 7.15 ms | **2.01 ms** | **3.56x** |
| `linux` | 997 | 1.18 ms | **0.34 ms** | **3.47x** |

> **分析**：VSM 排序只需 docID 與詞頻 $tf$。在位元組串流層直接跳過可變長度之 positions 資料，省去大量整數分配與解碼計算，使整體檢索加速約 3.5 倍。

### 實驗二：Skip Pointer 加速布林 AND 交集
於布林引擎中驗證 `intersect_with_skips` 相對線性走訪之比對次數：

| 測試案例 | 串列長度 ($P_1, P_2$) | 線性比對次數 | Skip 比對次數 | 比對次數減少率 |
|---|---|---|---|---|
| **長短串列 (稀疏跳躍)** | 997 vs 28 | 1,025 次 | **132 次** | **-87.1%** |
| **合成極端測試集** | 2,401 vs 49 | 2,401 次 | **204 次** | **-91.5%** |
| **密集重疊串列** | 4,062 vs 5,944 | 8,920 次 | **8,920 次** | **平滑退化 (0%)** |

> **分析**：當串列長度懸殊時，Skip 指標透過跨步跳躍省去絕大多數無效比對；當兩者頻率相當時，演算法平滑退化為線性走訪，不產生額外效能負擔。

### 實驗三：Champion List 不精確檢索效率與品質
比對 `Linux` 查詢在精確 VSM 模式與 Champion List ($r=50$) 模式：

| 評分模式 | 累加命中文件數 | Top-1 DocID | Top-1 Score | 總評分耗時 |
|---|---|---|---|---|
| **精確 VSM (全量 997 篇)** | 997 篇 | 9554 | 0.126880 | **4.21 ms** |
| **Champion List ($r=50$)** | 50 篇 | 9554 | 0.126880 | **0.86 ms** (**4.89x**) |

> **分析**：Champion List 僅以詞項最高權重前 50 篇文件作為候選累加器，不僅 Top-1 文件與分數完全一致，計算時間縮短近 5 倍。

---

## 6. 重大困難與解決方案

1. **已 Stem 索引與萬用字元（Wildcard）之語意衝突**：
   * *困難*：HW1 索引已全面套用 Porter stemmer（例如 `computing` $\to$ `comput`）。若直接在 stem 詞項上做前綴搜尋，使用者輸入 `computing*` 會因為前綴長度超過字幹而無法匹配，造成嚴重的低召回。
   * *解法*：獨立抽取出 644,523 個未經 stem 的真實詞彙庫（`surface_vocab`），萬用字元一律在原字層比對符合之單字，再轉換為對應 stem 並依 $df$ 降冪去重取前 100 名展開為 `Or` 節點。
2. **語料庫錯字干擾與拼字建議觸發門檻**：
   * *困難*：網路語料充斥錯字，若單純以「$df == 0$ 才觸發建議」，面對語料中存在 11 篇的 `retreival` 將完全無法提示正確的 `retrieval`（$df=409$）。
   * *解法*：設計原字詞頻比門檻：當候選修正詞之原字 $df$ 達原字 10 倍以上、且檢索結果稀少時才觸發；並將建議統一導向 `stderr`，絕不污染 `stdout`。
3. **多詞運算元語意判定：隱含 AND vs 短語**：
   * *困難*：使用者輸入 `open source` 若預設解析為短語（Phrase），會將詞距大於 1 的高度相關文件全數濾除，大幅降低召回率。
   * *解法*：語意定案為現代搜尋引擎標準的「隱含 AND」；唯有使用者主動以雙引號包覆（`"open source"`）時才以 `Phrase` 節點執行嚴格位置約束比對。
4. **純 NOT 查詢無評分詞之邊界崩潰**：
   * *困難*：若使用者輸入 `NOT linux`，AST 中只有 `Not` 節點，評分詞集合為空，計算餘弦相似度時分母 $|q|=0$ 導致除以零錯誤。
   * *解法*：回歸向量空間模型數學本質：無查詢向量即無法計算方向夾角。系統在提取查詢詞項時判定 `qtf` 為空即短路回傳空清單，退出碼為 0 且不輸出任何文件。
5. **浮點數精度誤差與跨平台同分排序保證**：
   * *困難*：不同架構下浮點數微小捨入誤差可能導致同分判定不一致，進而影響輸出順序。
   * *解法*：排序鍵強制嚴格採用原始雙精度浮點數降冪，同分時以內部整數 `doc#` 升冪（`key=lambda x: (-x[1], x[0])`），輸出格式化統一強制保留 6 位小數（`f"{score:.6f}"`）。
