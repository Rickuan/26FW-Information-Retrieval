"""T7 CLI 查詢介面與端到端搜尋引擎。

整合 Preprocessor (T1)、Parser (T4)、Boolean (T5) 與 VSM Rank (T6)，
提供 search_query 函式與 CLI 執行入口。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from boolean import evaluate
from parser import expand, parse, query_terms, query_words
from rank import rank
from spelling import did_you_mean
from tokenizer import Preprocessor
from writer import IndexReader


def search_query(
    query: str,
    reader: IndexReader,
    pre: Preprocessor,
    scheme: str = "ltc.ltc",
    champion_r: int | None = None,
    top_k: int | None = None,
) -> list[tuple[int, float]]:
    """執行單一查詢的端到端檢索管線。

    流程：
    1. parse(query, pre)：語法解析；語法不合法時拋出 ValueError。
    2. expand(node, reader)：原字展開 Wildcard / Soundex。
    3. 若 node 為 None（如空字串或全停用詞），回傳 []。
    4. evaluate(node, reader)：求得布林候選文件集合（自由文字回傳 None）。
    5. query_terms(node)：提取評分詞與 query tf；若為空（如純 NOT），回傳 []。
    6. rank(qtf, cands, reader, scheme=scheme, champion_r=champion_r)：計算分數並排序。
    7. 若指定 top_k，取前 top_k 筆（top_k < 1 時拋出 ValueError）。
    """
    if top_k is not None and top_k < 1:
        raise ValueError(f"top_k must be positive, got {top_k}")

    node = parse(query, pre)
    if node is None:
        return []

    node = expand(node, reader)
    if node is None:
        return []

    candidates = evaluate(node, reader)
    qtf = query_terms(node)
    if not qtf:
        return []

    hits = rank(qtf, candidates, reader, scheme=scheme, champion_r=champion_r)
    if top_k is not None:
        hits = hits[:top_k]
    return hits
