"""Module 5：Skip Builder & AND Query 演算法實作。

提供：
  - SkipPointer、PostingWithSkip 資料結構
  - build_skip_list：為單一 postings list 建立間隔 L = floor(sqrt(P)) 之 skip 指標
  - SkipBuilder：走訪全記憶體 Indexer 並產出帶 skip 之倒排索引
  - intersect_basic：基本線性比對交集演算法
  - intersect_with_skips：Manning IIR Fig. 2.10 連續跳躍之 skip 交集演算法
  - and_query：整合 Preprocessor 正規化之布林 AND 查詢入口
"""
from __future__ import annotations

import math
import resource
import sys
import time
from array import array
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from indexer import Indexer, Posting
    from tokenizer import Preprocessor

# 最小建立 Skip Pointer 的 postings 長度門檻（P < 9 不建立）
MIN_SKIP_LEN = 9


@dataclass(slots=True)
class SkipPointer:
    """單一 Skip Pointer 定義。

    Attributes:
        target_doc_num: 跳躍目標節點的 docID（用於數值條件比對）
        target_index: 跳躍目標在 list 中的索引位置（用於直接推進指標）
    """
    target_doc_num: int
    target_index: int


@dataclass(slots=True)
class PostingWithSkip:
    """帶有 Skip Pointer 的 Posting 結構。

    已將 positions 欄位移除以節省記憶體，僅保留布林檢索所需的 doc_num 與 skip 指標。
    """
    doc_num: int
    skip: SkipPointer | None = None


def build_skip_list(postings: list[Any]) -> list[PostingWithSkip]:
    """為單一 postings list 建立 Skip Pointer。

    間隔規則：
      L = floor(sqrt(P))
      當 P < 9 時不建立任何 skip pointer（全部為 None）。
      僅在 index 0, L, 2L, ... 且 i + L < P 時建立 skip 指向 i + L。

    Args:
        postings: 原始 Posting 串列（來自 M3 Indexer）

    Returns:
        包含 SkipPointer 的 PostingWithSkip 串列
    """
    p_len = len(postings)
    if p_len < MIN_SKIP_LEN:
        return [PostingWithSkip(p.doc_num, None) for p in postings]

    interval = math.isqrt(p_len)
    result = [PostingWithSkip(p.doc_num, None) for p in postings]

    for i in range(0, p_len, interval):
        target_idx = i + interval
        if target_idx < p_len:
            result[i].skip = SkipPointer(
                target_doc_num=postings[target_idx].doc_num,
                target_index=target_idx,
            )

    return result


class SkipBuilder:
    """走訪 Indexer 並建置全量詞彙的 Skip Pointer 倒排表。"""

    MIN_SKIP_LEN: int = MIN_SKIP_LEN

    def build(self, indexer: Indexer) -> dict[str, list[PostingWithSkip]]:
        """走訪全記憶體模式的 Indexer，建立含 skip 的 postings 索引。

        Args:
            indexer: M3 Indexer 物件

        Returns:
            dict[str, list[PostingWithSkip]]：以 term 為鍵的帶 skip 倒排索引。
            若為 SPIMI 模式則印出提示並回傳空 dict。
        """
        if getattr(indexer, "spimi", False):
            print("[SkipBuilder] 提示：Indexer 處於 SPIMI 模式（記憶體無全量索引），跳過 Skip List 建置。")
            return {}

        rss_scale = 1024 * 1024 if sys.platform == "darwin" else 1024
        rss_start = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / rss_scale

        t0 = time.time()
        skips: dict[str, list[PostingWithSkip]] = {}
        skip_terms_count = 0
        total_interval = 0

        for term, plist in indexer.iter_postings():
            slist = build_skip_list(plist)
            skips[term] = slist
            if len(plist) >= self.MIN_SKIP_LEN:
                skip_terms_count += 1
                total_interval += math.isqrt(len(plist))

        elapsed = time.time() - t0
        rss_end = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / rss_scale
        rss_delta = max(0.0, rss_end - rss_start)

        avg_interval = (total_interval / skip_terms_count) if skip_terms_count > 0 else 0.0

        print(f"[SkipBuilder] 建置完成：共 {len(skips):,} 個詞彙")
        print(f"  - 具備 Skip Pointer 的詞彙數 (df >= {self.MIN_SKIP_LEN})：{skip_terms_count:,}")
        print(f"  - 平均 Skip 間隔 (L)：{avg_interval:.2f}")
        print(f"  - 耗時：{elapsed:.2f} s")
        print(f"  - Peak RSS 變化：{rss_start:.1f} MB -> {rss_end:.1f} MB (增加約 {rss_delta:.1f} MB)")

        return skips

    def build_term(self, term: str, indexer: Indexer) -> list[PostingWithSkip]:
        """隨需為單一詞彙建置 Skip List（不需先全量建置）。"""
        plist = indexer.get_postings(term)
        return build_skip_list(plist)


def intersect_basic(
    p1: list[Any],
    p2: list[Any],
) -> tuple[list[int], int]:
    """基本線性掃描交集演算法。

    Args:
        p1: 第一個 postings 串列（支援 Posting 或 PostingWithSkip）
        p2: 第二個 postings 串列（支援 Posting 或 PostingWithSkip）

    Returns:
        (result_doc_nums, n_comparisons)
    """
    result: list[int] = []
    i = 0
    j = 0
    n_comparisons = 0
    len1 = len(p1)
    len2 = len(p2)

    while i < len1 and j < len2:
        n_comparisons += 1
        d1 = p1[i].doc_num
        d2 = p2[j].doc_num

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
    p1: list[PostingWithSkip],
    p2: list[PostingWithSkip],
) -> tuple[list[int], int]:
    """使用 Skip Pointer 的交集演算法（採用 Manning IIR Fig. 2.10 連續跳躍標準）。

    比較次數準則：
      1. 外層迴圈當前文件比對（d1 == d2, d1 < d2）：計 1 次比對。
      2. Skip 條件判定：每次評估 skip.target_doc_num <= target 時，計 1 次數值比較。

    Args:
        p1: 第一個 PostingWithSkip 串列
        p2: 第二個 PostingWithSkip 串列

    Returns:
        (result_doc_nums, n_comparisons)
    """
    result: list[int] = []
    i = 0
    j = 0
    n_comparisons = 0
    len1 = len(p1)
    len2 = len(p2)

    while i < len1 and j < len2:
        n_comparisons += 1
        d1 = p1[i].doc_num
        d2 = p2[j].doc_num

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


def and_query(
    skips: dict[str, list[PostingWithSkip]],
    preprocessor: Preprocessor,
    q1: str,
    q2: str,
    use_skips: bool = True,
) -> tuple[list[int], int]:
    """布林雙詞 AND 查詢入口。

    查詢詞先經由 Preprocessor 處理（含大小寫折疊與字幹提取）；
    若詞彙被停用詞清空或不在索引中，印出提示並回傳空結果。

    Args:
        skips: 已建置好之帶 skip 倒排字典
        preprocessor: 與 Indexer 相同配置之 Preprocessor
        q1: 第一個查詢詞
        q2: 第二個查詢詞
        use_skips: 是否啟用 skip pointer 比對（預設 True）

    Returns:
        (交集 doc_num 串列, 比較次數)
    """
    toks1 = preprocessor.process(q1)
    if not toks1:
        print(f"[and_query] 提示：查詢詞 {q1!r} 經正規化後為空（如停用詞），回傳空交集。")
        return [], 0

    toks2 = preprocessor.process(q2)
    if not toks2:
        print(f"[and_query] 提示：查詢詞 {q2!r} 經正規化後為空（如停用詞），回傳空交集。")
        return [], 0

    term1 = toks1[0][1]
    term2 = toks2[0][1]

    p1 = skips.get(term1)
    if p1 is None:
        print(f"[and_query] 提示：詞彙 {term1!r} 不存在於索引中。")
        return [], 0

    p2 = skips.get(term2)
    if p2 is None:
        print(f"[and_query] 提示：詞彙 {term2!r} 不存在於索引中。")
        return [], 0

    if use_skips:
        return intersect_with_skips(p1, p2)
    return intersect_basic(p1, p2)
