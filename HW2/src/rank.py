"""T6：VSM 排序引擎。

以向量空間模型（VSM）計算 query 與候選文件之相似度，支援 SMART 方案與 Champion list 加分項。
權重公式一律 import 自 weighting.py，不在這裡重寫。
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import TYPE_CHECKING

from weighting import formula, weight

if TYPE_CHECKING:
    from writer import IndexReader


def _parse_scheme(scheme: str) -> tuple[str, str]:
    """嚴格解析 SMART scheme 字串，格式必須為 '<doc_scheme>.<query_scheme>'。

    Raises:
        ValueError: 格式不符、非剛好 1 個小數點、長度非 7 碼、或單邊 scheme 非法。
    """
    if not isinstance(scheme, str) or scheme.count(".") != 1 or len(scheme) != 7:
        raise ValueError(f"invalid scheme format: {scheme!r}, expected '<doc>.<query>' (7 chars)")
    doc_scheme, query_scheme = scheme.split(".")
    # 利用 formula() 檢查前後 3 碼合法性（非法時 formula 內部會拋出 ValueError）
    formula(doc_scheme)
    formula(query_scheme)
    return doc_scheme, query_scheme


def rank(
    qtf: Counter[str],
    candidates: set[int] | None,
    reader: IndexReader,
    scheme: str = "ltc.ltc",
    champion_r: int | None = None,
) -> list[tuple[int, float]]:
    """依 VSM 相似度排序，回傳 [(doc_num, score), ...]。

    依 (-score, doc_num) 嚴格排序；candidates 為 None 時代表自由文字不過濾；
    僅回傳 score > 0 之文件。

    Args:
        qtf: query 評分詞與詞頻 (tf_{t,q})。
        candidates: 候選 docID 集合（來自 T5 Boolean 求值）；None 代表全語料不過濾。
        reader: IndexReader 實例。
        scheme: SMART 標記方案，格式為 '<doc_scheme>.<query_scheme>'（預設 'ltc.ltc'）。
        champion_r: 若指定則使用 df > r 之 champion list 進行不精確 top-k 召回。

    Returns:
        排序後之 (doc_num, score) 清單。

    Raises:
        ValueError: scheme 格式不合法或 champion_r < 1。
    """
    if champion_r is not None and champion_r < 1:
        raise ValueError(f"champion_r must be >= 1, got {champion_r}")

    doc_scheme, query_scheme = _parse_scheme(scheme)

    # 提早 short-circuit：候選集為空或 qtf 為空（如純 NOT 查詢無評分詞）
    if (candidates is not None and len(candidates) == 0) or not qtf:
        return []

    # 1. Query 向量計算與長度正規化
    q_weights: dict[str, tuple[int, float]] = {}  # term -> (df, w_tq)
    for term, tf_q in qtf.items():
        df = reader.df(term)
        if df <= 0:
            continue
        w_tq = weight(tf_q, df, reader.N, query_scheme)
        if w_tq > 0.0:
            q_weights[term] = (df, w_tq)

    if not q_weights:
        return []

    if query_scheme[2] == "c":
        q_norm = math.sqrt(sum(w ** 2 for _, w in q_weights.values()))
    else:  # "n"
        q_norm = 1.0

    if q_norm <= 0.0:
        return []

    # 2. Term-at-a-time (TAAT) 分子累加器
    acc: dict[int, float] = defaultdict(float)
    for term, (df, w_tq) in q_weights.items():
        if champion_r is not None:
            doc_nums, tfs = reader.get_champions(term, r=champion_r)
        else:
            doc_nums, tfs = reader.get_doc_tf(term)

        for d, tf in zip(doc_nums, tfs):
            if candidates is not None and d not in candidates:
                continue
            w_td = weight(tf, df, reader.N, doc_scheme)
            if w_td > 0.0:
                acc[d] += w_td * w_tq

    # 若無任何文件命中，提早返回以避免讀取 norms 檔之 I/O
    if not acc:
        return []

    # 3. 相似度計算、破同分與回傳
    norms = reader.get_norms(doc_scheme)
    hits: list[tuple[int, float]] = []
    for d, dot in acc.items():
        d_norm = norms[d]
        if d_norm <= 0.0:
            continue
        score = dot / (d_norm * q_norm)
        if score > 0.0:
            hits.append((d, score))

    # 分數高者在前；同分時依 doc_num 由小到大嚴格遞增
    hits.sort(key=lambda x: (-x[1], x[0]))
    return hits
