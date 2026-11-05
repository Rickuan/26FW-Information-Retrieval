"""T6：VSM 排序。權重公式一律 import 自 weighting.py，不在這裡重寫。"""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from writer import IndexReader


def rank(qtf: Counter[str], candidates: set[int] | None,
         reader: IndexReader) -> list[tuple[int, float]]:
    """依 cosine 排序，回傳 [(doc_num, score), ...]。

    依 (-score, doc_num) 排序；candidates 為 None 時不過濾。
    """
    raise NotImplementedError
