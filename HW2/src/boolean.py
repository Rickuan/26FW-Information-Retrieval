"""T5：Boolean 求值，產生候選文件集合。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from parser import Node

if TYPE_CHECKING:
    from writer import IndexReader


def evaluate(node: Node, reader: IndexReader) -> set[int] | None:
    """對已經 expand 過的 AST 求出候選 doc_num 集合。

    - 根節點是 Term（沒有運算子）→ None，代表不過濾
    - And／Or 之下的 Term → 其 tokens 全部出現的文件
    - Not → set(range(reader.N)) 減去 child 的結果
    - Phrase、Near → positional.position_match(node, reader)

    Raises:
        ValueError: 遇到 Wildcard（輸入必須先經過 expand）。
    """
    raise NotImplementedError
