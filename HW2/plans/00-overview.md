# IR HW2 實作規劃

## 已確定的設定

HW2 在 2026/11/18 截止。所有設計前提都已確定。

| 項目 | 決定 | 依據 |
| --- | --- | --- |
| 截止與繳交 | 2026/11/18，上傳 iSchool+，檔名 `<學號>_HW2.zip` | 作業說明 |
| Index | 交出去的 stop+stem 版（`output_main`）：573,233 個 term，N = 34,786 | 與繳交的 dictionary／postings 比對過 |
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

建議的檔案配置：`HW2/src/` 放 `parser.py`（T4）、`boolean.py`（T5）、`rank.py`（T6，含共用的 `weight()`）、`search.py`（T7 CLI）、`build_norms.py`（T2）；T1、T3 直接改 HW1 的 `writer.py` 與 `tokenizer.py`。

## 必做任務

必做部分共 7 項任務，另有一個共用函式 W。任務間只依賴**接口**：第一天先定好簽名並寫 stub，三個人就能平行開工。關鍵路徑是 T1 → T3 → T5 → T6 → T7；T2、T4 是旁支，T1 完成後就能開始。表中 G 編號對應盤點報告的缺口清單。

| 任務 | 對應作業要求 | 盤點缺口 | 直接依賴 | 提供的接口 |
| --- | --- | --- | --- | --- |
| W 權重函式 | tf-idf 公式（log10） | — | — | `weight()` | 
| T1 Index 載入、df、前處理還原 | 輸入：HW1 的 inverted index | G1、G4、G10 | — | `IndexReader.df()`、`IndexReader.N`、`Preprocessor.from_config()`  |
| T2 預算文件 norm | cosine 的 \|d\| | G3 | T1、W | `IndexReader.get_norms()` |
| T3 只取 doc／tf 的快速讀取 | 評分看效率 | G9 | T1 | `IndexReader.get_doc_tf()` |
| T4 Query parser | 三種 query 類型 | G5、G6 | T1 | `parse()`、`query_terms()` |
| T5 Boolean merge（AND／OR） | 簡單 Boolean query | G7 | T3、T4 | `evaluate()` |
| T6 VSM 排序 | VSM、tf-idf、cosine | G8 | W、T1、T2、T3、T4、T5 | `rank()` |
| T7 輸出與執行入口 | `<doc#> <score>` 由高到低 | G13 | T6 | `search.py` CLI |

### 接口定義
```python
# W — HW2/src/rank.py
def weight(tf: int, df: int, N: int) -> float: ...
    # (1 + log10 tf) * log10(N / df)；tf == 0 或 df == 0 回傳 0.0

# T1、T2、T3 — HW2/src/writer.py
class IndexReader:
    N: int                                    # T1：metadata["N"]
    def df(self, term: str) -> int: ...       # T1：term 不存在回傳 0
    def get_norms(self) -> array: ...         # T2：array('d')，下標 = doc_num
    def get_doc_tf(self, term: str) -> tuple[list[int], list[int]]: ...
        # T3：(doc_nums, tfs)，doc_nums 嚴格遞增；term 不存在回傳 ([], [])

# T1 — HW2/src/tokenizer.py
class Preprocessor:
    @classmethod
    def from_config(cls, cfg: dict) -> "Preprocessor": ...  # 缺 lemma 時預設 False

# T4 — HW2/src/parser.py
@dataclass
class Term:  tokens: list[str]       # 一個運算元經 process 後的所有 term
@dataclass
class And:   children: list["Node"]
@dataclass
class Or:    children: list["Node"]
Node = Term | And | Or

def parse(query: str, pre: Preprocessor) -> Node | None: ...  # 空 query 回傳 None
def query_terms(node: Node) -> Counter[str]: ...                # 評分用 term 與 query tf

# T5 — HW2/src/boolean.py
def evaluate(node: Node, reader: IndexReader) -> set[int] | None: ...
    # 根節點是 Term（沒有運算子）→ None，代表不過濾
    # 在 And／Or 之下的 Term → 其 tokens 全部出現的文件

# T6 — HW2/src/rank.py
def rank(qtf: Counter[str], candidates: set[int] | None,
         reader: IndexReader) -> list[tuple[int, float]]: ...
    # 依 (-score, doc) 排序；candidates 為 None 時不過濾

# T7 — HW2/src/search.py
# uv run python HW2/src/search.py --index-dir HW2/index [--top-k K] [--queries FILE] "query"
```

- **交接點 T3 → T5**：`get_doc_tf` 只回傳 docID 列表。要換成 `intersect_with_skips` 所需的物件（需有 `.doc_num`／`.skip`），由 skip pointer 負責人在 `boolean.py` 內處理。
- **交接點 W → T2、T6**：兩邊都只 import `weight()`，不自己寫公式。
- **還沒完成的上游用暫代品**：T5 先用既有的 `get_postings` 取 docID；T6 先用手算小語料的假 reader 測試。

### T1 Index 載入、df 與前處理設定還原

- **作業要求**：輸入是 HW1 建好的 index。idf 需要 N 和每個 term 的 df。
- **做法**
  - 把 `HW1/output`複製到 `HW2/index/`，用 sha256 跟繳交的 dictionary／postings 比對。HW2 程式一律明確指定這個路徑。
  - `IndexReader._load_lexicon` 保留 df，新增 `df(term) -> int`；若 term 不存在回傳 0。
  - 新增 `Preprocessor.from_config(metadata["preprocessor"])`。query 端只用這個入口建立 Preprocessor，確保和 index 一致。
- **注意**
  - `main.py query` 預設讀 `HW1/output`（未 stem 版），不要沿用這個預設。
  - 不要在未備份時跑 `main.test.py`，它會把 `HW1/output` 覆蓋成 100 篇的小 index。
  - 舊 index 的 metadata 可能沒有 `lemma` 欄位，`from_config` 要給預設值 false。
- **對應接口**：`IndexReader(dir)`（`writer.py:352`）、`_load_lexicon` 丟棄 df 處（`writer.py:381`）、`get_metadata()`（`writer.py:427`）、`metadata.json["N"]`、三處重複的設定還原（`main.py:104`、`:214`、`:423`）。

### T2 預算文件向量 norm

- **作業要求**：cosine 分母的 |d\_j| = sqrt(Σ w\_ij²)，對文件內**所有** term 加總。
- **做法**
  - 寫一個獨立後處理腳本 `build_norms.py`：依 lexicon 逐一讀取 posting，累加 `norm2[doc] += ((1 + log10 tf) × log10(N / df))²`，最後開根號。
  - 存成 `HW2/index/doc_norms.bin`（`array('d')`，下標就是 doc\_num，約 278 KB），附一份 `doc_norms.meta.json` 記錄 log 底數、公式版本與來源 index 的 hash。
  - `IndexReader` 新增 `get_norms()`。
  - 權重公式寫成共用函式 `weight(tf, df, N)`，T2 和 T6 都呼叫它。
- **注意**
  - Python 要用 `math.log10`。`math.log` 是自然對數，用錯不會報錯，只會讓分數悄悄偏掉。
  - 不要拿 `doc_len` 當 norm，它只是過濾 stopword 後的 token 數。
  - 那篇空文件 norm 為 0；df = N 的 term 權重為 0。
  - 實測全掃約 16.6 秒、283 MB，跑一次即可，不必優化。
- **對應接口**：`postings.bin` + `lexicon.tsv` + `metadata.json`；解碼可重用 `get_postings`（`writer.py:402`）或 T3 的 `get_doc_tf`。

### T3 只取 doc／tf 的快速讀取

- **作業要求**：加分評分看「scoring／ranking 效率」。
- **做法**：新增 `get_doc_tf(term) -> (doc_nums, tfs)`。讀到 n\_pos 後直接跳過那些 position 的 VByte，不建 `Posting` 物件；檔案只開一次，或改用 `mmap`。
- **注意**：position 仍是 VByte，要跳過就必須逐個讀出結束位元，無法直接 seek。既有的 `get_postings` 保持不動，留給 phrase／proximity 使用。
- **對應接口**：posting 磁碟格式 `[Δdoc][tf][n_pos][Δpos…]`（`writer.py:157-168`）；實測高 df 詞完整解碼可達 128 ms。

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
  - 運算元內的多詞（`open source`、`software engineer`）語意未定。建議最低要求當作「所有詞都要出現」（隱含 AND），加分版再升級為 phrase。
  - 運算元可能全是 stopword 或全不在 dictionary 中；要決定空運算元是否讓整個 AND 為空。建議：空運算元直接略過，並印出警告。
- **對應接口**：`Preprocessor.process`（`tokenizer.py:94-106`），回傳 `list[(position, term)]`。position 在過濾 stopword 前編號，空洞會保留。

### T5 Boolean merge（AND／OR）

- **作業要求**：Boolean query 要先選出候選文件，再交給 VSM 排序。
- **做法**
  - AND：依 df 由小到大兩兩交集；可重用 `intersect_with_skips` 取得 docID 集合。
  - OR：對已排序的 docID 做線性聯集。
  - 依 T4 的 AST 遞迴求值，得到候選 docID 集合。分數由 T6 另外計算，不在 merge 裡維護 tf。
  - 自由文字不做過濾，候選就是「至少含一個 query term」的文件，由 T6 的累加器自然產生。
- **注意**
  - 既有的多詞 AND（`main.py:248-282`）把中間結果重包成假的 `Posting(d, 1, …)`，tf 已經丟失，不能拿來評分。
  - `and_query`（`skip_builder.py:233`）只支援兩個詞，而且只能在 memory 模式下用，不要用。
  - 建議評分時使用**整個 query 的所有 term**（例如 `open`、`sourc`、`linux`），只拿 Boolean 結果來過濾。這是常見做法，但規格沒寫，文件中要說明。
- **對應接口**：`build_skip_list`（`skip_builder.py:51-80`）、`intersect_with_skips(p1, p2) -> (doc_nums, n_comparisons)`（`:174-230`）、`intersect_basic`（`:137-171`）。輸入只需要具備 `.doc_num`／`.skip` 的 list。

### T6 VSM 排序

- **作業要求**：w\_ij = (1 + log10 tf) × log10(N/df)，以 cosine 排序。
- **做法**（term-at-a-time 累加器）
  1. 對每個評分 term t（df > 0）：算出 idf、w\_tq，再把 w\_tq 加入 |q|²。
  2. 讀取 `get_doc_tf(t)`，對每個 (doc, tf) 做 `acc[doc] += weight(tf, df, N) × w_tq`。Boolean query 只累加候選集合內的 doc。
  3. `score = acc[doc] / (norm[doc] × |q|)`。
  4. 依 (−score, doc) 排序：分數由高到低，同分時 docID 小的在前。
- **注意**
  - w\_iq = `weight(tf_q, df, N)`，與文件同公式；tf\_q 是該 term 在 query 中出現的次數。其他方案（ntc、binary 等）留給加分的 SMART 切換。
  - query 中不在 dictionary 的 term：df = 0，idf 無定義，直接略過，也不計入 |q|。全部略過時輸出空結果。
  - tf = 0 的權重定義為 0；除以前要防 norm = 0。
  - |q| 不影響排序，但會影響輸出分數，必須照公式除上。
  - Python 累加器用 `dict` 即可。高 df 詞若太慢，可改用長度 N 的 `array('d')`。
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
- **對應接口**：`IndexReader.get_doc(n).trec_id`（`writer.py:418`），只在需要額外顯示 TREC ID 時使用。

## 加分任務

CP 值最高的是 phrase／proximity 和權重方案變體：前者 HW1 的 positions 已經備好，後者只是 T6 的參數化。評分看的是 query 類型多樣性、權重方案和效率，下表依建議優先序排列。

| 優先 | 項目 | 作業對應 | 做法 | 可重用的 HW1 接口 | 注意 |
| --- | --- | --- | --- | --- | --- |
| 1 | Phrase query（`"open source"`） | 複雜查詢，Ch.2 | 先 AND 取候選，再比對 positions：各 term 的位置差要等於它們在 query 內的位置差 | `get_postings`（含 positions）、`process` 回傳的 position | stopword 空洞在 index 與 query 都會保留，直接比位置差即可 |
| 2 | Proximity（`linux /5 kernel`） | 複雜查詢，Ch.2 | 兩個 position 列表做雙指標，找距離 ≤ k 的配對 | 同上 | 距離以含 stopword 的 token 位置計算，文件中要說明 |
| 3 | 權重方案變體（SMART：ltc.ltc、lnc.ltc、bnn 等） | Ch.6 | 把 tf、idf、normalization 三個字母各自實作成函式，以 `--scheme lnc.ltc` 切換 | T6 的 `weight()` | doc 端每改一種方案，norm 就要重算一份，檔名要帶 scheme |
| 4 | 多運算子與括號（`(A OR B) AND NOT C`） | Ch.2–3 | parser 改為遞迴下降；NOT 做集合差 | T4 的 AST、T5 的 merge | NOT 單獨出現時結果是「全部文件減掉 X」，要決定是否允許 |
| 5 | Skip pointer 加速 AND | Ch.2 | T5 直接使用 `intersect_with_skips`，並記錄比較次數對照 `intersect_basic` | `skip_builder.py:51`、`:174` | skip 每次查詢重建，成本 O(df)；要實測確認真的變快才寫進文件 |
| 6 | Wildcard（`comput*`） | Ch.3 | 用 trie 做 prefix 展開成多個 term，再以 OR 處理 | `RadixTrie.prefix_search`（`trie.py:108`） | dictionary 已經 stem 過：prefix 要對 stem 後的字串比對，且 prefix 本身不能再 stem |
| 7 | 拼字更正 | Ch.3 | query term 不在 dictionary 時，用 k-gram 篩候選、edit distance 排序，取 df 最高的 | dictionary、T1 的 `df()` | dictionary 是 stem 後的形式，建議顯示「Did you mean」而不是自動替換 |
| 8 | 不精確 top-k（champion list、index elimination） | Ch.7 | index elimination：只用 idf 高於門檻的 term。champion list：每個 term 預存 tf 前 r 名的 doc | T3 | 結果會跟精確 cosine 不同，必須是可關閉的選項，預設關閉 |
| 9 | Web UI 與 term highlighting | 介面 | Flask／FastAPI 單頁；快速版可用 Streamlit | `doc_map`（URL、TREC ID） | index 沒有存原文與字元 offset，highlight 要回 WARC 重讀文件，成本最高 |

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
- [ ] 決定是否附上 index 與 `doc_norms.bin`：附上則 TA 不必重建，但檔案會很大；不附則 README 要寫清楚重建步驟



## 風險與待確認事項

最大的風險是「不報錯的不一致」：log 底數、前處理、index 路徑只要一處不同，程式仍照常輸出，只是分數不對。

| 風險 | 後果 | 預防 |
| --- | --- | --- |
| norm 與評分用不同公式 | 分數偏差、排序可能變動 | 共用 `weight()`，norm 檔附 meta 並在載入時核對 |
| 用了 `math.log` | 全部分數偏掉 | 全專案搜尋 `math.log(`，只允許 `log10` |
| AND／OR 被當 stopword 吃掉 | Boolean query 退化成自由文字 | 先切運算子再 `process`（T4） |
| 多 token 詞只取第一個 | `e-mail` 這類詞結果錯 | 保留全部 token（T4） |
| 分數只印 3 位小數 | 分數接近的文件印成同分 | 印 6 位，並寫明同分規則 |

**待確認**

- [ ] Boolean query 的評分範圍：用整個 query 的所有 term 評分、Boolean 只當過濾器，是否符合 TA 預期？
- [ ] 運算元內的多詞（`open source`）：隱含 AND 還是 phrase？
- [ ] 輸出是否要截 top-k？
- [ ] zip 是否附 index？
