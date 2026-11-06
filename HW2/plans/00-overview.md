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

&#91;embedded content: HW2 資料流 · 左欄查詢路徑、右欄 index 接口\]

三條橫向箭頭之外，T6 也需要 T1 的 df 與 N。T2 只在 index 建好後跑一次，查詢時直接載入。

檔案配置（stub 都已建立）：
- `weighting.py`：W 與公式常數，由 T2 負責
- `build_norms.py`：T2
- `build_champions.py`：T2 加分
- `parser.py`：T4
- `positional.py`、`spelling.py`：T4b
- `boolean.py`：T5
- `rank.py`：T6
- `search.py`：T7 CLI，尚未建立

T1、T3 改的是 `HW2/src/` 裡從 HW1 複製過來的 `writer.py` 與 `tokenizer.py`，`HW1/` 不動。

## 必做任務

必做部分共 7 項任務，另有一個共用函式 W。任務間只依賴**接口**：第一天先定好簽名並寫 stub，三個人就能平行開工。關鍵路徑是 T1 → T3 → T5 → T6 → T7；T2、T4 是旁支，T1 完成後就能開始。表中 G 編號對應盤點報告的缺口清單。

| 任務 | 對應作業要求 | 盤點缺口 | 直接依賴 | 提供的接口 |
| --- | --- | --- | --- | --- |
| W 權重函式（由 T2 負責） | tf-idf 公式（log10） | — | — | `weighting.weight()` |
| T1 Index 載入、df、前處理還原 | 輸入：HW1 的 inverted index | G1、G4、G10 | — | `IndexReader.df()`、`IndexReader.N`（property）、`Preprocessor.from_config()`  |
| T2 預算文件 norm | cosine 的 \|d\| | G3 | T1、W | `IndexReader.get_norms()` |
| T3 只取 doc／tf 的快速讀取 | 評分看效率 | G9 | T1 | `IndexReader.get_doc_tf()` |
| T4 Query parser | 三種 query 類型 | G5、G6 | T1 | `parse()`、`query_terms()` |
| T5 Boolean merge（AND／OR） | 簡單 Boolean query | G7 | T3、T4 | `evaluate()` |
| T6 VSM 排序 | VSM、tf-idf、cosine | G8 | W、T1、T2、T3、T4、T5 | `rank()` |
| T7 輸出與執行入口 | `<doc#> <score>` 由高到低 | G13 | T6 | `search.py` CLI |

### 接口定義
核心接口如下。加分項新增的參數都有預設值，預設行為與核心相同。所有 stub 都已在 `HW2/src/` 建立。
```python
# W — HW2/src/weighting.py（由 T2 負責；rank.py 屬於 T6，避免兩人同時修改）
LOG_BASE = 10; DEFAULT_SCHEME = "ltc"; FORMULA = "(1+log10 tf)*log10(N/df)"
def weight(tf: int, df: int, N: int, scheme: str = "ltc") -> float: ...
    # (1 + log10 tf) * log10(N / df)；tf == 0 或 df == 0 回傳 0.0；非 ltc 屬於 T2 加分
    # scheme 是單邊三個字母（tf／idf／normalization），只算 tf × idf；不合法（含 "lnc.ltc"）拋 ValueError
def formula(scheme: str = "ltc") -> str: ...   # T2 加分：tf 片段 + "*" + idf 片段；formula("ltc") == FORMULA
def norm_filenames(scheme: str = "ltc") -> tuple[str, str]: ...
    # "ltc" → ("doc_norms.bin", "doc_norms.meta.json")；其他 c 方案 → ("doc_norms.<scheme>.bin", "doc_norms.<scheme>.meta.json")
    # normalization 為 n 時沒有 norm 檔，拋 ValueError

# T1、T2、T3 — HW2/src/writer.py
class IndexReader:
    N: int                                    # T1：property，metadata["N"]
    def df(self, term: str) -> int: ...       # T1：term 不存在回傳 0
    def get_norms(self, scheme: str = "ltc") -> array: ...
        # T2：array('d')，下標 = doc_num；載入時核對 meta（log_base、formula、scheme、N、count）與來源檔 size／sha256，
        #     不一致拋 ValueError、檔案不存在拋 FileNotFoundError；normalization 為 n 時直接回傳全 1.0，不讀檔
    def get_doc_tf(self, term: str) -> tuple[list[int], list[int]]: ...
        # T3：(doc_nums, tfs)，doc_nums 嚴格遞增；term 不存在回傳 ([], [])；postings.bin 用 mmap

# T1 — HW2/src/tokenizer.py
class Preprocessor:
    @classmethod
    def from_config(cls, cfg: dict) -> "Preprocessor": ...
        # 嚴格模式：cfg 為 None、{} 或缺 casefold／stopword／stem 時拋 ValueError；只有 lemma 可缺（預設 False）

# T4 — HW2/src/parser.py（dataclass 是真正的程式碼）
Term(tokens: list[str])                             # 沒加引號的運算元，隱含 AND
Phrase(tokens: list[str], positions: list[int])     # "..."，positions 取自 process，保留 stopword 空洞
Near(left: Term, right: Term, k: int)               # linux /5 kernel
Wildcard(prefix: str)                               # comput*，只做 casefold，不做 stem
Not(child: Node); And(children: list[Node]); Or(children: list[Node])
Node = Term | Phrase | Near | Wildcard | Not | And | Or

def parse(query: str, pre: Preprocessor) -> Node | None: ...
    # 單一遞迴下降 parser；空 query 或整棵樹都是空的回傳 None
    # 優先序 NOT > AND > OR；括號、phrase、/k、* 由 T4b 加入同一個 parser
    # 引號或括號沒有配對 → 拋 ValueError，訊息包含字元位置
def expand(node: Node | None, reader: IndexReader, limit: int = 100) -> Node | None: ...
    # Wildcard → 多個 Term 的 Or（依 df 取前 limit 個，超過時警告）；沒有 Wildcard 時原樣回傳
def query_terms(node: Node) -> Counter[str]: ...
    # 評分用 term 與 query tf；Phrase、Near 的 token 都計入；跳過 Not 的子樹；遇到 Wildcard 拋 ValueError
    # 純 NOT（例如 NOT linux）→ 回傳空的 Counter()

# T4b — HW2/src/positional.py
def position_match(node: Phrase | Near, reader: IndexReader) -> set[int]: ...   # 用 get_postings 的 positions

# T5 — HW2/src/boolean.py
def evaluate(node: Node, reader: IndexReader) -> set[int] | None: ...
    # 輸入一定已經過 expand：遇到 Wildcard 拋 ValueError
    # 根節點是 Term（沒有運算子）→ None，代表不過濾
    # 在 And／Or 之下的 Term → 其 tokens 全部出現的文件
    # Not → set(range(reader.N)) 減去 child；Phrase、Near → position_match(node, reader)
    # 純 NOT（例如 NOT linux）→ set(range(reader.N)) - {含 linux 的文件}

# T6 — HW2/src/rank.py
def rank(qtf: Counter[str], candidates: set[int] | None,
         reader: IndexReader) -> list[tuple[int, float]]: ...
    # 依 (-score, doc) 排序；candidates 為 None 時不過濾；權重只 import weighting.weight
    # 加分：scheme="ltc.ltc"（"ddd.qqq"，文件端.query 端）、champion_r: int | None = None，見「T6 配合加分項」

# T7 — HW2/src/search.py
# uv run python HW2/src/search.py --index-dir HW2/index [--top-k K] [--queries FILE] "query"
```

加分項的接口（stub 已建立，細節見各任務 plan）：
```python
# T1 加分 — writer.py
IndexReader.vocabulary() -> list[str]                    # 排序過的全部 term（快取，不可修改）
IndexReader.prefix_terms(prefix: str) -> list[str]       # 排序 list + bisect
# T2 加分 — weighting.py、build_norms.py、build_champions.py
formula(scheme: str = "ltc") -> str                       # 寫入／核對 meta 的 formula
build_norms(index_dir, scheme: str = "ltc") -> None      # CLI --scheme X（單邊）；n 方案拋 ValueError
build_champions(index_dir, r: int = 50) -> None          # champions.r<r>.{bin,tsv,meta.json}；r < 1 拋 ValueError
# T3 加分 — writer.py
IndexReader.get_champions(term: str, r: int = 50) -> tuple[list[int], list[int]]  # doc 遞增；r < 1、meta／tsv 不符拋 ValueError；檔案不存在拋 FileNotFoundError
IndexReader.set_doc_tf_cache(maxsize: int) -> None       # 0 = 關閉（預設）
IndexReader.doc_tf_cache_info() -> tuple[int, int]       # (hits, misses)
# T4b — spelling.py
suggest(term: str, reader, limit: int = 5) -> list[str]  # 只提供 Did you mean，不自動替換
soundex(word: str) -> str
suggest_soundex(term: str, reader, limit: int = 5) -> list[str]
```

### 查詢流程
每個 query 固定依序經過以下五步。`parse` 回傳 `None` 時直接輸出空結果，後面的步驟都不呼叫。
```python
node  = parse(query, pre)             # T4；pre = Preprocessor.from_config(metadata["preprocessor"])
node  = expand(node, reader)          # T4；沒有 Wildcard 時原樣回傳
cands = evaluate(node, reader)        # T5；None = 不過濾
qtf   = query_terms(node)             # T4
hits  = rank(qtf, cands, reader)      # T6 → T7 輸出
```

- **交接點 T3 → T5**：`get_doc_tf` 只回傳 docID 列表。要換成 `intersect_with_skips` 所需的物件（需有 `.doc_num`／`.skip`），由 skip pointer 負責人在 `boolean.py` 內處理。
- **交接點 W → T2、T6**：兩邊都只 import `weighting.weight()` 與 `weighting` 的公式常數，不自己寫公式。
- **還沒完成的上游用暫代品**：T5 先用既有的 `get_postings` 取 docID；T6 先用手算小語料的假 reader 測試。

### T1 Index 載入、df 與前處理設定還原

- **作業要求**：輸入是 HW1 建好的 index。idf 需要 N 和每個 term 的 df。
- **做法**
  - `HW2/index/` 的內容來自 `HW1/output_main`（stop+stem 版，不是未 stem 的 `HW1/output`），已與繳交的 dictionary／postings 逐 byte 比對。HW2 程式一律明確指定這個路徑。
  - `IndexReader._load_lexicon` 改存 `(df, offset, length)`，新增 `df(term) -> int`；若 term 不存在回傳 0。`N` 是 property。
  - 新增 `Preprocessor.from_config(metadata["preprocessor"])`。query 端只用這個入口建立 Preprocessor，確保和 index 一致。
- **注意**
  - `main.py query` 預設讀 `HW1/output`（未 stem 版），不要沿用這個預設。
  - 不要在未備份時跑 `main.test.py`，它會把 `HW1/output` 覆蓋成 100 篇的小 index。
  - `from_config` 採嚴格模式：`cfg` 為 `None` 或 `{}`，或缺 casefold／stopword／stem 時拋 `ValueError`，只有 `lemma` 可缺（預設 false）。悄悄套用預設值會讓 query 端與 index 不一致，而且不會報錯。
- **加分**：`vocabulary()`、`prefix_terms()`（排序 list + bisect），見 `done.T1.md`。實測 `prefix_terms('a')` 約 0.1 ms、`vocabulary()` 約占 4.6 MB；HW1 的 `RadixTrie` 光建置就約 1.3 s，所以選用 bisect。
- **對應接口**：`IndexReader(dir)`（`writer.py` `IndexReader.__init__`）、`_load_lexicon` 存 `(df, offset, length)`（`writer.py` `IndexReader._load_lexicon`）、`get_metadata()`（`writer.py` `IndexReader.get_metadata`）、`metadata.json["N"]`。HW1 `main.py` 只有 `run_query()` 是從 metadata 還原設定，HW2 不改它。

### T2 預算文件向量 norm

- **作業要求**：cosine 分母的 |d\_j| = sqrt(Σ w\_ij²)，對文件內**所有** term 加總。
- **做法**
  - 寫一個獨立後處理腳本 `build_norms.py`：依 lexicon 逐一讀取 posting，累加 `norm2[doc] += weight(tf, df, N, scheme)²`，最後開根號。scheme 會傳給 `weight`；核心固定是 ltc，即 `((1 + log10 tf) × log10(N / df))²`。
  - 存成 `HW2/index/doc_norms.bin`（`array('d')`，下標就是 doc\_num，278,288 bytes），附一份 `doc_norms.meta.json`，記錄 `log_base`、`formula`、`scheme`、`N`、`count`，以及 `lexicon.tsv`、`postings.bin`、`metadata.json` 的 size 與 sha256。
  - `IndexReader` 新增 `get_norms(scheme)`。第一次載入時核對 meta（`log_base`、`formula`、`scheme`、`N`、`count`）、來源檔的 size 與 sha256，以及 norm 檔大小（8 × N），不一致就拋 `ValueError`；結果依 scheme 快取。
  - 來源檔核對寫成 `writer.py` 的共用 helper `IndexReader._check_sources`，T3 的 `get_champions` 核對 champion meta 時也要共用它。
  - 權重公式寫成共用函式 `weight(tf, df, N, scheme)`，放在 `weighting.py`，由 T2 實作；T2 和 T6 都呼叫它。
  - 加分（已完成，見 `T2.md`）：
    - **SMART**：`weight`、`get_norms`、`build_norms`、`norm_filenames` 的 scheme 都是單邊三個字母；新增 `formula(scheme)`。normalization 為 `n` 時 `get_norms` 回傳全 1.0 的陣列、不讀檔，`build_norms` 與 `norm_filenames` 拋 `ValueError`；非 ltc 的 c 方案檔名帶 scheme（`doc_norms.<scheme>.bin`／`.meta.json`）。lnc 等非預設方案的 norm 檔要先執行 `build_norms.py --scheme X` 才會存在，否則 `get_norms(X)` 拋 `FileNotFoundError`。
    - **Champion list**：`build_champions.py` 產生 `champions.r50.{bin,tsv,meta.json}`。只收 df > r 的 term，依 `(-tf, doc)` 取前 r 筆再依 doc 遞增寫出；r = 50 時共 15,755 個 term。block 格式是 `u32be n` + n × `[VByte Δdoc][VByte tf]`，沒有 positions。
- **注意**
  - Python 要用 `math.log10`。`math.log` 是自然對數，用錯不會報錯，只會讓分數悄悄偏掉。
  - 不要拿 `doc_len` 當 norm，它只是過濾 stopword 後的 token 數。
  - 唯一的空文件是 doc 24621（`doc_len = 0`），c 方案下 norm 為 0；df = N 的 term 權重為 0。
  - 實測 `build_norms`（ltc）約 15–16 秒、峰值 221 MB；`build_champions`（r = 50）約 15 秒。跑一次即可，不必優化。
- **對應接口**：`postings.bin` + `lexicon.tsv` + `metadata.json`；`postings.bin` 只開一次，依 `IndexReader._load_lexicon` 的 offset／length 讀 block，用 `writer.py` 的 `decode_postings_block` 解碼（不用 `IndexReader.get_postings`，它每次呼叫都重新開檔）。已決定 `build_norms`、`build_champions` 都不改用 `get_doc_tf`（見 `T3.md` §9.2）。

### T3 只取 doc／tf 的快速讀取

- **作業要求**：加分評分看「scoring／ranking 效率」。
- **做法**：新增 `get_doc_tf(term) -> (doc_nums, tfs)`。讀到 n\_pos 後直接跳過那些 position 的 VByte，不建 `Posting` 物件。`postings.bin` 用 `mmap`（`ACCESS_READ`）開啟一次並快取，每次查詢只做記憶體切片。解完會核對 block 的結束位置等於 `offset + length`、df 標頭等於 lexicon 的 df，不符拋 `ValueError`。全 index 掃描會碰到 `postings.bin` 的全部 63 MB，這些 mmap 的 file-backed 分頁會算進 RSS。加分：`get_champions()` 與 LRU 快取，見 `T3.md`。
- **注意**：position 仍是 VByte，要跳過就必須逐個讀出結束位元，無法直接 seek。既有的 `get_postings` 保持不動，留給 phrase／proximity 使用。
- **對應接口**：posting 磁碟格式 `[Δdoc][tf][n_pos][Δpos…]`（寫入 `writer.py` `encode_postings_block`、讀取 `writer.py` `decode_postings_block`）；HW2 實測（暖身後 5 次中位數，見 `T3.md` §9.1）：`home` 由 `get_postings` 23.779 ms 降到 `get_doc_tf` 6.549 ms（3.63x），`new` 由 21.987 ms 降到 6.326 ms（3.48x）；加速主要來自跳過 positions，mmap 的貢獻可忽略。

### T4 Query parser

- **作業要求**：支援單一關鍵字（`Microsoft`）、自由文字（`United States government`）、簡單 Boolean（`open source AND Linux`、`software engineer OR project manager`）。
- **做法**
  1. 先用大寫的 `AND`／`OR` 把原始字串切成運算元，再對每個運算元呼叫 `Preprocessor.process`。
  2. 優先序：AND 高於 OR，最低要求不支援括號。
  3. 產出一個小 AST：`Term`、`And[...]`、`Or[...]`。單一關鍵字和自由文字都可以視為「沒有運算子的 query」。
  4. 同時保留「所有評分 term 及其 query tf」，給 T6 使用。
- **注意**
  - `and`／`or` 是 stopword，整句丟進 `process` 會被吃掉，所以一定要先切運算子。
  - 一個詞可能拆成多個 token（`e-mail` 變成 `e`、`mail`），要全部保留。不要重複 HW1 只取 `toks[0]` 的寫法。
  - 運算元內的多詞（`open source`、`software engineer`）已決定是 `Term`，代表隱含 AND（所有詞都要出現）。phrase 要加引號，對應 `Phrase` 節點（T4b）。
  - 空節點規則在樹上處理：
    - 空的 `Term`／`Phrase` 從父節點移除，並印出警告
    - 沒有 child 的 `And`／`Or` 也移除；只剩一個 child 時攤平
    - `Not` 的 child 是空的就移除這個 `Not`
    - 整棵樹都是空的就回傳 `None`
  - 只有一個遞迴下降 parser，接口是 `parse(query, pre)`。T4a／T4b 只代表實作順序與 commit 切分：
    - T4a（核心）：`Term`／`And`／`Or`、優先序、空節點規則
    - T4b（加分）：在同一個 parser 加入 NOT、括號、phrase、`/k`、`*`，以及拼字建議

    測試分為核心（`t4.test.py`）與加分（`t4_bonus.test.py`）兩組，T4b 合併後核心測試仍要全部通過。見 `T4.md`。
- **輸出約定**
  - **純 NOT**（例如 `NOT linux`）：`parse` 回傳 `Not(...)`；`evaluate` 回傳 `set(range(N))` 扣掉 X 的結果；`query_terms` 回傳空的 `Counter()`。
  - **引號或括號沒有配對**：`parse` 拋出 `ValueError`，訊息包含字元位置（從 0 起算），例如 `linux)` 的位置是 5。
- **對應接口**：`Preprocessor.process`（`tokenizer.py` `Preprocessor.process`），回傳 `list[(position, term)]`。position 在過濾 stopword 前編號，空洞會保留。

### T5 Boolean merge（AND／OR）

- **作業要求**：Boolean query 要先選出候選文件，再交給 VSM 排序。
- **做法**
  - AND：依 df 由小到大兩兩交集；可重用 `intersect_with_skips` 取得 docID 集合。
  - OR：對已排序的 docID 做線性聯集。
  - 依 T4 的 AST 遞迴求值，得到候選 docID 集合。分數由 T6 另外計算，不在 merge 裡維護 tf。
  - 自由文字不做過濾，候選就是「至少含一個 query term」的文件，由 T6 的累加器自然產生。
- **配合 T4b 加分**（這些分支在 T5 核心就先寫好）：
  - 輸入一定已經過 `expand`，遇到 `Wildcard` 就拋 `ValueError`。
  - 根節點是 `Term` 時回傳 `None`（不過濾）；根節點是 `Phrase`、`Near`、`Not` 時照常回傳集合。
  - `Not`：以 `set(range(reader.N))` 為全集，減去 child 的結果。
  - `Phrase`、`Near`：呼叫 `positional.position_match(node, reader)`。T4b 完成前它會拋 `NotImplementedError`，但核心 query 不會走到這裡。
- **注意**
  - 既有的多詞 AND（`main.py` `run_query`）把中間結果重包成假的 `Posting(d, 1, …)`，tf 已經丟失，不能拿來評分。
  - `and_query`（`skip_builder.py` `and_query`）只支援兩個詞，而且只能在 memory 模式下用，不要用。
  - 建議評分時使用**整個 query 的所有 term**（例如 `open`、`sourc`、`linux`），只拿 Boolean 結果來過濾。這是常見做法，但規格沒寫，文件中要說明。
- **對應接口**：`build_skip_list`（`skip_builder.py` `build_skip_list`）、`intersect_with_skips(p1, p2) -> (doc_nums, n_comparisons)`（`skip_builder.py` `intersect_with_skips`）、`intersect_basic`（`skip_builder.py` `intersect_basic`）。輸入只需要具備 `.doc_num`／`.skip` 的 list。

### T6 VSM 排序

- **作業要求**：w\_ij = (1 + log10 tf) × log10(N/df)，以 cosine 排序。
- **做法**（term-at-a-time 累加器）
  1. 對每個評分 term t（df > 0）：算出 idf、w\_tq，再把 w\_tq 加入 |q|²。
  2. 讀取 `get_doc_tf(t)`，對每個 (doc, tf) 做 `acc[doc] += weight(tf, df, N) × w_tq`。Boolean query 只累加候選集合內的 doc。
  3. `score = acc[doc] / (norm[doc] × |q|)`。
  4. 依 (−score, doc) 排序：分數由高到低，同分時 docID 小的在前。
- **注意**
  - w\_iq = `weight(tf_q, df, N)`（`weighting.py`），與文件同公式；tf\_q 是該 term 在 query 中出現的次數。其他方案留給加分的 SMART 切換（見下方「配合加分項」）。
  - query 中不在 dictionary 的 term：df = 0，idf 無定義，直接略過，也不計入 |q|。全部略過時輸出空結果。
  - `qtf` 是空的（例如純 NOT 的 query，`query_terms` 跳過了 `Not` 的子樹）時，沒有可評分的詞，所以 cosine 無法排序；輸出方式由 T6／T7 決定
  - tf = 0 的權重定義為 0；除以前要防 norm = 0。
  - |q| 不影響排序，但會影響輸出分數，必須照公式除上。
  - Python 累加器用 `dict` 即可。高 df 詞若太慢，可改用長度 N 的 `array('d')`。
- **配合加分項**（都排在 T6 核心之後；新參數的預設值要讓核心結果完全不變）：
  - **SMART（T2 加分）**：`rank(qtf, candidates, reader, scheme="ltc.ltc")` 要增加 scheme 參數。scheme 寫成 `"ddd.qqq"`（例如 `lnc.ltc`：文件端 lnc、query 端 ltc），由 `rank` 用 `doc_s, q_s = scheme.split(".")` 拆開，格式錯誤拋 `ValueError`；`weighting` 的函式只接受單邊的三個字母。
    - 文件端：權重用 `weight(tf, df, N, doc_s)`，分母用 `reader.get_norms(doc_s)[doc]`；norm 為 0 的文件（只有 c 方案下的 doc 24621）跳過。`n` 方案的 `get_norms` 回傳全 1.0，不必寫特例。
    - query 端：權重用 `weight(qtf, df, N, q_s)`。第三個字母是 `c` 時除以 |q|，是 `n` 時不除；|q| 由 T6 自己算。
    - 非預設的 c 方案要先執行 `build_norms.py --scheme X` 建好 norm 檔，否則 `get_norms` 拋 `FileNotFoundError`。
    - 預設 `ltc.ltc` 必須與核心結果完全相同（見 `T2.md` 6.1）。
  - **不精確 top-k（T2／T3 加分）**：champion list 加一個參數 `champion_r: int | None = None`，不是 `None` 時用 `reader.get_champions(term, champion_r)` 取代 `get_doc_tf`，分母仍用完整的 `get_norms(doc_s)`；index elimination 只用 idf 高於門檻的 term，由 T6 自己做。兩者都必須是可關閉的選項，而且預設關閉。
  - **Wildcard（T4b）**：沒有接口變動。展開後的每個 term 都會進入 `query_terms`，各計 1 次，照常評分。
  - **NOT（T4b）**：純 `NOT x` 的 query 沒有評分 term。純 NOT 的輸出方式由 T6／T7 負責人決定（見「已知限制」）。
- **對應接口**：T1 的 `df()`、T2 的 `get_norms()`、T3 的 `get_doc_tf()`、T5 的候選集合。

### T7 輸出與執行入口

- **作業要求**：每行 `<doc#> <similarity score>`，分數由高到低；TA 會自己挑 query 來跑。
- **做法**
  - CLI：`uv run python HW2/src/search.py --index-dir HW2/index "open source AND Linux"`，另外支援 `--queries queries.txt` 批次模式，每個 query 輸出一個檔。
  - `<doc#>` 直接印內部整數 docID，不必經過 `doc_map`。
  - 分數至少印 4～6 位小數，並在文件中寫明位數與同分規則。
  - 預設輸出所有分數 > 0 的文件，另加 `--top-k` 參數。
- **注意**
  - 規格沒說要不要截 top-k。預設全印最保險，但常見詞可能印出數千行。
  - 執行入口要能在 repo 根目錄以外執行。路徑一律以檔案位置推算，避免重蹈 HW1 寫死相對 cwd 的問題。
  - TA 無法執行時可能要當面 demo：README 要寫清楚 `uv sync` 和如何取得 index。index 在 gitignore 中，要決定是否放進 zip。
- **配合加分項**（預設行為不變）：
  - **SMART（T2 加分）**：加上 `--scheme` 參數（預設 `ltc.ltc`），傳給 `rank`，並把方案寫進輸出檔名。
  - **T4b 語法**：沒有接口變動，`parse(query, pre)` 合併 T4b 後就自動支援新語法。`parse` 拋出的 `ValueError`（引號或括號沒有配對）要印出訊息並以非 0 結束，不印 traceback。
  - **純 NOT 的 query**：`node` 不是 `None` 但 `qtf` 是空的。純 NOT 的輸出方式由 T6／T7 負責人決定。
  - **警告**：把 `parse` 與 `expand` 發出的警告（空運算元、wildcard 超過上限等）印到 stderr，不混進 ranked list。
  - **拼字建議（T4b）**：對每個 query token 呼叫 `s = spelling.suggest(token, reader)`。以下任一條件成立時，印出 `Did you mean: ...`，顯示前 3 個建議（`s[:3]`），不自動替換：
    - 原詞的 df == 0
    - 最佳建議的 df ≥ 原詞 df × 10，即 `reader.df(s[0]) >= reader.df(token) * 10`

    結果是 stem 形式，要在說明中提到。
  - **LRU 快取（T3 加分）**：批次模式（`--queries`）可以呼叫 `reader.set_doc_tf_cache(n)` 開啟，預設不開。
- **對應接口**：`IndexReader.get_doc(n).trec_id`（`writer.py` `IndexReader.get_doc`），只在需要額外顯示 TREC ID 時使用。

## 加分任務

CP 值最高的是 phrase／proximity 和權重方案變體：前者 HW1 的 positions 已經備好，後者只是 W 與 T6 的參數化。評分看的是 query 類型多樣性、權重方案和效率，下表依建議優先序排列。

每個加分項都排在負責任務的核心合併之後，新參數的預設值必須讓核心行為不變；測試放在 `HW2/tests/tN_bonus.test.py`。細節見各任務 plan 的「加分項」一節。

| 優先 | 項目 | 負責任務 | 作業對應 | 做法 | 可重用的 HW1 接口 | 注意 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Phrase query（`"open source"`） | T4（`Phrase`、`position_match`）；T5 呼叫 | 複雜查詢，Ch.2 | 先 AND 取候選，再比對 positions：各 term 的位置差要等於它們在 query 內的位置差 | `get_postings`（含 positions）、`process` 回傳的 position | stopword 空洞在 index 與 query 都會保留，直接比位置差即可 |
| 2 | Proximity（`linux /5 kernel`） | T4（`Near`、`position_match`）；T5 呼叫 | 複雜查詢，Ch.2 | 兩個 position 列表做雙指標，找距離 ≤ k 的配對 | 同上 | 距離以含 stopword 的 token 位置計算，文件中要說明 |
| 3 | 權重方案變體（SMART：ltc.ltc、lnc.ltc、bnn 等） | T2（`weight`、`get_norms` 的 scheme）；T6 增加 scheme 參數 | Ch.6 | 把 tf、idf、normalization 三個字母各自實作成函式，以 `--scheme lnc.ltc` 切換 | `weighting.weight()` | doc 端每改一種方案，norm 就要重算一份，檔名帶 scheme（`doc_norms.<scheme>.bin`） |
| 4 | 多運算子與括號（`(A OR B) AND NOT C`） | T4（T4b）；T5 處理 `Not` | Ch.2–3 | 在同一個遞迴下降 parser 加入 NOT 與括號，優先序 NOT > AND > OR；NOT 以 `set(range(N))` 做集合差 | T4 的 AST、T5 的 merge | 純 `NOT x` 沒有評分 term；純 NOT 的輸出方式由 T6／T7 負責人決定（見「已知限制」） |
| 5 | Skip pointer 加速 AND | T5 | Ch.2 | T5 直接使用 `intersect_with_skips`，並記錄比較次數對照 `intersect_basic` | `skip_builder.py` `build_skip_list`、`intersect_with_skips` | skip 每次查詢重建，成本 O(df)；要實測確認真的變快才寫進文件 |
| 6 | Wildcard（`comput*`） | T4（`Wildcard`、`expand`）；T1 提供 `prefix_terms` | Ch.3 | 用排序 list + bisect 做 prefix 展開，依 df 取前 100 個 term（超過時警告），再以 OR 處理 | 實測 `prefix_terms('a')` 約 0.1 ms、`vocabulary()` 約占 4.6 MB；HW1 的 `RadixTrie` 建置約 1.3 s，所以選用 bisect | dictionary 已經 stem 過：prefix 要對 stem 後的字串比對，且 prefix 本身不能再 stem |
| 7 | 拼字更正 | T4（`suggest`）；T1 提供 `vocabulary`；T7 顯示 | Ch.3 | 原詞 df == 0，或最佳建議的 df ≥ 原詞 df × 10 時，用 bigram 篩候選、Damerau 距離排序，df 決定同分時的次序；顯示前 3 個 | dictionary、T1 的 `df()` | dictionary 是 stem 後的形式，只顯示「Did you mean」，不自動替換 |
| 8a | 不精確 top-k：champion list | T2（建置，已完成）、T3（`get_champions`）；T6 使用（`champion_r`） | Ch.7 | 每個 df > r 的 term 依 `(-tf, doc)` 預存前 r 名的 doc（預設 r = 50，共 15,755 個 term，建置約 15 s），存成 `champions.r50.{bin,tsv,meta.json}` | T3；meta 核對共用 `IndexReader._check_sources` | 結果會跟精確 cosine 不同，必須是可關閉的選項，預設關閉 |
| 8b | 不精確 top-k：index elimination | T6 | Ch.7 | 只用 idf 高於門檻的 term | T1 的 `df()` | 同上 |
| 9 | Web UI 與 term highlighting | T7 | 介面 | Flask／FastAPI 單頁；快速版可用 Streamlit | `doc_map`（URL、TREC ID） | index 沒有存原文與字元 offset，highlight 要回 WARC 重讀文件，成本最高 |
| 10 | `get_doc_tf` 的 LRU 快取 | T3 | 效率 | `set_doc_tf_cache(maxsize)`，預設關閉 | — | 要量測同一個 query 重跑的加速，回傳複本避免被修改 |
| 11 | Soundex | T4 | Ch.3 | `soundex()`、`suggest_soundex()` | dictionary | stem 形式與大量碰撞讓它只能當輔助建議 |

建議至少做 1–3。第 5 項幾乎不花額外力氣，很適合放進文件的主要特色。

## 驗證與測試

評分方式是「檢查 ranked list 是否正確」，所以最重要的測試是拿一個完全獨立的暴力版本來對分數。

- [ ] **手算小語料**：3～5 篇假文件建成小 index，在 Excel 或紙上算出 cosine，與程式輸出比對到小數點第 6 位。
- [ ] **暴力對照**：在真實 index 上隨機抽 20 篇文件，從頭掃一遍 postings，算出完整向量與 norm，對照 T2 的 norm 和 T6 的分數。
- [ ] **前處理一致性**：取 query `information retrieval`、`open source AND Linux`、`e-mail`，確認解析出的 term 是 `inform`、`retriev`、`open`、`sourc`、`linux`、`e`、`mail`，且都存在於 dictionary。
- [ ] **作業範例 query**：`Microsoft`、`United States government`、`open source AND Linux`、`software engineer OR project manager` 都要能跑，結果存進 outputs。
- [ ] **Boolean 語意**：AND 結果要是各運算元結果的交集，OR 要是聯集；用 Python `set` 另外算一次對照。
- [ ] **邊界情況**：空 query、全是 stopword、不存在的詞、重複詞（`new new york`）、小寫 `and`、只有運算子。
- [ ] **分數健全性**：所有分數要落在 (0, 1\]，排序嚴格遞減，同分時 docID 遞增。
- [ ] **效率**：記錄載入時間、單次 query 時間（含高 df 詞）與峰值記憶體，寫進文件。
- [ ] **乾淨環境**：在一個新 clone 下跑 `uv sync` 和 README 的指令，確認 TA 照做能跑。

## 繳交物與時程

從今天到 11/18 還有兩週。建議 11/13 前完成必做並通過測試，剩下的時間留給加分與文件。

**`<學號>_HW2.zip` 內容**

- [ ] 原始碼：`HW2/src/`
- [ ] 管理設定：`pyproject.toml`、`uv.lock`（順便補宣告 `tqdm`）
- [ ] 輸出結果：範例 query 的 ranked list（`outputs/*.txt`）
- [ ] 一頁文件：主要特色、遇到的困難、執行環境需求、成員與分工
- [ ] 決定是否附上 index 與 `doc_norms*.bin`、`champions.*`（見「待確認」）：附上則 TA 不必重建，但檔案會很大；不附則 README 要寫清楚重建步驟與所需時間



## 風險與待確認事項

最大的風險是「不報錯的不一致」：log 底數、前處理、index 路徑只要一處不同，程式仍照常輸出，只是分數不對。

| 風險 | 後果 | 預防 |
| --- | --- | --- |
| norm 與評分用不同公式 | 分數偏差、排序可能變動 | 共用 `weight()`，norm 檔附 meta 並在載入時核對 |
| 用了 `math.log` | 全部分數偏掉 | 全專案搜尋 `math.log(`，只允許 `log10` |
| AND／OR 被當 stopword 吃掉 | Boolean query 退化成自由文字 | 先切運算子再 `process`（T4） |
| 多 token 詞只取第一個 | `e-mail` 這類詞結果錯 | 保留全部 token（T4） |
| 分數只印 3 位小數 | 分數接近的文件印成同分 | 印 6 位，並寫明同分規則 |

**已知限制**（要寫進繳交文件）

- **純 NOT 的 query**（例如 `NOT linux`、`NOT (a OR b)`）：`query_terms` 會跳過 `Not` 的子樹，所以沒有可評分的詞，cosine 無法排序。輸出方式由 T6／T7 決定。
- **拼字建議是 stem 形式**：dictionary 存的是 stem 過的詞，所以「Did you mean」會顯示 `retriev`，而不是 `retrieval`。
- **Wildcard 的 prefix 不做 stem**：`computing*` 對不到 dictionary 中的 `comput`，會展開成空的結果。展開數量上限是 100，超過時發出警告。

**待確認**

- [ ] Boolean query 的評分範圍：用整個 query 的所有 term 評分、Boolean 只當過濾器，是否符合 TA 預期？
- [x] 運算元內的多詞（`open source`）：已決定是隱含 AND（`Term`）；phrase 用引號（`Phrase`）
- [ ] 純 `NOT x` 的 query（沒有評分 term）：純 NOT 的輸出方式由 T6／T7 負責人決定（見「已知限制」）
- [x] 拼字建議的觸發條件：已決定在「原詞的 df == 0，或最佳建議的 df ≥ 原詞 df × 10」時觸發，T7 顯示前 3 個建議
- [ ] 輸出是否要截 top-k？
- [ ] zip 是否附 index，以及 `doc_norms*.bin`、`champions.*` 與其 meta？（不附時 README 要寫重建指令：`build_norms.py` 約 15–16 s、`build_champions.py` 約 15 s）
