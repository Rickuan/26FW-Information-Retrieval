# IR HW2 實作規劃

## 已確定的設定

| 項目 | 決定 | 依據 |
| --- | --- | --- |
| 截止與繳交 | 2026/11/18，上傳 iSchool+，檔名 `<學號>_HW2.zip` | 作業說明 |
| Index | 交出去的 stop+stem 版，來源 `HW1/output_main`，放在 `HW2/index/`：573,233 個 term，N = 34,786 | 與繳交的 dictionary／postings 逐 byte 比對過 |
| 文件權重 | w\_ij = (1 + log10 tf\_ij) × log10(N / df\_i) | 作業說明 + TA |
| 相似度 | cosine，\|d\| 對文件內全部 term 加總 | 投影片 |
| `<doc#>` | 內部整數 docID，與 postings.txt 相同 | 依 HW1 設定 |
| Query 權重 w\_iq | (1 + log10 tf\_iq) × log10(N / df\_i)，與文件同公式（ltc） | 上課公式，組內決定 |

```latex
sim(d_j, q) = \frac{\sum_{i} w_{i,j} \, w_{i,q}}{\sqrt{\sum_{i} w_{i,j}^2} \; \sqrt{\sum_{i} w_{i,q}^2}}, \qquad w = (1 + \log_{10} tf) \times \log_{10}\frac{N}{df}
```

## 整體架構

檔案配置（T1–T5 已完成，T6–T7 待實作）：
- `weighting.py`、`build_norms.py`、`build_champions.py`：W 權重與 T2 norm、champion 建置（已完成，見 `.done.T2-norms-weighting.md`）
- `writer.py`：T1、T2、T3 Index 讀取核心（df、N、get_norms、get_doc_tf、get_champions、快取，見 `.done.T1-index-reader.md`–`.done.T3-doc-tf-reader.md`）
- `tokenizer.py`：T1、T4c 前處理器與 `normalize_token`（見 `.done.T1-index-reader.md`、`.done.T4-query-parser.md`）
- `parser.py`、`positional.py`、`spelling.py`：T4/T4b/T4c AST、語法解析、位置比對、拼字建議（見 `.done.T4-query-parser.md`）
- `surface.py`、`build_surface_vocab.py`：T4c 原字詞彙層、k-gram 與 Soundex 分組（見 `.done.T4-query-parser.md`）
- `skip_builder.py`：T5 引入之 Skip 指標與交集演算法（自包含於 `HW2/src/`，見 `.done.T5-boolean-evaluate.md`）
- `boolean.py`：T5 Boolean 求值（已完成，見 `.done.T5-boolean-evaluate.md`）
- `rank.py`：T6 VSM 排序（stub，待實作）
- `search.py`：T7 CLI 查詢介面（尚未建立）

## 必做任務

關鍵路徑：T1 → T3 → T5 → T6 → T7；T2、T4 為旁支。
**進度：W、T1、T2、T3、T4、T5 皆已完成並通過單元測試，下游 T6–T7 的所有上游接口已全數就緒。**

| 任務 | 對應作業要求 | 狀態 | 盤點缺口 | 直接依賴 | 提供的接口 |
| --- | --- | --- | --- | --- | --- |
| W 權重函式（T2 負責） | tf-idf 公式（log10） | ✅ 已完成（PR #22） | — | — | `weighting.weight()` |
| T1 Index 載入與前處理還原 | 輸入：HW1 inverted index | ✅ 已完成（PR #21） | G1、G4、G10 | — | `IndexReader.df()`、`IndexReader.N`、`Preprocessor.from_config()` |
| T2 預算文件 norm | cosine 的 \|d\| | ✅ 已完成（PR #22） | G3 | T1、W | `IndexReader.get_norms()` |
| T3 只取 doc／tf 快速讀取 | 評分效率 | ✅ 已完成（PR #23） | G9 | T1 | `IndexReader.get_doc_tf()` |
| T4 Query parser | 三種 query 類型 | ✅ 已完成（PR #24） | G5、G6 | T1 | `parse()`、`query_terms()`、`expand()` |
| T5 Boolean merge | 簡單 Boolean query | ✅ 已完成（PR #26） | — | T3、T4 | `evaluate()` |
| T6 VSM 排序 | VSM、tf-idf、cosine | ⏳ 待開發（stub） | G8 | W、T1–T5 | `rank()` |
| T7 輸出與執行入口 | `<doc#> <score>` 排序輸出 | ⏳ 待開發 | G13 | T6 | `search.py` CLI |

### 接口定義

T1–T5 接口均已正式實作並通過完整測試，T6 目前為 stub。加分參數均有相容預設值。

```python
# W & T2 — weighting.py, build_norms.py, build_champions.py
LOG_BASE = 10; DEFAULT_SCHEME = "ltc"; FORMULA = "(1+log10 tf)*log10(N/df)"
def weight(tf: int, df: int, N: int, scheme: str = "ltc") -> float: ...  # tf==0 或 df==0 回傳 0.0
def formula(scheme: str = "ltc") -> str: ...
def norm_filenames(scheme: str = "ltc") -> tuple[str, str]: ...  # ltc -> ("doc_norms.bin", "doc_norms.meta.json")
def build_norms(index_dir: Path, scheme: str = "ltc") -> None: ...  # CLI 預算文件 norm；n 方案拋 ValueError
def build_champions(index_dir: Path, r: int = 50) -> None: ...      # champions.r<r>.{bin,tsv,meta.json}

# T1, T2, T3 — writer.py
class IndexReader:
    N: int                                                      # metadata["N"]
    def df(self, term: str) -> int: ...                         # 不存在回傳 0
    def vocabulary(self) -> list[str]: ...                      # 排序過的全部 term（共用快取）
    def prefix_terms(self, prefix: str) -> list[str]: ...       # bisect 前綴搜尋；空字串拋 ValueError
    def get_norms(self, scheme: str = "ltc") -> array: ...      # 核對來源 sha256；n 方案回傳全 1.0
    def get_doc_tf(self, term: str) -> tuple[list[int], list[int]]: ...       # mmap 讀取 (doc_nums, tfs)，跳過 positions
    def get_champions(self, term: str, r: int = 50) -> tuple[list[int], list[int]]: ...  # 取預存前 r 名
    def set_doc_tf_cache(self, maxsize: int) -> None: ...       # 0 = 關閉（預設）
    def doc_tf_cache_info(self) -> tuple[int, int]: ...         # (hits, misses)

# T1, T4c — tokenizer.py
class Preprocessor:
    @classmethod
    def from_config(cls, cfg: dict) -> "Preprocessor": ...      # 嚴格還原 index 前處理設定
    def normalize_token(self, tok: str) -> str | None: ...      # 單一 token 標準化（stopword 回傳 None）
    def process(self, text: str) -> list[tuple[int, str]]: ...  # 回傳 [(pos, term), ...]，保留空洞

# T4, T4b, T4c — parser.py, positional.py, spelling.py, surface.py
Node = Term | Phrase | Near | Wildcard | Soundex | Not | And | Or
def parse(query: str, pre: Preprocessor) -> Node | None: ...            # 遞迴下降解析 AST；語法錯誤拋 ValueError
def expand(node: Node | None, reader: IndexReader, limit: int = 100) -> Node | None: ...  # Wildcard/Soundex 原字展開
def query_terms(node: Node) -> Counter[str]: ...                       # 評分 term 與 qtf；跳過 Not；遇 Wildcard/Soundex 拋錯
def query_words(query: str, pre: Preprocessor) -> list[str]: ...        # 使用者輸入的原字清單（供拼字檢查）
def position_match(node: Phrase | Near, reader: IndexReader) -> set[int]: ...   # 位置比對，命中回傳 doc 集合
def did_you_mean(word: str, reader: IndexReader, show: int = 3) -> list[str]: ...  # 拼字建議（以原字 df 判斷觸發）
def load_surface(reader: IndexReader) -> SurfaceVocab: ...              # 載入 surface_vocab.{tsv,meta.json}

# T5 — boolean.py（已完成，見 .done.T5-boolean-evaluate.md）
def evaluate(node: Node, reader: IndexReader) -> set[int] | None: ...   # 根為 Term 回傳 None（不過濾），其餘回傳候選 doc 集合

# T6 — rank.py（待實作）
def rank(qtf: Counter[str], candidates: set[int] | None, reader: IndexReader,
         scheme: str = "ltc.ltc", champion_r: int | None = None) -> list[tuple[int, float]]: ...  # 依 (-score, doc) 排序

# T7 — search.py CLI（待實作）
# uv run python HW2/src/search.py --index-dir HW2/index [--top-k K] [--queries FILE] [--scheme SCHEME] "query"
```

### 查詢流程

每個 query 固定依序經過以下五步；`parse` 或 `expand` 回傳 `None` 則直接結束輸出空結果：
```python
node  = parse(query, pre)             # T4：解析 AST；語法錯誤報錯結束
node  = expand(node, reader)          # T4：展開 Wildcard/Soundex 為 Or[Term...]
cands = evaluate(node, reader)        # T5：Boolean 候選過濾；None = 不過濾
qtf   = query_terms(node)             # T4：提取評分詞與 query tf
hits  = rank(qtf, cands, reader)      # T6：VSM 計算分數並排序 → T7 輸出
```
- **交接點 T3 → T5**：`get_doc_tf` 回傳 docID 列表。`boolean.py` 需包裝成含 `.doc_num`／`.skip` 之節點供 `intersect_with_skips` 使用。
- **交接點 W → T2、T6**：一律由 `weighting.weight` 與常數計算權重，不自寫公式。

### 各模組設計規格

- **T1 Index 載入與前處理還原（已完成，見 `.done.T1-index-reader.md`）**：
  - `HW2/index/` 來自 `HW1/output_main`（stop+stem 版，N = 34,786，573,233 terms）。
  - `IndexReader._load_lexicon` 存 `(df, offset, length)`；提供 `df()`、`vocabulary()` 與 `prefix_terms()`。
  - `Preprocessor.from_config(metadata["preprocessor"])` 採嚴格模式還原設定。
  - `HW1/output`（未 stem 版）僅供 T4c 的 `build_surface_vocab.py` 抽取原字詞彙，不作查詢 index。
- **T2 文件向量 Norm 與加分項（已完成，見 `.done.T2-norms-weighting.md`）**：
  - 獨立腳本 `build_norms.py` 預先計算並產出 `doc_norms.bin`（$|d_j| = \sqrt{\sum w_{ij}^2}$）與 `meta.json`。
  - `IndexReader.get_norms(scheme)` 自動核對來源檔 sha256 並快取；`n` 方案直接回傳全 1.0。
  - 加分：SMART scheme 參數化（`formula()`、`norm_filenames()`）；`build_champions.py` 產出 `champions.r50.*`。
- **T3 快速讀取與快取（已完成，見 `.done.T3-doc-tf-reader.md`）**：
  - `get_doc_tf(term)` 透過 `mmap` 與直接跳過 positions VByte，大幅提升讀取效率（實測加速 ~3.5x）。
  - 加分：`get_champions(term, r)` 讀取預存名單；`set_doc_tf_cache(maxsize)` 提供 LRU 快取。
- **T4 Query Parser 與容錯檢索（已完成，見 `.done.T4-query-parser.md`）**：
  - 遞迴下降解析 AST（`Term`、`And`、`Or`、`Not`、`Phrase`、`Near`、`Wildcard`、`Soundex`），優先序 `NOT > AND > OR`。
  - 自動簡化空節點、攤平同型巢狀節點；未配對括號/引號、空萬用字元（`*`）、`/0`、非合法 SOUNDEX 拋 `ValueError`。
  - `expand` 於原字詞彙層（`surface_vocab.*`）透過 bigram index + regex 比對萬用字元或 Soundex 分組，依 stem 去重後取前 100 名。
  - 加分：`positional.position_match` 處理短語/鄰近比對；`spelling.did_you_mean` 原字拼字建議。
- **T5 Boolean 求值（已完成，見 `.done.T5-boolean-evaluate.md`）**：
  - 遞迴求值 AST 產生候選 doc 集合：根節點為 `Term` 回傳 `None`（自由文字不過濾）；`And` 採 df 由小到大兩兩交集（重用 `HW2/src/skip_builder.py` 之 `intersect_with_skips`，保持 HW2 自包含）；`Or` 採線性聯集；`Not` 採全集 `set(range(N))` 做集合差。
  - `Phrase` 與 `Near` 呼叫 `positional.position_match(node, reader)`。
  - 防呆：輸入必須先經 `expand`，遇 `Wildcard` 或 `Soundex` 拋 `ValueError`。
- **T6 VSM 排序（待實作，`rank.py`）**：
  - Term-at-a-time 累加器：逐評分 term 讀取 `get_doc_tf(t)`，對候選集合內（若為 None 則全部）文件累加 `acc[doc] += w_td * w_tq`。不在 dict 者 df=0 略過。
  - 最終分數 `score = acc[doc] / (norm[doc] * |q|)`，依 `(-score, doc)` 排序（同分 docID 小在前）。
  - 加分：SMART scheme 切換（如 `lnc.ltc`）；`champion_r` 開啟不精確 top-k。
- **T7 輸出與 CLI 入口（待實作，`search.py`）**：
  - CLI 支援單一 query 與 `--queries` 批次模式；每行輸出 `<doc#> <score>`（不加表頭，空白分隔，小數 6 位，同分嚴格依 `<doc#>` 遞增排序；預設輸出所有 score > 0，另加 `--top-k`）。
  - 整合錯誤處理：語法與缺檔錯誤輸出訊息並以非 0 退出；警告輸出至 stderr；結果罕見時觸發 `did_you_mean`。

## 加分任務

| 優先 | 項目 | 狀態 | 負責任務 | 做法與接口 | 注意 |
| --- | --- | --- | --- | --- | --- |
| 1 | Phrase query（`"open source"`） | ✅ 已完成（T4/T5） | T4 / T5 | 先 AND 取候選，再比對 positions（`position_match`） | stopword 空洞保留，比對位置差 |
| 2 | Proximity（`linux /5 kernel`） | ✅ 已完成（T4/T5） | T4 / T5 | 兩段 Phrase 區間間隔 ≤ k（`position_match`） | 距離以 index 位置計，重疊不算 |
| 3 | 權重方案變體（SMART） | ✅ T2 完成，⏳ 待 T6 整合 | T2 / T6 | `--scheme lnc.ltc` 切換 tf/idf/norm（`weight`、`get_norms`） | c 方案 norm 檔名帶 scheme |
| 4 | 多運算子與括號 | ✅ 已完成（T4/T5） | T4 / T5 | Parser 支援 NOT 與巢狀括號；NOT 以 `set(range(N))` 做差集 | 純 NOT 無評分詞 |
| 5 | Skip pointer 加速 AND | ✅ 已完成（T5） | T5 | 使用 `intersect_with_skips`，記錄比較次數對照 basic | skip 每次查詢動態建立 |
| 6 | Wildcard（`comput*`） | ✅ 已完成（T4c） | T4 | 原字 bigram 篩選 + regex post-filter 展開（`expand`、`surface.py`） | 展開上限 100，依 df 截斷 |
| 7 | 拼字更正 | ✅ T4c 完成，⏳ 待 T7 顯示 | T4 / T7 | 原字 bigram 篩選 + OSA 距離排序（`did_you_mean`、`spelling.py`） | 依原字 df 差距觸發，僅建議不替換 |
| 8a | 不精確 top-k：champion list | ✅ T2/T3 完成，⏳ 待 T6 整合 | T2 / T3 / T6 | 預存 df > r 前 r 名（`champions.r50.*`、`get_champions`） | 排序與精確不同，預設關閉 |
| 8b | 不精確 top-k：index elimination | ⏳ 待開發（獨立優化工項） | 待排定 | 僅使用 idf 高於門檻之 term 評分；T6/T7 完成後獨立開發 | 預設關閉 |
| 9 | Web UI 與 term highlighting | ⏳ 待開發（選用） | T7 | Flask/FastAPI 或 Streamlit 單頁介面 | highlight 需重讀 WARC，成本較高 |
| 10 | `get_doc_tf` 的 LRU 快取 | ✅ 已完成（T3） | T3 | `set_doc_tf_cache(maxsize)` | 回傳複本避免修改，預設關閉 |
| 11 | Soundex（`SOUNDEX(robert)`） | ✅ 已完成（T4c） | T4 | 運算子展開同碼原字；`suggest_soundex` 建議 | 為人名設計，一般詞碰撞多，輔助用 |

## 驗證與測試

已建置 **11 組單元測試套件（共 4,000+ 行測試代碼）**：
- `t1.test.py`（27/27）、`t1_bonus.test.py`：IndexReader、df、preprocessor 設定還原、vocabulary、prefix_terms
- `t2.test.py`、`t2_bonus.test.py`：weighting、build_norms、SMART 方案（ltc, lnc, bnn）、champions 建置
- `t3.test.py`、`t3_bonus.test.py`：get_doc_tf 跳過 positions、mmap 切片、get_champions、LRU 快取
- `t4.test.py`（48/48）、`t4_bonus.test.py`、`t4_surface.test.py`：AST、parser、phrase/proximity、wildcard、拼字建議、Soundex
- `t5.test.py`（18/18）、`skip_builder.test.py`（4/4）：Boolean 求值引擎、And/Or/Not/Phrase/Near 求值、MockReader、Skip 次數驗證

端到端與待開發驗證清單：
- [x] **T5 單元測試**：撰寫 `t5.test.py` 與 `skip_builder.test.py`，驗證 AND、OR、NOT、Phrase、Near 求值與邊界狀況。
- [ ] **T6 單元測試**：撰寫 `t6.test.py`，驗證 term-at-a-time 累加、候選文件過濾、cosine 排序、SMART scheme 切換與 champion_r。
- [ ] **手算小語料**：3～5 篇假文件建成小 index，在紙上或試算表算出 cosine，對照輸出至小數第 6 位。
- [ ] **暴力對照**：隨機抽 20 篇真實文件全掃 postings 算完整向量，對照 T2 norm 與 T6 分數。
- [ ] **前處理一致性**：確認解析詞彙（`inform`、`retriev`、`open`、`sourc`、`linux`、`e`、`mail`）皆存於 dictionary。
- [ ] **作業範例 query**：`Microsoft`、`United States government`、`open source AND Linux`、`software engineer OR project manager` 輸出至 outputs。
- [ ] **健全性與邊界**：空 query、全 stopword、不存在詞、純 NOT、重複詞；分數落在 (0, 1] 且嚴格遞減。

## 繳交物與時程

建議 11/13 前完成必做並通過測試，剩下時間留給加分與報告。

**`<學號>_HW2.zip` 內容**：
- [ ] 原始碼：`HW2/src/`
- [ ] 設定檔：`pyproject.toml`、`uv.lock`
- [ ] 輸出結果：範例 query 的 ranked list（`outputs/*.txt`）
- [ ] 一頁文件：主要特色、遇到的困難、執行環境需求、成員與分工
- [ ] 附上 `HW2/index/surface_vocab.tsv` 與 `surface_vocab.meta.json`（T4c，TA 無未 stem index 無法重建）
- [ ] 決定是否附 index 與 `doc_norms*.bin`、`champions.*`（不附則 README 需附重建指令：norms 16s、champions 15s）

## 風險、已完成技術決策與待確認事項

### 1. 核心風險防範

| 風險 | 後果 | 預防機制 |
| --- | --- | --- |
| norm 與評分用不同公式 | 分數偏差、排序變動 | 共用 `weight()`，norm 檔附 meta 載入核對 sha256 |
| 誤用自然對數 `math.log` | 全部分數偏掉 | 全專案搜尋只允許 `math.log10` |
| AND／OR 被當 stopword 吃掉 | Boolean 退化為自由文字 | Lexer 先切大寫運算子再丟 `process`（T4） |
| 多 token 詞只取首個 | `e-mail` 等詞結果錯誤 | 保留全部 token，不重複 HW1 僅取首詞的錯誤（T4） |
| 分數小數位數不足 | 接近文件印成同分 | 印出 6 位小數，寫明同分規則（T7） |

### 2. 已定案之技術決策與依據

- **運算元內多詞（`open source`）判定為隱含 AND**：
  - *決策依據*：若預設為 phrase 會排除非連續出現但相關的文件，降低召回率；隱含 AND 符合現代搜尋引擎慣例與直覺，若使用者需要精確相鄰則主動加引號為 `Phrase`。
- **拼字建議（`did_you_mean`）改用「原字 df 差距」而非純「df == 0」**：
  - *決策依據*：語料庫本身存在錯字（如 `retreival` df=1），純 `df==0` 會漏掉常見錯字；且原字 df 才能真實反映拼寫信心。規定最佳候選原字 df ≥ 原詞 df × 10 倍以上才觸發，避免對合法罕見詞造成干擾。
- **Wildcard 改於「原字詞彙層」展開再 stem 去重**：
  - *決策依據*：HW1 index 已 stem，若直接對 stem 做 prefix 比對，`computing*` 會比對不到 `comput` 而回傳空結果。在原字層比對才能符合直覺，並設定 100 筆上限避免高頻前綴爆量拖慢 OR 聯集。
- **前處理還原採「嚴格模式」**：
  - *決策依據*：`Preprocessor.from_config` 若缺少設定直接拋 `ValueError`，禁止悄悄套用預設值，徹底避免 query 端前處理與 index 不一致卻未報錯的隱蔽 bug。
- **Boolean 過濾與評分計算分離**：
  - *決策依據*：HW1 的 query 將中間結果包成假 posting 導致 tf 遺失；HW2 決定評分時保留 query 所有 term 的真實 qtf，Boolean 只單純負責產出候選 docID 集合供 VSM 過濾。
- **純 NOT 查詢與評分短路**：
  - *決策依據*：純 NOT 查詢無 query 評分詞（`qtf` 為空），依向量空間模型無查詢向量可供比對，T6 直接回傳空結果 `[]`，符合現代搜尋引擎語意與 VSM 數學定義。
- **T6 排序與 T7 top-k 職責分離**：
  - *決策依據*：`rank()` 專注於正確計算與破同分排序（依原始雙精度 float 與 docID 升冪），回傳所有 `score > 0` 的完整排序候選清單；Top-k 截斷與 6 位小數展示格式化一律交由下游 T7 CLI 處理，維持演算法核心的純粹性。

### 3. 已知限制

- **純 NOT query**（例如 `NOT linux`）：`query_terms` 跳過 Not 子樹無評分詞，cosine 無法排序。
- **拼字建議**（T4c）：原字比對不識語意，罕見人名可能觸發；初次呼叫建 k-gram 需 ~1.6s，建議僅於結果過少時呼叫。
- **Wildcard**（T4c）：原字比對轉 stem 檢索，展開上限 100 筆截斷。
- **Soundex**：為人名設計，一般字彙碰撞多，僅作輔助參考。

### 4. 待確認事項

- [x] 純 `NOT x` 的 query：無評分詞時依 VSM 定義無 query 向量，T6 直接回傳空結果 `[]`，T7 不輸出文件。
- [x] 輸出是否要截斷 top-k：T6 專注計算並回傳所有 `score > 0` 的排序清單；由 T7 CLI 接收 `--top-k` 參數進行截斷（預設輸出全量 score > 0）。
- [ ] zip 是否附 index 與 `doc_norms*.bin`、`champions.*`。
