# HW3 硬體試跑報告 — `kuan` (`embeddinggemma` + `qwen3:4b`)

> **分支用途**：本分支（`docs/hw3-bench-record-kuan`）僅供暫存記錄本機測試結果與環境設定，**不合併進 `main`**，待 HW3 作業結束後可直接刪除。  
> **測試時間**：2026-11-26  
> **測試工具**：`HW3/tools/bench.py`（commit `bffe3af`）

---

## 1. 執行指令

```bash
uv run --no-project --with langchain-core --with langchain-ollama --with numpy \
  python HW3/tools/bench.py --owner kuan --llm-model qwen3:4b
```

---

## 2. 硬體與軟體環境（A. 硬體資訊）

| 項目 | 數值 |
|---|---|
| `owner` | `kuan` |
| `os` | `macOS 15.3.2` |
| `cpu` | `Apple M1` |
| `cores` | `8` |
| `ram_gb` | `8.0` |
| `gpu` | `Apple Silicon (Apple M1)` |
| `vram_gb` | `unified` |
| `ollama_version` | `0.40.18` |

> **備註**：先前嘗試執行 `qwen3:8b`（5.2 GB）時，因 8 GB 統一記憶體吃緊導致大量 swap 與系統卡頓而中止，改以 `qwen3:4b`（2.5 GB）完成全流程測試。

---

## 3. 標準化測試結果表

| 項目 | 數值 |
|---|---|
| `owner` | `kuan` |
| `os` | `macOS 15.3.2` |
| `cpu` | `Apple M1` |
| `cores` | `8` |
| `ram_gb` | `8.0` |
| `gpu` | `Apple Silicon (Apple M1)` |
| `vram_gb` | `unified` |
| `ollama_version` | `0.40.18` |
| `embed_processor_mode` | `100% GPU` |
| `embed_passages_per_sec` | `11.38` |
| `embed_dim` | `768` |
| `embed_norm_mean` | `1.0` |
| `embed_est_total_min_for_120k` | `175.7` |
| `llm_processor_mode` | `100% GPU` |
| `llm_avg_total_sec` | `26.637` |
| `llm_avg_prompt_tokens_per_sec` | `186.957` |
| `llm_avg_tokens_per_sec` | `17.753` |
| `llm_load_sec` | `0.044` |
| `llm_think_leak` | `False` |
| `peak_mem_gb` | `3.2` |
| `llm_run1` | total `25.494s`, load `0.032s`, prompt `1885 tok @ 187.09 tok/s`, gen `268 tok @ 17.66 tok/s`, `think=False` |
| `llm_run2` | total `27.092s`, load `0.076s`, prompt `1886 tok @ 187.08 tok/s`, gen `300 tok @ 17.94 tok/s`, `think=False` |
| `llm_run3` | total `27.326s`, load `0.025s`, prompt `1888 tok @ 186.7 tok/s`, gen `300 tok @ 17.66 tok/s`, `think=False` |
| `llm_warmup_load_sec（冷載入）` | `3.823` |
| `peak_mem 說明` | `ollama RSS 3.12 GB + python 0.08 GB（不含 VRAM）` |
| `errors` | `(none)` |
| `判讀：embed 120000 段` | **可接受**（60–180 分區間，可過夜完成） |
| `判讀：LLM 每題` | **良好**（< 30 秒） |
| `判讀：RAM` | `< 16 GB`，跑 `qwen3:4b` 可能吃緊（實測峰值 RSS `3.2 GB`，運作流暢） |

```text
RESULT | kuan | embed 120k 約 175.7 分鐘 | LLM 每題約 26.637 秒（讀 prompt 186.957 tok/s） | GPU: 有
```

---

## 4. 各項量測明細

### B. Embedding 測速（`embeddinggemma`）

- 模型：`embeddinggemma:latest`（`85462619ee72`，`685 MB` in memory）
- `ollama ps` PROCESSOR：`100% GPU`（`CONTEXT: 2048`, `RUNNER: llamacpp`）
- 測試資料：256 段、每段 300 英文單字，前綴 `"title: none | text: "`
- 批次設定：`batch_size = 64`（第 1 批 64 段暖機丟棄，計時其餘 3 批共 192 段）
- 計時結果：192 passages / `16.87s` = **`11.38 passages/sec`**
- 向量維度：**`768`**（符合預期）
- 向量 L2 norm 平均：**`1.0`**
- 全量 120,000 段推估時間：`120000 / 11.38 / 60` = **`175.7` 分鐘**（約 2.93 小時）

### C. LLM 測速（`qwen3:4b`）

- 模型：`qwen3:4b`（`359d7dd4bcda`，`3.2 GB` in memory）
- `ollama ps` PROCESSOR：`100% GPU`（`CONTEXT: 8192`, `RUNNER: llamacpp`）
- 參數：`temperature=0.0`, `num_ctx=8192`, `reasoning=False`
- 暖機（seed=1000）：冷載入 `load_duration` = `3.823s`
- 正式 3 次測試（每次使用不同 seed 避免 prompt cache 失真）：

| 次數 | Seed | Total (s) | Load (s) | Prompt Tokens | Prompt Speed (tok/s) | Eval Tokens | Eval Speed (tok/s) | `<think>` 外洩 |
|---|---|---|---|---|---|---|---|---|
| Run 1 | 1001 | 25.494 | 0.032 | 1885 | 187.09 | 268 | 17.66 | `False` |
| Run 2 | 1002 | 27.092 | 0.076 | 1886 | 187.08 | 300 | 17.94 | `False` |
| Run 3 | 1003 | 27.326 | 0.025 | 1888 | 186.70 | 300 | 17.66 | `False` |
| **平均** | — | **26.637** | **0.044** | **1886.3** | **186.957** | **289.3** | **17.753** | **`False`** |

### D. 峰值記憶體

- 量測結果：`peak_mem_gb = 3.2` GB
- 明細：`ollama` RSS `3.12 GB` + `python` `0.08 GB`（不含統一記憶體中的 GPU/Metal VRAM 配置）

---

## 5. 原始輸出檔案

- JSON 結果：[bench_kuan_qwen3_4b.json](./bench_kuan_qwen3_4b.json)
- 執行進度日誌：[bench_kuan_qwen3_4b.stderr.txt](./bench_kuan_qwen3_4b.stderr.txt)
