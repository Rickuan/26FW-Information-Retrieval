"""帶前綴的 Embeddings 類別：全系統建立 embedding 的唯一入口（規格 1.6-4、2.5）。

- query 加 `[embed] query_prefix`、passage 加 `[embed] doc_prefix`；前綴只在這裡加，
  輸入已經以該前綴開頭時 raise ValueError（代表呼叫端違反規則），不默默跳過。
- 輸出一律做 L2 normalize（float32 計算），內積 = cosine。
- 兩種模式：
  - "build"：不指定 num_gpu，由 Ollama 自行配置（有 GPU 時使用 GPU）。
  - "query"：num_gpu=0，embedding 在 CPU 執行，GPU 留給 LLM（VERIFY-15）。
    num_gpu 是模式的語意，不放進 config（A3 Q1）。
- 超過 2,048 tokens 的輸入由 Ollama 預設的截斷保留開頭 2,048 tokens（VERIFY-15、A3 D2）；
  本類別不傳 truncate，也不自行截斷。
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np
from langchain_core.embeddings import Embeddings

Mode = Literal["build", "query"]


def l2_normalize(vecs: Any) -> np.ndarray:
    """把 (n, d) 的向量逐列 L2 normalize，回傳 float32 陣列。

    Raises:
        ValueError: 輸入不是二維，或有範數為 0（或非有限值）的向量。
    """
    arr = np.asarray(vecs, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError(f"需要二維向量陣列，收到 shape {arr.shape}")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    bad = ~np.isfinite(norms[:, 0]) | (norms[:, 0] == 0)
    if bad.any():
        raise ValueError(f"第 {np.flatnonzero(bad).tolist()} 個向量的範數為 0 或非有限值，無法 normalize")
    return arr / norms


class PrefixedOllamaEmbeddings(Embeddings):
    """加上 embeddinggemma 檢索前綴、輸出 L2 normalize 的 Embeddings。

    一般程式用 `from_config(mode)` 建立；`inner` 只給單元測試注入假的 Embeddings。
    """

    def __init__(self, model: str, query_prefix: str, doc_prefix: str, *,
                 num_gpu: int | None = None, inner: Embeddings | None = None) -> None:
        self.model = model
        self.query_prefix = query_prefix
        self.doc_prefix = doc_prefix
        self.num_gpu = num_gpu
        if inner is None:
            from langchain_ollama import OllamaEmbeddings   # 延後匯入：單元測試不需要 Ollama
            inner = OllamaEmbeddings(model=model, num_gpu=num_gpu, dimensions=None)
        self.inner = inner

    @classmethod
    def from_config(cls, mode: Mode, cfg: dict[str, Any] | None = None, *,
                    inner: Embeddings | None = None) -> PrefixedOllamaEmbeddings:
        """依 `cfg["embed"]` 建立；mode="build" 用 GPU（num_gpu=None），"query" 用 CPU（num_gpu=0）。"""
        if mode not in ("build", "query"):
            raise ValueError(f"mode 必須是 'build' 或 'query'，收到 {mode!r}")
        if cfg is None:
            from rag.config import get_config
            cfg = get_config()
        e = cfg["embed"]
        return cls(e["model"], e["query_prefix"], e["doc_prefix"],
                   num_gpu=None if mode == "build" else 0, inner=inner)

    @staticmethod
    def _add_prefix(prefix: str, text: str) -> str:
        if not isinstance(text, str):
            raise TypeError(f"輸入必須是 str，收到 {type(text).__name__}")
        if text.startswith(prefix):
            raise ValueError(f"輸入已經以前綴 {prefix!r} 開頭；前綴只能由 embed.py 加上（規格 1.6-4）")
        return prefix + text

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """每筆加一次 doc_prefix，整批一次送出（不自行分批），回傳 normalize 後的向量。"""
        if not texts:
            return []
        prefixed = [self._add_prefix(self.doc_prefix, t) for t in texts]
        vecs = self.inner.embed_documents(prefixed)
        if len(vecs) != len(texts):
            raise ValueError(f"embedding 筆數 {len(vecs)} 與輸入 {len(texts)} 不一致")
        return l2_normalize(vecs).tolist()

    def embed_query(self, text: str) -> list[float]:
        """加一次 query_prefix，回傳 normalize 後的向量。"""
        vec = self.inner.embed_query(self._add_prefix(self.query_prefix, text))
        return l2_normalize([vec])[0].tolist()
