"""HW2 Skip Pointer 與布林交集運算支援。

提供：SkipPointer、PostingWithSkip、build_skip_list、intersect_basic、intersect_with_skips、intersect_postings。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

MIN_SKIP_LEN = 9


@dataclass(slots=True)
class SkipPointer:
    """單一 Skip Pointer 定義：目標 docID 與索引位置。"""
    target_doc_num: int
    target_index: int


@dataclass(slots=True)
class PostingWithSkip:
    """帶有 Skip Pointer 的 Posting 結構。"""
    doc_num: int
    skip: SkipPointer | None = None


def _get_doc_num(item: int | Any) -> int:
    return item if isinstance(item, int) else item.doc_num


def build_skip_list(postings: Sequence[int | Any]) -> list[PostingWithSkip]:
    """為 postings 建立 Skip Pointer（間隔 L = floor(sqrt(P))，P < 9 不建）。"""
    p_len = len(postings)
    if p_len < MIN_SKIP_LEN:
        return [PostingWithSkip(_get_doc_num(p), None) for p in postings]

    interval = math.isqrt(p_len)
    result = [PostingWithSkip(_get_doc_num(p), None) for p in postings]
    for i in range(0, p_len, interval):
        target_idx = i + interval
        if target_idx < p_len:
            result[i].skip = SkipPointer(_get_doc_num(postings[target_idx]), target_idx)
    return result


def intersect_basic(
    p1: Sequence[int | Any],
    p2: Sequence[int | Any],
) -> tuple[list[int], int]:
    """基本線性掃描交集演算法，回傳 (result_doc_nums, n_comparisons)。"""
    result: list[int] = []
    i, j, n_comparisons = 0, 0, 0
    len1, len2 = len(p1), len(p2)

    while i < len1 and j < len2:
        n_comparisons += 1
        d1 = _get_doc_num(p1[i])
        d2 = _get_doc_num(p2[j])
        if d1 == d2:
            result.append(d1)
            i += 1
            j += 1
        elif d1 < d2:
            i += 1
        else:
            j += 1

    return result, n_comparisons


def intersect_with_skips(
    p1: Sequence[PostingWithSkip],
    p2: Sequence[PostingWithSkip],
) -> tuple[list[int], int]:
    """使用 Skip Pointer 連續跳躍之交集演算法（Manning IIR Fig. 2.10）。"""
    result: list[int] = []
    i, j, n_comparisons = 0, 0, 0
    len1, len2 = len(p1), len(p2)

    while i < len1 and j < len2:
        n_comparisons += 1
        d1, d2 = p1[i].doc_num, p2[j].doc_num
        if d1 == d2:
            result.append(d1)
            i += 1
            j += 1
        elif d1 < d2:
            has_skipped = False
            while p1[i].skip is not None:
                n_comparisons += 1
                if p1[i].skip.target_doc_num <= d2:
                    i = p1[i].skip.target_index
                    has_skipped = True
                else:
                    break
            if not has_skipped:
                i += 1
        else:
            has_skipped = False
            while p2[j].skip is not None:
                n_comparisons += 1
                if p2[j].skip.target_doc_num <= d1:
                    j = p2[j].skip.target_index
                    has_skipped = True
                else:
                    break
            if not has_skipped:
                j += 1

    return result, n_comparisons


def intersect_postings(
    docs1: Sequence[int | Any],
    docs2: Sequence[int | Any],
    use_skip: bool = True,
) -> tuple[list[int], int]:
    """統一交集運算入口，支援 int 串列或帶 skip 串列。"""
    if not use_skip:
        return intersect_basic(docs1, docs2)
    s1 = docs1 if (docs1 and isinstance(docs1[0], PostingWithSkip)) else build_skip_list(docs1)
    s2 = docs2 if (docs2 and isinstance(docs2[0], PostingWithSkip)) else build_skip_list(docs2)
    return intersect_with_skips(s1, s2)
