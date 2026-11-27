# IR HW3 — LLM + RAG（Hybrid Retrieval）實作規格與分工

> 本文件同時是**組員分工依據**與 **AI agent 實作依據**。
> - `[VERIFY-xx]` 標記的事項都已查證，結果見**第 6 節**。實作時以第 6 節與正文為準，**不得自行猜測**。若出現新的待查事項，沿用同樣的格式新增編號。
> - 本文件中的介面、資料格式、檔名為雙方約定；需要修改時，先更新本文件並通知對方。

---

## 0. 系統概要

```
使用者 query
  ├─▶ 詞彙檢索：stop+stem 前處理 → HW2 VSM（ltc.ltc，自由文字路徑）→ top-N 篇 → 每篇挑最佳 passage
  └─▶ 語意檢索：embedding → FAISS（LangChain vectorstore）→ top-N passage → 依 docid 去重
        │
        ▼
  RRF 合併（以 docid 為單位）→ top-k 篇（各附一段 passage）
        │
        ▼
  Prompt（附引用 ID）→ ChatOllama → 回答 + References
```

評分重點（來自作業投影片）：
1. 包含 ClueWeb09 內容的問題，要能用 RAG 正確回答
2. 包含**埋入語料的特殊 token**的問題，要能用 RAG 正確回答
3. 必須展示**有 RAG vs 無 RAG** 的差異

語料：沿用 HW1/HW2 的 `04.warc`（34,786 篇，TREC ID `clueweb09-en0000-04-*`）。

---

## 1. 共同約定

### 1.1 技術選型

| 項目 | 選擇 | 備註 |
|---|---|---|
| 語言 / 套件管理 | Python ≥ 3.12 + uv | **HW3 是獨立專案**：`HW3/pyproject.toml` + `HW3/uv.lock`，所有指令都在 `HW3/` 目錄下執行。依賴包含 hwlib 需要的 `beautifulsoup4`、`lxml`、`ftfy`、`nltk`、`spacy`，以及 LangChain 相關套件（版本見 `[VERIFY-14]`）。另鎖定間接依賴 `charset-normalizer==3.5.2`：bs4 的編碼偵測結果會隨它的版本改變，3.5.3 會讓 29 篇文件的解碼與 HW2 索引不同（`[VERIFY-14]`） |
| LLM 框架 | LangChain：`langchain-core`、`langchain-ollama`、`langchain-community` | 符合投影片建議。**RRF 合併自行實作**，不使用 `EnsembleRetriever`（它依 passage 內容去重，我們需要依 docid 合併） |
| LLM 執行 | Ollama ≥ v0.11.10 | embeddinggemma 的最低版本需求（`[VERIFY-11]`） |
| 生成模型 | `qwen3:8b`（預設，最終版本） | tag 寫死在 config，不用 `latest` |
| 開發用模型 | `qwen3:1.7b`，或 `qwen3:4b-q4_K_M` | 透過 `config.local.toml` 切換（見 1.3）。**不要用預設的 `qwen3:4b`**：它是只能思考的版本，思考模式關不掉。`1.7b` 會捏造文件中沒有的細節，**最終的 prompt 調整一定要在 `qwen3:8b` 上做** |
| Embedding 模型 | `embeddinggemma` | query 與 passage 必須用同一個模型與前綴（`[VERIFY-11]`） |
| 向量索引 | LangChain `FAISS` vectorstore（需安裝 `faiss-cpu` 套件） | 向量做 L2 normalize，使用內積（= cosine） |
| Doc store | SQLite（內建 `sqlite3`） | |
| WARC 讀取 / HTML 清理 / 前處理 / 索引 | **沿用 HW1/HW2 的實作，複製到 `HW3/src/hwlib/`**（見 2.1） | 不使用 `warcio`（HW1 已確認有 `Content-Length` 誤差問題），也不另外引入 HTML 清理套件。query、passage 評分、索引必須是同一套前處理（stop + stem） |
| 詞彙排序 | **沿用 HW2 的 VSM（`ltc.ltc`，log10）** | 走自由文字路徑，繞過 HW2 的 query parser（見 2.6） |
| 合併 | RRF，k = 60 | |
| 測試 | 標準函式庫 `unittest` | 不新增測試套件，慣例見 1.6 |

**LangChain 路線已實測通過**（以 bench 工具實測，獨立分支 `feat/hw3-bench`；bench 工具不合併進 main）：`OllamaEmbeddings` 搭配自行加上的前綴可正常取得向量；`ChatOllama(reasoning=False)` 可關閉 Qwen3 的思考模式。

**hwlib（HW1/HW2 程式碼的副本）**
- 從 `HW2/src` 複製到 `HW3/src/hwlib/`，取代原本「從 HW2/src 匯入」的做法。HW2/src 的 loader、cleaner、indexer 與 HW1 逐位元組相同；tokenizer、writer 是 HW1 的超集，建置產物已實測完全相同（`[VERIFY-10]`）。
- 複製的模組（彼此 import 封閉，不需要其他檔案）：`warc`、`extract`、`documents`、`tokenizer`、`indexer`、`trie`、`writer`、`weighting`、`build_norms`、`rank`，外加空的 `__init__.py`。
- **只修改 import 語句**：模組之間的扁平絕對匯入（`from warc import ...`）改成套件內的相對匯入（`from .warc import ...`），其他程式碼一律不動。
- `hwlib/README.md` 記錄：來源路徑與 commit hash、複製的檔案清單、每個檔案修改了哪幾行 import。
- 外部資料檔：`tokenizer` 使用 `spacy.blank("en")`，**不需要**下載 spaCy 模型；停用詞需要 NLTK 的 `stopwords` 資料。程式第一次執行時會自動下載，但 README 仍要寫下手動步驟：`uv run python -c "import nltk; nltk.download('stopwords')"`。
- 已完成（A1）：實際修改了 6 個檔案共 12 行 import（含 `rank.py` 位於 `if TYPE_CHECKING:` 區塊內的 `from writer import IndexReader`）；以 hwlib 全量重建的 `lexicon.tsv`、`postings.bin`、`doc_map.json` 與 `HW2/index` 逐位元組相同。
（依 A1 / 討論修正）

### 1.2 目錄結構

標記【程式產生】的資料夾不預先建立、不放進版控，由需要它的程式在執行時建立。

```
HW3/                         # 獨立 uv 專案，所有指令在此目錄執行
├── pyproject.toml
├── uv.lock
├── config.toml
├── config.local.toml        # 本機覆寫（不進版控，見 1.3）
├── src/
│   ├── main.py              # 統一入口：build / query / eval 子指令
│   ├── hwlib/               # HW1/HW2 程式碼副本（只改 import，見 1.1）(A)
│   │   └── README.md        # 來源 commit、import 修改紀錄、依賴鎖定理由
│   └── rag/                 # 每個模組旁邊放 <模組>.test.py（unittest，範圍見 1.6）
│       ├── __init__.py      # 空檔
│       ├── config.py        # 讀 config.toml + config.local.toml    (A)
│       ├── hw_bridge.py     # 使用 hwlib 的唯一位置                 (A)
│       ├── build.py         # 一鍵重建所有產物                      (A)
│       ├── embed.py         # 帶前綴的 Embeddings 類別（唯一入口）  (A)
│       ├── vectorstore.py   # FAISS 組裝與 load_vectorstore（2.5）  (A)
│       ├── lexical.py       # LexicalRetriever                      (A)
│       ├── fusion.py        # RRF + HybridRetriever                 (A)
│       ├── retrieve.py      # 對外統一介面 retrieve()               (A)
│       ├── docstore.py      # SQLite 存取                           (A)
│       ├── passages.py      # 切 passage                            (A)
│       ├── semantic.py      # SemanticRetriever（查詢端）           (B)
│       ├── llm.py           # ChatOllama 建立                       (B)
│       ├── prompt.py        # Prompt 模板與 chain                   (B)
│       ├── cli.py           # query 子指令                          (B)
│       └── evaluate.py      # eval 子指令                           (B)
├── tools/
│   └── inject_warc.py       # 依 [[inject.tokens]] 從 04.warc 產生 04_injected.warc（見 2.2）(A)
├── eval/
│   └── testset.jsonl        # 測試題（雙方共同撰寫，進版控）
├── dataset/                 # 使用者放入：04.warc（可用 symlink 指向 HW1/dataset/04.warc）、
│                            #   04_injected.warc（由 tools/inject_warc.py 產生，見 2.2）（不進版控）
├── index/                   # 【程式產生】重建後的詞彙索引 + HW2 norms（不進版控）
├── store/                   # 【程式產生】docstore.sqlite、vectorstore/、embed_ckpt/、build_meta.json（不進版控）
├── fixtures/                # 【程式產生】前 N 篇的建置產物，子結構同正式資料：index/、store/（不進版控，見 2.8）
├── output/                  # 【程式產生】eval 結果、對照輸出（單數，與 HW2 一致）（不進版控）
└── scratch/                 # 本機驗證用暫存腳本（不進版控）
```

- `.gitignore` 要包含 `HW3/config.local.toml`、`HW3/store/`、`HW3/fixtures/`、`HW3/scratch/`；`dataset/`、`index/`、`output/`、`*.warc` 已由根目錄的通用規則排除。
- bench 工具放在獨立分支 `feat/hw3-bench`，不合併進 main；main 上的 `tools/` 只有 `inject_warc.py`。
- `docstore.py`、`passages.py` 改由 A 負責；新增 `vectorstore.py`（A），理由見 2.5。
（依 A1 / 討論修正）

### 1.3 config.toml（初版）

所有路徑相對於 `HW3/`。

```toml
[corpus]
source_warc = "dataset/04.warc"            # 由使用者自行放入（README 說明）
injected_warc = "dataset/04_injected.warc"

[llm]
model = "qwen3:8b"
temperature = 0
num_ctx = 8192           # 已實測 qwen3:8b + 8192 可以完整放進 GPU
disable_thinking = true

[embed]
model = "embeddinggemma"
query_prefix = "task: search result | query: "   # model card 的檢索用 query 格式
doc_prefix = "title: none | text: "              # 沒有標題時固定寫 none
dim = 768
batch_size = 64

[retrieval]
k_each = 20              # 詞彙、語意兩路各取幾篇
k_final = 5              # 合併後送進 LLM 的篇數
rrf_k = 60
passage_words = 300
passage_stride = 250     # 相鄰 passage 重疊 50 字
prompt_passage_max_words = 300

[paths]
index_dir = "index"
docstore = "store/docstore.sqlite"
vectorstore_dir = "store/vectorstore"
embed_ckpt_dir = "store/embed_ckpt"
build_meta = "store/build_meta.json"
fixtures_dir = "fixtures"
output_dir = "output"

# 每位成員一組；學號、句子與 target_trec_ids 都由該成員自行挑選並填入（見 1.5）
[[inject.tokens]]
student_id = "<學號>"
sentence = "The IR HW3 verification code <學號> is registered by team member <姓名>."
target_trec_ids = []   # 固定 3 篇

[[inject.tokens]]
student_id = "<學號>"
sentence = "The IR HW3 verification code <學號> is registered by team member <姓名>."
target_trec_ids = []
```

- **`[[inject.tokens]]` 是 `04_injected.warc` 如何產生的唯一紀錄**：學號、句子與目標 TREC-ID 都只寫在這裡。本規格不列出具體的 TREC-ID，程式中也不得另外寫死。WARC 由 `tools/inject_warc.py` 依這份設定產生（見 2.2）；`main.py build` 沒有 inject 階段，只讀取已產生的 `injected_warc`。（依 A1–A3 同步）
- **本機覆寫 `config.local.toml`**（不進版控）：存在時，`rag/config.py` 以它逐鍵覆寫 `config.toml`（表格遞迴合併，其他值整個取代）。用途是讓開發者自行改用開發用模型（1.1）、調降 `k_final`，以及切換 fixtures（下一點）。不得在覆寫檔中修改 `[embed]`、`[paths]` 與 `[[inject.tokens]]`（前者與後者會讓產物與他人不一致，`[paths]` 會讓切換 fixtures 有兩種方式）；`rag/config.py` 遇到時會 raise `ConfigError`。範例見 `config.local.toml.example`。
- **切換 fixtures 只有一種方式**：在 `config.local.toml` 設定 `[runtime] use_fixtures = true`（預設 false，不寫在 `config.toml`）。
  - `query` 與 `eval` 讀到 true 時，所有路徑改為 `fixtures_dir/<config.toml 中的相對路徑>`。
  - `build` 不讀這個開關：有 `--limit` 時寫到 fixtures 路徑，沒有時寫到正式路徑（2.8）。
- **路徑解析**：`[corpus]` 的路徑由 `rag/config.py` 以 `HW3/` 為基準解析成絕對路徑。`[paths]` 在設定 dict 中保留 config.toml 的相對路徑字串，絕對路徑一律透過 `rag.config.paths(fixtures: bool) -> dict[str, Path]` 取得：
  - `paths(False)` = `HW3/<相對路徑>`；`paths(True)` = `HW3/<fixtures_dir>/<相對路徑>`（`fixtures_dir` 本身不變）。兩套都由同一份相對路徑計算，不會出現 `fixtures/fixtures/...`。
  - `[paths]` 的值必須是 `HW3/` 底下的相對路徑，而且 `fixtures_dir` 以外的路徑不得位於 `fixtures_dir` 之內，否則 raise `ConfigError`。
  - 與工作目錄無關；不跟隨 symlink。
- **建置完成檢查**：`rag.config.require_build_done(build_meta_path) -> dict` 確認 build_meta 檔案存在且 `status == "done"`（呼叫端傳入 `paths(...)["build_meta"]`，檔名不寫死），否則 raise `BuildNotDoneError`，訊息提示重新執行 build（`status` 為 `"in_progress"` 時說明上次建置未完成）；通過時回傳 build_meta 內容。lexical、eval 啟動時都必須呼叫（2.6、3.5）；semantic 透過 `load_vectorstore` 呼叫（2.5、3.3）。build_meta 無法解析時也 raise `BuildNotDoneError`。
- **`rag.config` 其他介面**：`load_config(config_path=CONFIG_PATH, local_path=LOCAL_CONFIG_PATH) -> dict`；`get_config() -> dict`（整個 process 只讀一次，回傳深複本，一般程式用這個）；常數 `HW3_ROOT`、`CONFIG_PATH`、`LOCAL_CONFIG_PATH`；例外 `ConfigError(ValueError)`（設定不合法）、`BuildNotDoneError(RuntimeError)`。`[runtime] use_fixtures` 必須是布林值。（依 A1–A3 同步）
- 前綴字串要原樣保留，包括 `|` 兩側的空白和結尾的空白。`langchain-ollama` 會把文字原樣送出，所以前綴一律由 `embed.py` 加上。
- embeddinggemma 的輸入上限是 2048 tokens。絕大多數 300 字的 passage 在範圍內；全量有 53 段（31 篇，多為序列化資料等符號密集文字）超過，由 Ollama 預設截斷保留開頭 2,048 tokens，不需處理（`[VERIFY-15]`、2.5）。（依 A3 修正）
（依 A1 / 討論修正）

規模預估（用於檢查建置結果是否合理，非硬性數字）：平均每篇約 870 字，以 300/250 切分，約 **12 萬段 passage**。A2 全量實測：**123,251 段**（34,786 篇，空文件 1 篇不佔 pid），`docstore.sqlite` 458 MB，建置 204 秒（幾乎都是 HTML 清理）。（依 A1–A3 同步）

### 1.4 資料格式（Data Contract）

**文件編號**：全系統的 `docid` = HW2 輸出的 `doc#` = 索引內部的文件編號 = TREC-ID 尾碼整數，從 0 起算（`[VERIFY-01]`）。

**`store/docstore.sqlite`**
```sql
CREATE TABLE docs (
  docid   INTEGER PRIMARY KEY,   -- 與 HW2 doc# 一致
  trec_id TEXT NOT NULL,
  url     TEXT,
  text    TEXT NOT NULL          -- Cleaner 輸出的純文字（未 tokenize）
);
CREATE TABLE passages (
  pid        INTEGER PRIMARY KEY, -- 0..N-1，連續
  docid      INTEGER NOT NULL REFERENCES docs(docid),
  start_word INTEGER NOT NULL,    -- 以空白切字的位置，含頭不含尾
  end_word   INTEGER NOT NULL,
  text       TEXT NOT NULL
);
CREATE INDEX idx_passages_docid ON passages(docid);
```
- `docid`、`trec_id`、`url`、`text` 全部直接取自 `hw_bridge.iter_documents()`。寫入後檢查文件數與 docid 集合都與 `doc_map.json` 一致，且 passages 的 pid 為 0..N−1 連續；不一致就 raise `ValueError`（明確 raise，不用 `assert` 敘述）（`[VERIFY-08]`）。（依 A1–A3 同步）

**`store/vectorstore/`**：LangChain `FAISS.save_local()` 的輸出（`index.faiss` + `index.pkl`）。每筆 Document 的 metadata：`{"pid": int, "docid": int}`，id = `str(pid)`；FAISS 的第 i 個向量 = pid i。`store/embed_ckpt/`：embedding checkpoint（格式見 2.5）。（依 A1–A3 同步）載入時需 `allow_dangerous_deserialization=True`（`[VERIFY-12]`）。

**`store/build_meta.json`**（只保留下列欄位）
```json
{
  "status": "in_progress",
  "embed_model": "embeddinggemma",
  "query_prefix": "...", "doc_prefix": "...", "dim": 768,
  "passage_words": 300, "passage_stride": 250,
  "limit": null,
  "inject_tokens": [ {"student_id": "...", "sentence": "...", "target_trec_ids": ["..."]} ]
}
```
- `limit` 為 null 代表全量建置，fixtures 則為 N（見 2.8）。
- `inject_tokens` 是建置時 config 的 `[[inject.tokens]]` 原樣內容。
- `passage_words`、`passage_stride` 是建置時 config `[retrieval]` 的值：改了切分參數，pid 與向量都會不同，必須重建（2.8 比對）。
- `status`：`"in_progress"` 或 `"done"`。建置一開始就寫入 `"in_progress"`，全部階段完成後改為 `"done"`（見 2.8）。
（依討論修正）（依 A1–A3 同步）

**檢索結果格式**：所有 retriever 都回傳 LangChain `Document`，`page_content` = passage 文字，`metadata` 固定包含：
```python
{
  "docid": int,
  "trec_id": str,
  "url": str,
  "pid": int,
  "score": float,          # 該模式的最終分數；hybrid 時為 RRF 分數
  "rank": int,             # 1 起算
  "sources": list[str],    # ["lexical"]、["semantic"] 或兩者
}
```

**統一介面（`rag/retrieve.py`）**
```python
from typing import Literal
from langchain_core.documents import Document

def retrieve(query: str, k: int | None = None,
             mode: Literal["lexical", "semantic", "hybrid"] = "hybrid") -> list[Document]:
    """k 預設為 config.retrieval.k_final；回傳依 rank 排序、每個 docid 至多一筆。"""
```

**測試集 `eval/testset.jsonl`**（一行一題）
```json
{"id": "f01", "type": "fact",  "query": "When was the premiere of The Magic Flute?", "gold_docids": [123], "answer": "1791", "paraphrase": false}
{"id": "f02", "type": "fact",  "query": "In what year did Mozart's last opera first hit the stage?", "gold_docids": [123], "answer": "1791", "paraphrase": true}
{"id": "t01", "type": "token", "query": "<學號>", "gold_docids": [45, 9876, 20001], "answer": "<埋入句子的重點>", "paraphrase": false}
```
- `paraphrase: true` 表示問題刻意換句話說，避開文件中的原始用詞（用來展示語意檢索的效果）。

### 1.5 特殊 token

- 每位成員的 token 就是**學號**，是純數字的單一 term。
- 每個學號搭配一句完整句子，讓 LLM 有內容可以回答：
  `The IR HW3 verification code <學號> is registered by team member <姓名>.`
- 每人埋 **3 篇**，兩人共 6 篇。
- 設計說明：純數字 token 預期在語意檢索中表現差、在詞彙檢索中命中，正好用來展示 hybrid 的效果。
- 設定來源：1.3 的 `[[inject.tokens]]`，每位成員一組；**每位成員自行挑選自己的 3 篇目標**，連同學號、句子填入。
- **擺放位置**：第 1 篇 docid < 200（落在預設 N = 200 的 fixtures 內）；其餘 2 篇建議放在語料的中段與後段，但不強制。
- **挑選目標時的確認**（手動執行，不是程式的事前驗證）：
  1. 每組的 `target_trec_ids` 恰好 3 篇。
  2. 用 `hw_bridge.inspect_targets(source_warc, set(target_trec_ids))` 確認：3 篇都在結果中、`content_type == "text/html"`、`cleaned_text` 不是 `None` 也不是空字串。
  3. 每組至少一篇 `docid < 200`（docid = TREC-ID 尾碼整數，即 `TargetInfo.docid`）。
  4. 學號原本查不到：在 repo 根目錄執行 `uv run python HW2/src/search.py "<學號>" --index-dir HW2/index`，沒有任何輸出。學號是純數字，不會被 stem（`[VERIFY-04]`）。需要本機已有 `HW2/index`（不進版控，需先依 HW2 README 建置）；HW3 README 的開發說明也要提及。
- 為什麼只選 `text/html`：`text/plain` 文件沒有 `</body>`，插入的 `<p>` 會留在清理後的文字裡。
- **WARC 的修改**：由 A 統一進行，只產生一份 `dataset/04_injected.warc`（見 2.2）。
- **驗收**（A 執行）：
  1. 用 `hw_bridge.iter_documents` 讀取新 WARC，文件數仍為 34,786，docid 恰為 0..34785。
  2. 用 `hw_bridge.inspect_targets(injected_warc, 全部 6 篇目標)` 確認每篇的 `cleaned_text` 都包含該組的句子。
  3. 建置完成後用詞彙檢索查詢每個學號，命中的文件必須 = 埋入的文件。
- **選做**：把一則資訊拆成 3 部分，分別放進同一組的 3 篇文件，展示 LLM 綜合多篇文件回答的能力。
（依 VERIFY-04 修正）（依 A1 / 討論修正）

### 1.6 共同實作規範（雙方都適用）

1. 不得單方面修改 1.3、1.4 的介面、資料格式、檔名；需要修改時，先更新本文件
2. 遇到 `[VERIFY-xx]`：以第 6 節的結論為準；新的待查事項查不到時，停下來回報，不要猜測
3. hwlib 的模組**只能透過 `rag/hw_bridge.py` 使用**；其他檔案不得 import `hwlib`。需要讀取 WARC 中特定文件的 content type 與清理後文字時，使用已提供的 `hw_bridge.inspect_targets(warc_path, trec_ids: set[str]) -> dict[str, TargetInfo]`（`TargetInfo(docid: int, content_type: str, cleaned_text: str | None)`，見 2.1），不要另外讀 WARC（依 A1 / 討論修正）
4. Embedding 一律使用 `rag/embed.py` 提供的類別；**禁止在其他地方自行建立 `OllamaEmbeddings` 或加前綴**
5. 所有參數從 config 讀取，程式中不寫死模型名稱、路徑或 k 值
6. 提示與進度訊息只寫到 `stderr`；回答與結果寫到 `stdout`（與 HW2 一致）。hwlib 函式 print 到 stdout 的輸出，由 `hw_bridge` 轉到 stderr（見 2.1）
7. 單元測試（`unittest`）**只寫以下三項**，只使用測試程式內自建的小資料，不依賴 `fixtures/`（不進版控，乾淨 clone 上不存在）或全量產物。`fixtures/` 用於手動測試與整合測試：
   - `passages`（切分邊界、短文件、空文件）
   - `fusion`（RRF 分數、同分規則、passage 選擇、sources）
   - `embed`（query / doc 前綴各加一次、空白原樣保留；輸入已以該前綴開頭 → `ValueError`；輸出已 L2 normalize；兩種模式的 `num_gpu`）
   - 檔名：放在被測模組旁邊，命名為 `<模組>.test.py`（例如 `rag/passages.py` → `rag/passages.test.py`），依照 AGENTS.md 的慣例。
   - 寫法：使用 `unittest.TestCase`，檔尾加上 `if __name__ == "__main__": unittest.main()`。
   - 匯入：直接執行測試檔時，`sys.path[0]` 是 `HW3/src/rag/`，所以檔頭要把 `HW3/src` 插入 `sys.path`，之後一律用 `from rag.xxx import ...` 匯入，不可以直接 `import xxx`，否則同一個模組會被載入兩份。這是唯一允許的 `sys.path` 操作。
   - 執行（在 `HW3/` 下）：`uv run python src/rag/passages.test.py`；全部執行用 `for f in src/rag/*.test.py; do uv run python "$f" || break; done`。
   - 不能用 `python -m unittest <路徑>` 或 `unittest discover -p "*.test.py"`：檔名中多了一個 `.`，無法當成模組名稱匯入（已實測，前者報錯，後者找到 0 個測試）。
   - **待處理**：AGENTS.md 寫的測試指令（`uv run python -m unittest HW1/src/*.test.py`）因上述原因無法執行，也沒有涵蓋 HW3 的獨立專案。實作時再一併修正 AGENTS.md（A1–A3 時仍未修正）。
   - 目前的測試檔：`passages.test.py`（12 項）、`embed.test.py`（15 項）。
   （依 A1 / 討論修正）（依 A1–A3 同步）
8. 尚未完成的相依元件，先用介面相同的假實作（例如 `fake_retrieve()`），不得等待
9. 開發時可以使用小模型 `qwen3:1.7b`（在 `config.local.toml` 設定，見 1.3），最後調整時再換回 `qwen3:8b`

### 1.7 分工與交接順序

| A：建置與詞彙線 | B：查詢與生成 |
|---|---|
| `config`、`hw_bridge`、`hwlib`（1.1、2.1） | LLM、prompt（3.1、3.2） |
| 埋入 WARC（`tools/inject_warc.py`，1.5、2.2） | CLI（3.4） |
| 重建索引（2.3） | `semantic`（查詢端：查詢、依 docid 去重、補 metadata，3.3） |
| `docstore`、`passages`（2.4） | `evaluate`（3.5）、README 與打包（3.7） |
| `embed.py`、`vectorstore.py`（含 `load_vectorstore`）、embedding、FAISS 建置（2.5） | |
| `lexical`（2.6） | |
| `fusion`、`retrieve`、`build.py`（2.7、2.8） | |

- 埋特殊 token（1.5、2.2）：每位成員各自挑選目標並填入 `[[inject.tokens]]`；WARC 由 A 以 `tools/inject_warc.py` 統一產生，token 題的 `gold_docids` 也由 A 填寫。
- 向量庫的載入（含建置完成檢查、模型一致性檢查、`DistanceStrategy`）由 A 的 `load_vectorstore` 負責；B 的 `semantic` 只負責查詢端的邏輯。

交接順序：
1. A 完成 `hwlib`、`config`、`hw_bridge`（已完成，A1）與 inject（已完成：`dataset/04_injected.warc`、1.5 的驗收、token 題的 `gold_docids`）
2. A 完成 `docstore`、`passages`、`embed.py`、`load_vectorstore`、`build.py`，產出包含向量庫的 fixtures（`main.py build --limit N`，見 2.8；fixtures 不進版控，B 在本機以同一指令自行產生）
3. B 在第 2 步完成前，以 `fake_retrieve()` 開發 LLM、prompt、CLI；fixtures 可以產出後開發 `semantic`
4. B 交出 `semantic`，A 接上 `fusion` 與 `retrieve`（`fusion` 可先接假資料寫好）
5. A 完成全量建置（`index/`、`store/`）；整合

（依 A1 / 討論修正）

---

## 2. 建置期：資料管線、索引、embedding 與詞彙檢索

本節全部由 A 負責（2.2 的目標挑選由各成員進行，分工見 1.7）。建置期產物統一由 `main.py build` 產生；`04_injected.warc` 例外，是建置前先以 `tools/inject_warc.py` 產生的輸入。B 在建置期唯一使用的介面是 2.5 的 `load_vectorstore` 與 2.4 的 docstore 讀取函式。（依 A1 / 討論修正）

### 2.1 hwlib 橋接（`rag/hw_bridge.py`）
對外只暴露下列函式（`[VERIFY-01]`–`[VERIFY-10]`）：
```python
def iter_documents(warc_path, limit: int | None = None) -> Iterator[tuple[int, str, str, str]]  # (docid, trec_id, url, cleaned_text)
def iter_raw_records(warc_path) -> Iterator[bytes]                    # 逐筆原始 record（tools/inject_warc.py 使用，見 2.2）
def inspect_targets(warc_path, trec_ids: set[str]) -> dict[str, TargetInfo]   # 1.5 挑選目標時的確認
def preprocess(text: str) -> list[str]                               # stop+stem 前處理，回傳 term 序列
def build_lexical_index(warc_path, index_dir, limit: int | None = None) -> dict   # 2.3，回傳 N、vocab_size 等統計
def build_doc_norms(index_dir) -> None                               # 2.3，ltc norms
def load_ranker(index_dir) -> Ranker                                  # HW2 VSM 排序器
```
```python
@dataclass(frozen=True, slots=True)
class TargetInfo:
    docid: int                 # TREC-ID 尾碼整數
    content_type: str          # HTTP Content-Type 的 MIME 部分：小寫、去掉參數；缺少時為 "(none)"
    cleaned_text: str | None   # 與 iter_documents 的 cleaned_text 相同；hwlib 排除該文件時為 None
```
- `inspect_targets`：只讀一次 WARC、只對目標 record 執行清理；找不到的 trec_id 不出現在回傳的 dict 中；全部找到後提前停止（A1 實測：3 篇目標 1.5 秒，含不存在的 id 需讀完整檔 2.8 秒）。
- `limit` 必須是 `None` 或 ≥ 1，否則 raise `ValueError`（HW1 的 `--limit 0` 代表不限制，這裡不沿用）。
- 實作者另可參考 `plans/.done.A1-hwlib-config-bridge.md` 的介面表與驗證結果。
- `Ranker` 也可直接以 `Ranker(index_dir)` 建立，`load_ranker` 只是包裝；檢查失敗時 raise `ValueError`（preprocessor 不符、sha256 / N 不符）或 `FileNotFoundError`（缺 norms）。
（依 A1 / 討論修正）（依 A1–A3 同步）

**匯入方式**
- `from hwlib import documents, tokenizer, ...`，不需要操作 `sys.path`。
- 不使用 `HW1/src/main.py` 的對應功能：它的路徑寫死（`[VERIFY-05]`），也沒有被複製進 hwlib。

**HW1 與 HW2 同名模組的差異**（說明為什麼只從 HW2 複製，`[VERIFY-10]`）

| 模組 | 狀態 | 對 lexicon / postings / doc_map 的影響 |
|---|---|---|
| `warc`、`extract`、`documents`、`indexer`、`trie` | 逐位元組相同 | 無 |
| `tokenizer` | HW2 把 `process` 的逐 token 步驟抽成 `normalize_token`，步驟與順序不變（casefold → stopword → stem）；另外新增 `from_config` | 無。已實測輸出相同 |
| `writer` | 寫出端（`IndexWriter` 與編碼函式）只差 import；HW2 的 `IndexReader` 多了 `N`、`df`、`get_norms`、`get_doc_tf`、champion 與 sha256 檢查 | 無 |
| `skip_builder` | 不複製（建置與 `rank()` 都不會 import 它） | 無 |

- 實測：用同一份合成 WARC，分別以 HW1/src 與 HW2/src 建置。`lexicon.tsv`、`postings.bin`、`doc_map.json`、`dictionary.txt`、`postings.txt` 全部逐位元組相同，`metadata.json` 只有 `created_at` 不同。

**各函式要呼叫的 hwlib 函式與轉接**

| 對外函式 | 呼叫 | 轉接 |
|---|---|---|
| `iter_documents` | `documents.iter_documents(str(path))` | 轉成 `(doc.doc_num, doc.trec_id, doc.url, doc.text)`。`limit` 計算產出的篇數，與 HW1 `build --limit` 相同。**`doc_num` = TREC-ID 尾碼整數，不是流水號**。被排除的文件不會產出；空文字的文件仍會產出（`text == ""`） |
| `iter_raw_records` | `warc.iter_records(path)` | 原樣轉出；所有 record 依序串接後與原檔逐位元組相同。解析標頭用 `warc.split_headers` + `warc.parse_header_lines`（欄位名為小寫，例如 `warc-trec-id`） |
| `inspect_targets` | `warc.iter_responses(path)`，只對目標呼叫 `documents.to_document(resp)` | 與 `documents.iter_documents` 走同一條路徑，結果與 `iter_documents` 逐字相同；`to_document` 回傳 None 時 `cleaned_text = None` |
| `preprocess` | 模組層級單例 `tokenizer.Preprocessor(**PREPROCESSOR_CONFIG)`，呼叫 `.process(text)` | 取 `[t for _, t in ...]`。初始化約 1.8 秒，必須重用同一個實例 |
| `build_lexical_index` | `indexer.Indexer(spimi=False)` 逐篇呼叫 `add_document(doc, PRE.process(doc.text))`；再由 `writer.IndexWriter(index_dir)` 依序呼叫 `.write_binary_format(ix)`、`.write_doc_map(ix)`、`.write_metadata(ix, config=PREPROCESSOR_CONFIG)` | 不用 `Indexer.build()`（會 print 進度），也不用 `write_all()`（會多寫出約 221 MB 的 `postings.txt` 與 `dictionary.txt`）。`metadata.json` 要最後寫。寫完後執行 2.3 的 docid 連續性檢查 |
| `build_doc_norms` | `build_norms.build_norms(index_dir, "ltc")` | 必須在 `metadata.json` 寫完之後呼叫 |
| `load_ranker` | `writer.IndexReader(index_dir)` + `rank.rank` | 回傳 `Ranker`（定義見下） |

- `PREPROCESSOR_CONFIG = {"casefold": True, "stopword": True, "stem": True, "lemma": False}`。HW2 的 `Preprocessor.from_config` 要求必須有前三個欄位。
- **stdout 轉向**：hwlib 的函式會直接 print 到 stdout，例如 `build_norms` 會印出耗時，`Indexer` 的 SPIMI 模式會印出進度。`hw_bridge` 呼叫任何 hwlib 函式時，都要用 `contextlib.redirect_stdout(sys.stderr)` 包住，讓 stdout 只留給 HW3 的結果（1.6-6）。

**`Ranker`**（定義在 `hw_bridge`，lexical.py 只使用這個介面）
```python
class Ranker:
    N: int
    def search(self, terms: list[str], k: int) -> list[tuple[int, float]]   # [(docid, score)]，score 遞減
```
- `search` = `rank.rank(Counter(terms), None, reader, scheme="ltc.ltc")[:k]`。
  - `candidates=None` 就是 HW2 的自由文字路徑，已實測與 `search_query()` 的結果逐筆相同。
  - `rank` 沒有 top-k 參數，會算出所有 score > 0 的文件，依 `(-round(score, 6), docid)` 排序。
  - terms 為空，或所有 term 的 df 都是 0 時，回傳 `[]`。
- 建構時要做兩件事：
  1. 確認 `reader.get_metadata()["preprocessor"] == PREPROCESSOR_CONFIG`，不同就 raise。
  2. 立刻呼叫一次 `reader.get_norms("ltc")`，讓 HW2 的 sha256 與 N 檢查在載入時就失敗，不要拖到第一次查詢。
（依 VERIFY-01–07、09、10 修正）

### 2.2 埋特殊 token（`tools/inject_warc.py`，取代原本的 `rag/inject.py`）
- 不放在 `rag/`、不屬於 `main.py build`：build 沒有 inject 階段，直接讀 `injected_warc`。
- 流程：
  1. 每位成員依 1.5 挑選自己的 3 篇目標並完成確認，把 `student_id`、`sentence`、`target_trec_ids` 填入 `config.toml` 的 `[[inject.tokens]]`。
  2. WARC 由 A 以 `tools/inject_warc.py` 依 config 產生（在 `HW3/` 下執行 `uv run python tools/inject_warc.py`）：以 `source_warc` 為底，只修改目標 record，產生唯一一份 `injected_warc`（`dataset/04_injected.warc`）。其他人不另外產生；需要時可用同一指令重新產生，輸出逐位元組相同。
  3. 工具寫完後自動執行 1.5 的驗收第 1、2 項，以及第 3、4 點的位元組檢查，並印出每組埋入的 docid；A 把它（TREC-ID 尾碼整數，依遞增排序）填入 `eval/testset.jsonl` 對應 token 題的 `gold_docids`。
- 工具的做法：
  - 在目標 HTML 最後一個 `</body>`（不分大小寫）前插入 `<p>{句子}</p>`（ASCII）；找不到 `</body>` 就停止，不改插入位置。record 邊界依 `b"WARC/0.18"`（`[VERIFY-03]`）。
  - WARC 標頭的 `Content-Length` 加上插入的位元組數，HTTP 標頭有 `Content-Length` 時一併加上；只改數字，其他位元組（含換行）不動。hwlib 不讀 `Content-Length`，更新只為格式正確。
  - 非目標 record 逐位元組相同；目標 record 的大小差 = 插入位元組數 + `Content-Length` 數字增加的位數。
  - 先寫暫存檔，全部成功後才 `os.replace` 成正式檔名；設定不完整（每組不是恰好 3 篇、學號非純數字等）時不寫任何檔案。
  - 設定檢查還包括：句子必須包含學號、只能是 ASCII、不含 `< > &`；同一個 TREC-ID 不得出現在兩組。
  - 結束碼：設定不完整 exit 2（不寫檔）、驗收失敗 exit 1、全部通過 exit 0；驗收結果與每組的 docid 印到 stderr。
  - `dataset/04.warc` 可用 symlink 指向 `HW1/dataset/04.warc`；`04_injected.warc` 約 1 GB，不進版控。
（依 VERIFY-01、VERIFY-03 修正）（依 A1 / 討論修正）（依 A1–A3 同步）

### 2.3 重建詞彙索引（`rag/build.py` 的第一階段）
- 以 `injected_warc` 為輸入，依序呼叫 `hw_bridge.build_lexical_index(injected_warc, index_dir, limit)` 與 `hw_bridge.build_doc_norms(index_dir)`（`[VERIFY-05][VERIFY-09]`）。
  - 產物：`lexicon.tsv`、`postings.bin`、`doc_map.json`、`metadata.json`、`doc_norms.bin`、`doc_norms.meta.json`。
- 不需要 surface vocab 與 champion list。走 `rank()` 的路徑時不會讀這兩類檔案，缺檔也不會報錯（`[VERIFY-07]`）。
- **docid 連續性檢查**（寫完索引後立刻執行，不成立就 raise）：
  - `doc_map.json` 的 key 集合必須恰好是 `{"0", ..., str(N-1)}`，而且 `metadata.json` 的 `N == len(doc_map)`。
  - 原因：docid 實際上是 TREC-ID 尾碼，不是流水號。HW2 的 norms 是以 docid 為下標、長度為 N 的陣列，docid 有空號或沒從 0 開始時會出錯，或靜默讀錯資料。
- 驗收：見 1.5（查詢學號，命中的文件 = 埋入的文件）。
- 耗時參考：全量索引約 8.5–9 分鐘（A1 實測 517 秒）、峰值記憶體約 1.0 GB；norms 約 15 秒。
（依 VERIFY-01、05、07、09 修正）（依 A1 / 討論修正）

### 2.4 Doc store 與 passage（`rag/docstore.py`、`rag/passages.py`）（A）
- `docs` 表：`docid`、`trec_id`、`url`、`text` 直接取自 `hw_bridge.iter_documents()`；寫入後檢查文件數與 docid 集合都與 `doc_map.json` 一致（不一致 raise `ValueError`，見 1.4）。
- **切分規則**（`rag/passages.py`，純函式；設 `words = text.split()`、`n = len(words)`、`W = passage_words`、`S = passage_stride`）：
  1. `n == 0`（空文件或只有空白）→ 沒有 passage，不佔 pid；`docs` 表仍寫入該文件。
  2. `n ≤ W`，或 `n < MIN_SPLIT_WORDS`（模組常數 30，不放進 config）→ 整篇一段。
  3. 其餘：起點為 **S 的倍數**（0, S, 2S, …），每段 `[s, min(s + W, n))`，某段結尾等於 `n` 就停止。最後一段一定止於 `n`，且至少 `W − S + 1` 字（300/250 時 **≥ 51 字**）；段數 = `1 + ceil((n − W) / S)`。
  4. passage 文字 = `" ".join(words[start:end])`（空白正規化為單一空白）；`start_word`/`end_word` 含頭不含尾，對應 `docs.text.split()` 的位置。
  5. 任何 ≤ `W − S` 字（50 字）的連續片段必定完整落在某一段內，所以埋入的句子一定完整出現在某段 passage 中。
  6. pid 從 0 起全域連續，依 docid 遞增、同篇內依 start 遞增。
  - 參數檢查：`W ≥ 1` 且 `1 ≤ S ≤ W`，否則 `ValueError`。
  - 函式：`split_passages(text, passage_words, passage_stride) -> list[tuple[int, int, str]]`（`(start, end, text)`）；`number_passages(docs, passage_words, passage_stride) -> Iterator[tuple[int, int, int, int, str]]`（`docs` 為 `(docid, text)`，產出 `(pid, docid, start, end, text)`）。
- **建置**（`rag/docstore.py`，給 build.py 的 docstore 階段）：
  ```python
  def build_docstore(warc_path, db_path, limit: int | None, *, doc_map_path,
                     passage_words: int, passage_stride: int) -> dict   # {n_docs, n_passages, n_empty_docs, seconds}
  ```
  - 寫到 `<db_path>.tmp`，通過檢查後才 `os.replace` 成 `db_path`：**`db_path` 存在 ⇔ 內容完整**（build.py 可直接以檔案存在判斷跳過）。上層資料夾自動建立；`--force` 由 build.py 刪除 `db_path`。
  - 單一交易、`journal_mode=OFF`；每 1,000 篇 `executemany` 一次；`idx_passages_docid` 在資料寫完後才建立。
  - docstore 階段再讀一次 WARC（不修改 `hw_bridge` 介面），全量約 3.5 分鐘、峰值記憶體約 0.2 GB；`--limit 200` 約 1 秒（1,718 段）。
- **讀取**（唯讀存取；路徑由呼叫端以 `paths(...)["docstore"]` 傳入）：
  | 介面 | 說明 |
  |---|---|
  | `Doc(docid, trec_id, url, text)`、`Passage(pid, docid, start_word, end_word, text)` | frozen dataclass |
  | `DocStore(db_path)` | 唯讀開啟（`mode=ro`）；檔案不存在 → `FileNotFoundError`；支援 `with` 與 `close()`；`check_same_thread=False` |
  | `.get_doc(docid) -> Doc`、`.get_passage(pid) -> Passage` | 不存在 → `KeyError` |
  | `.get_passages_by_doc(docid) -> list[Passage]` | 依 pid 排序；空文件或 docid 不存在 → `[]` |
  | `.count_passages() -> int`、`.iter_passages(start_pid=0) -> Iterator[Passage]` | 給 embedding 階段依 pid 分批與續跑 |
- 全量實測（A2）：123,251 段；每段字數中位數 300、平均 262.6；每段字元數 p99 2,440、最大 16,172（序列化資料）；`get_doc` + `get_passages_by_doc` 約 0.02 ms。
- 由 `build.py` 的 `docstore` 階段呼叫。
- **使用者**：A 的 `lexical`（挑最佳 passage）、B 的 `semantic`（補 `trec_id`、`url`）。
- **交接**：屬於交接順序第 2 步，與 `embed.py`、`load_vectorstore`、`build.py` 一起完成後，產出包含向量庫的 fixtures。
- **fixtures 不進版控**：需要時以 `main.py build --limit N` 產出語料**前 N 篇**的產物（N 預設 200，見 2.8）。
  - 只能取前 N 篇，不能挑任意子集，因為 2.3 的連續性檢查會擋下。
  - 依 1.5 的規則，每個學號至少有一篇在 fixtures 中。測試 fixtures 時，`gold_docids` 要先過濾成 docid < N 的那幾篇。
（依 VERIFY-01、VERIFY-09 修正）（依 A1 / 討論修正）（依 A1–A3 同步）

### 2.5 Embedding 與向量庫（`rag/embed.py`、`rag/vectorstore.py` + `build.py` 第二階段）
- `embed.py` 定義 `PrefixedOllamaEmbeddings(langchain_core.embeddings.Embeddings)`：
  - `__init__(model, query_prefix, doc_prefix, *, num_gpu=None, inner=None)`；一般程式用 `PrefixedOllamaEmbeddings.from_config(mode, cfg=None)`（`inner` 只給單元測試注入假的 Embeddings）
  - `embed_query(text)`：加 `query_prefix`
  - `embed_documents(texts)`：加 `doc_prefix`
  - 內部使用 `langchain_ollama.OllamaEmbeddings(model=..., num_gpu=..., dimensions=None)`，輸出以 `l2_normalize(vecs) -> np.ndarray`（float32；零向量或非有限值 raise `ValueError`）做 L2 normalize
  - `OllamaEmbeddings.embed_documents` 會把整個 list 放在一個請求裡送出，不會自動分批
- **兩種模式**（`PrefixedOllamaEmbeddings.from_config(mode)`，`mode` 為 `"build"` 或 `"query"`）：
  - 建置時：不指定 `num_gpu`，由 Ollama 使用 GPU。
  - 查詢時：`num_gpu=0`，embedding 改用 CPU，避免和 LLM 搶 GPU 記憶體（已實測兩者同時載入 GPU 會讓速度慢約 20 倍）。`num_gpu` 是模式的語意，不放進 config。
  - 已實測有效（`[VERIFY-15]`）：查詢模式 embedding 0% GPU、`qwen3:8b` 100% GPU，兩者同時常駐；查詢 embedding 約 20 ms。LLM 第一次載入時會卸載 embedding 一次，之後共存。
- **前綴**：一律加一次；輸入已經以該前綴開頭時 raise `ValueError`（代表呼叫端違反 1.6-4），不默默跳過。
- **長 passage**：`OllamaEmbeddings` 不傳 `truncate`，Ollama 預設靜默截斷、保留開頭 2,048 tokens；不另外截斷（字元數無法準確對應 token 數）。**不可**設定小於 2048 的 `num_ctx`（會進一步截短），也不可傳 `truncate=false`（超長時整批回 HTTP 400）。（依 A1 / 討論修正）（依 A3 修正）（依 A1–A3 同步）
- B 的 `semantic` 不自行建立 embeddings：query 由 `load_vectorstore` 回傳的向量庫內含的 `PrefixedOllamaEmbeddings`（查詢模式）轉換（見下方 `load_vectorstore`）。
- **`rag/vectorstore.py` 對外介面**（A3）：
  | 介面 | 說明 |
  |---|---|
  | `ckpt_meta_from_config(cfg, *, limit, n_passages) -> dict` | checkpoint 的比對設定 |
  | `embed_passages(db_path, ckpt_dir, embeddings, *, batch_size, ckpt_meta) -> dict` | embedding 階段；回傳 `{n_passages, n_batches, n_new_batches, resumed_from, seconds}`；進度每 10 秒寫 stderr |
  | `is_embed_done(ckpt_dir, ckpt_meta) -> bool` | 設定相同且涵蓋全部 pid（build.py 的跳過判斷；不修改檔案） |
  | `build_vectorstore(db_path, ckpt_dir, vectorstore_dir, embeddings) -> dict` | 組裝並存檔；回傳 `{ntotal, n_batches, seconds}` |
  | `open_vectorstore(vectorstore_dir, build_meta_path, cfg=None) -> FAISS` | 載入的實際邏輯（可指定任意路徑，供驗證使用） |
  | `load_vectorstore(fixtures: bool) -> FAISS` | 給 B：`open_vectorstore(paths(fixtures)["vectorstore_dir"], paths(fixtures)["build_meta"])` |
  | `EmbedMismatchError(RuntimeError)` | build_meta 的 embed 設定與 config 不同 |
- **embedding 階段**（函式放在 `rag/vectorstore.py`，由 `build.py` 呼叫；細節見 `plans/A3-embed-vectorstore.md`）：
  - 從 `DocStore.iter_passages` 依 pid 讀取，依 `batch_size` 切批 embed 所有 passage。
  - 每批一個 checkpoint：`embed_ckpt_dir/{start:07d}-{end:07d}.npy`（float32 `(end-start, dim)`，已 normalize，pid 範圍 `[start, end)`），先寫 `.tmp` 再 `os.replace`。
  - **中斷後可續跑**：只保留從 pid 0 起首尾相接、形狀正確的檔案，從涵蓋到的位置繼續。`ckpt_meta.json` 記錄 `embed_model`、前綴、`dim`、`passage_words`、`passage_stride`、`limit`、`n_passages`；與目前不同時清空 checkpoint 重來。`batch_size` 不在比對範圍內。（依 A3 修正）
- **組裝 vectorstore（逐批載入，不一次讀完；放在 `rag/vectorstore.py`，由 `build.py` 呼叫）**：
  1. 匯入（只在 `rag/vectorstore.py` 出現）：`from langchain_community.vectorstores import FAISS`，以及 `from langchain_community.vectorstores.utils import DistanceStrategy`。
     - **不可以**寫成 `from langchain_community.vectorstores import DistanceStrategy`。那會拿到 kinetica 的同名 enum（值為 `"inner"`），FAISS 比對不到，會在不報錯的情況下改建 `IndexFlatL2`。
  2. 只載入**第一個** checkpoint，呼叫 `vs = FAISS.from_embeddings(text_embeddings=[(text, vec), ...], embedding=PrefixedOllamaEmbeddings(...), metadatas=[{"pid": .., "docid": ..}, ...], ids=[str(pid), ...], distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT)`。
  3. 檢查 `isinstance(vs.index, faiss.IndexFlatIP)`（否則 `TypeError`）且 `vs.index.d == dim`（否則 `ValueError`）。text 與 docid 由 `DocStore.iter_passages(0)` 依 pid 對齊，pid 對不上就 raise。
  4. 其餘的 checkpoint 依序**逐一載入**，以 `vs.add_embeddings(text_embeddings, metadatas=..., ids=...)` 加入**同一個** vectorstore；每處理完一批就釋放那一批的資料。
  5. 全部加入後檢查 `vs.index.ntotal == n_passages`（否則 `ValueError`），`save_local` 到 `<vectorstore_dir>.tmp`，再換成正式目錄（**目錄存在 ⇔ 完整**；既有目錄會被取代）。
  - 檢查一律用明確 raise，不用 `assert` 敘述（`python -O` 會略過）。組裝開始前，checkpoint 必須完整涵蓋全部 pid，否則 `RuntimeError`。
  - 不要全部讀完後才一次呼叫 `from_embeddings`：12.3 萬 × 768 個 Python float 大約要 3 GB 記憶體；checkpoint 全量約 379 MB、約 1,926 檔，組裝時每次只讀一檔。
  - 向量已經由 `embed.py` normalize 過，**不要**傳 `normalize_L2=True`。在內積模式下它只會發出警告。
- **載入向量庫（`rag/vectorstore.py` 的 `load_vectorstore`，A 提供給 B 的 `semantic` 使用）**
  ```python
  def load_vectorstore(fixtures: bool) -> FAISS   # semantic 傳入 cfg["runtime"]["use_fixtures"]
  ```
  實際邏輯在 `open_vectorstore(vectorstore_dir, build_meta_path, cfg=None)`：
  1. `p = paths(fixtures)`；`meta = require_build_done(p["build_meta"])`，建置未完成就 raise `BuildNotDoneError`（1.3）。
  2. **模型一致性檢查**：`meta` 的 `embed_model`、`query_prefix`、`doc_prefix`、`dim` 任一項與 config 的 `[embed]` 不一致，就 raise `EmbedMismatchError`（定義在 `vectorstore.py`），訊息列出不一致的欄位並提示 `build --force`。不檢查就繼續的話，結果會錯亂但不會報錯。
  3. `FAISS.load_local(p["vectorstore_dir"], PrefixedOllamaEmbeddings(查詢模式), allow_dangerous_deserialization=True, distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT)`（`[VERIFY-12]`）。
     - `load_local` **不會**保存 `distance_strategy`，必須再傳一次；沒傳時查詢會以 L2 的方式解讀分數。
     - `DistanceStrategy` 必須從 `langchain_community.vectorstores.utils` 匯入（見上方組裝步驟 1 的匯入陷阱）。
     - 載入前若 `index.faiss` 或 `index.pkl` 不存在 → `FileNotFoundError`。
  4. 檢查 `isinstance(vs.index, faiss.IndexFlatIP)`（否則 `TypeError`），且 `vs.index.d == config 的 dim`（否則 `ValueError`）；回傳 `vs`。
  - A3 實測（`--limit 200`）：載入 29 ms；查詢（CPU embed + 搜尋）暖機約 22 ms，第一次約 2 秒（模型重新載入到 CPU）。
- **為什麼新增 `rag/vectorstore.py`，而不是放在 `embed.py`**：
  - `embed.py` 的單元測試（前綴，1.6-7）只需要 `langchain_core`；放在一起會讓測試必須匯入 `faiss` 與 `langchain_community`。
  - 組裝（建置端）與載入（查詢端）共用 `DistanceStrategy` 的匯入與 `IndexFlatIP` 的檢查，放在同一個模組，匯入陷阱只需要處理一次。
  - `embed.py` 維持「帶前綴的 Embeddings 類別」單一職責（1.6-4）。
  - checkpoint 的寫入（embedding 階段）與讀取（組裝）共用同一份格式定義，所以 embedding 階段也放在這裡。
（依 VERIFY-11、VERIFY-12 修正）（依討論修正）（依 A1–A3 同步）

### 2.6 詞彙檢索（`rag/lexical.py`）
- `LexicalRetriever(BaseRetriever)`，`_get_relevant_documents(query)`：
  1. `preprocess(query)` 得到 term 序列。**不經過 HW2 的 query parser**：parser 會把 `AND/OR/NOT`、引號、括號、`*`、`?` 當成語法處理，未配對的引號會讓它 raise ValueError。
  2. 呼叫 `Ranker.search(terms, k_each)` 取 top-`k_each` 篇（`[VERIFY-06]`）。
  3. 每篇從 `get_passages_by_doc` 挑最佳 passage：對每段 passage 執行 `preprocess`，以 query term 命中次數計分，同分取 pid 較小者。
     - 不使用索引中的位置資訊來定位 passage：位置是「保留停用詞空洞的 token 序號」，對不回清理後文字的字位置。
- 查詢沒有任何有效 term（例如全是停用詞）時回傳空清單，不報錯。
- **啟動時**：路徑取自 `paths(cfg["runtime"]["use_fixtures"])`，並先呼叫 `require_build_done(paths(...)["build_meta"])`；建置未完成就直接報錯，不載入索引（1.3）。
（依討論修正）

### 2.7 RRF 合併（`rag/fusion.py`）與統一介面（`rag/retrieve.py`）
- `HybridRetriever(BaseRetriever)`：
  1. 詞彙、語意兩路各取 `k_each` 篇（語意那一路已依 docid 去重）
  2. `score(d) = Σ 1 / (rrf_k + rank_i(d))`，rank 從 1 起算；只出現在一路的文件只算那一路
  3. 依 score 遞減排序，同分依 docid 遞增（與 HW2 破同分規則一致）
  4. passage 選擇：優先用語意那一路命中的 pid，沒有則用詞彙那一路的 pid
  5. `sources` 記錄來源
- 開發時先接假資料（兩路的假結果）寫好並通過單元測試，不等 semantic 完成。
- `retrieve()` 依 `mode` 分派到三個 retriever 之一，回傳前 k 筆並補上 `rank`
- **待決（A5）：RRF 同分問題**
  - 現象：A3 的 V4（`--limit 200`）中，語意檢索把兩個學號的正確文件排在 200 篇中的第 180、195 名，不會進入 `k_each = 20`；語意那一路的前幾名是拼字變體列表等雜訊頁。
  - 影響：學號查詢時，詞彙那一路只有埋入的 3 篇（第 1–3 名），語意那一路的第 1–3 名是無關文件，兩路同名次的 RRF 分數兩兩相同（例如 `1/(60+1)`）。依目前「同分依 docid 遞增」的規則，第 3 篇 gold 可能被擠出前 `k_final` 名，References 也會混入無關文件。
  - 候選解法：(a) 同分時優先排兩路都出現的文件，其次優先排詞彙那一路的文件；(b) 加權 RRF（例如詞彙 1.0、語意 0.8）；(c) 提高 `k_final`。
  - A5 實作 fusion 時，用全量資料查詢兩個學號與 fact 題，比較各解法後決定，並更新上方第 3 步與 1.6-7 的 `fusion` 測試項目。
（依 A1–A3 同步）

### 2.8 一鍵重建（`main.py build` → `rag/build.py`）
- 輸入：`injected_warc`（以 `tools/inject_warc.py` 產生，見 2.2）。不存在時報錯，提示先執行 `uv run python tools/inject_warc.py`。
- **輸出位置（目標資料夾）**：
  - 由 `rag.config.paths(fixtures=--limit 是否有給)` 決定；**build 不讀 `[runtime] use_fixtures`**（1.3）。
  - 沒有 `--limit`：`paths(False)` 的 `index_dir`、`docstore`、`vectorstore_dir`、`embed_ckpt_dir`、`build_meta`。
  - 有 `--limit N`：`paths(True)` 的同名路徑（`fixtures/index/`、`fixtures/store/docstore.sqlite`、`fixtures/store/vectorstore/`、`fixtures/store/embed_ckpt/`、`fixtures/store/build_meta.json`）。**不讀取也不覆寫**正式產物。
  - 理由：避免開發者忘了切換路徑時，`--force` 清掉全量產物（全量重建約 50–55 分鐘：索引實測約 9 分鐘、docstore 約 3.5 分鐘；embedding 依 A3 的 `--limit 200` 實測（50.5 段/秒）推估約 41 分鐘，全量建置後以實測數字更新）。
- 階段順序：寫入 build_meta（`status: "in_progress"`）→ `index`（含 doc_map）→ `norms` → `docstore`（含 passages）→ `embed` → `vectorstore` → build_meta 改為 `status: "done"`
- **開始時比對 build_meta**：只要目標資料夾的 `build_meta.json` 存在（不論 `status`），就比對其中的 `limit`、`inject_tokens`、embed 設定（`embed_model`、`query_prefix`、`doc_prefix`、`dim`）、切分參數（`passage_words`、`passage_stride`）與目前的 config / `--limit`；任一項不一致就報錯並停止，提示加 `--force` 重建。`status` 為 `"in_progress"` 時，在 stderr 提示上次建置未完成、這次會從中斷處繼續。
- **跳過規則**：比對通過後，每個階段的產物已存在就跳過：`docstore` 看 `db_path` 是否存在（原子寫入，2.4）；`embed` 看 `is_embed_done(...)`（2.5）；`vectorstore` 看 `vectorstore_dir` 是否存在（原子寫入）。
- `--force`：只清空**這次建置的目標資料夾**（上面列出的位置；不動 `dataset/`、`eval/`、`output/`，有 `--limit` 時也不動正式產物），再重建所有階段。
- 輸出資料夾由 `build.py` 在執行時建立（1.2）。
- embedding 階段可以中斷後續跑（見 2.5）。
- docid 連續性檢查（見 2.3，不成立 raise `ValueError`）每次建置都執行。
- `--limit N`：只處理語料前 N 篇，同時套用到索引、docstore、passage、embedding，與 HW1 的同名選項一致。N 必須 ≥ 1，否則報錯（2.1）。N 預設 200，可以調到 500 或 1000。
- **fixtures**：就是 `--limit N` 的建置結果，不進版控，需要時自行產生，用於手動測試與整合測試（單元測試不使用，見 1.6-7）。query / eval 要讀 fixtures 時，在 `config.local.toml` 設定 `[runtime] use_fixtures = true`（1.3）。
（依 A1 / 討論修正）（依 A1–A3 同步）

---

## 3. 查詢期：語意檢索、生成、CLI、評估、繳交文件（B）

### 3.1 LLM（`rag/llm.py`）
```python
def get_llm() -> BaseChatModel   # 回傳設定好的 ChatOllama
```
- `ChatOllama(model=..., temperature=0, num_ctx=8192, reasoning=not disable_thinking, validate_model_on_init=True)`（`[VERIFY-13]`）
  - `reasoning=False` 會關閉 Qwen3 的思考模式，送到 Ollama API 時轉成 `think: false`（已實測）。
  - 不可以省略這個參數：預設值 `None` 會讓 Qwen3 照常思考，`<think>` 會出現在回答中。
- 輸出若殘留 `<think>...</think>` 區塊，一律剝除（放在 chain 的輸出解析步驟）。
- 連不到 Ollama 或模型未 pull 時，`validate_model_on_init` 會丟出 `ValueError`，模型不存在時訊息已包含 `ollama pull <model>` 的提示。呼叫端要接住它，把訊息印到 stderr，然後以 exit 1 結束。
- 開發時可用 `config.local.toml` 換成開發用模型（1.1），但 prompt 的最終調整必須在 `qwen3:8b` 上做。
（依 VERIFY-13 修正）

### 3.2 Prompt 與 chain（`rag/prompt.py`）
```python
def build_rag_chain()    # 輸入 {"question": str, "docs": list[Document]} → 回答字串
def build_plain_chain()  # 輸入 {"question": str} → 回答字串（無 RAG baseline）
```
RAG system prompt：
```
You are a question-answering assistant. Answer ONLY using the documents provided.
If the documents do not contain the answer, reply "I don't know based on the given documents."
Cite the supporting documents using their bracketed IDs, e.g. [clueweb09-en0000-04-00001].
Keep the answer concise.
```
RAG user prompt：
```
Documents:
[<trec_id>] (<url>)
<passage>

[<trec_id>] (<url>)
<passage>
...

Question: <question>
```
- 無 RAG 版：system prompt 只保留第一句與最後一句；user prompt 只放問題
- 每段 passage 最多 `prompt_passage_max_words` 字，超過就截斷並加上 `...`
- 用 `ChatPromptTemplate` 組合：`prompt | llm | 輸出解析`

### 3.3 語意檢索（`rag/semantic.py`）
- `SemanticRetriever(BaseRetriever)`：
  1. **啟動時取得向量庫**：`vs = load_vectorstore(cfg["runtime"]["use_fixtures"])`（A 提供，見 2.5）。建置完成檢查、模型一致性檢查、`DistanceStrategy`、`IndexFlatIP` 都已在其中處理，`semantic` 不重複做，也不自行呼叫 `FAISS.load_local`、建立 `OllamaEmbeddings` 或匯入 `DistanceStrategy`。docstore 以 `DocStore(paths(...)["docstore"])` 唯讀開啟（2.4；`get_doc` 找不到時 raise `KeyError`）。查詢 embedding 在 CPU 執行（`num_gpu=0`，`[VERIFY-15]`），不和 LLM 搶 GPU。
  2. `vs.similarity_search_with_score(query, k=k_each * 3)`
     - 分數是內積，也就是 cosine，**越大越相似**，結果已經依遞減排序。
     - 原始碼 docstring 寫的「L2 distance, lower is better」不適用於這裡。
     - 分數型別是 `numpy.float32`，要轉成 `float()`。
  3. 同一 docid 只保留分數最好的 passage，取前 `k_each` 篇
  4. 以 docstore 的 `get_doc(docid)` 補上 `trec_id`、`url`，依 1.4 的 metadata 格式組成 `Document` 輸出
- B 的責任範圍：查詢、依 docid 去重、補 `trec_id` 與 `url`、組成 metadata；向量庫的載入細節屬於 A（2.5）。
（依 VERIFY-12 修正）（依討論修正）（依 A1–A3 同步）

### 3.4 CLI（`main.py query` → `rag/cli.py`）
```
uv run python src/main.py query "When was the premiere of The Magic Flute?" --mode hybrid --k 5
uv run python src/main.py query "114598xxx" --compare
uv run python src/main.py query --interactive        # 選做：prompt> 互動模式
```
- **必做**：
  - `--mode {none, lexical, semantic, hybrid}`，`none` = 無 RAG
  - `--compare`：同一題依序輸出「無 RAG」與「Hybrid RAG」的回答，中間以明顯分隔線區隔（截圖主要用這個）
- **選做**：
  - `--interactive`：互動模式
  - `--show-context`：印出送進 LLM 的完整 prompt
- 開發時先接 `fake_retrieve()`，不等 A 的 `retrieve()` 完成。
- 輸出格式（stdout）：
  ```
  === Answer (mode: hybrid) ===
  ...
  === References ===
  1. Document ID#: clueweb09-en0000-04-xxxxx | <url> | sources: lexical+semantic | score: 0.032787
     "...passage 前 30 字..."
  ```
- 檢索與生成的耗時寫到 stderr
- **建置完成檢查**：
  - `--mode none` 不需要建置產物，所以不呼叫 `require_build_done`。
  - `lexical`、`semantic`、`hybrid` 由對應的 retriever 在啟動時檢查（2.6、3.3）。
  - `--compare` 在**開始時**先呼叫 `require_build_done(paths(use_fixtures)["build_meta"])`，未完成就直接報錯並以 exit 1 結束，不輸出無 RAG 的回答。原因：避免先花時間產生無 RAG 回答，最後才因建置未完成而失敗。

### 3.5 評估（`main.py eval` → `rag/evaluate.py`）
- **生成對照（必做，截圖的來源）**：每一題跑 `none` 與 `hybrid`，把問題、兩個回答、引用文件寫到 `output/compare.md`
- **檢索評估（加分項，保留）**：對 testset 每一題跑 lexical / semantic / hybrid，計算 Hit@1、Hit@5、MRR（命中 `gold_docids` 任一篇即算），**分 fact / token 兩類**，fact 再分出 `paraphrase` 題，輸出 Markdown 表格到 `output/retrieval_eval.md`
- 預期現象（報告會用到）：token 題（純學號）lexical 強；**semantic 幾乎完全失效**（A3 V4：兩個學號的正確文件在 200 篇中排第 180、195 名，語意前幾名是雜訊頁），hybrid 能否穩定取回 3 篇取決於 2.7 的同分處理；paraphrase 題 semantic 較強；hybrid 在各類題目都應穩定。（依 A1–A3 同步）
- **啟動時**：路徑（含 `output_dir`）取自 `paths(cfg["runtime"]["use_fixtures"])`，因此 `use_fixtures = true` 時輸出到 `fixtures/output/`。這是刻意的設計：避免 fixtures 的 eval 結果覆蓋正式輸出。先呼叫 `require_build_done(paths(...)["build_meta"])`，建置未完成就直接報錯，不跑任何題目（1.3）。
（依討論修正）

### 3.6 截圖
- 從 `--compare` 的結果挑選：至少 3 題 fact 題，加上每位成員的 token 題各 1 題
- 每張截圖要看得到：問題、無 RAG 回答、有 RAG 回答、引用的 Document ID

### 3.7 README、說明文件與打包
- `HW3/README.md`（格式比照 HW1/HW2 README）：環境、`uv sync`（在 `HW3/` 下）、NLTK `stopwords` 下載步驟（見 1.1）、`ollama pull` 指令（兩個模型）、Ollama 最低版本、`04.warc` 放置位置、`04_injected.warc` 的產生方式（以 `config.toml` 的 `[[inject.tokens]]` 為準，可用 `tools/inject_warc.py` 從 `04.warc` 重新產生：在 `HW3/` 下執行 `uv run python tools/inject_warc.py`；不進版控、不隨繳交附上）、開發說明（1.5 的 `search.py` 檢查需要本機已有 `HW2/index`）、`build` / `query` / `eval` 用法、`config.local.toml` 的用途、系統特色、困難與解決方案
- 一頁說明文件（彙整 A 提供的段落）：
  - 主要特色：hybrid retrieval（RRF）、引用來源、無 RAG 對照模式、檢索評估表、可續跑的建置流程
  - 遇到的主要困難
  - 執行環境需求：Python 版本、uv、Ollama 版本、模型名稱與 tag
  - 組員名單與負責部分（依 1.7 列出）
- 打包：單一壓縮檔，內容是 `HW3/` 目錄。**HW3 是獨立專案（hwlib 已複製進來），不需要包含 HW1/HW2**。**繳交前確認檔名格式**。依大小決定是否附上 `HW3/index/`、`HW3/store/`（HW2 有附完整索引）；不附的話，README 要寫清楚重建指令與預估耗時
- 最後在乾淨的 clone 上照 README 從頭跑一次，確認可以重現（`04_injected.warc` 以 `tools/inject_warc.py` 從 `04.warc` 重新產生）
（依討論修正）

---

## 4. 共同工作
- 各寫 **5–8 題** fact 題，其中至少 2 題是換句話說（`"paraphrase": true`），加上自己的 token 題，填入 `testset.jsonl`
  - 答案必須確定在語料中。可以直接用現有的 HW2 索引找題目（token 尚未埋入不影響 fact 題）
- 整合後一起跑 `eval`，依結果調整 `passage_words`、`k_each`、`k_final`
- 說明文件中屬於自己的段落各自撰寫

---

## 5. 查證清單（VERIFY-01–15 已查證；結果見第 6 節）

| ID | 要確認的事項 | 查證位置 | 影響範圍 |
|---|---|---|---|
| VERIFY-01 | HW1 loader 的函式名稱、回傳內容；doc# 從 0 或 1 起算；文件順序是否固定為 WARC 內的順序 | `HW1/src/`（loader 模組） | 1.4、2.1、2.3 |
| VERIFY-02 | Cleaner 能否單獨呼叫取得清理後文字（不經過 tokenizer）；空文件如何處理 | `HW1/src/`（cleaner 模組） | 2.1、2.4 |
| VERIFY-03 | WARC record 切割的實作位置，能否重用來逐筆複製 record；是否有任何地方讀取 `Content-Length` | `HW1/src/`（loader 模組） | 2.2 |
| VERIFY-04 | 前處理的公開函式名稱；連字號、純數字、長度上限（MAX_LEN = 64）的處理方式；確認學號能完整保留 | `HW1/src/`（tokenizer / preprocessor） | 1.5、2.1、2.2 |
| VERIFY-05 | HW1 `build` 能否指定輸入 WARC 路徑與輸出目錄；若寫死，如何以參數或函式呼叫方式覆寫 | `HW1/src/main.py` | 2.3 |
| VERIFY-06 | HW2 自由文字 VSM 的函式介面：輸入是 term 序列還是 AST；如何只取 top-k；回傳格式（doc#、score） | `HW2/src/rank.py`、`search.py` | 2.1、2.6 |
| VERIFY-07 | HW2 載入索引時讀取哪些檔案；缺少 surface vocab / champion 檔時是否報錯；sha256 檢查在何時執行 | `HW2/src/`（索引載入、各 meta 檢查） | 2.3 |
| VERIFY-08 | `doc_map.json` 的結構（key 型別是字串還是整數、欄位名稱） | `HW2/index/doc_map.json` 及產生它的程式 | 1.4、2.4 |
| VERIFY-09 | `doc_map.json` 由哪支程式產生；`build_norms.py` 的輸入與輸出參數 | `HW1/src/`、`HW2/src/` | 2.3、2.4 |
| VERIFY-10 | HW1/HW2 的匯入方式（是否為 package、是否需要調整 `sys.path`、模組間是否有相對匯入衝突、兩者是否有同名模組） | `HW1/src/`、`HW2/src/`、根目錄 `pyproject.toml` | 1.1、2.1 |
| VERIFY-11 | embeddinggemma 的 query / document 前綴格式、預設維度、是否支援截短維度 | Ollama library 頁面、Google model card | 1.1、1.3、2.5 |
| VERIFY-12 | LangChain FAISS 目前版本的 API：`from_embeddings` 參數、內積距離設定（`distance_strategy`）、`load_local` 的反序列化參數、`similarity_search_with_score` 回傳的是距離還是相似度 | `langchain-community` 文件 / 原始碼 | 1.4、2.5、3.3 |
| VERIFY-13 | `ChatOllama` 關閉 Qwen3 思考模式的參數名稱 | `langchain-ollama` 文件 / 原始碼 | 3.1 |
| VERIFY-14 | Python 版本與既有依賴；新增 LangChain 相關套件是否與既有套件衝突 | 根目錄 `pyproject.toml`、`uv.lock` | 1.1 |
| VERIFY-15 | `langchain_ollama.OllamaEmbeddings` 是否支援 `num_gpu`；查詢模式（`num_gpu=0`）的 embedding 與 `qwen3:8b` 同時載入時，`ollama ps` 是否顯示 embedding 100% CPU、LLM 100% GPU | `langchain-ollama` 原始碼；本機 `ollama ps` | 2.5、3.3（依 A1 / 討論修正） |

---

## 6. 查證結果表

| ID | 結論 | 依據（檔案:行號 / 連結） | 查證者 / 日期 |
|---|---|---|---|
| VERIFY-01 | **入口**：`documents.iter_documents(path, stats=None) -> Iterator[Document]`，`Document(doc_num, trec_id, url, kind, text)`，是 frozen dataclass。<br>**docid 不是流水號**：`doc_num` = TREC-ID 尾碼整數（`clueweb09-en0000-04-00123` → 123），從 0 起算；缺少 TREC-ID 時直接 raise。<br>**順序**：固定是 WARC 內的順序。<br>**04.warc 實際情況**：0 篇被排除，所以 docid 剛好是連續的 0..34785，而且與 doc_map 的 key、TREC 尾碼一一相等（已實測）。換成其他 WARC 時可能出現空號。 | `HW1/src/warc.py:24,67-72,96-117`；`HW1/src/documents.py:18-24,86-90`；`HW1/logs/dataset_report.txt`；本機 scratch 實測（腳本不進版控）；A1 驗證 1 以 hw_bridge 重驗（`plans/.done.A1-hwlib-config-bridge.md`） | Claude Code / 2026-11-25 |
| VERIFY-02 | **可以單獨呼叫**：`extract.classify(content_type, body) -> (kind, reason)`，再呼叫 `extract.extract_text(body, kind) -> str`；也可以用 `documents.to_document(resp)` 一次完成。兩者都不經過 tokenizer。<br>**排除**：二進位、非 HTML/plain 類型或解析例外時回傳 None，不產出。<br>**空文件**：擷取後為空字串時仍會產出，`text == ""`；04.warc 只有 1 篇。 | `HW1/src/extract.py:42-50,84-93`；`HW1/src/documents.py:6,56-83`；`HW1/README.md:107` | Claude Code / 2026-11-25 |
| VERIFY-03 | **切割**：`warc.iter_records(path) -> Iterator[bytes]`，逐行讀取，遇到以 `b"WARC/0.18"` 開頭的行就切出一筆。依序串接後與原檔逐位元組相同（已用合成 WARC 實測）。<br>**Content-Length**：HW1 原始碼中沒有任何地方讀取它。 | `HW1/src/warc.py:13,31-59`；本機 scratch 實測（腳本不進版控）；A1 驗證 2 以全量 04.warc 重驗（`plans/.done.A1-hwlib-config-bridge.md`） | Claude Code / 2026-11-25 |
| VERIFY-04 | **公開介面**：`tokenizer.Preprocessor(casefold=True, stopword=False, stem=False, lemma=False)`，方法 `.process(text) -> list[tuple[int, str]]`（位置從 1 起算，保留停用詞空洞）；另有 `tokenize(text) -> list[str]`。<br>**stop+stem 實測**：`"The IR HW3 verification code 114598000 quokkazen is registered by team member Terry."` → `ir, hw3, verif, code, 114598000, quokkazen, regist, team, member, terri`。<br>**純數字**：保留，不 stem（只有 `isalpha()` 的 token 才 stem）；`1,234`、`3.14` 也會原樣保留。<br>**連字號**：`-` 會被切開（`114598000-quokkazen` → 兩個 term）。<br>**長度**：超過 `MAX_LEN = 64` 的 token 整個丟掉。<br>**結論**：學號可以完整保留。HW2 的 `tokenizer.py` 輸出與 HW1 完全相同。 | `HW1/src/tokenizer.py:12-13,36-58,84-106`；本機 scratch 實測（腳本不進版控）；A1 驗證 3 重驗（`plans/.done.A1-hwlib-config-bridge.md`） | Claude Code / 2026-11-25 |
| VERIFY-05 | **寫死，沒有參數可以覆寫**：<br>• 輸入由 `resolve_warc_input()` 掃描相對於 CWD 的 `HW1/dataset/*.warc`，必須剛好 1 個檔案。<br>• 輸出固定為 `HW1/output`。<br>**替代做法**：以函式呼叫重現 `run_build` 的核心邏輯，見 2.1 的 `build_lexical_index`。 | `HW1/src/main.py:52-80,83-159,446-456` | Claude Code / 2026-11-25 |
| VERIFY-06 | **函式**：`rank.rank(qtf: Counter[str], candidates: set[int] \| None, reader, scheme="ltc.ltc", champion_r=None) -> list[tuple[int, float]]`。<br>• 輸入是 term 的 Counter，**不是 AST**。`candidates=None` 就是自由文字。<br>• 沒有 top-k 參數，回傳所有 score > 0 的文件，依 `(-round(score, 6), doc_num)` 排序。<br>• 與 `search_query()` 的自由文字結果逐筆相同（實測 5 個查詢）。<br>• 未配對的 `"` 會讓 parser raise ValueError。 | `HW2/src/rank.py:33-120`；`HW2/src/search.py:23-61`；`HW2/src/parser.py:222-241,447-474`；`HW2/src/boolean.py:37-38`；本機 scratch 實測（腳本不進版控）；A1 驗證 5 重驗（`plans/.done.A1-hwlib-config-bridge.md`） | Claude Code / 2026-11-25 |
| VERIFY-07 | **`IndexReader` 全部是 lazy-load**：<br>• `lexicon.tsv` 在第一次查詢時讀（實測 0.56 秒）。<br>• `doc_norms.*` 在第一次 `get_norms` 時讀；此時核對 log_base、formula、scheme、N、count，以及 `lexicon.tsv`、`postings.bin`、`metadata.json` 的 size 與 sha256，另外檢查 bin 大小是否 = 8×N（實測 0.07 秒）。<br>**缺檔行為**：`champions.*` 只有在 `champion_r` 不是 None 時才讀；`surface_vocab.*` 只有在 parser 展開 wildcard/Soundex 或拼字建議時才讀。所以走 `rank(..., champion_r=None)` 時，缺少這兩類檔案不會報錯。 | `HW2/src/writer.py:357-366,399-423,481-552,668-701`；`HW2/src/parser.py:355-373`；`HW2/src/surface.py:167`；本機 scratch 實測（腳本不進版控）；A1 驗證 5 重驗（`plans/.done.A1-hwlib-config-bridge.md`） | Claude Code / 2026-11-25 |
| VERIFY-08 | **結構**：`{"<doc_num 字串>": {"trec_id": str, "doc_len": int, "url": str}}`。key 是**字串**，`IndexReader` 讀取時會轉成 int。<br>**範例**：`"0": {"trec_id": "clueweb09-en0000-04-00000", "doc_len": 369, "url": "http://0-men.lyricsfans.com/"}`。<br>**實測**：34,786 筆，key 是連續的 0..34785；檔案 5.3 MB，載入 0.04 秒。 | `HW1/src/writer.py:320-337`；`HW2/src/writer.py:413-423`；本機 scratch 實測（腳本不進版控）；A1 驗證 1 以 hw_bridge 重驗（`plans/.done.A1-hwlib-config-bridge.md`） | Claude Code / 2026-11-25 |
| VERIFY-09 | **doc_map.json**：由 `writer.IndexWriter.write_doc_map(indexer)` 產生（HW1 與 HW2 相同）。<br>**build_norms**：<br>• 函式：`build_norms.build_norms(index_dir, scheme="ltc") -> None`。<br>• 輸入：同一目錄的 `lexicon.tsv`、`postings.bin`、`metadata.json`。<br>• 輸出：`doc_norms.bin`（N 個 double，下標 = doc_num）與 `doc_norms.meta.json`；結果會 print 到 stdout。<br>• **限制**：doc_num 必須剛好是 0..N-1，否則會發生 IndexError。 | `HW1/src/writer.py:242-282,320-337`；`HW2/src/build_norms.py:21-66` | Claude Code / 2026-11-25 |
| VERIFY-10 | **結構**：兩者都不是 package，模組之間用扁平的絕對匯入，只能透過 `sys.path` 匯入。<br>**同名模組**有 8 個：5 個逐位元組相同；`tokenizer`、`writer`、`skip_builder` 不同，差異見 2.1 的表格。<br>**結論**：都不影響建置產物。已用合成 WARC 分別以兩邊建置，`lexicon.tsv`、`postings.bin`、`doc_map.json` 逐位元組相同。因此只採用 `HW2/src`。<br>**後續決定**：改為複製到 `HW3/src/hwlib/` 並把 import 改成相對匯入（見 1.1），不再操作 `sys.path`。所需模組 `warc`、`extract`、`documents`、`tokenizer`、`indexer`、`trie`、`writer`、`weighting`、`build_norms`、`rank` 彼此 import 封閉（`rank` 的 `from writer import IndexReader` 位於 `if TYPE_CHECKING:` 區塊內，不是函式內 import；也在清單內，已一併改成相對匯入）。<br>**A1 實測**：以 hwlib 全量重建的 `lexicon.tsv`、`postings.bin`、`doc_map.json` 與 `HW2/index` 逐位元組相同（需鎖定 charset-normalizer，見 VERIFY-14）。（依 A1 / 討論修正） | `diff HW1/src/{tokenizer,writer,skip_builder}.py HW2/src/…`；本機 scratch 實測（腳本不進版控）；`grep import HW2/src/*.py`；A1 驗證 4 以全量 04.warc 重驗（`plans/.done.A1-hwlib-config-bridge.md`） | Claude Code / 2026-11-25、2026-11-26 |
| VERIFY-11 | **query 前綴**：`task: search result \| query: `<br>**document 前綴**：`title: none \| text: `<br>**維度**：預設 768（本專案不截短）。<br>**輸入上限**：2048 tokens。<br>**Ollama**：頁面範例直接送原文；需要 **v0.11.10 以上**；`embeddinggemma:latest` 等於 `300m`（622 MB）。<br>**實測**：以 bench 工具實測（獨立分支 `feat/hw3-bench`），`OllamaEmbeddings` 加前綴取得向量，正常運作。（依 A1 / 討論修正） | https://ollama.com/library/embeddinggemma ；https://gemma.ai/models/embeddinggemma/model-card-v1/ ；https://huggingface.co/google/embeddinggemma-300m ；以 bench 工具實測（獨立分支 `feat/hw3-bench`） | Claude Code / 2026-11-25；實測 2026-11-26 |
| VERIFY-12 | 以 langchain-community **0.4.2** 的原始碼為準。<br>**建立**：`FAISS.from_embeddings(text_embeddings, embedding, metadatas=None, ids=None, **kwargs)`；傳入 `distance_strategy=MAX_INNER_PRODUCT` 時建 `IndexFlatIP`，其他值一律建 L2。<br>**匯入陷阱**：`DistanceStrategy` 必須從 `.vectorstores.utils` 匯入，從 `.vectorstores` 匯入會拿到 kinetica 的同名 enum。<br>**追加**：`add_embeddings(text_embeddings, metadatas, ids)`。<br>**載入**：`load_local(folder, embeddings, *, allow_dangerous_deserialization=False, **kwargs)`；不會保存 `distance_strategy`。<br>**分數**：IP 原始分數（`numpy.float32`），越大越相似，已依遞減排序。 | `langchain_community/vectorstores/faiss.py:203-235,365-453,985-1011,1091-1128,1147-1225`；`.../utils.py:12-20`；`.../__init__.py:381,391`；`.../kinetica.py:23-28`；https://pypi.org/project/langchain-community/0.4.2/ | Claude Code / 2026-11-25 |
| VERIFY-13 | **參數名稱**：`reasoning`，型別 `bool \| str \| None`。`False` 會關閉思考模式（送出 `think: false`）；`None` 會使用模型預設，Qwen3 會思考。<br>**驗證模型**：`validate_model_on_init=True` 在模型不存在或連線失敗時丟出 `ValueError`。<br>**實測**：以 bench 工具實測（獨立分支 `feat/hw3-bench`），`ChatOllama(reasoning=False)` 可關閉思考模式。預設的 `qwen3:4b` 是只能思考的版本，關不掉（見 1.1）。（依 A1 / 討論修正） | `langchain_ollama/chat_models.py:529-548,805,966-967`；`langchain_ollama/_utils.py:12-47`；https://pypi.org/project/langchain-ollama/1.2.0/ ；以 bench 工具實測（獨立分支 `feat/hw3-bench`） | Claude Code / 2026-11-25；實測 2026-11-26 |
| VERIFY-14 | **根目錄 pyproject**：`name="hw1"`，`requires-python=">=3.12"`。直接依賴有 beautifulsoup4、ftfy、langdetect、lxml、nltk、spacy；`tqdm`、`numpy` 只是間接依賴。<br>**衝突檢查**：以既有 lock 版本為約束條件做解析（不安裝），結果無衝突，解析出 langchain-core 1.7.2、langchain-community 0.4.2、langchain-ollama 1.2.0、ollama 0.6.3、faiss-cpu 1.16.0。<br>**後續決定**：HW3 改為獨立專案（`HW3/pyproject.toml`），沿用上述版本；hwlib 實際用到的是 beautifulsoup4、lxml、ftfy、nltk、spacy（不需要 langdetect）。<br>**A1 補充：間接依賴也會影響建置產物**。bs4 的 `UnicodeDammit` 會使用已安裝的 `charset-normalizer` 偵測編碼；HW3 自動解析出 3.5.3，全量建置時 29 篇文件解碼不同（vocab +241、tokens +451），索引與 HW2 不再逐位元組相同。同一份程式碼在 3.5.2（根目錄環境的版本）下 29 篇全部一致，因此 `HW3/pyproject.toml` 鎖定 `charset-normalizer==3.5.2`（理由也記在 `hwlib/README.md`）。其餘直接依賴一律以 `==` 鎖定。<br>測試用標準函式庫 `unittest`，不需要新增測試套件。（依 A1 / 討論修正） | `pyproject.toml`；`uv.lock`；本機 scratch 解析結果（不進版控）；`HW3/pyproject.toml`、`HW3/uv.lock`；`HW2/src/{extract,tokenizer}.py`；A1 驗證 4 | Claude Code / 2026-11-25、2026-11-26 |
| VERIFY-15 | **`num_gpu` 有效**。<br>**原始碼**：`OllamaEmbeddings` 有 `num_gpu` 欄位，經 `_default_params` 放進 `options` 送到 `/api/embed`（攔截 request body 確認；值為 None 的鍵也會送出，Ollama 忽略）。`truncate` 不會送出（使用 Ollama 預設 = true）。<br>**共存（`/api/ps`）**：查詢模式 embeddinggemma `size_vram = 0`（0% GPU），`ChatOllama(qwen3:8b, num_ctx=8192)` 100% GPU，兩者同時常駐。build 模式（GPU）載入後再以查詢模式呼叫，會重新載入到 CPU。qwen3:8b 第一次載入時 Ollama 會卸載 embedding 一次，下一次 embed 重新載入（約 1 秒），之後共存。<br>**耗時**（8 GB 級 GPU 上的參考值）：查詢 embedding CPU 約 20 ms（LLM 常駐時相同）、GPU 約 9 ms；冷啟動 0.8–1.9 秒。<br>**長輸入**：預設靜默截斷、保留開頭 2,048 tokens（向量與能完整放入的最長前綴 cosine ≥ 0.99999）；`truncate=false` 回 HTTP 400 且整批失敗；`num_ctx` 只能把上限降低，不能提高。全量 53 段（31 篇）超過 2,048 tokens，最短 2,399 字元。<br>（依 A3 修正） | `langchain_ollama/embeddings.py:224-226,276-291,316-330`；`ollama/_client.py:433-454`；`scratch/a3/v0_*`（腳本不進版控）；`plans/A3-embed-vectorstore.md` 第 4 節 | Claude Code / 2026-11-27 |
