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
| 語言 / 套件管理 | Python ≥ 3.12 + uv | **HW3 是獨立專案**：`HW3/pyproject.toml` + `HW3/uv.lock`，所有指令都在 `HW3/` 目錄下執行。依賴包含 hwlib 需要的 `beautifulsoup4`、`lxml`、`ftfy`、`nltk`、`spacy`，以及 LangChain 相關套件（版本見 `[VERIFY-14]`） |
| LLM 框架 | LangChain：`langchain-core`、`langchain-ollama`、`langchain-community` | 符合投影片建議。**RRF 合併自行實作**，不使用 `EnsembleRetriever`（它依 passage 內容去重，我們需要依 docid 合併） |
| LLM 執行 | Ollama ≥ v0.11.10 | embeddinggemma 的最低版本需求（`[VERIFY-11]`） |
| 生成模型 | `qwen3:8b`（預設，最終版本） | tag 寫死在 config，不用 `latest` |
| 開發用模型 | `qwen3:1.7b`，或 `qwen3:4b-q4_K_M` | 透過 `config.local.toml` 切換（見 1.3）。**不要用預設的 `qwen3:4b`**：它是只能思考的版本，思考模式關不掉。`1.7b` 會捏造文件中沒有的細節，**最終的 prompt 調整一定要在 `qwen3:8b` 上做** |
| Embedding 模型 | `embeddinggemma` | 備選 `qwen3-embedding:0.6b`。query 與 passage 必須用同一個模型與前綴（`[VERIFY-11]`） |
| 向量索引 | LangChain `FAISS` vectorstore（需安裝 `faiss-cpu` 套件） | 向量做 L2 normalize，使用內積（= cosine） |
| Doc store | SQLite（內建 `sqlite3`） | |
| WARC 讀取 / HTML 清理 / 前處理 / 索引 | **沿用 HW1/HW2 的實作，複製到 `HW3/src/hwlib/`**（見 2.1） | 不使用 `warcio`（HW1 已確認有 `Content-Length` 誤差問題），也不另外引入 HTML 清理套件。query、passage 評分、索引必須是同一套前處理（stop + stem） |
| 詞彙排序 | **沿用 HW2 的 VSM（`ltc.ltc`，log10）** | 走自由文字路徑，繞過 HW2 的 query parser（見 2.6） |
| 合併 | RRF，k = 60 | |
| 測試 | 標準函式庫 `unittest` | 不新增測試套件，慣例見 1.6 |

**LangChain 路線已實測通過**（`tools/bench.py`）：`OllamaEmbeddings` 搭配自行加上的前綴可正常取得向量；`ChatOllama(reasoning=False)` 可關閉 Qwen3 的思考模式。

**hwlib（HW1/HW2 程式碼的副本）**
- 從 `HW2/src` 複製到 `HW3/src/hwlib/`，取代原本「從 HW2/src 匯入」的做法。HW2/src 的 loader、cleaner、indexer 與 HW1 逐位元組相同；tokenizer、writer 是 HW1 的超集，建置產物已實測完全相同（`[VERIFY-10]`）。
- 複製的模組（彼此 import 封閉，不需要其他檔案）：`warc`、`extract`、`documents`、`tokenizer`、`indexer`、`trie`、`writer`、`weighting`、`build_norms`、`rank`，外加空的 `__init__.py`。
- **只修改 import 語句**：模組之間的扁平絕對匯入（`from warc import ...`）改成套件內的相對匯入（`from .warc import ...`），其他程式碼一律不動。
- `hwlib/README.md` 記錄：來源路徑與 commit hash、複製的檔案清單、每個檔案修改了哪幾行 import。
- 外部資料檔：`tokenizer` 使用 `spacy.blank("en")`，**不需要**下載 spaCy 模型；停用詞需要 NLTK 的 `stopwords` 資料。程式第一次執行時會自動下載，但 README 仍要寫下手動步驟：`uv run python -c "import nltk; nltk.download('stopwords')"`。

### 1.2 目錄結構

```
HW3/                         # 獨立 uv 專案，所有指令在此目錄執行
├── pyproject.toml
├── uv.lock
├── config.toml
├── config.local.toml        # 本機覆寫（不進版控，見 1.3）
├── src/
│   ├── main.py              # 統一入口：build / query / eval 子指令
│   ├── hwlib/               # HW1/HW2 程式碼副本（只改 import，見 1.1）(A)
│   │   └── README.md        # 來源 commit 與 import 修改紀錄
│   └── rag/                 # 每個模組旁邊放 <模組>.test.py（unittest，範圍見 1.6）
│       ├── config.py        # 讀 config.toml + config.local.toml    (A)
│       ├── hw_bridge.py     # 使用 hwlib 的唯一位置                 (A)
│       ├── inject.py        # 埋特殊 token                          (A)
│       ├── build.py         # 一鍵重建所有產物                      (A)
│       ├── embed.py         # 帶前綴的 Embeddings 類別（唯一入口）  (A)
│       ├── lexical.py       # LexicalRetriever                      (A)
│       ├── fusion.py        # RRF + HybridRetriever                 (A)
│       ├── retrieve.py      # 對外統一介面 retrieve()               (A)
│       ├── docstore.py      # SQLite 存取                           (B)
│       ├── passages.py      # 切 passage                            (B)
│       ├── semantic.py      # SemanticRetriever（查詢端）           (B)
│       ├── llm.py           # ChatOllama 建立                       (B)
│       ├── prompt.py        # Prompt 模板與 chain                   (B)
│       ├── cli.py           # query 子指令                          (B)
│       └── evaluate.py      # eval 子指令                           (B)
├── tools/
│   ├── bench.py             # 硬體試跑工具（embedding / LLM 速度）
│   └── bench_results/       # bench 輸出（不進版控）
├── fixtures/                # 小型樣本產物（前 N 篇，供開發與測試）
├── eval/
│   └── testset.jsonl        # 測試題（雙方共同撰寫）
├── dataset/                 # 04.warc、04_injected.warc（不進版控）
├── index/                   # 重建後的詞彙索引 + HW2 norms（不進版控）
├── store/                   # docstore.sqlite、vectorstore/、embed_ckpt/、build_meta.json（不進版控）
└── output/                  # eval 結果、對照輸出（單數，與 HW2 一致）
```

- `.gitignore` 要包含 `HW3/config.local.toml`、`HW3/tools/bench_results/`。

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

[inject]
baseline_lexicon = "../HW2/index/lexicon.tsv"   # 重建前的 stop+stem 索引，用來檢查 df = 0（見下方待決定事項）

# 每位成員一組；學號與句子由各成員提供，target_trec_ids 由 A 挑選
[[inject.tokens]]
student_id = "<學號>"
sentence = "The IR HW3 verification code <學號> is registered by team member <姓名>."
target_trec_ids = []   # 固定 3 篇，由 A 於實作時挑選後填入

[[inject.tokens]]
student_id = "<學號>"
sentence = "The IR HW3 verification code <學號> is registered by team member <姓名>."
target_trec_ids = []
```

- **`config.toml` 是埋入設定的唯一來源**：學號、句子與目標 TREC-ID 都只寫在 `[[inject.tokens]]`。本規格不列出具體的 TREC-ID，程式中也不得另外寫死。
- **本機覆寫 `config.local.toml`**（不進版控）：存在時，`rag/config.py` 以它逐鍵覆寫 `config.toml`（表格遞迴合併，其他值整個取代）。用途是讓開發者自行改用開發用模型（1.1）、調降 `k_final` 等。不得在覆寫檔中修改 `[embed]` 與 `[[inject.tokens]]`，否則產物會與他人不一致。
- 前綴字串要原樣保留，包括 `|` 兩側的空白和結尾的空白。`langchain-ollama` 會把文字原樣送出，所以前綴一律由 `embed.py` 加上。
- embeddinggemma 的輸入上限是 2048 tokens，300 字的 passage 在範圍內。
- **待決定**：HW3 是獨立專案，但 `baseline_lexicon` 仍指向 HW2 的索引。需要決定在乾淨 clone 上執行 inject 時，df = 0 檢查要從哪裡取得 baseline。

規模預估（用於檢查建置結果是否合理，非硬性數字）：平均每篇約 870 字，以 300/250 切分，約 **12 萬段 passage**。

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
- `docid`、`trec_id`、`url`、`text` 全部直接取自 `hw_bridge.iter_documents()`。寫入後 assert 文件數與 `doc_map.json` 的筆數一致（`[VERIFY-08]`）。

**`store/vectorstore/`**：LangChain `FAISS.save_local()` 的輸出（`index.faiss` + `index.pkl`）。每筆 Document 的 metadata：`{"pid": int, "docid": int}`。載入時需 `allow_dangerous_deserialization=True`（`[VERIFY-12]`）。

**`store/build_meta.json`**（只保留下列欄位）
```json
{
  "embed_model": "embeddinggemma",
  "query_prefix": "...", "doc_prefix": "...", "dim": 768,
  "limit": null,
  "inject_tokens": [ {"student_id": "...", "sentence": "...", "target_trec_ids": ["..."]} ]
}
```
- `limit` 為 null 代表全量建置，fixtures 則為 N（見 2.8）。
- `inject_tokens` 是建置時 config 的 `[[inject.tokens]]` 原樣內容。

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
- 設定來源：1.3 的 `[[inject.tokens]]`，每位成員一組。
- **擺放位置**：第 1 篇 docid < 200（落在 fixtures 內）；其餘 2 篇建議放在語料的中段與後段，但不強制。
- **驗證規則**（inject 執行前檢查，見 2.2；**任何一條不符合，就報錯並停止，不得自動替換目標**）：
  1. 每組的 `target_trec_ids` 恰好 3 篇。
  2. 每篇目標都存在於 `source_warc`，HTTP 回應的 Content-Type 為 `text/html`，而且清理後的文字不能是空的。
  3. `student_id` 在 baseline 索引（`[inject] baseline_lexicon`）中 df = 0：查 `preprocess(student_id)` 的結果，第 1 欄是 term，查不到才算 df = 0。學號是純數字，不會被 stem。
  4. assert 每組至少一篇 docid < 200（docid = TREC-ID 尾碼整數）。
- **驗收**：建置完成後用詞彙檢索查詢每個學號，命中的文件必須 = 埋入的文件。
- **選做**：把一則資訊拆成 3 部分，分別放進同一組的 3 篇文件，展示 LLM 綜合多篇文件回答的能力。
- **分工**：目標由 A 依上述規則挑選，填入 config；B 只提供自己的 `student_id` 與 `sentence`。
（依 VERIFY-04 修正）

### 1.6 共同實作規範（雙方都適用）

1. 不得單方面修改 1.3、1.4 的介面、資料格式、檔名；需要修改時，先更新本文件
2. 遇到 `[VERIFY-xx]`：以第 6 節的結論為準；新的待查事項查不到時，停下來回報，不要猜測
3. hwlib 的模組**只能透過 `rag/hw_bridge.py` 使用**；其他檔案不得 import `hwlib`
4. Embedding 一律使用 `rag/embed.py` 提供的類別；**禁止在其他地方自行建立 `OllamaEmbeddings` 或加前綴**
5. 所有參數從 config 讀取，程式中不寫死模型名稱、路徑或 k 值
6. 提示與進度訊息只寫到 `stderr`；回答與結果寫到 `stdout`（與 HW2 一致）。hwlib 函式 print 到 stdout 的輸出，由 `hw_bridge` 轉到 stderr（見 2.1）
7. 單元測試（`unittest`）**只寫以下四項**，使用 `fixtures/` 或測試內自建的小資料，不依賴全量產物：
   - `passages`（切分邊界、短文件、空文件）
   - `fusion`（RRF 分數、同分規則、passage 選擇、sources）
   - `inject`（驗證規則、插入位置、Content-Length 更新）
   - `embed` 前綴（query / doc 前綴正確加上，不重複加）
   - 檔名：放在被測模組旁邊，命名為 `<模組>.test.py`（例如 `rag/passages.py` → `rag/passages.test.py`），依照 AGENTS.md 的慣例。
   - 寫法：使用 `unittest.TestCase`，檔尾加上 `if __name__ == "__main__": unittest.main()`。
   - 匯入：直接執行測試檔時，`sys.path[0]` 是 `HW3/src/rag/`，所以檔頭要把 `HW3/src` 插入 `sys.path`，之後一律用 `from rag.xxx import ...` 匯入，不可以直接 `import xxx`，否則同一個模組會被載入兩份。這是唯一允許的 `sys.path` 操作。
   - 執行（在 `HW3/` 下）：`uv run python src/rag/passages.test.py`；全部執行用 `for f in src/rag/*.test.py; do uv run python "$f" || break; done`。
   - 不能用 `python -m unittest <路徑>` 或 `unittest discover -p "*.test.py"`：檔名中多了一個 `.`，無法當成模組名稱匯入（已實測，前者報錯，後者找到 0 個測試）。
   - **待處理**：AGENTS.md 寫的測試指令（`uv run python -m unittest HW1/src/*.test.py`）因上述原因無法執行，也沒有涵蓋 HW3 的獨立專案。實作時再一併修正 AGENTS.md。
8. 尚未完成的相依元件，先用介面相同的假實作（例如 `fake_retrieve()`），不得等待
9. 開發時可以使用小模型 `qwen3:1.7b`（在 `config.local.toml` 設定，見 1.3），最後調整時再換回 `qwen3:8b`

### 1.7 分工與交接順序

| A：建置與詞彙線 | B：查詢與生成 |
|---|---|
| `config`、`hw_bridge`、`hwlib`（1.1、2.1） | `docstore`、`passages`（2.4） |
| `inject`、重建索引（2.2、2.3） | `semantic`（查詢端，含模型一致性檢查，3.3） |
| `embed.py` 與 embedding、FAISS 建置（2.5） | LLM、prompt（3.1、3.2） |
| `lexical`（2.6） | CLI（3.4） |
| `fusion`、`retrieve`、`build.py`（2.7、2.8） | `evaluate`（3.5）、README 與打包（3.7） |

交接順序：
1. A 交出 `hw_bridge`（含 `hwlib`、`config`）
2. A 交出 `dataset/04_injected.warc`
3. B 交出 `docstore`、`passages` 和 `fixtures/`（**第一優先**）。fixtures 先包含索引、docstore、passages；vectorstore 等 A 的 `embed.py` 完成後再補上
4. 兩人並行開發：A 的 `fusion` 先接假資料寫好；B 的 CLI 先接 `fake_retrieve()`
5. A 完成全量建置（`index/`、`store/`）
6. 整合

---

## 2. 建置期：資料管線、索引、embedding 與詞彙檢索

本節除 2.4（B）外由 A 負責。建置期產物統一由 `main.py build` 產生。

### 2.1 hwlib 橋接（`rag/hw_bridge.py`）
對外只暴露下列函式（`[VERIFY-01]`–`[VERIFY-10]`）：
```python
def iter_documents(warc_path, limit: int | None = None) -> Iterator[tuple[int, str, str, str]]  # (docid, trec_id, url, cleaned_text)
def iter_raw_records(warc_path) -> Iterator[bytes]                    # 2.2 逐筆複製用
def preprocess(text: str) -> list[str]                               # stop+stem 前處理，回傳 term 序列
def build_lexical_index(warc_path, index_dir, limit: int | None = None) -> dict   # 2.3，回傳 N、vocab_size 等統計
def build_doc_norms(index_dir) -> None                               # 2.3，ltc norms
def load_ranker(index_dir) -> Ranker                                  # HW2 VSM 排序器
```
- 2.2 的 inject 驗證另需讀取每筆 record 的 TREC-ID 與 HTTP Content-Type，對應函式由 A 在實作時補進此清單。

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

### 2.2 埋特殊 token（`rag/inject.py`）
- 輸入：config 的 `[[inject.tokens]]`。目標由 A 依 1.5 的規則挑選並填入 config；B 只提供自己的 `student_id` 與 `sentence`。
- **inject 開始前先執行驗證**：
  - 檢查 1.5 的四條驗證規則。任何一條不符合，就在 stderr 列出**所有**違規項目，然後 exit 1；不寫出任何檔案，也不自動替換目標。
  - 驗證要讀 `source_warc` 一次：只需要每筆 record 的 TREC-ID 與 HTTP Content-Type，並且只對目標文件執行清理。
- 驗證通過後，用 `hw_bridge.iter_raw_records()` 讀 `source_warc`（依 `b"WARC/0.18"` 邊界切割，`[VERIFY-03]`），逐筆寫到 `injected_warc`。非目標的 record 以原始 bytes 直接寫出，不重新組裝。
  - 先寫到暫存檔，完成後再以 `os.replace` 換成正式檔名，避免中斷時留下不完整的檔案。
- 遇到目標 TREC-ID（WARC 標頭的 `warc-trec-id`）時，在 HTML 的 `</body>` 前插入 `<p>{句子}</p>`；找不到 `</body>` 就加在 payload 尾端。
- 更新被修改 record 的 WARC 標頭 `Content-Length`；若 HTTP 標頭也有 `Content-Length`，一併更新。hwlib 不讀這個欄位，更新只是為了格式正確。
- 為什麼只選 `text/html`（1.5 規則 2）：`text/plain` 文件沒有 `</body>`，插入的 `<p>` 會留在清理後的文字裡。
- **同步 gold_docids**：
  - inject 完成後，把每組被埋入的 docid（TREC-ID 尾碼整數，依遞增排序）寫進 `eval/testset.jsonl` 中 `type == "token"` 且 `query == student_id` 的題目的 `gold_docids`。其他行原樣保留。
  - 找不到對應的題目時，新增一行 `{"id": "t-<student_id>", "type": "token", "query": "<student_id>", "gold_docids": [...], "answer": "<sentence>", "paraphrase": false}`。
- 驗收：
  1. 新 WARC 用 `hw_bridge.iter_documents` 讀取，文件數仍為 34,786，而且所有非目標文件的清理後文字與原檔完全相同。
  2. 目標文件的清理後文字包含該句子。
  3. `preprocess(句子)` 的結果包含學號這個 term。
  4. `testset.jsonl` 中每個學號的 `gold_docids`，與 config 的 `target_trec_ids` 換算出的 docid 相同。
（依 VERIFY-01、VERIFY-03 修正）

### 2.3 重建詞彙索引（`rag/build.py` 的第一階段）
- 以 `injected_warc` 為輸入，依序呼叫 `hw_bridge.build_lexical_index(injected_warc, index_dir, limit)` 與 `hw_bridge.build_doc_norms(index_dir)`（`[VERIFY-05][VERIFY-09]`）。
  - 產物：`lexicon.tsv`、`postings.bin`、`doc_map.json`、`metadata.json`、`doc_norms.bin`、`doc_norms.meta.json`。
- 不需要 surface vocab 與 champion list。走 `rank()` 的路徑時不會讀這兩類檔案，缺檔也不會報錯（`[VERIFY-07]`）。
- **docid 連續性檢查**（寫完索引後立刻執行，不成立就 raise）：
  - `doc_map.json` 的 key 集合必須恰好是 `{"0", ..., str(N-1)}`，而且 `metadata.json` 的 `N == len(doc_map)`。
  - 原因：docid 實際上是 TREC-ID 尾碼，不是流水號。HW2 的 norms 是以 docid 為下標、長度為 N 的陣列，docid 有空號或沒從 0 開始時會出錯，或靜默讀錯資料。
- 驗收：見 1.5（查詢學號，命中的文件 = 埋入的文件）。
- 耗時參考：全量建置約 6–7 分鐘、峰值記憶體約 1.1 GB；norms 約 15 秒。
（依 VERIFY-01、05、07、09 修正）

### 2.4 Doc store 與 passage（`rag/docstore.py`、`rag/passages.py`）（B）
- `docs` 表：`docid`、`trec_id`、`url`、`text` 直接取自 `hw_bridge.iter_documents()`；寫入後 assert 文件數與 `doc_map.json` 的筆數一致。
- `passages` 表：清理後文字以空白切字，每段 `passage_words` 字、步長 `passage_stride`；少於 30 字的文件整篇當一段，空文件跳過。
- 存取函式：`get_doc(docid)`、`get_passage(pid)`、`get_passages_by_doc(docid)`。
- 由 `build.py` 的 `docstore` 階段呼叫（A 負責串接）。
- **盡早產出 `fixtures/`**（交接順序第 3 步，第一優先）：
  - 內容：用 `main.py build --limit N` 產出語料**前 N 篇**的產物（N 預設 200，見 2.8）。
  - 只能取前 N 篇，不能挑任意子集，因為 2.3 的連續性檢查會擋下。
  - 依 1.5 的規則，每個學號至少有一篇在 fixtures 中。測試 fixtures 時，`gold_docids` 要先過濾成 docid < N 的那幾篇。
（依 VERIFY-01、VERIFY-09 修正）

### 2.5 Embedding（`rag/embed.py` + `build.py` 第二階段）
- `embed.py` 定義 `PrefixedOllamaEmbeddings(langchain_core.embeddings.Embeddings)`：
  - `embed_query(text)`：加 `query_prefix`
  - `embed_documents(texts)`：加 `doc_prefix`
  - 內部使用 `langchain_ollama.OllamaEmbeddings(model=..., dimensions=None)`，輸出做 L2 normalize
  - `OllamaEmbeddings.embed_documents` 會把整個 list 放在一個請求裡送出，不會自動分批
- **兩種模式**（建構時指定）：
  - 建置時：預設使用 GPU。
  - 查詢時：`num_gpu=0`，embedding 改用 CPU，避免和 LLM 搶 VRAM（已實測兩者同時載入 GPU 會讓速度慢約 20 倍）。
- B 的 `semantic` 只能透過 `embed.py`（查詢模式）轉換 query。
- **embedding 階段**：
  - 由 `build.py` 依 `batch_size` 切批 embed 所有 passage。
  - 每批結果存成 checkpoint（`embed_ckpt_dir/*.npy`，內容是向量，以及該批的 pid 範圍）。
  - **中斷後可從最後一批續跑**。checkpoint 目錄另存一份 `embed_model`、前綴、`dim`；與目前 config 不同時清空 checkpoint 重來。
- **組裝 vectorstore（逐批載入，不一次讀完）**：
  1. 匯入：`from langchain_community.vectorstores import FAISS`，以及 `from langchain_community.vectorstores.utils import DistanceStrategy`。
     - **不可以**寫成 `from langchain_community.vectorstores import DistanceStrategy`。那會拿到 kinetica 的同名 enum（值為 `"inner"`），FAISS 比對不到，會在不報錯的情況下改建 `IndexFlatL2`。
  2. 只載入**第一個** checkpoint，呼叫 `vs = FAISS.from_embeddings(text_embeddings=[(text, vec), ...], embedding=PrefixedOllamaEmbeddings(...), metadatas=[{"pid": .., "docid": ..}, ...], ids=[str(pid), ...], distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT)`。
  3. assert `isinstance(vs.index, faiss.IndexFlatIP)`。
  4. 其餘的 checkpoint 依序**逐一載入**，以 `vs.add_embeddings(text_embeddings, metadatas=..., ids=...)` 加入**同一個** vectorstore；每處理完一批就釋放那一批的資料。
  5. 全部加入後 assert `vs.index.ntotal == n_passages`，再呼叫 `vs.save_local(vectorstore_dir)`。
  - 不要全部讀完後才一次呼叫 `from_embeddings`：12 萬 × 768 個 Python float 大約要 3 GB 記憶體。
  - 向量已經由 `embed.py` normalize 過，**不要**傳 `normalize_L2=True`。在內積模式下它只會發出警告。
（依 VERIFY-11、VERIFY-12 修正）

### 2.6 詞彙檢索（`rag/lexical.py`）
- `LexicalRetriever(BaseRetriever)`，`_get_relevant_documents(query)`：
  1. `preprocess(query)` 得到 term 序列。**不經過 HW2 的 query parser**：parser 會把 `AND/OR/NOT`、引號、括號、`*`、`?` 當成語法處理，未配對的引號會讓它 raise ValueError。
  2. 呼叫 `Ranker.search(terms, k_each)` 取 top-`k_each` 篇（`[VERIFY-06]`）。
  3. 每篇從 `get_passages_by_doc` 挑最佳 passage：對每段 passage 執行 `preprocess`，以 query term 命中次數計分，同分取 pid 較小者。
     - 不使用索引中的位置資訊來定位 passage：位置是「保留停用詞空洞的 token 序號」，對不回清理後文字的字位置。
- 查詢沒有任何有效 term（例如全是停用詞）時回傳空清單，不報錯。

### 2.7 RRF 合併（`rag/fusion.py`）與統一介面（`rag/retrieve.py`）
- `HybridRetriever(BaseRetriever)`：
  1. 詞彙、語意兩路各取 `k_each` 篇（語意那一路已依 docid 去重）
  2. `score(d) = Σ 1 / (rrf_k + rank_i(d))`，rank 從 1 起算；只出現在一路的文件只算那一路
  3. 依 score 遞減排序，同分依 docid 遞增（與 HW2 破同分規則一致）
  4. passage 選擇：優先用語意那一路命中的 pid，沒有則用詞彙那一路的 pid
  5. `sources` 記錄來源
- 開發時先接假資料（兩路的假結果）寫好並通過單元測試，不等 semantic 完成。
- `retrieve()` 依 `mode` 分派到三個 retriever 之一，回傳前 k 筆並補上 `rank`

### 2.8 一鍵重建（`main.py build` → `rag/build.py`）
- 階段順序：`inject` → `index`（含 doc_map）→ `norms` → `docstore`（含 passages）→ `embed` → `vectorstore` → 寫出 build_meta
- **跳過規則**：每個階段的產物已存在就跳過。改了 config 或 `--limit` 之後，要加 `--force` 全部重建。
- `--force`：忽略既有產物，所有階段全部重建（embedding checkpoint 一併清空）。
- embedding 階段可以中斷後續跑（見 2.5）。
- docid 連續性 assert（見 2.3）每次建置都執行。
- `--limit N`：只處理語料前 N 篇，同時套用到索引、docstore、passage、embedding，與 HW1 的同名選項一致。fixtures 就是前 N 篇的建置結果，輸出到 `fixtures_dir`；N 預設 200，可以調到 500 或 1000。

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
  1. **模型一致性檢查**：啟動時讀 `build_meta.json`；若 `embed_model`、`query_prefix`、`doc_prefix`、`dim` 任一項與 config 不一致，**直接 raise 錯誤並停止**（否則結果會錯亂但不會報錯）
  2. 載入：`FAISS.load_local(vectorstore_dir, PrefixedOllamaEmbeddings(查詢模式), allow_dangerous_deserialization=True, distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT)`（`[VERIFY-12]`）
     - query 只能透過 `embed.py` 轉換（見 2.5），不得自行建立 `OllamaEmbeddings`。
     - `load_local` **不會**保存 `distance_strategy`，必須再傳一次。`DistanceStrategy` 的匯入方式見 2.5。
     - 載入後 assert `isinstance(vs.index, faiss.IndexFlatIP)`。
  3. `similarity_search_with_score(query, k=k_each * 3)`
     - 分數是內積，也就是 cosine，**越大越相似**，結果已經依遞減排序。
     - 原始碼 docstring 寫的「L2 distance, lower is better」不適用於這裡。
     - 分數型別是 `numpy.float32`，要轉成 `float()`。
  4. 同一 docid 只保留分數最好的 passage，取前 `k_each` 篇
  5. 從 docstore 補上 `trec_id`、`url`，依 1.4 的 metadata 格式輸出
（依 VERIFY-12 修正）

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

### 3.5 評估（`main.py eval` → `rag/evaluate.py`）
- **生成對照（必做，截圖的來源）**：每一題跑 `none` 與 `hybrid`，把問題、兩個回答、引用文件寫到 `output/compare.md`
- **檢索評估（加分項，保留）**：對 testset 每一題跑 lexical / semantic / hybrid，計算 Hit@1、Hit@5、MRR（命中 `gold_docids` 任一篇即算），**分 fact / token 兩類**，fact 再分出 `paraphrase` 題，輸出 Markdown 表格到 `output/retrieval_eval.md`
- 預期現象（報告會用到）：token 題（純學號）lexical 強、semantic 弱；paraphrase 題 semantic 較強；hybrid 在各類題目都穩定

### 3.6 截圖
- 從 `--compare` 的結果挑選：至少 3 題 fact 題，加上每位成員的 token 題各 1 題
- 每張截圖要看得到：問題、無 RAG 回答、有 RAG 回答、引用的 Document ID

### 3.7 README、說明文件與打包
- `HW3/README.md`（格式比照 HW1/HW2 README）：環境、`uv sync`（在 `HW3/` 下）、NLTK `stopwords` 下載步驟（見 1.1）、`ollama pull` 指令（兩個模型）、Ollama 最低版本、`04.warc` 放置位置、`build` / `query` / `eval` 用法、`config.local.toml` 的用途、系統特色、困難與解決方案
- 一頁說明文件（彙整 A 提供的段落）：
  - 主要特色：hybrid retrieval（RRF）、引用來源、無 RAG 對照模式、檢索評估表、可續跑的建置流程
  - 遇到的主要困難
  - 執行環境需求：Python 版本、uv、Ollama 版本、模型名稱與 tag
  - 組員名單與負責部分（依 1.7 列出）
- 打包：單一壓縮檔，內容是 `HW3/` 目錄。**HW3 是獨立專案（hwlib 已複製進來），不需要包含 HW1/HW2**。**繳交前確認檔名格式**。依大小決定是否附上 `HW3/index/`、`HW3/store/`（HW2 有附完整索引）；不附的話，README 要寫清楚重建指令與預估耗時
- 最後在乾淨的 clone 上照 README 從頭跑一次，確認可以重現

---

## 4. 共同工作
- 各寫 **5–8 題** fact 題，其中至少 2 題是換句話說（`"paraphrase": true`），加上自己的 token 題，填入 `testset.jsonl`
  - 答案必須確定在語料中。可以直接用現有的 HW2 索引找題目（token 尚未埋入不影響 fact 題）
- 整合後一起跑 `eval`，依結果調整 `passage_words`、`k_each`、`k_final`
- 說明文件中屬於自己的段落各自撰寫

---

## 5. 查證清單（已全部查證，結果見第 6 節）

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

---

## 6. 查證結果表

| ID | 結論 | 依據（檔案:行號 / 連結） | 查證者 / 日期 |
|---|---|---|---|
| VERIFY-01 | **入口**：`documents.iter_documents(path, stats=None) -> Iterator[Document]`，`Document(doc_num, trec_id, url, kind, text)`，是 frozen dataclass。<br>**docid 不是流水號**：`doc_num` = TREC-ID 尾碼整數（`clueweb09-en0000-04-00123` → 123），從 0 起算；缺少 TREC-ID 時直接 raise。<br>**順序**：固定是 WARC 內的順序。<br>**04.warc 實際情況**：0 篇被排除，所以 docid 剛好是連續的 0..34785，而且與 doc_map 的 key、TREC 尾碼一一相等（已實測）。換成其他 WARC 時可能出現空號。 | `HW1/src/warc.py:24,67-72,96-117`；`HW1/src/documents.py:18-24,86-90`；`HW1/logs/dataset_report.txt`；實測 `HW3/scratch/v01_doc_map.py` | Claude Code / 2026-11-25 |
| VERIFY-02 | **可以單獨呼叫**：`extract.classify(content_type, body) -> (kind, reason)`，再呼叫 `extract.extract_text(body, kind) -> str`；也可以用 `documents.to_document(resp)` 一次完成。兩者都不經過 tokenizer。<br>**排除**：二進位、非 HTML/plain 類型或解析例外時回傳 None，不產出。<br>**空文件**：擷取後為空字串時仍會產出，`text == ""`；04.warc 只有 1 篇。 | `HW1/src/extract.py:42-50,84-93`；`HW1/src/documents.py:6,56-83`；`HW1/README.md:107` | Claude Code / 2026-11-25 |
| VERIFY-03 | **切割**：`warc.iter_records(path) -> Iterator[bytes]`，逐行讀取，遇到以 `b"WARC/0.18"` 開頭的行就切出一筆。依序串接後與原檔逐位元組相同（已用合成 WARC 實測）。<br>**Content-Length**：HW1 原始碼中沒有任何地方讀取它。 | `HW1/src/warc.py:13,31-59`；實測 `HW3/scratch/v03_records_roundtrip.py` | Claude Code / 2026-11-25 |
| VERIFY-04 | **公開介面**：`tokenizer.Preprocessor(casefold=True, stopword=False, stem=False, lemma=False)`，方法 `.process(text) -> list[tuple[int, str]]`（位置從 1 起算，保留停用詞空洞）；另有 `tokenize(text) -> list[str]`。<br>**stop+stem 實測**：`"The IR HW3 verification code 114598000 quokkazen is registered by team member Terry."` → `ir, hw3, verif, code, 114598000, quokkazen, regist, team, member, terri`。<br>**純數字**：保留，不 stem（只有 `isalpha()` 的 token 才 stem）；`1,234`、`3.14` 也會原樣保留。<br>**連字號**：`-` 會被切開（`114598000-quokkazen` → 兩個 term）。<br>**長度**：超過 `MAX_LEN = 64` 的 token 整個丟掉。<br>**結論**：學號可以完整保留。HW2 的 `tokenizer.py` 輸出與 HW1 完全相同。 | `HW1/src/tokenizer.py:12-13,36-58,84-106`；實測 `HW3/scratch/v04_preprocess.py`（`v04_hw1.out`、`v04_hw2.out`） | Claude Code / 2026-11-25 |
| VERIFY-05 | **寫死，沒有參數可以覆寫**：<br>• 輸入由 `resolve_warc_input()` 掃描相對於 CWD 的 `HW1/dataset/*.warc`，必須剛好 1 個檔案。<br>• 輸出固定為 `HW1/output`。<br>**替代做法**：以函式呼叫重現 `run_build` 的核心邏輯，見 2.1 的 `build_lexical_index`。 | `HW1/src/main.py:52-80,83-159,446-456` | Claude Code / 2026-11-25 |
| VERIFY-06 | **函式**：`rank.rank(qtf: Counter[str], candidates: set[int] \| None, reader, scheme="ltc.ltc", champion_r=None) -> list[tuple[int, float]]`。<br>• 輸入是 term 的 Counter，**不是 AST**。`candidates=None` 就是自由文字。<br>• 沒有 top-k 參數，回傳所有 score > 0 的文件，依 `(-round(score, 6), doc_num)` 排序。<br>• 與 `search_query()` 的自由文字結果逐筆相同（實測 5 個查詢）。<br>• 未配對的 `"` 會讓 parser raise ValueError。 | `HW2/src/rank.py:33-120`；`HW2/src/search.py:23-61`；`HW2/src/parser.py:222-241,447-474`；`HW2/src/boolean.py:37-38`；實測 `HW3/scratch/v06_rank_equiv.py` | Claude Code / 2026-11-25 |
| VERIFY-07 | **`IndexReader` 全部是 lazy-load**：<br>• `lexicon.tsv` 在第一次查詢時讀（實測 0.56 秒）。<br>• `doc_norms.*` 在第一次 `get_norms` 時讀；此時核對 log_base、formula、scheme、N、count，以及 `lexicon.tsv`、`postings.bin`、`metadata.json` 的 size 與 sha256，另外檢查 bin 大小是否 = 8×N（實測 0.07 秒）。<br>**缺檔行為**：`champions.*` 只有在 `champion_r` 不是 None 時才讀；`surface_vocab.*` 只有在 parser 展開 wildcard/Soundex 或拼字建議時才讀。所以走 `rank(..., champion_r=None)` 時，缺少這兩類檔案不會報錯。 | `HW2/src/writer.py:357-366,399-423,481-552,668-701`；`HW2/src/parser.py:355-373`；`HW2/src/surface.py:167`；實測 `HW3/scratch/v06_rank_equiv.py` | Claude Code / 2026-11-25 |
| VERIFY-08 | **結構**：`{"<doc_num 字串>": {"trec_id": str, "doc_len": int, "url": str}}`。key 是**字串**，`IndexReader` 讀取時會轉成 int。<br>**範例**：`"0": {"trec_id": "clueweb09-en0000-04-00000", "doc_len": 369, "url": "http://0-men.lyricsfans.com/"}`。<br>**實測**：34,786 筆，key 是連續的 0..34785；檔案 5.3 MB，載入 0.04 秒。 | `HW1/src/writer.py:320-337`；`HW2/src/writer.py:413-423`；實測 `HW3/scratch/v01_doc_map.py` | Claude Code / 2026-11-25 |
| VERIFY-09 | **doc_map.json**：由 `writer.IndexWriter.write_doc_map(indexer)` 產生（HW1 與 HW2 相同）。<br>**build_norms**：<br>• 函式：`build_norms.build_norms(index_dir, scheme="ltc") -> None`。<br>• 輸入：同一目錄的 `lexicon.tsv`、`postings.bin`、`metadata.json`。<br>• 輸出：`doc_norms.bin`（N 個 double，下標 = doc_num）與 `doc_norms.meta.json`；結果會 print 到 stdout。<br>• **限制**：doc_num 必須剛好是 0..N-1，否則會發生 IndexError。 | `HW1/src/writer.py:242-282,320-337`；`HW2/src/build_norms.py:21-66` | Claude Code / 2026-11-25 |
| VERIFY-10 | **結構**：兩者都不是 package，模組之間用扁平的絕對匯入，只能透過 `sys.path` 匯入。<br>**同名模組**有 8 個：5 個逐位元組相同；`tokenizer`、`writer`、`skip_builder` 不同，差異見 2.1 的表格。<br>**結論**：都不影響建置產物。已用合成 WARC 分別以兩邊建置，`lexicon.tsv`、`postings.bin`、`doc_map.json` 逐位元組相同。因此只採用 `HW2/src`。<br>**後續決定**：改為複製到 `HW3/src/hwlib/` 並把 import 改成相對匯入（見 1.1），不再操作 `sys.path`。所需模組 `warc`、`extract`、`documents`、`tokenizer`、`indexer`、`trie`、`writer`、`weighting`、`build_norms`、`rank` 彼此 import 封閉（唯一的函式內 import 是 `rank` 的 `from writer import IndexReader`，也在清單內）。 | `diff HW1/src/{tokenizer,writer,skip_builder}.py HW2/src/…`；實測 `HW3/scratch/v02b_build_equiv.py`、`v02b_make_warc.py`；`grep import HW2/src/*.py` | Claude Code / 2026-11-25、2026-11-26 |
| VERIFY-11 | **query 前綴**：`task: search result \| query: `<br>**document 前綴**：`title: none \| text: `<br>**維度**：預設 768（本專案不截短）。<br>**輸入上限**：2048 tokens。<br>**Ollama**：頁面範例直接送原文；需要 **v0.11.10 以上**；`embeddinggemma:latest` 等於 `300m`（622 MB）。<br>**實測**：`tools/bench.py` 以 `OllamaEmbeddings` 加前綴取得向量，正常運作。 | https://ollama.com/library/embeddinggemma ；https://gemma.ai/models/embeddinggemma/model-card-v1/ ；https://huggingface.co/google/embeddinggemma-300m ；`HW3/tools/bench.py` | Claude Code / 2026-11-25；實測 2026-11-26 |
| VERIFY-12 | 以 langchain-community **0.4.2** 的原始碼為準。<br>**建立**：`FAISS.from_embeddings(text_embeddings, embedding, metadatas=None, ids=None, **kwargs)`；傳入 `distance_strategy=MAX_INNER_PRODUCT` 時建 `IndexFlatIP`，其他值一律建 L2。<br>**匯入陷阱**：`DistanceStrategy` 必須從 `.vectorstores.utils` 匯入，從 `.vectorstores` 匯入會拿到 kinetica 的同名 enum。<br>**追加**：`add_embeddings(text_embeddings, metadatas, ids)`。<br>**載入**：`load_local(folder, embeddings, *, allow_dangerous_deserialization=False, **kwargs)`；不會保存 `distance_strategy`。<br>**分數**：IP 原始分數（`numpy.float32`），越大越相似，已依遞減排序。 | `langchain_community/vectorstores/faiss.py:203-235,365-453,985-1011,1091-1128,1147-1225`；`.../utils.py:12-20`；`.../__init__.py:381,391`；`.../kinetica.py:23-28`；https://pypi.org/project/langchain-community/0.4.2/ | Claude Code / 2026-11-25 |
| VERIFY-13 | **參數名稱**：`reasoning`，型別 `bool \| str \| None`。`False` 會關閉思考模式（送出 `think: false`）；`None` 會使用模型預設，Qwen3 會思考。<br>**驗證模型**：`validate_model_on_init=True` 在模型不存在或連線失敗時丟出 `ValueError`。<br>**實測**：`tools/bench.py` 以 `ChatOllama(reasoning=False)` 確認可關閉思考模式。預設的 `qwen3:4b` 是只能思考的版本，關不掉（見 1.1）。 | `langchain_ollama/chat_models.py:529-548,805,966-967`；`langchain_ollama/_utils.py:12-47`；https://pypi.org/project/langchain-ollama/1.2.0/ ；`HW3/tools/bench.py` | Claude Code / 2026-11-25；實測 2026-11-26 |
| VERIFY-14 | **根目錄 pyproject**：`name="hw1"`，`requires-python=">=3.12"`。直接依賴有 beautifulsoup4、ftfy、langdetect、lxml、nltk、spacy；`tqdm`、`numpy` 只是間接依賴。<br>**衝突檢查**：以既有 lock 版本為約束條件做解析（不安裝），結果無衝突，解析出 langchain-core 1.7.2、langchain-community 0.4.2、langchain-ollama 1.2.0、ollama 0.6.3、faiss-cpu 1.16.0。<br>**後續決定**：HW3 改為獨立專案（`HW3/pyproject.toml`），沿用上述版本；hwlib 實際用到的是 beautifulsoup4、lxml、ftfy、nltk、spacy（不需要 langdetect）。<br>測試用標準函式庫 `unittest`，不需要新增測試套件。 | `pyproject.toml`；`uv.lock`；`HW3/scratch/v14_resolved_locked.txt`；`HW2/src/{extract,tokenizer}.py` | Claude Code / 2026-11-25、2026-11-26 |
