"""對外統一檢索介面 retrieve()（規格 1.4、2.7，A5）。

- mode：lexical / semantic / hybrid；k 預設為 config 的 k_final；回傳前 k 筆，rank 重新編號為 1..k，
  每個 docid 至多一筆。可用筆數不足 k 時回傳較少的筆數。
- retriever 第一次使用時建立，整個 process 只建立一次；hybrid 共用 lexical、semantic 的實例。
- **semantic 尚未接上**（B 的 `rag/semantic.py`）：mode 為 semantic 或 hybrid 時 raise NotImplementedError。
  接上時只需修改 `_semantic()`。fusion 的驗證暫時使用 scratch 中的語意查詢。
"""
from __future__ import annotations

from functools import cache
from typing import Literal

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from rag.config import get_config

MODES = ("lexical", "semantic", "hybrid")


@cache
def _lexical() -> BaseRetriever:
    from rag.lexical import LexicalRetriever   # 延後匯入：只在用到時載入 hwlib
    return LexicalRetriever.from_config()


@cache
def _semantic() -> BaseRetriever:
    raise NotImplementedError(
        "semantic 尚未接上（B 的 rag/semantic.py 完成後才能使用 semantic / hybrid 模式）；"
        "目前請使用 mode='lexical'")


@cache
def _hybrid() -> BaseRetriever:
    from rag.fusion import HybridRetriever
    semantic = _semantic()                     # 先建立 semantic：未接上時不必載入索引
    return HybridRetriever.from_config(_lexical(), semantic)


_FACTORIES = {"lexical": _lexical, "semantic": _semantic, "hybrid": _hybrid}


def retrieve(query: str, k: int | None = None,
             mode: Literal["lexical", "semantic", "hybrid"] = "hybrid") -> list[Document]:
    """k 預設為 config.retrieval.k_final；回傳依 rank 排序、每個 docid 至多一筆。

    Raises:
        ValueError: mode 不是 lexical / semantic / hybrid，或 k 不是 ≥ 1 的整數。
        NotImplementedError: semantic 尚未接上時使用 semantic / hybrid。
        BuildNotDoneError: 建置未完成（由各 retriever 啟動時檢查）。
    """
    if mode not in MODES:
        raise ValueError(f"mode 必須是 {' / '.join(MODES)} 之一，實際為 {mode!r}")
    if k is None:
        k = int(get_config()["retrieval"]["k_final"])
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError(f"k 必須是 ≥ 1 的整數，實際為 {k!r}")
    docs = _FACTORIES[mode]().invoke(query)[:k]
    return [Document(page_content=d.page_content, metadata={**d.metadata, "rank": i, "sources": list(d.metadata["sources"])})
            for i, d in enumerate(docs, 1)]
