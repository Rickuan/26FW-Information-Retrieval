# Ranked Retrieval & Vector Space Model Search System (HW2)

> **語料集**：ClueWeb09 English 子集 `04.warc`（TREC ID `clueweb09-en0000-04-*`，N = 34,786 篇 Web 文件）；索引沿用 HW1 stop+stem 版產物（573,233 個詞項）  
> **環境**：需 Python ≥ 3.12、`uv`；本報告數據皆在 Python 3.12 環境量測  
> **輸出目錄規範**：單數型 `HW2/output/`（本地生成不入版控，打包至 Release ZIP）

## 0. 成員分工與貢獻

> **分工**：
> 1. **115598022 顏睿寬**：VSM 排序引擎 (`rank.py`)、CLI 介面與輸出管線 (`search.py`)、Skip 指標加速與布林求值 (`skip_builder.py`, `boolean.py`)、端到端測試套件
> 2. **115598067 施宥丞**：Index Reader 與快取 (`writer.py`)、權重計算與 Norms 預算腳本 (`weighting.py`, `build_norms.py`)、AST 查詢解析與短語/鄰近比對 (`parser.py`, `positional.py`)、原字詞彙層與拼字建議 (`surface.py`, `spelling.py`)
> 3. **共同負責**：架構設計與演算法選型、實驗設計、報告撰寫、系統整合與驗證
> 4. **GitHub Repo**: https://github.com/Rickuan/26FW-Information-Retrieval，查看最新 Release

---

## 1. 系統簡介

本系統延續 HW1 的倒排索引，實作基於**向量空間模型 (VSM)** 的排序檢索。查詢流程為：`parser.py` 遞迴下降解析為 AST（`NOT > AND > OR`、括號、隱含 AND、短語、鄰近、萬用字元、`SOUNDEX()`）→ `surface.py` 在原字層展開萬用字元與 Soundex → `boolean.py`／`positional.py` 產生候選文件 → `rank.py` 以 Term-at-a-time 累加並餘弦正規化 → `search.py` 輸出 `<doc#> <score:.6f>`，提示訊息只寫入 `stderr`。

---

## 2. 環境與索引

於專案根目錄執行 `uv sync` 安裝相依套件。繳交檔已附上完整的 `HW2/index/`，**請直接使用附檔，不需重建**。檢索時讀取的檔案：

| 檔案 | 用途 |
|---|---|
| `lexicon.tsv`, `postings.bin`, `metadata.json` | 倒排索引本體（詞項 → $df$／位移、VByte 倒排表、$N$ 與前處理設定） |
| `doc_map.json` | 文件對照表（`doc#` → TREC ID、URL、文件長度） |
| `doc_norms.bin`, `doc_norms.meta.json` | `ltc` 文件向量長度 $\lvert d \rvert$（預設 `ltc.ltc` 必要） |
| `surface_vocab.tsv`, `surface_vocab.meta.json` | 原字詞彙層（需 HW1 未 stem 索引才能重建，務必使用附檔） |
| `champions.r50.bin`, `.tsv`, `.meta.json` | Champion List（僅 `--champion-r 50` 使用） |

各預算檔的 meta 記錄來源檔的 size 與 sha256，與索引不一致時直接報錯。若需自行重建（各約 15 秒）：
```bash
uv run python HW2/src/build_norms.py --index-dir HW2/index --scheme ltc
uv run python HW2/src/build_champions.py --index-dir HW2/index --r 50
```

- **權重方案**：附檔只預建 `ltc` 的 norm 檔。`--scheme` 文件端（`.` 之前）若為 `ltc` 以外、以 `c` 結尾的方案（如 `lnc.ltc`），需先以 `build_norms.py --scheme lnc` 建檔，否則會因缺檔而報錯；文件端以 `n` 結尾（如 `bnn.bnn`）時 $\lvert d \rvert = 1$，不需 norm 檔。
- **Champion**：只預建 $r = 50$；其他 `--champion-r R` 需先執行 `build_champions.py --r R`。

---

## 3. 執行指令

```bash
uv run python HW2/src/search.py --top-k 5 "Microsoft"                           # 自由文字
uv run python HW2/src/search.py --top-k 5 "(apple OR google) AND NOT hardware"  # 布林
uv run python HW2/src/search.py --top-k 5 '"open source"'                       # 短語
uv run python HW2/src/search.py --top-k 5 'linux /5 kernel'                     # 鄰近
uv run python HW2/src/search.py --top-k 5 'co*tion'                             # 萬用字元
uv run python HW2/src/search.py --top-k 5 'SOUNDEX(robert)'                     # Soundex
uv run python HW2/src/search.py --scheme bnn.bnn --champion-r 50 "Linux"        # 加分項
uv run python HW2/src/search.py --queries HW2/queries.txt --output-dir HW2/output  # 批次
```

- 預設輸出所有 score > 0 的文件，`--top-k K` 截斷；單一查詢可用 `-o FILE` 寫檔。
- 批次查詢加上 `--output-dir DIR` 時，第 $i$ 行的 query 寫入 `DIR/query_<i>.txt`（空白行略過但仍佔行號）；未指定時各 query 結果直接接續印至 `stdout`，**中間沒有分隔行**。
- 語法錯誤時於 `stderr` 指出錯誤並以 exit code 1 結束（批次中後續 query 不再執行）。

---

## 4. 系統特色與加分項

### 1. VSM 與破同分
- **權重**：$w = (1 + \log_{10} tf) \times \log_{10}(N / df)$，只在 `weighting.py` 實作一次，`build_norms.py` 與 `rank.py` 共用；餘弦相似度 $sim(d, q) = \frac{\sum w_{t,d} w_{t,q}}{|d| \cdot |q|}$。
- **破同分**：排序鍵為 `(-round(score, 6), doc#)`，分數先四捨五入至與輸出相同的 6 位小數再降冪，相同者依 `doc#` 遞增，因此輸出中看起來同分的文件 `doc#` 一定嚴格遞增。

### 2. 布林過濾與評分分離
- 整個查詢只有一個運算元（如 `Microsoft`、`United States government`）時視為自由文字，不過濾，由 VSM 對含任一查詢詞的文件評分；布林複合查詢則先產出候選集合，VSM 只對候選評分。
- `NOT` 子樹內的詞不計入評分詞；純 `NOT` 查詢沒有查詢向量，直接回傳 0 筆。

### 3. `get_doc_tf` 與 LRU 快取
- `get_doc_tf()` 在位元組層級跳過 positions，不建立 `Posting` 物件；單次讀取一個詞項比 `get_postings` 快約 **3.2～3.8 倍**（實驗一），這不是整體檢索時間的倍數。
- `set_doc_tf_cache(maxsize)` 提供 LRU 快取，屬程式 API 選項，**CLI 預設關閉**。

### 4. Skip Pointer（加分項 5）
- 布林結構內的多詞運算元（如 `open source AND Linux` 中的 `open source`）依 $df$ 由小到大以 `intersect_with_skips` 兩兩交集（$L = \lfloor\sqrt{P}\rfloor$）；顯式 `AND` 則對子節點結果做集合交集。

### 5. 短語與鄰近（加分項 1 & 2）
- 前處理保留停用詞空洞的位置（`"lord of the rings"` → pos 1 與 4），短語要求位置差恰好等於詞距。
- 鄰近 `a /k b`：兩側位置區間的間隔 $\le k$ 即命中，**不分先後**，重疊不算；`linux /5 kernel` 與 `kernel /5 linux` 皆 192 篇。

### 6. 萬用字元與 Soundex（加分項 6 & 11）
- 索引已 stem，`computing*` 無法直接比對，故改在原字層比對：`*` 可出現在任意位置（`comput*`、`*mon`、`co*tion`），以 Bigram 索引初篩、正規表達式確認，再轉 stem 去重，依 $df$ 取前 100 個展開為 `Or`（超過時於 `stderr` 警告）。
- `SOUNDEX(robert)` 取同代碼（`R163`）的純英文字母原字，同樣轉 stem 取前 100 個。

### 7. 拼字建議（加分項 7）
- Bigram Jaccard（$\ge 0.3$）初篩，排除與原字同 stem 者，依 Damerau-OSA 距離排序。
- 有候選且「原字 $df = 0$」或「最佳建議原字 $df \ge$ 原字 $df \times 10$」時觸發，在結果少於 20 筆時於 `stderr` 顯示前 3 個。例：`retreival`（$df = 1$）→ `retrieval`（$df = 81$）。

### 8. Champion Lists（加分項 8a）
- 對 $df > 50$ 的 15,755 個詞項，依 **$tf$ 由大到小**選取前 50 篇（$df \le 50$ 直接用完整倒排表）；`--champion-r 50` 只對這些文件評分，分母仍用完整 $\lvert d \rvert$，結果**不精確**。

---

## 5. 實驗

### 實驗一：`get_doc_tf` vs `get_postings`
暖身後各跑 21 次取中位數（x86_64 / Linux，耗時依機器而異）：

| 詞項 | $df$ | `get_postings` | `get_doc_tf` | 倍率 |
|---|---|---|---|---|
| `home` | 22,611 | 26.25 ms | **6.83 ms** | **3.84x** |
| `open` | 5,944 | 6.34 ms | **1.98 ms** | **3.21x** |
| `linux` | 997 | 1.13 ms | **0.34 ms** | **3.29x** |

### 實驗二：Skip Pointer 比對次數
以 `intersect_postings(use_skip=False／True)` 對真實倒排表計數（與機器無關，可完全重現）：

| 詞項 | 串列長度 | 線性 | Skip | 變化 |
|---|---|---|---|---|
| `linu` & `linux` | 28 vs 997 | 986 | **567** | **-42.5%** |
| `kernel` & `linux` | 279 vs 997 | 1,028 | **908** | **-11.7%** |
| `sourc` & `open` | 4,062 vs 5,944 | 8,496 | **8,592** | **+1.1%** |
| `project` & `manag` | 4,556 vs 7,062 | 9,919 | **9,613** | **-3.1%** |

> 長度懸殊時可整段跳過、明顯減少比對；長度相近的密集串列幾乎每步都需前進，檢查跳躍目標反而略增。

### 實驗三：Champion List（`Linux`，$r = 50$）
`rank()` 暖身後跑 51 次取中位數：

| 模式 | 命中文件 | Top-1 | `rank()` 耗時 | 與精確結果重疊（Top-1／10／50） |
|---|---|---|---|---|
| 精確 VSM | 997 | 20949（0.187963） | 1.053 ms | — |
| Champion | 50 | 9554（0.126880） | **0.045 ms** | 0／2／8 |

> 速度快約 23 倍，但品質明顯下降：精確 Top-1 不在 champion 名單中。選取只依 $tf$，而 $tf$ 高的多為長文件，正規化後分數偏低（Top-10 的文件長度中位數：精確 164.5、champion 494.5）。

---

## 6. 重大困難與解決方案

1. **已 stem 索引與萬用字元衝突**：`computing*` 在 stem 詞項（`comput`）上無法比對。→ 另建 644,523 個原字的 `surface_vocab`，在原字層比對後再轉 stem 展開。
2. **語料錯字使 `df == 0` 門檻失效**：`retreival` 在語料中出現過（原字 $df = 1$），純 `df == 0` 不會提示 `retrieval`（$df = 81$）。→ 改用「最佳建議原字 $df \ge$ 原字 $df \times 10$」門檻，並只輸出至 `stderr`。
3. **多詞運算元語意**：若預設為短語會濾掉大量相關文件。→ 未加引號解析為隱含 AND（在布林結構內要求所有詞都出現；單獨成為整個查詢時視為自由文字），加引號才是 `Phrase`。
4. **純 NOT 查詢無評分詞**：`NOT linux` 沒有評分詞，$|q| = 0$ 會除以零。→ `qtf` 為空即回傳空清單，exit code 0。
5. **輸出精度與同分順序不一致**：原本以原始分數排序、輸出卻只到 6 位小數，4 個範例 query 共 803 處「看似同分但 `doc#` 逆序」（801 處為小於 $10^{-6}$ 的真實分差，2 處為浮點微差）。→ 排序鍵改為 `(-round(score, 6), doc#)`，排序依據與輸出精度一致。
