"""T4b：Phrase／Near 的 position 比對，由 T5 的 evaluate 呼叫。"""
from __future__ import annotations

from bisect import bisect_left
from typing import TYPE_CHECKING

from parser import Near, Phrase

if TYPE_CHECKING:
    from writer import IndexReader

Interval = tuple[int, int]  # [start, end]，以 index 的位置計算（含 stopword 空洞）


def position_match(node: Phrase | Near, reader: IndexReader) -> set[int]:
    """用 get_postings 的 positions 找出符合 Phrase／Near 的文件。

    Phrase：存在 p，使每個 tokens[i] 都出現在 p + (positions[i] - positions[0])；
    每個符合的 p 對應一個位置區間 [p, p + positions[-1] - positions[0]]。
    Near：兩側各自依 Phrase 的規則找出位置區間（單一 token 時 start == end），兩段區間之間的間隔
    （右側在後時是 R.start − L.end，左側在後時是 L.start − R.end）在 1..k 之間就命中；
    不分左右順序，兩段區間重疊時不算命中。一篇文件內只要有任一組區間命中就算符合。
    位置以含 stopword 的 token 位置計算（與 index 相同）。
    每個不同的 token 只呼叫一次 get_postings（Near 兩側共用）。
    """
    if isinstance(node, Phrase):
        phrases = [node]
    elif isinstance(node, Near):
        phrases = [node.left, node.right]
    else:
        raise TypeError(f"position_match: expected Phrase or Near, got {type(node).__name__}")
    if any(not ph.tokens for ph in phrases):
        return set()  # parse 不會產生空的 Phrase／Near 側；手建的節點視為沒有文件符合

    postings = _load_positions({t for ph in phrases for t in ph.tokens}, reader)
    if postings is None:
        return set()

    if isinstance(node, Phrase):
        return set(_phrase_intervals(node, postings))

    left = _phrase_intervals(node.left, postings)
    right = _phrase_intervals(node.right, postings)
    k = node.k
    hits: set[int] = set()
    for doc, l_ivs in left.items():
        r_ivs = right.get(doc)
        if r_ivs is not None and _near_hit(l_ivs, r_ivs, k):
            hits.add(doc)
    return hits


def _load_positions(terms: set[str], reader: IndexReader) -> dict[str, dict[int, object]] | None:
    """每個 term 呼叫一次 get_postings，只保留全部 term 都出現的文件：term → {doc: positions}。

    依 df 由小到大讀，候選文件集合變空時就停（不再讀剩下的高 df term），回傳 None。
    """
    order = sorted(terms, key=lambda t: (reader.df(t), t))
    by_term: dict[str, dict[int, object]] = {}
    cands: set[int] | None = None
    for t in order:
        plist = reader.get_postings(t)
        if cands is None:
            m = {p.doc_num: p.positions for p in plist}
            cands = set(m)
        else:
            m = {p.doc_num: p.positions for p in plist if p.doc_num in cands}
            cands &= m.keys()
        by_term[t] = m
        if not cands:
            return None
    return {t: {d: m[d] for d in cands} for t, m in by_term.items()}


def _phrase_intervals(phrase: Phrase, postings: dict[str, dict[int, object]]) -> dict[int, list[Interval]]:
    """每篇候選文件中 phrase 完整出現的位置區間，依 start 遞增；沒有出現的文件不列入。"""
    toks, poss = phrase.tokens, phrase.positions
    base = poss[0]
    span = poss[-1] - base
    first = postings[toks[0]]
    # 其餘 token 的 (相對位移, 該 token 的 doc → positions)；同一個 token 出現兩次時共用同一份
    rest = [(p - base, postings[t]) for t, p in zip(toks[1:], poss[1:])]
    out: dict[int, list[Interval]] = {}
    for doc, pos0 in first.items():
        if rest:
            sets = [(off, set(m[doc])) for off, m in rest]
            starts = [p for p in pos0 if all(p + off in s for off, s in sets)]
        else:
            starts = list(pos0)
        if starts:
            out[doc] = [(p, p + span) for p in starts]  # positions 已遞增，所以 starts 也是
    return out


def _near_hit(left: list[Interval], right: list[Interval], k: int) -> bool:
    """是否存在 (L, R) 使 1 ≤ R.start − L.end ≤ k 或 1 ≤ L.start − R.end ≤ k。

    同一側的區間長度固定，所以依 start 排序後 end 也是遞增，可以用 bisect 查範圍。
    """
    r_starts = [s for s, _ in right]
    r_ends = [e for _, e in right]
    for ls, le in left:
        # 右側在後：R.start ∈ [L.end + 1, L.end + k]
        i = bisect_left(r_starts, le + 1)
        if i < len(r_starts) and r_starts[i] <= le + k:
            return True
        # 左側在後：R.end ∈ [L.start − k, L.start − 1]
        j = bisect_left(r_ends, ls - k)
        if j < len(r_ends) and r_ends[j] <= ls - 1:
            return True
    return False
