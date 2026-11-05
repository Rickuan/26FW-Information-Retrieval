"""T4：Query parser。

查詢流程：parse → expand → evaluate（T5）→ query_terms → rank（T6）。
只有一個遞迴下降 parser。T4a／T4b 只是實作順序與 commit 切分：
T4a 先做 Term、And、Or；T4b 再加入 Phrase、Near、Wildcard、Not 與括號。
"""
from __future__ import annotations

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
    left: Term
    right: Term
    k: int  # linux /5 kernel：兩邊 term 的位置差 ≤ k，不分先後


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
    raise NotImplementedError


def expand(node: Node | None, reader: IndexReader, limit: int = 100) -> Node | None:
    """把 Wildcard 展開成多個 Term 組成的 Or（T4b）；樹中沒有 Wildcard 時原樣回傳（T4a）。

    依 df 由高到低取前 limit 個 term，超過 limit 時發出警告；
    展開結果為空時依空節點規則移除。不修改傳入的 node。
    """
    raise NotImplementedError


def query_terms(node: Node) -> Counter[str]:
    """評分用 term 及其 query tf。

    涵蓋整棵樹的所有 token 並計算重複次數；Phrase、Near 的 token 都計入；跳過 Not 的子樹。

    Raises:
        ValueError: 樹中仍有 Wildcard（必須先呼叫 expand）。
    """
    raise NotImplementedError
