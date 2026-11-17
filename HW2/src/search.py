"""T7 CLI 查詢介面與端到端搜尋引擎。

整合 Preprocessor (T1)、Parser (T4)、Boolean (T5) 與 VSM Rank (T6)，
提供 search_query 函式與 CLI 執行入口。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from boolean import evaluate
from parser import expand, parse, query_terms, query_words
from rank import rank
from spelling import did_you_mean
from tokenizer import Preprocessor
from writer import IndexReader

FEW_RESULTS_THRESHOLD = 20


def search_query(
    query: str,
    reader: IndexReader,
    pre: Preprocessor,
    scheme: str = "ltc.ltc",
    champion_r: int | None = None,
    top_k: int | None = None,
) -> list[tuple[int, float]]:
    """執行單一查詢的端到端檢索管線。

    流程：
    1. parse(query, pre)：語法解析；語法不合法時拋出 ValueError。
    2. expand(node, reader)：原字展開 Wildcard / Soundex。
    3. 若 node 為 None（如空字串或全停用詞），回傳 []。
    4. evaluate(node, reader)：求得布林候選文件集合（自由文字回傳 None）。
    5. query_terms(node)：提取評分詞與 query tf；若為空（如純 NOT），回傳 []。
    6. rank(qtf, cands, reader, scheme=scheme, champion_r=champion_r)：計算分數並排序。
    7. 若指定 top_k，取前 top_k 筆（top_k < 1 時拋出 ValueError）。
    """
    if top_k is not None and top_k < 1:
        raise ValueError(f"top_k must be positive, got {top_k}")

    node = parse(query, pre)
    if node is None:
        return []

    node = expand(node, reader)
    if node is None:
        return []

    candidates = evaluate(node, reader)
    qtf = query_terms(node)
    if not qtf:
        return []

    hits = rank(qtf, candidates, reader, scheme=scheme, champion_r=champion_r)
    if top_k is not None:
        hits = hits[:top_k]
    return hits


def format_hits(hits: list[tuple[int, float]]) -> str:
    """將檢索結果格式化為每行 '<doc#> <score:.6f>' 字串。"""
    if not hits:
        return ""
    return "\n".join(f"{doc} {score:.6f}" for doc, score in hits)


def suggest_spelling_corrections(
    query: str,
    reader: IndexReader,
    pre: Preprocessor,
    show: int = 3,
) -> list[tuple[str, list[str]]]:
    """檢驗 query 中的原詞，若有拼字更正建議則回傳 [(word, [suggestions...]), ...]"""
    suggestions: list[tuple[str, list[str]]] = []
    try:
        words = query_words(query, pre)
    except Exception:
        return []
    for w in words:
        s = did_you_mean(w, reader, show=show)
        if s:
            suggestions.append((w, s))
    return suggestions


def build_arg_parser() -> argparse.ArgumentParser:
    """建構 CLI 命令列參數解析器。"""
    parser = argparse.ArgumentParser(
        prog="search.py",
        description="IR HW2 Ranked Retrieval CLI Search Interface",
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="單一檢索查詢字串",
    )
    parser.add_argument(
        "--index-dir",
        default="HW2/index",
        help="索引目錄路徑（預設：HW2/index）",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="截斷回傳排名前 K 筆結果（預設輸出所有 score > 0）",
    )
    parser.add_argument(
        "--queries",
        type=str,
        default=None,
        help="批次查詢檔案路徑（每行一個 query）",
    )
    parser.add_argument(
        "--scheme",
        default="ltc.ltc",
        help="SMART 權重方案（預設：ltc.ltc）",
    )
    parser.add_argument(
        "--champion-r",
        type=int,
        default=None,
        help="不精確 top-k Champion list r 大小（預設關閉）",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="單一查詢之輸出結果檔案路徑（預設輸出至 stdout）",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="批次查詢輸出目錄路徑（搭配 --queries，每筆查詢寫入獨立檔案）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 主程式入口。"""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.query is None and args.queries is None:
        parser.error("must provide either 'query' or '--queries'")
    if args.query is not None and args.queries is not None:
        parser.error("cannot specify both 'query' and '--queries'")

    if args.top_k is not None and args.top_k < 1:
        parser.error("--top-k must be a positive integer")
    if args.champion_r is not None and args.champion_r < 1:
        parser.error("--champion-r must be a positive integer")

    index_path = Path(args.index_dir)
    if not index_path.is_dir():
        sys.stderr.write(f"Error: index directory not found: {index_path}\n")
        return 1

    try:
        reader = IndexReader(str(index_path))
        meta = reader.get_metadata()
        pre = Preprocessor.from_config(meta["preprocessor"])
    except Exception as e:
        sys.stderr.write(f"Error initializing index: {e}\n")
        return 1

    if args.query is not None:
        try:
            hits = search_query(
                args.query,
                reader,
                pre,
                scheme=args.scheme,
                champion_r=args.champion_r,
                top_k=args.top_k,
            )
        except ValueError as e:
            sys.stderr.write(f"Query error: {e}\n")
            return 1

        if len(hits) < FEW_RESULTS_THRESHOLD:
            for word, suggs in suggest_spelling_corrections(args.query, reader, pre):
                sys.stderr.write(f"Did you mean for '{word}': {', '.join(suggs)}?\n")

        formatted = format_hits(hits)
        if args.output:
            out_file = Path(args.output)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(formatted + ("\n" if formatted else ""), encoding="utf-8")
        else:
            if formatted:
                print(formatted)
        return 0

    queries_file = Path(args.queries)
    if not queries_file.is_file():
        sys.stderr.write(f"Error: queries file not found: {queries_file}\n")
        return 1

    lines = queries_file.read_text(encoding="utf-8").splitlines()
    if args.output_dir:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

    for idx, raw_line in enumerate(lines, 1):
        q = raw_line.strip()
        if not q:
            continue
        try:
            hits = search_query(
                q,
                reader,
                pre,
                scheme=args.scheme,
                champion_r=args.champion_r,
                top_k=args.top_k,
            )
        except ValueError as e:
            sys.stderr.write(f"Query error on line {idx} ({q!r}): {e}\n")
            return 1

        if len(hits) < FEW_RESULTS_THRESHOLD:
            for word, suggs in suggest_spelling_corrections(q, reader, pre):
                sys.stderr.write(f"Did you mean for '{word}': {', '.join(suggs)}?\n")

        formatted = format_hits(hits)
        if args.output_dir:
            out_path = Path(args.output_dir) / f"query_{idx}.txt"
            out_path.write_text(formatted + ("\n" if formatted else ""), encoding="utf-8")
        else:
            if formatted:
                print(formatted)
    return 0


if __name__ == "__main__":
    sys.exit(main())

