"""T4b：拼字更正（只提供「Did you mean」建議，不自動替換）。

dictionary 存的是 stem 過的詞，所以建議的結果也是 stem 形式（例如 retriev）。
k-gram index 與 Soundex 對照表在第一次呼叫時由 reader.vocabulary() 建立，並依 reader 快取在本模組
（writer.py 不動）；vocabulary() 是共用的 list，這裡只讀不改。
"""
from __future__ import annotations

import weakref
from array import array
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from writer import IndexReader

JACCARD_MIN = 0.3

# reader → (vocabulary, gram → array 的 term id, 每個 term 的 bigram 數)
_kgram_cache: "weakref.WeakKeyDictionary[IndexReader, tuple[list[str], dict[str, array], array]]" = \
    weakref.WeakKeyDictionary()
# reader → (Soundex 碼 → 依 (-df, term) 排序的 term list)
_soundex_cache: "weakref.WeakKeyDictionary[IndexReader, dict[str, list[str]]]" = weakref.WeakKeyDictionary()


def _bigrams(term: str) -> set[str]:
    s = f"${term}$"
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _kgram_index(reader: IndexReader) -> tuple[list[str], dict[str, array], array]:
    cached = _kgram_cache.get(reader)
    if cached is None:
        vocab = reader.vocabulary()
        index: dict[str, array] = defaultdict(lambda: array("I"))
        sizes = array("H")
        for tid, term in enumerate(vocab):
            grams = _bigrams(term)
            sizes.append(min(len(grams), 0xFFFF))
            for g in grams:
                index[g].append(tid)
        cached = (vocab, dict(index), sizes)
        _kgram_cache[reader] = cached
    return cached


def _osa(a: str, b: str) -> int:
    """Damerau 距離的 OSA（optimal string alignment）版本：插入、刪除、替換、相鄰對調各算 1。"""
    la, lb = len(a), len(b)
    prev2: list[int] = []
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        ai = a[i - 1]
        for j in range(1, lb + 1):
            bj = b[j - 1]
            d = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ai != bj))
            if i > 1 and j > 1 and ai == b[j - 2] and a[i - 2] == bj:
                d = min(d, prev2[j - 2] + 1)
            cur[j] = d
        prev2, prev = prev, cur
    return prev[lb]


def suggest(term: str, reader: IndexReader, limit: int = 5) -> list[str]:
    """回傳 term 的拼字建議，最多 limit 個。

    以 bigram（前後加 $）的 Jaccard 係數篩選候選，再依
    (edit distance, -df, term) 排序；edit distance 採 Damerau（OSA，相鄰對調算 1）。
    不包含 term 本身。
    """
    if limit < 1:
        return []
    vocab, index, sizes = _kgram_index(reader)
    grams = _bigrams(term)
    overlap: dict[int, int] = defaultdict(int)
    for g in grams:
        for tid in index.get(g, ()):
            overlap[tid] += 1
    n = len(grams)
    cands = []
    for tid, c in overlap.items():
        if c / (n + sizes[tid] - c) >= JACCARD_MIN:
            t = vocab[tid]
            if t != term:
                cands.append(t)
    ranked = sorted(cands, key=lambda t: (_osa(term, t), -reader.df(t), t))
    return ranked[:limit]


_SOUNDEX_CODE = {c: d for d, letters in
                 {"1": "BFPV", "2": "CGJKQSXZ", "3": "DT", "4": "L", "5": "MN", "6": "R"}.items()
                 for c in letters}


def soundex(word: str) -> str:
    """American Soundex 編碼（第一個字母 + 3 位數字，例如 Robert → R163）。

    只看 ASCII 字母（其餘字元略過）；沒有任何字母時回傳空字串。
    相鄰同碼只記一次，第一個字母也算在內（Pfister → P236）；h／w 不隔開同碼（Ashcraft → A261），
    母音（a e i o u y）會隔開（Tymczak → T522）。
    """
    letters = [c for c in word.upper() if "A" <= c <= "Z"]
    if not letters:
        return ""
    first = letters[0]
    digits: list[str] = []
    prev = _SOUNDEX_CODE.get(first, "")
    for c in letters[1:]:
        if c in "HW":
            continue  # 不改 prev：h／w 兩側的同碼視為相鄰
        d = _SOUNDEX_CODE.get(c, "")
        if d and d != prev:
            digits.append(d)
            if len(digits) == 3:
                break
        prev = d  # 母音的 d 是 ""，會隔開兩側的同碼
    return (first + "".join(digits) + "000")[:4]


def _soundex_table(reader: IndexReader) -> dict[str, list[str]]:
    table = _soundex_cache.get(reader)
    if table is None:
        groups: dict[str, list[str]] = defaultdict(list)
        for t in reader.vocabulary():
            if t.isascii() and t.isalpha():
                groups[soundex(t)].append(t)
        table = {code: sorted(ts, key=lambda t: (-reader.df(t), t)) for code, ts in groups.items()}
        _soundex_cache[reader] = table
    return table


def suggest_soundex(term: str, reader: IndexReader, limit: int = 5) -> list[str]:
    """回傳與 term 同 Soundex 碼的 dictionary term，依 (-df, term) 排序，不包含 term 本身。"""
    code = soundex(term)
    if not code or limit < 1:
        return []
    out: list[str] = []
    for t in _soundex_table(reader).get(code, ()):
        if t != term:
            out.append(t)
            if len(out) == limit:
                break
    return out
