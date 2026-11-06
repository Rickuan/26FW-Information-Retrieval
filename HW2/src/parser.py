"""T4：Query parser。

查詢流程：parse → expand → evaluate（T5）→ query_terms → rank（T6）。
只有一個遞迴下降 parser。T4a／T4b 只是實作順序與 commit 切分：
T4a 先做 Term、And、Or；T4b 再加入 Phrase、Near、Wildcard、Not 與括號。
"""
from __future__ import annotations

import re
import warnings
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tokenizer import Preprocessor

if TYPE_CHECKING:
    from writer import IndexReader


@dataclass
class Term:
    tokens: list[str]  # 沒加引號的運算元經 process 後的所有 term，隱含 AND


@dataclass
class Phrase:
    tokens: list[str]     # "..." 內經 process 後的 term
    positions: list[int]  # 取自 process，保留 stopword 空洞；與 tokens 一一對應


@dataclass
class Near:
    left: Phrase   # 單一 token 視為長度 1 的 Phrase（linux → Phrase(['linux'], [1])）
    right: Phrase
    k: int  # 兩段 phrase 位置區間之間的間隔 ≤ k，不分先後；位置含 stopword 空洞


@dataclass
class Wildcard:
    prefix: str  # comput* 的 "comput"：只做 casefold，不做 stem


@dataclass
class Not:
    child: "Node"


@dataclass
class And:
    children: list["Node"]


@dataclass
class Or:
    children: list["Node"]


Node = Term | Phrase | Near | Wildcard | Not | And | Or


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------
# 一開始就辨識全部 token 類型（T4b 不必重寫）：
#   "..."（PHRASE，結尾引號可能缺少，由 parser 判斷）、( 、)、其餘不含空白／括號／引號的字串。
_TOKEN_RE = re.compile(r'"[^"]*"?|[()]|[^\s()"]+')
_NEAR_RE = re.compile(r"/\d+")
_OPERATORS = {"AND", "OR", "NOT"}  # 只有獨立的大寫才是運算子；and、Or、ANDROID 都是 WORD

Token = tuple[str, str, int]  # (kind, text, pos)；pos 是字元位置，從 0 起算


def _lex(query: str) -> list[Token]:
    """把 query 切成 token：kind 為 WORD、AND、OR、NOT、(、)、PHRASE、WILDCARD、NEAR。

    運算子在 process 之前就切出來，因為 and／or 是 stopword，順序反過來會被濾掉。
    PHRASE 的 text 保留引號（含沒有配對的情況）；WILDCARD 是結尾為 * 的詞；NEAR 是整個 token 符合 /\\d+。
    """
    tokens: list[Token] = []
    for m in _TOKEN_RE.finditer(query):
        text, pos = m.group(), m.start()
        if text.startswith('"'):
            kind = "PHRASE"
        elif text in ("(", ")"):
            kind = text
        elif text in _OPERATORS:
            kind = text
        elif _NEAR_RE.fullmatch(text):
            kind = "NEAR"
        elif text.endswith("*"):
            kind = "WILDCARD"
        else:
            kind = "WORD"
        tokens.append((kind, text, pos))
    return tokens


# ---------------------------------------------------------------------------
# Parser（遞迴下降）
# ---------------------------------------------------------------------------
_BONUS_SYNTAX = {
    "NOT": "NOT operator",
    "(": "parentheses",
    ")": "parentheses",
    "PHRASE": "quoted phrase",
    "WILDCARD": "wildcard (prefix*)",
    "NEAR": "proximity (/k)",
}
# 能開始一個 unary 的 token：出現在運算元之後時視為隱含 AND（T4b）。
# T4a 中連續的 WORD 已在 primary 合併，所以這裡只會碰到加分語法。
_UNARY_START = {"WORD", "NOT", "(", "PHRASE", "WILDCARD"}


def _unsupported(tok: Token) -> NotImplementedError:
    kind, text, pos = tok
    return NotImplementedError(f"T4b: {_BONUS_SYNTAX[kind]} not implemented yet ({text!r} at position {pos})")


class _Parser:
    """or := and ("OR" and)*；and := unary (["AND"] unary)*；primary := WORD+（T4a）。"""

    def __init__(self, tokens: list[Token], pre: Preprocessor):
        self.tokens = tokens
        self.i = 0
        self.pre = pre

    def peek(self) -> Token | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def peek_kind(self) -> str | None:
        tok = self.peek()
        return tok[0] if tok else None

    def parse(self) -> Node:
        node = self.parse_or()
        tok = self.peek()
        if tok is not None:
            # T4a 走到這裡只可能是加分語法（例如多出來的 ")"）；T4b 改成 ValueError 等處理
            raise _unsupported(tok)
        return node

    def parse_or(self) -> Node:
        children = [self.parse_and()]
        while self.peek_kind() == "OR":
            self.i += 1
            children.append(self.parse_and())
        return children[0] if len(children) == 1 else Or(children)

    def parse_and(self) -> Node:
        children = [self.parse_unary()]
        while (kind := self.peek_kind()) == "AND" or kind in _UNARY_START:
            if kind == "AND":
                self.i += 1
            children.append(self.parse_unary())
        return children[0] if len(children) == 1 else And(children)

    def parse_unary(self) -> Node:
        tok = self.peek()
        if tok is not None and tok[0] == "NOT":
            raise _unsupported(tok)  # T4b
        return self.parse_primary()

    def parse_primary(self) -> Node:
        tok = self.peek()
        if tok is not None and tok[0] in _BONUS_SYNTAX:
            raise _unsupported(tok)  # T4b：(、PHRASE、WILDCARD、NEAR
        words: list[str] = []
        while self.peek_kind() == "WORD":
            words.append(self.tokens[self.i][1])
            self.i += 1
        # 少了運算元（運算子相鄰、開頭或結尾）時 words 是空的 → Term([])，交給 _prune
        return Term([t for _, t in self.pre.process(" ".join(words))]) if words else Term([])


# ---------------------------------------------------------------------------
# 空節點規則
# ---------------------------------------------------------------------------
def _prune(node: Node) -> Node | None:
    """空節點規則（在樹上處理），回傳新的樹；整棵樹都是空的時回傳 None。

    - 空的 Term 移除，每移除一個警告一次（根節點本身是空的也算）
    - 沒有 child 的 And／Or 移除；只剩一個 child 時攤平成那個 child
    - 同類型的巢狀節點合併：And([And([a, b]), c]) → And([a, b, c])（T4.md §4.4 D3）
    - Not 的 child 是空的就移除這個 Not
    Phrase、Near、Wildcard 的規則屬於 T4b，目前原樣保留。
    """
    if isinstance(node, Term):
        if not node.tokens:
            warnings.warn("empty operand removed from query (only stopwords or a missing operand)",
                          stacklevel=2)
            return None
        return node
    if isinstance(node, (And, Or)):
        kind = type(node)
        children: list[Node] = []
        for child in node.children:
            pruned = _prune(child)
            if pruned is None:
                continue
            if isinstance(pruned, kind):  # child 已經 prune 過，所以只需攤平一層
                children.extend(pruned.children)
            else:
                children.append(pruned)
        if not children:
            return None
        if len(children) == 1:
            return children[0]
        return kind(children)
    if isinstance(node, Not):
        child = _prune(node.child)
        return None if child is None else Not(child)
    # Phrase、Near、Wildcard：T4b
    return node


def _contains_wildcard(node: Node) -> bool:
    if isinstance(node, Wildcard):
        return True
    if isinstance(node, (And, Or)):
        return any(_contains_wildcard(c) for c in node.children)
    if isinstance(node, Not):
        return _contains_wildcard(node.child)
    return False


def parse(query: str, pre: Preprocessor) -> Node | None:
    """以遞迴下降解析 query 字串為 AST。

    運算子只認獨立的大寫 AND／OR／NOT，優先序 NOT > AND > OR；相鄰的運算元之間視為隱含 AND。
    另支援括號、"phrase"、prefix*、a /k b（T4b）。

    空節點規則（在樹上處理）：空的 Term／Phrase 從父節點移除並發出警告；
    沒有 child 的 And／Or 移除，只剩一個 child 時攤平；Not 的 child 是空的就移除該 Not。

    Returns:
        AST 根節點；空 query 或整棵樹都是空的時回傳 None。

    Raises:
        ValueError: 引號或括號沒有配對，訊息指出字元位置。
    """
    if not query.strip():
        return None
    return _prune(_Parser(_lex(query), pre).parse())


def expand(node: Node | None, reader: IndexReader, limit: int = 100) -> Node | None:
    """把 Wildcard 展開成多個 Term 組成的 Or（T4b）；樹中沒有 Wildcard 時原樣回傳（T4a）。

    依 df 由高到低取前 limit 個 term，超過 limit 時發出警告；
    展開結果為空時依空節點規則移除。不修改傳入的 node。
    """
    if node is None:
        return None
    if _contains_wildcard(node):
        raise NotImplementedError("T4b: wildcard expansion is not supported yet")
    return node


def query_terms(node: Node) -> Counter[str]:
    """評分用 term 及其 query tf。

    涵蓋整棵樹的所有 token 並計算重複次數；Phrase、Near 的 token 都計入；跳過 Not 的子樹。

    Raises:
        ValueError: 樹中仍有 Wildcard（必須先呼叫 expand）。
    """
    qtf: Counter[str] = Counter()

    def walk(n: Node) -> None:
        if isinstance(n, (Term, Phrase)):
            qtf.update(n.tokens)
        elif isinstance(n, Near):
            qtf.update(n.left.tokens)
            qtf.update(n.right.tokens)
        elif isinstance(n, (And, Or)):
            for c in n.children:
                walk(c)
        elif isinstance(n, Not):
            return  # 跳過 Not 的子樹
        elif isinstance(n, Wildcard):
            raise ValueError(f"query_terms: unexpanded Wildcard({n.prefix!r}); call expand() first")
        else:
            raise TypeError(f"query_terms: unknown node {n!r}")

    walk(node)
    return qtf
