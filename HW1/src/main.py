"""HW1 Inverted Index System — CLI 統一入口點 (main.py)

提供三個主要子命令：
  1. build：全流程索引建置（M1 -> M2 -> M3 -> M4，可選 --eval-skips）
  2. query：布林 AND 檢索展示介面（從磁碟讀取二進制索引，支援多詞交集）
  3. eval-skips：M5 Skip Pointer 效能評測與報告產出

用法範例：
  uv run python HW1/src/main.py build --input HW1/dataset/04.warc --output HW1/output/ --limit 1000
  uv run python HW1/src/main.py build --mode spimi --block-size-mb 100
  uv run python HW1/src/main.py query "information" "retrieval" --show-docs 5
  uv run python HW1/src/main.py eval-skips --limit 1000
"""
from __future__ import annotations

import argparse
import math
import os
import resource
import sys
import time
from array import array
from pathlib import Path
from typing import Any

from tqdm import tqdm

from documents import iter_documents
from indexer import Indexer, Posting
from skip_builder import (
    MIN_SKIP_LEN,
    PostingWithSkip,
    SkipBuilder,
    build_skip_list,
    intersect_basic,
    intersect_with_skips,
)
from tokenizer import Preprocessor
from writer import IndexReader, IndexWriter


def get_peak_rss_mb() -> float:
    """取得當前行程的 Peak RSS 記憶體使用量（MB）。"""
    rss_scale = 1024 * 1024 if sys.platform == "darwin" else 1024
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / rss_scale


# ---------------------------------------------------------------------------
# Step 6-B: build 子命令
# ---------------------------------------------------------------------------

def run_build(args: argparse.Namespace) -> None:
    """執行端到端索引建置流程。"""
    warc_path = Path(args.input)
    if not warc_path.is_file():
        print(f"錯誤：找不到輸入語料檔案 '{warc_path}'", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("🚀 [Step 6: Build] 開始執行端到端倒排索引建置")
    print(f"  - 輸入檔案：{warc_path}")
    print(f"  - 輸出目錄：{out_dir}")
    print(f"  - 建置模式：{args.mode.upper()}")
    print(f"  - 文件上限：{args.limit or '全量'}")
    print(f"  - Preprocessor：casefold=True, stopword={not args.no_stopword}, stem={not args.no_stem}")
    print("=" * 70)

    # 1. 初始化 Preprocessor 與 Indexer
    preprocessor = Preprocessor(
        casefold=True,
        stopword=not args.no_stopword,
        stem=not args.no_stem,
    )

    if args.flush_every:
        flush_every = args.flush_every
    else:
        # 依 block-size-mb 換算位置數門檻（約 20,000 位置/MB）
        flush_every = args.block_size_mb * 20_000

    indexer = Indexer(
        spimi=(args.mode == "spimi"),
        flush_every=flush_every,
        tmp_dir=str(out_dir / "spimi_tmp"),
    )
    if indexer.spimi:
        indexer._reset_tmp()

    # 2. 串流讀取、斷詞並建立索引 (M1 -> M2 -> M3)
    t_start = time.time()
    t_index_start = time.time()

    total_tokens_read = 0
    docs_iter = iter_documents(str(warc_path))
    
    with tqdm(desc="Indexing documents", total=args.limit, unit="docs", dynamic_ncols=True) as pbar:
        for i, doc in enumerate(docs_iter, 1):
            tokens = preprocessor.process(doc.text)
            total_tokens_read += len(tokens)
            indexer.add_document(doc, tokens)
            pbar.update(1)
            if args.limit and i >= args.limit:
                break

    if indexer.spimi:
        print("\n[SPIMI] 刷新最後區塊並執行多路歸併 (Multi-way merge)...")
        indexer._flush_partial()
        indexer._merge_partials()

    indexer.get_stats()
    t_index = time.time() - t_index_start

    # 3. 輸出 6 項作業評分檔案 (M4)
    print("\n[Writer] 正在寫出 6 項產物至輸出目錄...")
    t_write_start = time.time()
    writer = IndexWriter(out_dir)
    config = {
        "casefold": True,
        "stopword": not args.no_stopword,
        "stem": not args.no_stem,
    }
    writer.write_all(indexer, config=config)
    t_write = time.time() - t_write_start
    t_total = time.time() - t_start

    peak_rss = get_peak_rss_mb()
    stats = indexer.stats

    print("\n" + "=" * 70)
    print("✅ 索引建置完成摘要 (Build Summary)")
    print("=" * 70)
    print(f"  - 處理文件篇數 (N)：{stats['N']:,}")
    print(f"  - 詞彙總量 (Vocab Size)：{stats['vocab_size']:,}")
    print(f"  - 總 Tokens 數：{stats['total_tokens']:,}")
    print(f"  - 平均文件長度：{stats['avg_doc_len']:.2f} tokens")
    print(f"  - 索引耗時：{t_index:.2f} s ({stats['N'] / max(t_index, 0.001):.1f} docs/s)")
    print(f"  - 寫檔耗時：{t_write:.2f} s")
    print(f"  - 總共耗時：{t_total:.2f} s")
    print(f"  - Peak RSS：{peak_rss:.1f} MB")
    print("\n產生物件檢查：")
    for fname in ["dictionary.txt", "postings.txt", "metadata.json", "doc_map.json", "lexicon.tsv", "postings.bin"]:
        fpath = out_dir / fname
        if fpath.exists():
            fsize = fpath.stat().st_size
            print(f"  ✓ {fname:<16} ({fsize:,} bytes)")
        else:
            print(f"  ✗ {fname:<16} (MISSING!)")
    print("=" * 70)

    # 4. 可選執行 M5 Skip Pointer 評測
    if args.eval_skips:
        if args.mode == "spimi":
            print("\n[Notice] SPIMI 模式下記憶體倒排表已清空，如需執行 Skip 評測請使用全記憶體模式或執行：")
            print("         uv run python HW1/src/main.py eval-skips")
        else:
            print("\n[Eval-Skips] 自動執行 M5 Skip 評測模組...")
            report_path = out_dir.parent / "logs" / "skip_eval_report.md"
            run_eval_skips_on_indexer(indexer, preprocessor, report_path)


# ---------------------------------------------------------------------------
# Step 6-D: query 子命令
# ---------------------------------------------------------------------------

def run_query(args: argparse.Namespace) -> None:
    """執行布林 AND 檢索查詢。"""
    index_dir = Path(args.index_dir)
    if not (index_dir / "lexicon.tsv").is_file() or not (index_dir / "postings.bin").is_file():
        print(f"錯誤：目錄 '{index_dir}' 下未找到完整索引檔案（請先執行 build）", file=sys.stderr)
        sys.exit(1)

    # 1. 讀取元資料與建立 Reader
    reader = IndexReader(index_dir)
    metadata = reader.get_metadata()
    prep_config = metadata.get("preprocessor", {})

    preprocessor = Preprocessor(
        casefold=prep_config.get("casefold", True),
        stopword=prep_config.get("stopword", True),
        stem=prep_config.get("stem", True),
    )

    raw_query_terms = args.terms
    print(f"\n🔍 [Query] 查詢詞：{raw_query_terms}")
    print(f"   索引目錄：{index_dir} (N={metadata.get('N', 'N/A')}, vocab={metadata.get('vocab_size', 'N/A')})")

    # 2. 查詢詞正規化處理
    t0 = time.time()
    normalized_terms: list[str] = []
    for term in raw_query_terms:
        toks = preprocessor.process(term)
        if not toks:
            print(f"  [提示] 查詢詞 '{term}' 經正規化後為空（例如為停用詞），AND 查詢結果為空。")
            print("  匹配文件數：0 篇 (耗時: 0.00 ms)")
            return
        normalized_terms.append(toks[0][1])

    print(f"   正規化後詞彙：{normalized_terms}")

    # 3. 從磁碟取得各詞彙之 Postings
    postings_map: dict[str, list[Posting]] = {}
    for term in set(normalized_terms):
        plist = reader.get_postings(term)
        if not plist:
            print(f"  [提示] 詞彙 '{term}' 不存在於索引中，AND 查詢結果為空。")
            print("  匹配文件數：0 篇 (耗時: 0.00 ms)")
            return
        postings_map[term] = plist

    # 4. 執行布林 AND 交集運算
    total_comparisons = 0
    use_skips = not args.no_skips

    if len(normalized_terms) == 1:
        single_term = normalized_terms[0]
        match_doc_nums = [p.doc_num for p in postings_map[single_term]]
        total_comparisons = 0
    else:
        # 多詞交集最佳化：按 postings 長度 (df) 升冪排序（由小到大交集）
        sorted_terms = sorted(normalized_terms, key=lambda t: len(postings_map[t]))
        
        # 首組 postings
        first_postings = postings_map[sorted_terms[0]]
        curr_skips = build_skip_list(first_postings) if use_skips else first_postings

        for next_term in sorted_terms[1:]:
            next_postings = postings_map[next_term]
            next_skips = build_skip_list(next_postings) if use_skips else next_postings

            if use_skips:
                matched_docs, comp = intersect_with_skips(curr_skips, next_skips)
            else:
                matched_docs, comp = intersect_basic(curr_skips, next_skips)

            total_comparisons += comp
            if not matched_docs:
                curr_skips = []
                break
            
            # 若還有下一個詞要交集，將當前結果包裝為 postings list 供下一次比對
            temp_postings = [Posting(d, 1, array("I")) for d in matched_docs]
            curr_skips = build_skip_list(temp_postings) if use_skips else temp_postings

        match_doc_nums = [p.doc_num for p in curr_skips]

    elapsed_ms = (time.time() - t0) * 1000.0

    # 5. 輸出結果與前 K 篇文件資訊
    mode_str = "Skip Pointer" if use_skips else "Basic Linear Scan"
    print(f"\n📊 檢索結果 ({mode_str})：")
    print(f"  - 匹配文件數：{len(match_doc_nums):,} 篇")
    print(f"  - 檢索耗時：{elapsed_ms:.2f} ms")
    if len(normalized_terms) > 1:
        print(f"  - 總比較次數：{total_comparisons:,} 次")

    show_k = min(args.show_docs, len(match_doc_nums))
    if show_k > 0:
        print(f"\n顯示前 {show_k} 篇符合文件：")
        print("-" * 80)
        print(f"{'docID':<8} {'TREC ID':<25} {'長度':<8} {'URL'}")
        print("-" * 80)
        for doc_num in match_doc_nums[:show_k]:
            doc_entry = reader.get_doc(doc_num)
            if doc_entry:
                print(f"{doc_num:<8} {doc_entry.trec_id:<25} {doc_entry.doc_len:<8} {doc_entry.url}")
            else:
                print(f"{doc_num:<8} {'[Unknown]':<25} {'-':<8} -")
        print("-" * 80)


# ---------------------------------------------------------------------------
# Step 6-C: eval-skips 子命令與核心邏輯
# ---------------------------------------------------------------------------

def run_eval_skips_on_indexer(indexer: Indexer, preprocessor: Preprocessor, report_path: Path | None = None) -> list[dict]:
    """在已建好的全記憶體 Indexer 上評測 5 組典型 Query Pair。"""
    builder = SkipBuilder()
    skips = builder.build(indexer)

    terms_by_df = sorted(indexer.index.keys(), key=lambda t: indexer.df(t), reverse=True)
    high_terms = [t for t in terms_by_df if indexer.df(t) >= 50]
    low_terms = [t for t in terms_by_df if 1 <= indexer.df(t) < MIN_SKIP_LEN]

    # 1. 高頻 + 高頻
    q_pair1 = (high_terms[0], high_terms[1]) if len(high_terms) >= 2 else ("inform", "servic")
    # 2. 長串列 + 短串列（高頻 + 低頻）
    q_pair2 = (high_terms[0], low_terms[0]) if high_terms and low_terms else ("inform", "rare")
    # 3. 無交集詞組
    disjoint_pair = None
    for t_a in high_terms[:20]:
        for t_b in low_terms[:50]:
            docs_a = set(p.doc_num for p in indexer.get_postings(t_a))
            docs_b = set(p.doc_num for p in indexer.get_postings(t_b))
            if not (docs_a & docs_b):
                disjoint_pair = (t_a, t_b)
                break
        if disjoint_pair:
            break
    q_pair3 = disjoint_pair if disjoint_pair else ("game", "zzzznonexistent")
    # 4. df < 9 邊界詞組
    q_pair4 = (low_terms[0], low_terms[1]) if len(low_terms) >= 2 else ("rare1", "rare2")
    # 5. 典型詞組 ("game" AND "play")
    w_game = "game" if "game" in indexer.index else high_terms[2]
    w_play = "play" if "play" in indexer.index else high_terms[3]
    q_pair5 = (w_game, w_play)

    test_pairs = [
        ("高頻 + 高頻", q_pair1[0], q_pair1[1]),
        ("長串列 + 短串列", q_pair2[0], q_pair2[1]),
        ("無交集 (Disjoint)", q_pair3[0], q_pair3[1]),
        ("低頻邊界 (df < 9)", q_pair4[0], q_pair4[1]),
        ("典型詞組 (game & play)", q_pair5[0], q_pair5[1]),
    ]

    results_table = []
    for cat, w1, w2 in test_pairs:
        p1 = skips.get(w1, [])
        p2 = skips.get(w2, [])
        df1 = len(p1)
        df2 = len(p2)

        res_basic, comp_basic = intersect_basic(p1, p2)
        res_skip, comp_skip = intersect_with_skips(p1, p2)

        reduction = ((comp_basic - comp_skip) / comp_basic * 100.0) if comp_basic > 0 else 0.0
        speedup = (comp_basic / comp_skip) if comp_skip > 0 else 1.0

        results_table.append({
            "category": cat,
            "q1": w1,
            "df1": df1,
            "q2": w2,
            "df2": df2,
            "inter_len": len(res_basic),
            "basic_comp": comp_basic,
            "skip_comp": comp_skip,
            "reduction": reduction,
            "speedup": speedup,
        })

    # 印出終端 Markdown 報告
    print("\n" + "=" * 95)
    print("### M5 Skip Pointer 效能評測報告")
    print(f"> **Preprocessor 設定**：`casefold=True, stopword=True, stem=True` | **文件數**：{indexer.stats['N']:,}\n")
    print("| 類別 | Query Pair | df(q1) | df(q2) | 交集文件數 | Basic 比較次數 | Skip 比較次數 | 比較減少率 (%) | 加速比 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in results_table:
        print(
            f"| {r['category']} | `{r['q1']}` AND `{r['q2']}` | {r['df1']:,} | {r['df2']:,} | "
            f"{r['inter_len']:,} | {r['basic_comp']:,} | {r['skip_comp']:,} | "
            f"{r['reduction']:.1f}% | {r['speedup']:.2f}x |"
        )
    print("=" * 95)

    # 存檔至報告路徑
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("w", encoding="utf-8") as f:
            f.write("# M5 Skip Pointer 效能評測報告\n\n")
            f.write(f"> **測試時間**：{time.strftime('%Y-%m-%d %H:%M:%S')}  \n")
            f.write(f"> **文件數**：{indexer.stats['N']:,} | **詞彙量**：{indexer.stats['vocab_size']:,}  \n\n")
            f.write("| 類別 | Query Pair | df(q1) | df(q2) | 交集文件數 | Basic 比較次數 | Skip 比較次數 | 比較減少率 (%) | 加速比 |\n")
            f.write("|---|---|---|---|---|---|---|---|---|\n")
            for r in results_table:
                f.write(
                    f"| {r['category']} | `{r['q1']}` AND `{r['q2']}` | {r['df1']:,} | {r['df2']:,} | "
                    f"{r['inter_len']:,} | {r['basic_comp']:,} | {r['skip_comp']:,} | "
                    f"{r['reduction']:.1f}% | {r['speedup']:.2f}x |\n"
                )
        print(f"\n[報告輸出] 評測報告已成功儲存至：{report_path}")

    return results_table


def run_eval_skips(args: argparse.Namespace) -> None:
    """獨立執行 eval-skips 子命令。"""
    warc_path = Path(args.input)
    if not warc_path.is_file():
        print(f"錯誤：找不到輸入語料檔案 '{warc_path}'", file=sys.stderr)
        sys.exit(1)

    print(f"正在全記憶體模式下建立索引以供 Skip 評測 (limit: {args.limit})...")
    preprocessor = Preprocessor(
        casefold=True,
        stopword=not args.no_stopword,
        stem=not args.no_stem,
    )
    indexer = Indexer(spimi=False).build(str(warc_path), preprocessor, limit=args.limit)
    report_path = Path(args.output_report)
    run_eval_skips_on_indexer(indexer, preprocessor, report_path)


# ---------------------------------------------------------------------------
# CLI Parser 定義
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """建立 CLI 命令列解析器。"""
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="HW1 Inverted Index System — CLI 統一入口管線",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="執行子命令")

    # 1. build 子命令
    p_build = subparsers.add_parser("build", help="端到端全流程索引建置")
    p_build.add_argument("--input", default="HW1/dataset/04.warc", help="WARC 語料路徑 (預設: HW1/dataset/04.warc)")
    p_build.add_argument("--output", default="HW1/output", help="索引產物輸出目錄 (預設: HW1/output)")
    p_build.add_argument("--limit", type=int, default=None, help="處理最大文件篇數 (預設: 全量)")
    p_build.add_argument("--mode", choices=["memory", "spimi"], default="memory", help="建置模式 (預設: memory)")
    p_build.add_argument("--block-size-mb", type=int, default=150, help="SPIMI 區塊記憶體大小門檻 MB (預設: 150)")
    p_build.add_argument("--flush-every", type=int, default=None, help="SPIMI 累積位置數門檻 (若指定則覆蓋 block-size-mb)")
    p_build.add_argument("--no-stem", action="store_true", help="關閉 Porter Stemmer 字幹提取")
    p_build.add_argument("--no-stopword", action="store_true", help="關閉停用詞過濾")
    p_build.add_argument("--eval-skips", action="store_true", help="建置完成後自動執行 M5 Skip Pointer 評測 (僅限 memory 模式)")

    # 2. query 子命令
    p_query = subparsers.add_parser("query", help="布林 AND 檢索查詢")
    p_query.add_argument("terms", nargs="+", help="查詢詞 (支援 1 個或多個詞進行 AND 交集)")
    p_query.add_argument("--index-dir", default="HW1/output", help="索引所在目錄 (預設: HW1/output)")
    p_query.add_argument("--show-docs", type=int, default=10, help="顯示前 K 篇匹配文件資訊 (預設: 10)")
    p_query.add_argument("--no-skips", action="store_true", help="強制使用 Basic 線性掃描比對 (不使用 Skip 指標)")

    # 3. eval-skips 子命令
    p_eval = subparsers.add_parser("eval-skips", help="獨立執行 M5 Skip Pointer 評測並產出報告")
    p_eval.add_argument("--input", default="HW1/dataset/04.warc", help="WARC 語料路徑 (預設: HW1/dataset/04.warc)")
    p_eval.add_argument("--limit", type=int, default=1000, help="評測取樣文件篇數 (預設: 1000)")
    p_eval.add_argument("--output-report", default="HW1/logs/skip_eval_report.md", help="評測報告輸出 Markdown 路徑")
    p_eval.add_argument("--no-stem", action="store_true", help="關閉 Porter Stemmer 字幹提取")
    p_eval.add_argument("--no-stopword", action="store_true", help="關閉停用詞過濾")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "build":
        run_build(args)
    elif args.command == "query":
        run_query(args)
    elif args.command == "eval-skips":
        run_eval_skips(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
