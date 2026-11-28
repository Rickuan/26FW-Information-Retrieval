"""RRF 合併詞彙、語意兩路的檢索結果（規格 2.7，A5）。

- 以 docid 為單位合併：`score(d) = Σ 1 / (rrf_k + rank_i(d))`，rank_i 取該路清單的位置（1 起算），
  不使用上游的 metadata["rank"]。排序以 `fractions.Fraction` 精確比較，metadata["score"] 存 float。
- 同分規則（A5 決定 (a)）：兩路都有 > 只有詞彙 > 只有語意；仍同分時依 docid 遞增。
- 語意門檻（A5 決定 (d)）：只出現在語意那一路、且語意分數低於 `semantic_min_score` 的文件不納入；
  兩路都有的文件不受門檻影響。語意那一路的名次不因過濾而改變。
- passage：兩路都有時用語意那一路的 pid 與內容，否則用該路的。
- 只依賴 langchain_core：不匯入 lexical / semantic / hwlib / faiss（組裝放在 retrieve.py）。
"""
from __future__ import annotations

from fractions import Fraction
from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from rag.config import get_config

LEXICAL, SEMANTIC = "lexical", "semantic"

# 同分時的類別順序（數字小者在前）
_BOTH, _LEXICAL_ONLY, _SEMANTIC_ONLY = 0, 1, 2


def _positions(docs: list[Document], name: str) -> dict[int, tuple[int, Document]]:
    """docid → (清單位置 1 起算, Document)；同一清單 docid 重複時 raise ValueError。"""
    out: dict[int, tuple[int, Document]] = {}
    for i, d in enumerate(docs, 1):
        docid = int(d.metadata["docid"])
        if docid in out:
            raise ValueError(f"{name} 那一路的結果中 docid {docid} 重複（應先依 docid 去重）")
        out[docid] = (i, d)
    return out


def rrf_fuse(lexical: list[Document], semantic: list[Document], *, rrf_k: int,
             semantic_min_score: float | None = None) -> list[Document]:
    """合併兩路結果，回傳依 RRF 排序的全部文件（rank 為 1..n，每個 docid 一筆）。

    Args:
        lexical, semantic: 各自依 rank 排序、docid 不重複的檢索結果（metadata 依規格 1.4）。
        rrf_k: RRF 常數（config 的 rrf_k），必須是 ≥ 0 的整數。
        semantic_min_score: 只出現在語意那一路的文件，語意 metadata["score"] 低於此值就不納入；
            None 表示不過濾。

    Raises:
        ValueError: rrf_k 不合法，或同一路中 docid 重複。
    """
    if isinstance(rrf_k, bool) or not isinstance(rrf_k, int) or rrf_k < 0:
        raise ValueError(f"rrf_k 必須是 ≥ 0 的整數，實際為 {rrf_k!r}")
    lex = _positions(lexical, LEXICAL)
    sem = _positions(semantic, SEMANTIC)

    ranked: list[tuple[tuple[Fraction, int, int], Document, Fraction, list[str]]] = []
    for docid in lex.keys() | sem.keys():
        in_lex, in_sem = docid in lex, docid in sem
        if (not in_lex and semantic_min_score is not None
                and float(sem[docid][1].metadata["score"]) < semantic_min_score):
            continue
        score = Fraction(0)
        if in_lex:
            score += Fraction(1, rrf_k + lex[docid][0])
        if in_sem:
            score += Fraction(1, rrf_k + sem[docid][0])
        category = _BOTH if in_lex and in_sem else (_LEXICAL_ONLY if in_lex else _SEMANTIC_ONLY)
        sources = [name for name, hit in ((LEXICAL, in_lex), (SEMANTIC, in_sem)) if hit]
        base = sem[docid][1] if in_sem else lex[docid][1]
        ranked.append(((-score, category, docid), base, score, sources))

    ranked.sort(key=lambda item: item[0])
    out: list[Document] = []
    for rank, (key, base, score, sources) in enumerate(ranked, 1):
        m = base.metadata
        out.append(Document(page_content=base.page_content, metadata={
            "docid": key[2],
            "trec_id": m["trec_id"],
            "url": m["url"],
            "pid": int(m["pid"]),
            "score": float(score),
            "rank": rank,
            "sources": sources,
        }))
    return out


class HybridRetriever(BaseRetriever):
    """兩路各 invoke 一次後以 rrf_fuse 合併；回傳全部合併結果（截斷交給 retrieve）。"""

    lexical: BaseRetriever
    semantic: BaseRetriever
    rrf_k: int
    semantic_min_score: float | None = None

    @classmethod
    def from_config(cls, lexical: BaseRetriever, semantic: BaseRetriever,
                    cfg: dict[str, Any] | None = None) -> HybridRetriever:
        r = (cfg or get_config())["retrieval"]
        return cls(lexical=lexical, semantic=semantic, rrf_k=int(r["rrf_k"]),
                   semantic_min_score=float(r["semantic_min_score"]))

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun | None = None,
    ) -> list[Document]:
        config = {"callbacks": run_manager.get_child()} if run_manager else None
        lexical = self.lexical.invoke(query, config=config)
        semantic = self.semantic.invoke(query, config=config)
        return rrf_fuse(lexical, semantic, rrf_k=self.rrf_k,
                        semantic_min_score=self.semantic_min_score)
