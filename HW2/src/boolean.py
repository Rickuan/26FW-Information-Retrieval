"""T5：Boolean 求值，產生候選文件集合。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from parser import And, Near, Node, Not, Or, Phrase, Soundex, Term, Wildcard
from positional import position_match
from skip_builder import (
    PostingWithSkip,
    SkipPointer,
    build_skip_list,
    intersect_basic,
    intersect_postings,
    intersect_with_skips,
)

if TYPE_CHECKING:
    from writer import IndexReader


def evaluate(node: Node | None, reader: IndexReader) -> set[int] | None:
    """對已經 expand 過的 AST 求出候選 doc_num 集合。

    - node is None → None（空 query 或全 stopword 查詢情境）
    - 根節點是 Term（沒有運算子）→ None，代表不過濾（自由文字由 VSM 排序）
    - And／Or 之下的 Term → 其 tokens 全部出現的文件（以 skip 交集運算）
    - And → 子節點遞迴求值之交集（依大小排序並 short-circuit）
    - Or → 子節點遞迴求值之聯集
    - Not → set(range(reader.N)) 減去 child 的結果
    - Phrase、Near → positional.position_match(node, reader)

    Raises:
        ValueError: 遇到未展開之 Wildcard 或 Soundex（輸入必須先經過 expand）。
    """
    if node is None:
        return None
    if isinstance(node, Term):
        return None
    return _eval(node, reader)


def _eval(node: Node | None, reader: IndexReader) -> set[int]:
    """遞迴評估內部節點，一律回傳 doc_num 集合。"""
    if node is None:
        return set()

    if isinstance(node, Term):
        if not node.tokens:
            return set()

        unique_tokens = sorted(set(node.tokens), key=lambda t: (reader.df(t), t))
        if reader.df(unique_tokens[0]) == 0:
            return set()

        if len(unique_tokens) == 1:
            docs, _ = reader.get_doc_tf(unique_tokens[0])
            return set(docs)

        # 多詞隱含 AND：依 df 遞增以 skip pointer 依序兩兩交集
        current_docs, _ = reader.get_doc_tf(unique_tokens[0])
        if not current_docs:
            return set()

        for tok in unique_tokens[1:]:
            if reader.df(tok) == 0:
                return set()
            next_docs, _ = reader.get_doc_tf(tok)
            if not next_docs:
                return set()
            current_docs, _ = intersect_postings(current_docs, next_docs, use_skip=True)
            if not current_docs:
                return set()

        return set(current_docs)

    elif isinstance(node, And):
        if not node.children:
            return set()
        child_sets = [_eval(c, reader) for c in node.children]
        child_sets.sort(key=len)
        res = child_sets[0]
        for s in child_sets[1:]:
            if not res:
                return set()
            res = res & s
        return res

    elif isinstance(node, Or):
        if not node.children:
            return set()
        res: set[int] = set()
        for c in node.children:
            res |= _eval(c, reader)
        return res

    elif isinstance(node, Not):
        child_res = _eval(node.child, reader)
        return set(range(reader.N)) - child_res

    elif isinstance(node, (Phrase, Near)):
        return position_match(node, reader)

    elif isinstance(node, (Wildcard, Soundex)):
        raise ValueError(f"evaluate: unexpanded {type(node).__name__}; call expand() first")

    else:
        raise TypeError(f"evaluate: unexpected node type {type(node).__name__}")
