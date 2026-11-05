"""T4：Query parser。"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from tokenizer import Preprocessor


@dataclass
class Term:
    tokens: list[str]  # 一個運算元經 process 後的所有 term


@dataclass
class And:
    children: list["Node"]


@dataclass
class Or:
    children: list["Node"]


Node = Term | And | Or


def parse(query: str, pre: Preprocessor) -> Node | None:
    """解析 query 字串為 AST。

    Returns:
        AST 根節點；空 query 回傳 None。
    """
    raise NotImplementedError


def query_terms(node: Node) -> Counter[str]:
    """評分用 term 及其 query tf。"""
    raise NotImplementedError
