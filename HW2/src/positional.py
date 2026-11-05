"""T4b：Phrase／Near 的 position 比對，由 T5 的 evaluate 呼叫。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from parser import Near, Phrase

if TYPE_CHECKING:
    from writer import IndexReader


def position_match(node: Phrase | Near, reader: IndexReader) -> set[int]:
    """用 get_postings 的 positions 找出符合 Phrase／Near 的文件。

    Phrase：存在 p，使每個 tokens[i] 都出現在 p + (positions[i] - positions[0])。
    Near：left 與 right 的某對位置差的絕對值 ≤ k。
    位置以含 stopword 的 token 位置計算（與 index 相同）。
    """
    raise NotImplementedError
