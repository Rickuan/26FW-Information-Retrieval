"""T4b：拼字更正（只提供「Did you mean」建議，不自動替換）。

dictionary 存的是 stem 過的詞，所以建議的結果也是 stem 形式（例如 retriev）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from writer import IndexReader


def suggest(term: str, reader: IndexReader, limit: int = 5) -> list[str]:
    """回傳 term 的拼字建議，最多 limit 個。

    以 bigram（前後加 $）的 Jaccard 係數篩選候選，再依
    (edit distance, -df, term) 排序；edit distance 採 Damerau（OSA，相鄰對調算 1）。
    不包含 term 本身。
    """
    raise NotImplementedError


def soundex(word: str) -> str:
    """American Soundex 編碼（第一個字母 + 3 位數字，例如 Robert → R163）。"""
    raise NotImplementedError


def suggest_soundex(term: str, reader: IndexReader, limit: int = 5) -> list[str]:
    """回傳與 term 同 Soundex 碼的 dictionary term，依 (-df, term) 排序，不包含 term 本身。"""
    raise NotImplementedError
