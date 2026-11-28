"""詞彙檢索：HW2 的 VSM（ltc.ltc，自由文字路徑）+ 每篇挑最佳 passage（規格 2.6，A5）。

- query 以 `hw_bridge.preprocess` 轉成 term 序列，不經過 HW2 的 query parser
  （parser 會把 AND/OR/NOT、引號、括號當語法處理，未配對的引號會 raise）。
- 每篇的最佳 passage：先比命中的不同 query term 數，再比總命中次數，同分取 pid 較小者；
  都沒命中時取 pid 最小的一段。不使用索引的位置資訊（位置對不回清理後文字的字位置）。
- 建構一律用 `LexicalRetriever.from_config()`：先 require_build_done，才載入索引與 docstore。
"""
from __future__ import annotations

import sys
from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import PrivateAttr

from rag import hw_bridge
from rag.config import get_config, paths, require_build_done
from rag.docstore import DocStore, Passage

SOURCE = "lexical"


def passage_hits(query_terms: set[str], passage_text: str) -> tuple[int, int]:
    """回傳 (命中的不同 query term 數, query term 的總命中次數)。"""
    distinct: set[str] = set()
    total = 0
    for t in hw_bridge.preprocess(passage_text):
        if t in query_terms:
            distinct.add(t)
            total += 1
    return len(distinct), total


def best_passage(query_terms: set[str], passages: list[Passage]) -> tuple[Passage, tuple[int, int]]:
    """挑出最佳 passage，回傳 (passage, (不同 term 數, 總命中次數))。

    排序鍵 (不同 term 數, 總次數) 取最大，同分取 pid 較小者；passages 不可為空。
    """
    if not passages:
        raise ValueError("passages 不可為空")
    ordered = sorted(passages, key=lambda p: p.pid)
    best, best_key = ordered[0], passage_hits(query_terms, ordered[0].text)
    for p in ordered[1:]:
        key = passage_hits(query_terms, p.text)
        if key > best_key:          # 嚴格大於：同分保留 pid 較小者
            best, best_key = p, key
    return best, best_key


class LexicalRetriever(BaseRetriever):
    """回傳 top-k 篇，每篇一段最佳 passage；metadata 依規格 1.4。"""

    k: int
    _ranker: Any = PrivateAttr(default=None)
    _docstore: Any = PrivateAttr(default=None)

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None = None) -> LexicalRetriever:
        """路徑取自 paths(use_fixtures)；建置未完成時 raise BuildNotDoneError，不載入索引。"""
        cfg = cfg or get_config()
        p = paths(cfg["runtime"]["use_fixtures"], cfg)
        require_build_done(p["build_meta"])
        r = cls(k=int(cfg["retrieval"]["k_each"]))
        r._ranker = hw_bridge.load_ranker(p["index_dir"])
        r._docstore = DocStore(p["docstore"])
        return r

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun | None = None,
    ) -> list[Document]:
        terms = hw_bridge.preprocess(query)
        if not terms:
            return []
        query_terms = set(terms)
        out: list[Document] = []
        for docid, score in self._ranker.search(terms, self.k):
            passages = self._docstore.get_passages_by_doc(docid)
            if not passages:
                print(f"[lexical] docid {docid} 沒有 passage，略過", file=sys.stderr)
                continue
            passage, _ = best_passage(query_terms, passages)
            doc = self._docstore.get_doc(docid)
            out.append(Document(page_content=passage.text, metadata={
                "docid": int(docid),
                "trec_id": doc.trec_id,
                "url": doc.url or "",
                "pid": passage.pid,
                "score": float(score),
                "rank": len(out) + 1,
                "sources": [SOURCE],
            }))
        return out
