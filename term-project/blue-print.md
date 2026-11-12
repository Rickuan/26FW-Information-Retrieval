# 電商搜尋 Query Expansion 專案 Blueprint

> 版本 v1.0｜2026-11-12｜狀態：草案（標示「待驗證」的項目，需在對應 task 內驗證後才能當作事實）
> 團隊假設：2 人、4 週。資料集假設：WANDS 為主，ESCI 為選配。

## 0. 如何閱讀本文件

| 你是 | 先讀 | 再讀 |
|---|---|---|
| 人類開發者（想快速掌握全貌） | §1 概述 → §2 三版本總覽 → §3.1 資料流 → §5.4 刪減指南 → §7 里程碑 | §6 的 task 表（只讀你負責的 epic） |
| 人類開發者（要開工） | §3.3 資料契約 → §6 task 表 → §8 協作規範 | 附錄 A、B |
| AI agent | **全文**，然後**立刻執行 §10**（向開發人員確認，記錄決策後才可寫程式） | §3.6 技術注意事項、§4 評估協議 |

---

## 1. 專案概述

### 1.1 一句話定義

在電商商品搜尋（WANDS 資料集）上，以 **BM25 為底**，比較 **PRF（RM3）** 與 **LLM Query Expansion** 的效果，並用 **逐 query 分析** 說明「QE 在哪些 query 上有效、哪些上有害」。

### 1.2 研究問題（RQ）

| ID | 問題 | 對應版本 |
|---|---|---|
| RQ1 | LLM QE 與 RM3 相比，是否顯著優於 BM25 baseline？ | 基本版 |
| RQ2 | QE 的收益與風險分布在哪些 query（長度、難度、類型）？ | 基本版（贏/輸統計）→ 加強版（分組） |
| RQ3 | 擴展方式（重複次數、擴展內容組成）如何影響結果？何時不該擴展？ | 加強版 |
| RQ4 | 結論在第二個資料集、dense 檢索、或評論詞彙來源下是否成立？ | 完整版 |

### 1.3 非目標（Non-goals）

- 不訓練、不微調任何模型（只用預訓練模型做 zero-shot）。
- 不做線上服務或部署（demo 為選配）。
- 不做多語言（ESCI 的日文／西文子集不在範圍內）。
- 不追求超越 SOTA；重點是**實驗設計與分析品質**。

### 1.4 資料集決策摘要

| 資料集 | 角色 | 版本 | 備註 |
|---|---|---|---|
| WANDS（Wayfair） | 主資料集 | 基本版起 | corpus 小、含完整商品目錄、三級標註；筆電可跑 |
| ESCI-US（reduced 版子樣本） | 第二資料集 | 完整版 | 需自行設計抽樣與 corpus 組裝（T08-02） |
| Amazon Reviews 2023（某類別子集） | 擴展詞來源 | 完整版 | 需先通過 Go/No-Go spike（T10-01）；領域可能與 WANDS 不吻合 |

### 1.5 技術棧

| 用途 | 工具 | 備註 |
|---|---|---|
| 稀疏檢索 + RM3 | Pyserini（需 Java） | RM3 需要索引時存 doc vectors；Java 版本依 Pyserini 當時文件（待驗證） |
| 評估 | ranx（或 pytrec_eval） | API 依所裝版本文件確認 |
| LLM | 由 D-01 決定 | 全部離線生成並快取 |
| Dense（完整版） | sentence-transformers，預訓練小模型 | 不微調；WANDS 規模以 numpy 矩陣即可，不需 faiss |
| Reranker（完整版） | 預訓練 cross-encoder | zero-shot |
| 設定 | YAML + dataclass | 所有路徑與參數由 config 提供 |
| 測試 | pytest | 以 fixture 小資料集驗證契約 |

### 1.6 設計原則（所有 task 必須遵守）

1. **契約優先**：模組之間只透過 §3.3 的檔案格式溝通，不共享記憶體狀態。
2. **Run 檔是唯一介面**：任何檢索、融合、重排、選擇器的輸出都是 TREC run 檔；任何評估或分析只讀 run 檔。
3. **LLM 呼叫只發生在「生成階段」**：結果寫入磁碟快取，其餘階段只讀快取檔。
4. **Config 驅動**：不得 hardcode 路徑、模型名、參數。
5. **先評估後實驗**：在任何 QE 實驗之前，評估腳本必須先在 fixture 與 baseline 上驗證過。
6. **每個 task 可用 fixture 獨立驗證**，不需等其他人的產出。

---

## 2. 三版本總覽

| 項目 | 基本版（Basic） | 加強版（Enhanced） | 完整版（Full） |
|---|---|---|---|
| 定位 | **保底，必須完成** | 基本版 + 分析深度 | 加強版 + 擴充模組 |
| 資料集 | WANDS | WANDS | WANDS + ESCI-US 子樣本 + 評論資料 |
| 檢索 | BM25、RM3 | 同左 | + Dense、RRF 融合、Cross-encoder 重排 |
| QE 方法 | LLM QE（1 個 prompt） | + prompt 變體、LLM+RM3 疊加、選擇性擴展（規則 + oracle） | + 評論詞挖掘 QE、第二個 LLM |
| 評估 | nDCG@10、Recall@100、MAP、judged@10、顯著性檢定 | + condensed-list 評估 | + bootstrap CI |
| 分析 | 贏/輸/平統計與圖 | + 分組分析、案例研究、擴展詞命中率 | + 跨資料集、跨檢索器比較 |
| 消融 | 無 | n_repeat、擴展組成、RM3／BM25 參數敏感度 | + 系統矩陣（retriever × QE × rerank） |
| Task 數（約） | 39 | +16 | +22 |
| 粗估人時* | 60–80 | +30–40 | +60–80 |
| 對 2 人 4 週 | **可完成，有緩衝** | 可能完成（視 G2 是否準時） | **不建議全做；只挑一個模組** |

\* 粗估，假設熟悉 Python 與基本 IR；請在 W1 結束時用實際速度修正。

**版本之間是累加關係**：加強版包含基本版全部 task；完整版包含加強版全部 task。task 表中的「版」欄標示該 task **最早出現的版本**。

---

## 3. 系統架構

### 3.1 資料流

```
  [WANDS raw]──►(T01)──► corpus.jsonl / queries.tsv / qrels.tsv ──┐
                                   │                              │
                                   ▼                              │
                         (T02) BM25 index (含 docvectors)         │
                                   │                              │
   queries.tsv ──►(T03)LLM 生成 ──► expansions/*.jsonl (快取)      │
                                   │                              │
        ┌──────────────────────────┼───────────────┐              │
        ▼                          ▼               ▼              │
   BM25 baseline run          RM3 run        LLM-QE run  ...      │
        └──────────────┬───────────┴───────────────┘              │
                       ▼   (所有 run 都是 TREC run 檔)             │
                 (T04) 評估 ◄──────────────────────────────────────┘
                       ▼
        metrics.csv / per_query.csv ──► (T05) 分析 ──► (T07) 選擇性擴展
                       ▼                      │
                  (T06) 消融                   ▼
                       └────────► (T12) 圖表與報告
```

### 3.2 目錄結構

```
qe-ecom-ir/
├── README.md
├── Makefile
├── requirements.txt            # 或 pyproject.toml（core / dense / dev extras）
├── configs/
│   ├── data.yaml  bm25.yaml  qe_llm.yaml  eval.yaml
│   └── experiments/            # 一個實驗一個 yaml
├── prompts/                    # v1_*.txt, v2_*.txt（含版本 id）
├── data/                       # gitignored，除 .gitkeep
│   ├── raw/{wands,esci,reviews}/
│   ├── processed/{wands,esci}/ # corpus.jsonl queries.tsv qrels.tsv
│   ├── expansions/             # {method}__{model}__{prompt_ver}.jsonl
│   └── indexes/
├── runs/                       # *.trec + *.meta.json
├── results/                    # metrics.csv per_query.csv figures/ tables/
├── src/qe_ir/
│   ├── config.py  runmeta.py
│   ├── data/      wands.py esci.py validate.py stats.py
│   ├── index/     build_bm25.py build_dense.py
│   ├── retrieve/  run_io.py bm25.py rm3.py dense.py fusion.py rerank.py selective.py
│   ├── qe/        llm_client.py cache.py generate.py postprocess.py compose.py review_mining.py
│   ├── eval/      metrics.py judged.py significance.py condensed.py bootstrap.py
│   ├── analysis/  per_query.py features.py grouping.py cases.py plots.py
│   └── cli.py
├── scripts/                    # check_env.py download_*.sh
├── notebooks/                  # 探索與出圖（不放核心邏輯）
├── tests/
│   ├── fixtures/               # 10 docs / 4 queries / qrels / 手算預期值
│   └── test_*.py
└── docs/
    ├── DECISIONS.md            # 決策紀錄（§10 的產出）
    ├── DATA.md  data_report.md  experiments.md
    └── report/
```

### 3.3 資料契約（Data Contracts）

> **契約變更必須同步修改本表並通知另一位開發者。** 這是讓 task 能獨立開發的基礎。

| 產物 | 路徑 | 格式 | 產生者 → 使用者 |
|---|---|---|---|
| Corpus | `data/processed/{ds}/corpus.jsonl` | 每行 `{"id": str, "contents": str, "title": str}`；`id` 唯一 | T01-03 → T02-02、T09-02、T10 |
| Queries | `data/processed/{ds}/queries.tsv` | `qid\tquery[\tquery_class]`，UTF-8，含 header | T01-04 → 幾乎所有 |
| Qrels | `data/processed/{ds}/qrels.tsv` | TREC：`qid 0 docid grade`；grade 為整數，0 = 不相關 | T01-05 → T04 |
| Expansion | `data/expansions/{method}__{model}__{pv}.jsonl` | 每行 `{"qid","query","raw","clean","meta":{model,prompt_ver,params,ts}}` | T03-05 → T03-07/08、T05-05 |
| LLM 快取 | `data/cache/llm/*.json` | key = hash(model, prompt, params) | T03-02（內部） |
| Run | `runs/{run_name}.trec` | TREC：`qid Q0 docid rank score tag`，top-1000 | 所有檢索器 → 評估/分析/融合/重排 |
| Run meta | `runs/{run_name}.meta.json` | config 快照、git hash、seed、時間、輸入檔 hash | T00-06 |
| 指標 | `results/metrics.csv` | `run_name,metric,value` | T04-04 |
| 逐 query 指標 | `results/per_query.csv` | `run_name,qid,metric,value` | T04-01 → T05 |

**Run 命名規則**：`{dataset}__{retriever}__{qe}__{variant}`，例：`wands__bm25__llm_v1__rep5`、`wands__bm25__rm3__fb10x5`。

### 3.4 Fixture 與獨立開發

`tests/fixtures/` 提供最小資料集（10 篇文件、4 個 query、手算 nDCG 預期值）以及一份假的 expansion 檔與假的 run 檔。**所有模組都要能只靠 fixture 完成開發與測試**；這讓人 A 的檢索與人 B 的評估、LLM 生成可以同時進行。

### 3.5 同步點（Lane 之間唯一需要等待的地方）

| 同步點 | 條件 | 解鎖 |
|---|---|---|
| S1 | T01-06 通過（corpus/queries/qrels 驗證完畢） | T02-02、T03-04 |
| S2 | T02-03 產出 baseline run | T05-01、T03-08 的真實評估 |
| S3 | T03-05 完成（expansion 檔就緒） | T03-08、T05-05、T05-06 |

### 3.6 技術注意事項（agent 開工前必讀）

1. **RM3 需要 doc vectors**：建索引時必須存（T02-02）；漏掉會讓 T02-04 失敗。
2. **重複 query 詞是否加權需要實測**：「原 query 重複 n 次」的做法來自 query2doc 類方法（常見設定 n=5，請自行確認），但 Pyserini 的 query 解析是否讓重複詞提高權重，**不可假設**；T03-06 是專門驗證的 spike，結果決定 `compose()` 的實作（重複 vs. 明確權重）。
3. **長 query 可能觸及 Lucene 的 boolean clause 上限**（常見預設為 1024，待驗證）；擴展文字需有長度上限。
4. **Dense 模型前綴**：不同模型對 query／passage 有不同前綴（例如 E5 系列要求）；實作前以 model card 為準（T09-01）。
5. **未標註文件**：WANDS 標註來自候選池；QE 撈到的「真的相關但未標註」文件會被當成不相關，**QE 的效果可能被低估**。必須同時報告 judged@k。
6. **LLM few-shot 不得使用評估 query 或其 qrels**，否則資料洩漏。
7. **LLM 可能見過公開資料集**：報告需聲明（T12-05），並在 T03-09 抽查是否直接複述商品名。

---

## 4. 評估協議（所有實驗共用；細節以 D-05～D-08 的決策為準）

| 項目 | 預設設定 | 備註 |
|---|---|---|
| 主指標 | nDCG@10 | |
| 副指標 | Recall@100、MAP、judged@10 | MAP 的截斷深度由 D-06 決定 |
| 分級映射 | Exact=2、Partial=1、Irrelevant=0 | nDCG 對 gain 的線性縮放不敏感（2/1/0 與 1/0.5/0 結果相同）；非線性映射則會改變結果 |
| 二元指標門檻 | grade ≥ 1 視為相關 | 備選：只算 Exact；需於報告說明 |
| 未標註文件 | 視為不相關（標準做法）| 另報 judged@k；加強版再報 condensed-list |
| 資料切分 | 全部 query 當 test，**不調參** | 參數用文獻預設，掃描結果一律稱「敏感度分析」，不稱「調出最佳值」 |
| 顯著性檢定 | paired test，α = 0.05 | 多重比較需校正（D-08） |
| 贏/輸/平 | \|Δ nDCG@10\| < ε 視為平 | ε 預設 0.01（D-12） |
| Baseline 健全性 | BM25 分數量級須與 WANDS 官方評估方式對照 | 異常 → 停下查 bug（T02-05） |
| 負面結果 | 允許，並視為有效交付 | 重點是解釋「為什麼」 |

---

## 5. 相依關係與刪減指南

### 5.1 Epic 層級相依圖

```
T00 基礎 ─┬─► T01 資料 ──► T02 BM25/RM3 ──┬─► T05 分析 ──► T07 選擇性擴展
          │        │                      │        └──► T06 消融
          │        └──► (S1)              ├─► T04 評估（可用 fixture 先行）
          └─► T03-01~03（LLM client/cache/prompt）可與 T01 並行
                   └─► T03-04~09 生成/組合/QE run（需 S1、S2）

 完整版（全部只依賴 run 檔或契約，彼此獨立）：
   T08 ESCI（輸出同契約）   T09 Dense/RRF/Rerank   T10 評論詞挖掘   T11 其他
```

### 5.2 硬依賴（「一定要先 A 才能 B」）

| 先 | 後 | 原因 |
|---|---|---|
| T01-02（schema 探查） | T01-03/04/05 | 欄位假設（附錄 A）未驗證前不得寫 loader |
| T02-02（含 docvectors 的索引） | T02-04（RM3） | RM3 需要 doc vectors |
| T03-06（重複詞 spike） | T03-07（composer） | 實作方式取決於 spike 結果 |
| T03-04 → T03-05 | T03-08 | QE run 需要清理過的擴展檔 |
| T02-03（baseline run） | T05-01 | baseline 是 Δ 的基準 |
| T04-01（逐 query 指標） | T04-03、T05-* | 都讀 per_query.csv |
| T05-01 | T07-01 | oracle 需要 per-query Δ |
| T05-03（query 特徵） | T07-02 | 規則依特徵訂定 |
| T03-10（prompt 變體） | T06-03 | 擴展組成消融需要變體 |
| T10-01 通過 Go | T10-02～06 | 資料可行性 gate |
| T08-02 → T08-03 | T08-04 → T08-05 | 先有抽樣與 adapter 才能重跑 |
| T09-01 → 02 → 03 | T09-04 | dense 管線串接 |
| 所有核心 task | T12-04（reproduce） | 重現流程需完整 |

### 5.3 軟依賴與可平行群

| 軟依賴（建議順序，非必須） | 說明 |
|---|---|
| T02-05 先於所有 QE 實驗 | 否則 baseline 若有 bug，所有結論無效 |
| T05-02 先於 T05-03 | 先看贏/輸圖，再決定要切哪些特徵 |
| T09-05（RRF）、T09-07（重排） | 只需要 run 檔，T02-03 完成後即可獨立開發，**不依賴 dense** |

**建議的平行 Lane**

| Lane | 負責範圍 | 只靠 fixture 即可開發到 |
|---|---|---|
| A：資料 + 檢索 | T00、T01、T02、T08、T09 | S1、S2 |
| B：QE + 評估 + 分析 | T03、T04、T05、T06、T07、T10 | S3 |
| 共同 | T12 報告、各 Gate 檢查 | |

### 5.4 刪減指南

#### 5.4.1 禁止刪除（核心）

T00-01～07、T01-01～07、T02-01～05、T03-01～09（含 T03-06 spike）、T04-01～04、T05-01/02、T12-01/04/05。**刪掉任何一個，基本版就不成立或結論不可信。**

#### 5.4.2 加強版：可簡化的部分

| 項目 | 簡化方式 | 簡化後的影響 | 連動／相依 |
|---|---|---|---|
| 消融網格 T06-02～05 | 只保留 n_repeat（3 值）與擴展組成（3 值），省略 T06-04/05 | 無法回答參數敏感度；以文獻預設值並在限制段說明 | T06-01 仍需保留 |
| 分組分析 T05-03/04 | 只切「query 長度」一維 | 分析深度降低 | T07-02 的規則只能用長度 |
| 案例研究 T05-05 | 各取 top-3 贏／輸 | 質性分析變薄 | 無 |
| 擴展詞命中率 T05-06 | 整個省略 | 少一個機制解釋 | 無 |
| Prompt 變體 T03-10 | 只做 1 個變體（keywords-only） | T06-03 變成兩組比較 | T06-03 |
| Condensed 評估 T04-05 | 省略，用 judged@10 + 文字說明替代 | 未標註偏差只能定性討論 | T12-05 須如實寫 |
| 選擇性擴展 T07-02～04 | 只做 oracle（T07-01），說明 headroom | 少「實用策略」故事；oracle 僅為上限 | T07-01 只需 T05-01 |
| LLM+RM3 疊加 T06-06 | 省略 | 少一組組合結果 | 無 |

**建議簡化順序（先砍 → 後砍）**：T05-06 → T06-05 → T06-06 → T05-05 → T04-05 → T07-02～04 → T05-04（降為一維）。

#### 5.4.3 完整版：可砍除的部分

| 模組 | 刪除後 | 必須連動處理 | 誰依賴它 |
|---|---|---|---|
| Demo（T11-02） | 無展示 | 無 | 無 |
| 第二個 LLM（T11-01） | 無模型比較 | 報告不寫模型比較 | 無 |
| Bootstrap CI（T04-06） | 改用 T04-03 顯著性 | 無 | 無 |
| Reranker（T09-06/07） | 無第二階段 | T09-08 少一維 | 僅 T09-08 |
| ESCI（T08） | 只有單一資料集 | 報告限制段加註「僅 WANDS」；RQ4 降級 | 僅 T08-05 |
| Dense + RRF（T09-01～05） | 只有稀疏檢索 | T09-08 少一維；T09-07 仍可獨立存在 | T09-04、T09-08 |
| 評論詞挖掘（T10） | 少 corpus-based QE 亮點 | 刪 T10-06；若 T10-01 判 No-Go 則**自動刪除整個 T10** | 僅 T10-06 |

**建議砍除順序（先砍 → 後砍）**：Demo → 第二 LLM → Bootstrap CI → Reranker → ESCI → Dense+RRF → 評論詞挖掘。
**若 2 人 4 週只能加一個完整版模組**：選 T10（但 T10-01 必須在 W2 先做 spike，W3 開頭依結果決定去留）。

---

## 6. Task 工票

**欄位說明**：版 = 最早出現的版本（B 基本／E 加強／F 完整）；commits = 預估上限（皆 ≤ 15）；依賴 = 硬依賴；DoD = 完成定義（所有 task 另須符合 §8 的全域 DoD）。

### E0 專案基礎

| ID | 任務 | 版 | 依賴 | commits | DoD |
|---|---|---|---|---|---|
| T00-01 | 建立 repo 骨架（§3.2 目錄、.gitignore、Makefile 空殼、README stub） | B | — | 3 | `tree` 與 §3.2 一致；`make help` 可執行 |
| T00-02 | 環境檢查腳本 `scripts/check_env.py`（Python 版本、Java、pyserini import、磁碟與 RAM） | B | T00-01 | 3 | 兩位開發者機器皆輸出明確 PASS/FAIL |
| T00-03 | 依賴釘版（core / dense / dev 三組） | B | T00-02 | 2 | 全新 venv 安裝後 `pytest` 可跑 |
| T00-04 | 設定載入器（YAML → dataclass；路徑全由 config） | B | T00-01 | 4 | 單元測試涵蓋缺欄位與型別錯誤 |
| T00-05 | Fixture 小資料集 + 手算預期值 + pytest 設定 | B | T00-01 | 3 | `tests/fixtures/README.md` 說明手算過程 |
| T00-06 | Run metadata 工具（config 快照、git hash、seed、時間戳） | B | T00-04 | 2 | 每個 run 旁有 `.meta.json` |
| T00-07 | Makefile 目標（data / index / qe / run / eval / report / reproduce） | B | T00-04 | 3 | 目標可呼叫（允許先為 stub） |

### E1 資料

| ID | 任務 | 版 | 依賴 | commits | DoD |
|---|---|---|---|---|---|
| T01-01 | WANDS 取得腳本與來源說明（URL、commit、授權、引用格式） | B | T00-01 | 2 | `data/raw/wands/` 有原始檔；來源寫入 `docs/DATA.md` |
| T01-02 | **Schema 探查 spike**：輸出欄位、列數、缺值、label 分布，與附錄 A 逐項比對 | B | T01-01 | 3 | `docs/data_report.md`；有差異 → 停下回報（§10.4） |
| T01-03 | Corpus builder（欄位串接策略由 config：title 重複次數、是否含 class/description/features） | B | T01-02、T00-04 | 4 | 產出 corpus.jsonl；契約測試通過 |
| T01-04 | queries.tsv writer（保留 query_class，若存在） | B | T01-02 | 2 | 契約測試通過 |
| T01-05 | qrels.tsv writer（label → grade 映射來自 config） | B | T01-02 | 3 | TREC 格式；映射可由 config 改 |
| T01-06 | 資料驗證器（id 唯一、qrels docid ∈ corpus、每 query ≥1 相關、空文字檢查） | B | T01-03～05 | 3 | 驗證通過即達成 **S1** |
| T01-07 | 資料統計圖表（query 長度、相關文件數／query、文件長度） | B | T01-06 | 3 | 圖存入 `results/figures/` |

### E2 檢索（BM25／RM3）

| ID | 任務 | 版 | 依賴 | commits | DoD |
|---|---|---|---|---|---|
| T02-01 | Run I/O（TREC run 讀寫 + meta；格式驗證） | B | T00-05 | 3 | 以 fixture 獨立測試 |
| T02-02 | BM25 index builder（包裝 Pyserini CLI；**必須存 docvectors**） | B | T01-03、T00-02 | 3 | 索引可查詢；fixture 結果正確 |
| T02-03 | BM25 runner（k1、b 由 config；輸出 top-1000） | B | T02-01、T02-02、T01-04 | 3 | 結果決定性（重跑相同）；達成 **S2** |
| T02-04 | RM3 runner（fb_terms、fb_docs、original_query_weight 由 config） | B | T02-03 | 3 | 產出 RM3 run |
| T02-05 | Baseline 健全性檢查（分數量級與 WANDS 官方評估方式對照） | B | T02-03、T04-01 | 2 | 結論寫入 `DECISIONS.md`；異常即停 |
| T02-06 | 【條件式】Pyserini 不可用時的 fallback（bm25s + 自寫 RM3） | B* | T00-02 | 8 | 僅在 D-02 判定 Java 不可用時啟動 |

### E3 LLM Query Expansion

| ID | 任務 | 版 | 依賴 | commits | DoD |
|---|---|---|---|---|---|
| T03-01 | LLM client 抽象（provider-agnostic、重試、速率限制、Mock client） | B | T00-04 | 4 | Mock client 可跑完整流程測試 |
| T03-02 | 磁碟快取（key = hash(model, prompt, params)；命中不得再呼叫 API） | B | T03-01 | 3 | 測試：第二次呼叫 0 次 API |
| T03-03 | Prompt v1（`prompts/v1_*.txt`，版本 id；不得含評估 query／qrels 的 few-shot） | B | — | 2 | 附設計說明（輸出格式、要求內容） |
| T03-04 | 批次生成腳本（resume、dry-run、預算上限、失敗清單） | B | T03-02、T03-03、T01-04 | 5 | dry-run 顯示預估呼叫數與成本；可中斷續跑 |
| T03-05 | 擴展後處理（去 markdown／重複、長度上限、保留 raw 與 clean） | B | T03-04 | 3 | 產出符合契約；達成 **S3** |
| T03-06 | **Spike**：驗證 Pyserini 中重複詞是否加權、clause 上限行為 | B | T02-03 | 2 | 結論寫入 `DECISIONS.md` |
| T03-07 | Query composer：`compose(query, expansion, n_repeat, mode)` | B | T03-06 | 3 | 單元測試；長度上限生效 |
| T03-08 | LLM-QE runner | B | T03-05、T03-07、T02-03 | 3 | 產出 `wands__bm25__llm_v1__*` run |
| T03-09 | 擴展品質人工抽樣（20 筆）：幻覺、洩漏（複述商品名）、離題 | B | T03-05 | 2 | `docs/qe_sample_review.md` |
| T03-10 | Prompt 變體（keywords-only、pseudo-doc-only） | E | T03-03 | 3 | 變體各自生成擴展檔 |

### E4 評估

| ID | 任務 | 版 | 依賴 | commits | DoD |
|---|---|---|---|---|---|
| T04-01 | 評估包裝（ndcg@10、recall@100、map；輸出 aggregate 與 per-query CSV） | B | T02-01 | 4 | fixture 手算值吻合 |
| T04-02 | judged@k | B | T02-01 | 2 | fixture 手算值吻合 |
| T04-03 | 顯著性檢定包裝（paired test + 多重比較校正選項） | B | T04-01 | 3 | 對 fixture 與假 run 有可預期結果 |
| T04-04 | 結果彙整（runs/* → metrics.csv + Markdown 表） | B | T04-01、T04-02 | 3 | 新增 run 自動出現在表中 |
| T04-05 | Condensed-list 評估（移除未標註文件後重算） | E | T04-01 | 3 | fixture 測試 |
| T04-06 | Bootstrap 信賴區間 | F | T04-01 | 3 | 種子固定、可重現 |

### E5 分析

| ID | 任務 | 版 | 依賴 | commits | DoD |
|---|---|---|---|---|---|
| T05-01 | Per-query Δ 表（對 baseline；ε 由 config） | B | T04-01 | 3 | 輸出 win/loss/tie 計數 |
| T05-02 | 贏/輸/平統計圖（長條 + baseline-vs-method 散點） | B | T05-01 | 3 | 圖含 n 與 ε 註記 |
| T05-03 | Query 特徵抽取（長度、含數字、baseline 難度分桶、query_class） | E | T01-04、T04-01 | 4 | 特徵表 `results/query_features.csv` |
| T05-04 | 分組分析（每組 n、平均 Δ、信賴區間） | E | T05-01、T05-03 | 4 | 小組（n 過小）標示警語 |
| T05-05 | 案例研究產生器（top-k 贏／輸：query、擴展、前 5 文件、標籤）→ Markdown | E | T05-01、T03-05 | 3 | 可直接貼進報告 |
| T05-06 | 擴展詞命中率（擴展詞在相關文件 vs. 非相關 top 文件的出現率） | E | T05-01、T03-05 | 4 | 輸出每 query 與整體統計 |

### E6 消融

| ID | 任務 | 版 | 依賴 | commits | DoD |
|---|---|---|---|---|---|
| T06-01 | 實驗網格執行器（config 列舉 runs；已存在則跳過） | E | T03-08、T02-04 | 4 | 重跑不重複計算 |
| T06-02 | n_repeat 掃描 | E | T06-01 | 2 | 每個值一個 run |
| T06-03 | 擴展組成消融（keywords／pseudo-doc／both） | E | T06-01、T03-10 | 2 | 三組比較表 |
| T06-04 | RM3 參數敏感度（小網格） | E | T06-01 | 2 | 標示為「敏感度分析」 |
| T06-05 | BM25 k1/b 敏感度 | E | T06-01 | 2 | 同上 |
| T06-06 | LLM-QE + RM3 疊加 | E | T06-01 | 3 | 一組比較結果 |

### E7 選擇性擴展

| ID | 任務 | 版 | 依賴 | commits | DoD |
|---|---|---|---|---|---|
| T07-01 | Oracle 上限（每 query 取 baseline／LLM-QE 較佳者） | E | T05-01 | 2 | 報告需註明 oracle 使用了標註，僅為上限 |
| T07-02 | 規則式選擇器（規則來自 T05-03 的特徵；config 可調） | E | T05-03 | 3 | 規則寫成可序列化的 config |
| T07-03 | Selective runner（依規則自既有 run 檔逐 query 挑選；不需重新檢索） | E | T07-02、T02-01 | 3 | 輸出標準 run 檔 |
| T07-04 | 閾值掃描與報告 | E | T07-03、T04-01 | 3 | 與 oracle、baseline 並列 |

### E8 ESCI 第二資料集（完整版）

| ID | 任務 | 版 | 依賴 | commits | DoD |
|---|---|---|---|---|---|
| T08-01 | ESCI 取得 + schema 探查（parquet） | F | T00-01 | 3 | `docs/data_report.md` 增補 |
| T08-02 | 子樣本策略定案與實作（locale=us、small_version=1、test split；N 個 query 以固定 seed 抽樣；corpus 組成方式見 D-14） | F | T08-01 | 4 | 抽樣方式與 seed 文件化 |
| T08-03 | ESCI adapter 輸出同一契約（含 E/S/C/I 的 gain 映射） | F | T08-02 | 4 | 通過 T01-06 同款驗證 |
| T08-04 | ESCI baseline + judged@10 | F | T08-03、T02-03 | 2 | 與 WANDS 的 judged@10 並列 |
| T08-05 | 核心實驗於 ESCI 重跑（僅換 config） | F | T08-04 + 對應 B/E task | 3 | 結果併入 metrics.csv |

### E9 Dense／融合／重排（完整版）

| ID | 任務 | 版 | 依賴 | commits | DoD |
|---|---|---|---|---|---|
| T09-01 | Dense encoder wrapper（模型 id 由 config；CPU/GPU 自動；batch；前綴處理） | F | T00-03 | 4 | 前綴依 model card；單元測試 |
| T09-02 | Dense index（numpy 矩陣） | F | T09-01、T01-03 | 3 | 編碼可續跑、結果落盤 |
| T09-03 | Dense runner（原 query） | F | T09-02、T02-01 | 3 | 產出 run 檔 |
| T09-04 | Dense + QE 變體（擴展文字當查詢／原 query+擴展 concat／假想描述 embedding） | F | T09-03、T03-05 | 4 | 每個變體一個 run |
| T09-05 | RRF 融合（輸入任意 ≥2 個 run 檔；k 由 config） | F | T02-01 | 3 | fixture 手算驗證 |
| T09-06 | Reranker wrapper（zero-shot cross-encoder；模型由 config） | F | T00-03 | 3 | 單元測試 |
| T09-07 | Rerank runner（輸入任意 run + top-k → 新 run） | F | T09-06、T02-01 | 3 | 產出 run 檔 |
| T09-08 | 系統矩陣評估（retriever × QE × rerank）與表格 | F | T09-04/05/07 | 3 | 一張總表 |

### E10 評論詞挖掘 QE（完整版）

| ID | 任務 | 版 | 依賴 | commits | DoD |
|---|---|---|---|---|---|
| T10-01 | **可行性 spike（Go/No-Go）**：取近似類別的評論資料子集，抽 20 個 query 檢查評論詞彙是否提供可用關聯 | F | T01-04 | 3 | 判定寫入 `DECISIONS.md`；No-Go 則 T10 全部取消 |
| T10-02 | 評論前處理（清洗、與索引相同 analyzer 斷詞、停用詞、長度過濾） | F | T10-01(Go) | 4 | 產出處理後語料 |
| T10-03 | 詞關聯統計（PMI／條件機率；最小頻次門檻） | F | T10-02 | 5 | 輸出 term→related terms 表 |
| T10-04 | 擴展詞選擇器（每 query 取 top-k；過濾過泛詞） | F | T10-03 | 3 | 輸出契約格式的 expansion 檔 |
| T10-05 | Corpus-based QE runner（重用 composer） | F | T10-04、T03-07 | 2 | 產出 run 檔 |
| T10-06 | 與 LLM-QE 比較與合併（concat 兩種擴展） | F | T10-05、T03-08 | 3 | 三者並列比較 |

### E11 其他（完整版）

| ID | 任務 | 版 | 依賴 | commits | DoD |
|---|---|---|---|---|---|
| T11-01 | 第二個 LLM 的擴展與比較（快取 key 含 model） | F | T03-08 | 3 | 兩個模型並列 |
| T11-02 | Demo（Gradio/Streamlit；baseline vs QE 並列） | F | T03-08、T02-03 | 5 | 本機可啟動（選配） |

### E12 報告與重現

| ID | 任務 | 版 | 依賴 | commits | DoD |
|---|---|---|---|---|---|
| T12-01 | 實驗登錄表自動產生（run → config → git hash → 指標） | B | T04-04、T00-06 | 3 | `docs/experiments.md` 可重生 |
| T12-02 | 圖表產生腳本（`make figures`） | B | T05-02、T04-04 | 3 | 圖可由指令重現 |
| T12-03 | 報告骨架（章節見附錄 C） | B | — | 2 | 各節有標題與待填摘要 |
| T12-04 | 重現流程 `make reproduce`（自快取擴展重跑至結果）+ README | B | T00-07 + 全部核心 task | 4 | 乾淨環境可重現主表 |
| T12-05 | 限制與威脅段落（洩漏、未標註、小樣本、無獨立 test、領域限制） | B | T04-02 | 2 | 與實際做法一致 |
| T12-06 | 簡報（選配） | B | T12-03 | 3 | 依課程要求 |

---

## 7. 里程碑與分工（2 人、4 週）

**建議分工**：人 A = Lane A（資料 + 檢索）；人 B = Lane B（QE + 評估 + 分析）。兩人在 T12 與各 Gate 共同工作。

### 7.1 基本版時程（有緩衝）

| 週 | 人 A | 人 B | Gate |
|---|---|---|---|
| W1 | T00-01～07、T01-01～07、T02-01 | T03-01～03、T04-01～02（用 fixture） | **G1**：S1 達成；BM25 baseline 能跑 |
| W2 | T02-02～05（S2） | T03-04～09（S3）、T04-03～04 | **G2**：baseline 通過健全性；expansion 檔就緒 |
| W3 | T05-01～02、T12-01～02 | 同左（分工互換亦可）、T12-05 | **G3**：RM3、LLM-QE 結果與顯著性齊備 |
| W4 | T12-03～04、報告 | 報告、補實驗缺口 | **G4**：凍結實驗；僅寫報告與修缺 |

### 7.2 升級到加強版的條件

| 條件 | 動作 |
|---|---|
| G2 準時達成 | W3 起加入 T03-10、T06、T05-03～06 |
| G3 準時達成 | W3 末加入 T07 |
| G2 或 G3 延遲 | **立即退回基本版**，不進入加強版 |

### 7.3 完整版（僅在 G3 準時且有餘力時）

1. **W2 就先跑 T10-01 spike**（低成本），W3 開頭依結果決定是否進 T10。
2. 其餘完整版模組依 §5.4.3 的砍除順序反向挑選（最後才砍評論詞挖掘）。
3. **G4 之後不再新增任何 task。**

---

## 8. 協作規範

| 項目 | 規範 |
|---|---|
| 分支 | 一個 task 一個分支：`T05-03-query-features` |
| Commit 訊息 | `T05-03: add query length feature`（task ID 開頭） |
| PR | 一個 task 一個 PR；描述含：task ID、DoD 勾選、是否變更契約；由另一人 review |
| 契約變更 | 先改 §3.3 表格，再改程式，並通知對方 |
| 實驗紀錄 | 每個 run 必有 `.meta.json`；結果進 `docs/experiments.md` |
| 祕密 | API key 只放環境變數或未追蹤檔案，不入版控 |

**全域 DoD（每個 task 皆需符合）**

- [ ] 測試通過（至少用 fixture 的契約測試）
- [ ] 參數與路徑皆來自 config，無 hardcode
- [ ] 產出符合 §3.3 契約
- [ ] 新產生的 run 有 meta 檔
- [ ] 程式碼有簡短 docstring；必要時更新 README
- [ ] 沒有未說明的新增依賴

---

## 9. 風險

| 風險 | 可能性 | 影響 | 緩解 |
|---|---|---|---|
| Java／Pyserini 環境裝不起來 | 中 | 高 | T00-02 第一天驗證；備案 T02-06 |
| WANDS schema 與預期不符 | 中 | 中 | T01-02 先探查；差異即停下回報 |
| 未標註偏差使 QE 看起來無效 | 中 | 中 | judged@k、condensed 評估、如實討論 |
| QE 無顯著提升 | 中 | 低 | 負面結果有效；以分組與案例分析解釋原因 |
| LLM 成本或速率限制 | 低 | 中 | 預算上限、快取、resume（T03-04） |
| 資料洩漏（LLM 見過資料集） | 中 | 中 | 抽查 T03-09；T12-05 聲明 |
| 評論資料與 WANDS 領域不符 | 高 | 中 | T10-01 Go/No-Go |
| 時程膨脹 | 高 | 高 | Gate 機制；超時即退版（§7.2） |

---

## 10. AI Agent 開工協議

### 10.1 流程

1. **讀完整份 blueprint。**
2. **向開發人員確認 §10.2 的決策**（先問 P0，其餘在對應 epic 開工前才問）；一次最多問一批相關問題，並附上預設建議，讓對方可回覆「採預設」。
3. 將每項決策記入 `docs/DECISIONS.md`（格式：ID、決策、日期、理由、影響的 task）。
4. 依 §6 與 §7 的順序執行；每完成一個 Gate，向開發人員回報並請求繼續。
5. 遇到 §10.4 的情況時**停止並詢問**，不自行猜測。

### 10.2 需確認事項

| ID | 問題 | 預設建議 | 阻塞 | 優先級 |
|---|---|---|---|---|
| D-00 | 目標版本（基本／加強／完整）與預計完成日 | 基本版起步，G3 後再決定 | 全部 | P0 |
| D-01 | LLM 供應商、模型、API key 提供方式、預算上限、temperature | 小型快速模型、低溫度；上限由開發者決定 | T03-* | P0 |
| D-02 | Java 與 Pyserini 是否可安裝 | 優先 Pyserini；不行則 T02-06 | T02-* | P0 |
| D-03 | 運算資源（GPU、RAM、磁碟）、Python 版本 | 假設僅 CPU | T09、T10 | P1 |
| D-04 | 是否納入 ESCI、評論資料 | 基本版不納入 | T08、T10 | P1 |
| D-05 | 分級映射與二元門檻 | 2/1/0；grade ≥ 1 | T01-05、T04 | P0 |
| D-06 | 指標集合與 MAP 截斷深度 | nDCG@10、Recall@100、MAP、judged@10 | T04 | P0 |
| D-07 | 切分策略 | 全部 query 當 test，不調參 | T04、T06 | P0 |
| D-08 | 顯著性檢定方法、α、多重比較校正 | paired test、α=0.05、做校正 | T04-03 | P1 |
| D-09 | 文件欄位組成與 title 重複次數 | title×2 + class + description + features（依 T01-02 實際欄位調整） | T01-03 | P0 |
| D-10 | Prompt 語言與輸出格式；few-shot 來源 | 英文；few-shot 不得取自評估 query | T03-03 | P0 |
| D-11 | n_repeat 預設與掃描範圍 | 預設 5；掃描 {1,3,5} | T03-07、T06-02 | P1 |
| D-12 | 贏/輸/平門檻 ε | 0.01 | T05-01 | P1 |
| D-13 | 分工與 review 流程；notebook 與腳本的使用界線 | 人 A／人 B 如 §7；核心邏輯一律放 `src/` | T00、§8 | P0 |
| D-14 | ESCI 抽樣大小、corpus 組成（只含被標註商品？是否加入隨機干擾項？） | 以固定 seed 抽樣；是否加干擾項由開發者決定 | T08-02 | P1 |
| D-15 | 資料授權與引用（WANDS、ESCI、評論資料） | 開工前逐一確認條款並記錄 | T01-01、T08-01、T10-01 | P0 |
| D-16 | 報告語言、格式與交付規範（課程要求） | 依課程規定 | T12 | P1 |

### 10.3 行為規則

**可自行決定**：內部命名、模組內部實作、小型重構、測試寫法、圖表樣式。

**必須先確認**：契約變更、評估協議變更、新增重量級依賴、刪減 scope、可能超出預算的 LLM 呼叫、任何對基準（baseline）的修改。

**一律禁止**：

- 在評估階段呼叫 LLM API（只能讀快取）。
- 使用評估 query 或其 qrels 作為 few-shot 或調參依據。
- 為了讓結果好看而修改評估設定。
- 將 API key 寫入程式碼或版控。
- 在沒有 fixture 測試的情況下合併新模組。

### 10.4 必須停止並詢問的情況

| 情況 | 處理 |
|---|---|
| 實際資料 schema 與附錄 A 不符 | 停下，回報差異，更新附錄 A 與契約後再繼續 |
| BM25 baseline 分數明顯不合理 | 停下，先查資料處理與評估，不得繼續跑 QE 實驗 |
| LLM 呼叫預估成本超過 D-01 上限 | 停下，提出縮減方案 |
| T03-06 spike 顯示重複詞不加權或有 clause 上限問題 | 回報並提出 compose 的替代設計 |
| T10-01 結果為 No-Go | 回報並取消 T10 |
| 任一 Gate 延遲 | 提出退版方案（§7.2），等待決定 |
| 需要變更 §3.3 的契約 | 先徵得同意 |

---

## 附錄 A：WANDS 預期 Schema（記憶所及，**未驗證**，由 T01-02 驗證）

| 檔案 | 預期欄位 |
|---|---|
| `product.csv` | product_id、product_name、product_class、category hierarchy、product_description、product_features、rating_count、average_rating、review_count |
| `query.csv` | query_id、query、query_class |
| `label.csv` | id、query_id、product_id、label（Exact／Partial／Irrelevant） |

預期規模：約 4 萬餘商品、480 個 query、二十餘萬筆標註（待驗證）；檔案分隔符號與編碼亦待驗證。若 `query_class` 不存在，T05-03 的 query_class 特徵自動省略。若評分欄位確實存在，可作為額外特徵，但**評論全文不在 WANDS 中**，因此評論詞挖掘需要外部資料（T10）。

## 附錄 B：設定檔範例（示意）

```yaml
# configs/experiments/wands__bm25__llm_v1__rep5.yaml
dataset: wands
retriever:
  type: bm25
  k1: 0.9
  b: 0.4
qe:
  type: llm
  expansion_file: data/expansions/llm__MODEL_ID__v1.jsonl
  compose:
    n_repeat: 5
    max_expansion_tokens: 200
output:
  run_name: wands__bm25__llm_v1__rep5
  depth: 1000
seed: 42
```

（k1、b 的數值僅為示意，實際以 D-07 的決策為準。）

## 附錄 C：報告章節與對應 Task

| 章節 | 內容 | 資料來源 task |
|---|---|---|
| 1 緒論 | 動機、RQ | §1.2 |
| 2 相關工作 | PRF、LLM QE（query2doc／HyDE 類） | 文獻閱讀 |
| 3 方法 | baseline、RM3、LLM QE、composer | T02、T03 |
| 4 實驗設定 | 資料集、評估協議、參數 | T01、§4、T01-07 |
| 5 結果 | 主表、顯著性、judged@10 | T04-04、T04-03、T04-02 |
| 6 分析 | 贏/輸/平、分組、案例、命中率 | T05 |
| 7 消融與選擇性擴展 | 參數與組成、oracle／規則 | T06、T07 |
| 8 限制與威脅 | 洩漏、未標註、小樣本、領域 | T12-05 |
| 9 結論與未來工作 | 含未做的完整版模組 | §5.4.3 |