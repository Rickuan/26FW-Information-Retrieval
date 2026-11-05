"""W：共用權重函式（T6 之後在此加入 rank()）。"""
from __future__ import annotations


def weight(tf: int, df: int, N: int) -> float:
    """(1 + log10 tf) * log10(N / df)；tf == 0 或 df == 0 回傳 0.0。"""
    raise NotImplementedError
