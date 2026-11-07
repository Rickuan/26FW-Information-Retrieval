"""T4：Query parser。

查詢流程：parse → expand → evaluate（T5）→ query_terms → rank（T6）。
只有一個遞迴下降 parser。T4a／T4b 只是實作順序與 commit 切分：
T4a 先做 Term、And、Or；T4b 再加入 Phrase、Near、Wildcard、Not 與括號；
T4c 把 Wildcard 改成任意位置的 *、新增 SOUNDEX()，兩者都在原字詞彙（surface.py）上展開，
並新增 query_words 取出使用者輸入的原字給拼字建議。
"""
from __future__ import annotations

import copy
import re
import warnings
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

import surface
from spelling import soundex
from tokenizer import Preprocessor, tokenize

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
    pattern: str  # co*tion、*mon、comput*：只做 casefold、連續的 * 合併成一個；含 *，在原字詞彙上比對（T4c）


@dataclass
class Soundex:
    word: str  # SOUNDEX(Robert) 的 "robert"：只做 casefold，不濾 stopword、不做 stem（T4c）


@dataclass
class Not:
    child: "Node"


@dataclass
class And:
    children: list["Node"]


@dataclass
class Or:
    children: list["Node"]


Node = Term | Phrase | Near | Wildcard | Soundex | Not | And | Or


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------
# 一開始就辨識全部 token 類型（T4b 不必重寫）：
#   "..."（PHRASE，結尾引號可能缺少，由 parser 判斷）、( 、)、其餘不含空白／括號／引號的字串。
_TOKEN_RE = re.compile(r'"[^"]*"?|[()]|[^\s()"]+')
_NEAR_RE = re.compile(r"/\d+")
_STARS_RE = re.compile(r"\*+")
_OPERATORS = {"AND", "OR", "NOT"}  # 只有獨立的大寫才是運算子；and、Or、ANDROID 都是 WORD

Token = tuple[str, str, int]  # (kind, text, pos)；pos 是字元位置，從 0 起算


def _lex(query: str) -> list[Token]:
    """把 query 切成 token：kind 為 WORD、AND、OR、NOT、(、)、PHRASE、WILDCARD、NEAR、SOUNDEX。

    運算子在 process 之前就切出來，因為 and／or 是 stopword，順序反過來會被濾掉。
    分類順序：PHRASE → 括號 → 運算子 → SOUNDEX → NEAR → WILDCARD → WORD。
    PHRASE 的 text 保留引號（含沒有配對的情況）；NEAR 是整個 token 符合 /\\d+；
    WILDCARD 是任何位置含有 * 的詞（T4c，/5* 也是 WILDCARD）；
    SOUNDEX 只有在文字恰好是大寫的 SOUNDEX、而且緊接著 (（中間沒有空白）時才是運算子（T4c）。
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
        elif text == "SOUNDEX" and query[m.end():m.end() + 1] == "(":
            kind = "SOUNDEX"
        elif _NEAR_RE.fullmatch(text):
            kind = "NEAR"
        elif "*" in text:
            kind = "WILDCARD"
        else:
            kind = "WORD"
        tokens.append((kind, text, pos))
    return tokens


# ---------------------------------------------------------------------------
# Parser（遞迴下降）
# ---------------------------------------------------------------------------
# 能開始一個 unary 的 token：出現在運算元之後時視為隱含 AND（linux NOT windows = linux AND NOT windows）。
# NEAR 也算：前面沒有可當 side 的運算元時（例如 (a) /5 b），它的左側是空的，交給 _prune 的 Near 規則。
_UNARY_START = {"WORD", "NOT", "(", "PHRASE", "WILDCARD", "NEAR", "SOUNDEX"}
_EMPTY_WARNING = "empty operand removed from query (only stopwords or a missing operand)"


class _Parser:
    """or := and ("OR" and)*；and := unary (["AND"] unary)*；unary := "NOT" unary | primary；
    primary := side [NEAR side] | "(" or ")" | WILDCARD | SOUNDEX "(" WORD ")"；side := WORD+ | PHRASE。"""

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
            # parse_or 只會停在 ")"：其餘 token 都會被 parse_and／parse_primary 吃掉
            raise ValueError(f"unmatched ')' at position {tok[2]}")
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
        if self.peek_kind() == "NOT":
            self.i += 1
            return Not(self.parse_unary())  # NOT 後面沒有運算元 → Not(Term([]))，由 _prune 移除
        return self.parse_primary()

    def parse_primary(self) -> Node:
        tok = self.peek()
        kind = tok[0] if tok else None
        if kind == "(":
            self.i += 1
            node = self.parse_or()
            if self.peek_kind() != ")":
                raise ValueError(f"unmatched '(' at position {tok[2]}")
            self.i += 1
            return node
        if kind == "WILDCARD":
            self.i += 1
            pattern = _STARS_RE.sub("*", tok[1]).casefold()  # 只做 casefold，不做 stem、不經過 tokenize
            if pattern == "*":
                raise ValueError(f"wildcard without any fixed text {tok[1]!r} at position {tok[2]}")
            return Wildcard(pattern)
        if kind == "SOUNDEX":
            return self.parse_soundex()
        # side [NEAR side]；side 可能是空的（運算子相鄰、開頭或結尾，或 NEAR 前沒有 side）
        left = self.parse_side()
        if self.peek_kind() != "NEAR":
            if left is None:
                return Term([])  # 少了運算元 → 空的 Term，交給 _prune
            if isinstance(left, Phrase):
                return left  # 單一 token 的 Phrase 由 _prune 簡化成 Term
            return Term(left[0])
        near_tok = self.tokens[self.i]
        self.i += 1
        k = int(near_tok[1][1:])
        if k == 0:
            raise ValueError(f"proximity distance must be at least 1: {near_tok[1]!r} at position {near_tok[2]}")
        right = self.parse_side()
        return Near(self._as_phrase(left), self._as_phrase(right), k)

    def parse_soundex(self) -> Soundex:
        """SOUNDEX "(" WORD ")"：括號內必須恰好是一個 WORD，而且至少有一個 ASCII 字母（§6.8.5、§8 G5）。

        lexer 只在 SOUNDEX 緊接 ( 時才產生 SOUNDEX，所以下一個 token 一定是 (。
        """
        _, _, sx_pos = self.tokens[self.i]
        _, _, paren_pos = self.tokens[self.i + 1]
        self.i += 2
        arg, close = self.peek(), (self.tokens[self.i + 1] if self.i + 1 < len(self.tokens) else None)
        if arg is None or (arg[0] == "WORD" and close is None):
            raise ValueError(f"unmatched '(' at position {paren_pos}")
        if arg[0] != "WORD" or close[0] != ")":
            raise ValueError(f"SOUNDEX() needs exactly one word at position {sx_pos}")
        word = arg[1].casefold()  # 只做 casefold：不濾 stopword、不做 stem
        if not soundex(word):  # 與 expand 用同一個函式判斷，沒有 ASCII 字母時回傳空字串
            raise ValueError(f"SOUNDEX() needs a word with ASCII letters at position {sx_pos}")
        self.i += 2
        return Soundex(word)

    def parse_side(self) -> Phrase | tuple[list[str], list[int]] | None:
        """WORD+ → (tokens, positions)；PHRASE → Phrase；都不是 → None（不消耗 token）。

        WORD+ 先回傳 tuple，等看到後面有沒有 NEAR 再決定是 Term 還是 Near 的一側。
        """
        kind = self.peek_kind()
        if kind == "PHRASE":
            _, text, pos = self.tokens[self.i]
            if len(text) < 2 or not text.endswith('"'):
                raise ValueError(f"unmatched '\"' at position {pos}")
            self.i += 1
            toks = self.pre.process(text[1:-1])
            return Phrase([t for _, t in toks], [p for p, _ in toks])
        if kind == "WORD":
            words: list[str] = []
            while self.peek_kind() == "WORD":
                words.append(self.tokens[self.i][1])
                self.i += 1
            toks = self.pre.process(" ".join(words))
            return [t for _, t in toks], [p for p, _ in toks]
        return None

    @staticmethod
    def _as_phrase(side: Phrase | tuple[list[str], list[int]] | None) -> Phrase:
        """Near 的一側一律是 Phrase（單一 token 是長度 1 的 Phrase）；空的一側是 Phrase([], [])。"""
        if side is None:
            return Phrase([], [])
        if isinstance(side, Phrase):
            return side
        return Phrase(side[0], side[1])


# ---------------------------------------------------------------------------
# 空節點規則
# ---------------------------------------------------------------------------
def _warn_empty() -> None:
    warnings.warn(_EMPTY_WARNING, stacklevel=3)


def _prune(node: Node) -> Node | None:
    """空節點規則（在樹上處理），回傳新的樹；整棵樹都是空的時回傳 None。

    - 空的 Term／Phrase 移除，每移除一個警告一次（根節點本身是空的也算）
    - 沒有 child 的 And／Or 移除；只剩一個 child 時攤平成那個 child
    - 同類型的巢狀節點合併：And([And([a, b]), c]) → And([a, b, c])（T4.md §4.4 D3）
    - Not 的 child 是空的就移除這個 Not
    - 只有一個 token 的 Phrase 簡化成 Term；Near 的兩側除外（仍是長度 1 的 Phrase）
    - Near 的一側是空的：整個 Near 由另一側取代並警告一次；另一側只有 1 個 token 時是 Term，
      多個 token 時保留為 Phrase（不能轉成 Term，否則失去相鄰條件）。兩側都空就移除（每側各警告一次）
    Wildcard、Soundex 原樣保留；展開成 0 個 term 時的移除由 expand 處理。
    """
    if isinstance(node, Term):
        if not node.tokens:
            _warn_empty()
            return None
        return node
    if isinstance(node, Phrase):
        if not node.tokens:
            _warn_empty()
            return None
        if len(node.tokens) == 1:
            return Term(list(node.tokens))
        return node
    if isinstance(node, Near):
        left, right = node.left, node.right
        if left.tokens and right.tokens:
            return node
        if not left.tokens and not right.tokens:
            _warn_empty()
            _warn_empty()
            return None
        _warn_empty()
        side = left if left.tokens else right
        if len(side.tokens) == 1:
            return Term(list(side.tokens))
        return side
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
    # Wildcard、Soundex
    return node


def _needs_expand(node: Node) -> bool:
    """樹中有沒有要由 expand 展開的節點（Wildcard、Soundex）。"""
    if isinstance(node, (Wildcard, Soundex)):
        return True
    if isinstance(node, (And, Or)):
        return any(_needs_expand(c) for c in node.children)
    if isinstance(node, Not):
        return _needs_expand(node.child)
    return False


def parse(query: str, pre: Preprocessor) -> Node | None:
    """以遞迴下降解析 query 字串為 AST。

    運算子只認獨立的大寫 AND／OR／NOT，優先序 NOT > AND > OR；相鄰的運算元之間視為隱含 AND。
    另支援括號、"phrase"、a /k b（T4b），以及任意位置的 *（co*tion、*mon）與 SOUNDEX(word)（T4c）。
    SOUNDEX 只有大寫、而且緊接著 ( 時才是運算子；Wildcard 與 Soundex 留到 expand 才展開。

    空節點規則（在樹上處理）：空的 Term／Phrase 從父節點移除並發出警告；
    沒有 child 的 And／Or 移除，只剩一個 child 時攤平；Not 的 child 是空的就移除該 Not。
    單一 token 的 Phrase 變成 Term（Near 的兩側除外）；Near 一側為空時由另一側取代並警告。

    Returns:
        AST 根節點；空 query 或整棵樹都是空的時回傳 None。

    Raises:
        ValueError: 引號或括號沒有配對、wildcard 只有 *（沒有固定片段）、/0、
            SOUNDEX() 的參數不是恰好一個 WORD 或其中沒有 ASCII 字母，訊息指出字元位置（從 0 起算）。
    """
    if not query.strip():
        return None
    return _prune(_Parser(_lex(query), pre).parse())


def expand(node: Node | None, reader: IndexReader, limit: int = 100) -> Node | None:
    """把 Wildcard、Soundex 展開成多個 Term 組成的 Or；樹中兩者都沒有時原樣回傳（T4a）。

    兩者都在原字詞彙上比對（surface_vocab.*，T4c §6.8.4、§6.8.5）：Wildcard 取完整比對 pattern 的原字，
    Soundex 取同碼的所有原字（含輸入本身）。比對到的原字轉成 stem、略過 stopword、去重，
    依 stem 的 (-df, term) 取前 limit 個；超過 limit 時發出警告（總數是去重後的 stem 數）。
    展開成 0 個 term 時依空節點規則移除並警告；整棵樹因此變空時回傳 None。不修改傳入的 node。

    Raises:
        FileNotFoundError: 需要展開但 surface_vocab.* 不存在（先執行 build_surface_vocab.py）。
        ValueError: surface_vocab.meta.json 與目前的 index 不一致。
    """
    if node is None:
        return None
    if not _needs_expand(node):
        return node  # 原樣回傳同一個物件（T4a），不讀任何檔案
    sv = surface.load_surface(reader)  # 經由模組屬性呼叫，測試可以 spy
    # 先整棵深拷貝：回傳的樹與輸入不共用任何可變節點，呼叫端改動結果也不會影響原樹
    return _prune_expanded(_expand_node(copy.deepcopy(node), sv, reader, limit))


def _expand_node(node: Node, sv: surface.SurfaceVocab, reader: IndexReader, limit: int) -> Node | None:
    """把 Wildcard、Soundex 換成 Or／Term；展開成 0 個 term 時回傳 None（並警告）。"""
    if isinstance(node, Wildcard):
        return _top_terms(sv, sv.match_wildcard(node.pattern), f"wildcard {node.pattern}", reader, limit)
    if isinstance(node, Soundex):
        # 同碼的所有原字（含輸入的字本身），與 suggest_soundex 共用同一份對照表
        ids = sv.soundex_groups().get(soundex(node.word), ())
        return _top_terms(sv, ids, f"SOUNDEX({node.word})", reader, limit)
    if isinstance(node, (And, Or)):
        kids = [e for c in node.children if (e := _expand_node(c, sv, reader, limit)) is not None]
        return type(node)(kids)
    if isinstance(node, Not):
        child = _expand_node(node.child, sv, reader, limit)
        return None if child is None else Not(child)
    return node


def _top_terms(sv: surface.SurfaceVocab, ids, label: str, reader: IndexReader, limit: int) -> Node | None:
    """原字 id → stem（略過 stopword 的空字串）去重 → 依 (-df, term) 取前 limit 個 → Term 或 Or。

    警告的 stacklevel=4：Wildcard／Soundex 是根節點時指到 expand 的呼叫端（巢狀時會指得更深一些）。
    """
    stems = {s for i in ids if (s := sv.stems[i])}
    if not stems:
        warnings.warn(f"{label} matched no term in the dictionary; removed from query", stacklevel=4)
        return None
    top = sorted(stems, key=lambda t: (-reader.df(t), t))[:max(limit, 0)]
    if len(stems) > limit:
        warnings.warn(f"{label} matched {len(stems)} terms; using the top {limit} by df", stacklevel=4)
    if not top:  # limit < 1
        return None
    return Term([top[0]]) if len(top) == 1 else Or([Term([t]) for t in top])


def _prune_expanded(node: Node | None) -> Node | None:
    """展開後再跑一次 _prune（攤平、同類型合併）；parse 已移除空的運算元，這裡不會再發出空運算元警告。"""
    return None if node is None else _prune(node)


def query_words(query: str, pre: Preprocessor) -> list[str]:
    """使用者輸入的原字，供拼字建議（spelling.did_you_mean）使用（§6.8.3、§8 G4）。

    用 _lex 取出 WORD、PHRASE 的內文（Near 兩側也是 WORD／PHRASE），切法與 parse 相同；
    跑 tokenize 與 casefold，略過 stopword（它們會被 process 濾掉，不參與檢索），依出現順序去重。
    不包含 Wildcard 與 SOUNDEX(...) 的參數；不檢查語法（parse 已經先檢查過）。
    stopword 的判斷用 pre.normalize_token（與 process 同一段程式）。
    """
    tokens = _lex(query)
    texts: list[str] = []
    i = 0
    while i < len(tokens):
        kind, text, _ = tokens[i]
        if kind == "SOUNDEX":
            i += 3  # SOUNDEX、(、參數；) 與其他 token 照一般規則略過
            continue
        if kind == "WORD":
            texts.append(text)
        elif kind == "PHRASE":
            texts.append(text[1:-1] if len(text) >= 2 and text.endswith('"') else text[1:])
        i += 1
    out: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for tok in tokenize(text):
            w = tok.casefold()
            if w not in seen and pre.normalize_token(tok) is not None:
                seen.add(w)
                out.append(w)
    return out


def query_terms(node: Node) -> Counter[str]:
    """評分用 term 及其 query tf。

    涵蓋整棵樹的所有 token 並計算重複次數；Phrase、Near 的 token 都計入；跳過 Not 的子樹。

    Raises:
        ValueError: 樹中仍有 Wildcard 或 Soundex（必須先呼叫 expand）。
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
        elif isinstance(n, (Wildcard, Soundex)):
            raise ValueError(f"query_terms: unexpanded {n!r}; call expand() first")
        else:
            raise TypeError(f"query_terms: unknown node {n!r}")

    walk(node)
    return qtf
