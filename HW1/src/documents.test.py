"""資料集總覽（診斷工具，不屬於索引流程）。

執行：uv run python -m tools.dataset_report 04.warc
"""
from __future__ import annotations

import argparse
import re
import time
from collections import Counter

from langdetect import DetectorFactory, LangDetectException, detect

from documents import ExtractionStats, to_document
from warc import iter_responses, parse_trec_id, read_warcinfo

LANG_SNIPPET = 1000
MIN_LETTERS = 20
PROGRESS_EVERY = 5000
SEGMENT_RE = re.compile(r"clueweb09-([a-z]+)\d+")


def detect_lang(text: str) -> str:
    snippet = text[:LANG_SNIPPET]
    if sum(ch.isalpha() for ch in snippet) < MIN_LETTERS:
        return "(too short)"
    try:
        return detect(snippet)
    except LangDetectException:
        return "(unknown)"


def print_counter(title: str, counter: Counter, total: int) -> None:
    print(f"\n{title}")
    print("-" * 50)
    for key, n in counter.most_common():
        pct = n / total * 100 if total else 0.0
        print(f"{n:8d}  {pct:6.2f}%  {key}")


def report_ids(raw_nums: list[int], kept_nums: list[int],
               prefixes: Counter, n_excluded: int) -> bool:
    print("\n[ID] docID 檢查")
    print("-" * 50)
    if not raw_nums:
        print("  ✗ 沒有任何 response 紀錄")
        return False
    raw_set = set(raw_nums)
    dup = len(raw_nums) - len(raw_set)
    non_inc = sum(1 for a, b in zip(raw_nums, raw_nums[1:]) if b <= a)
    lo, hi = min(raw_set), max(raw_set)
    missing = sorted(set(range(lo, hi + 1)) - raw_set)
    dropped = raw_set - set(kept_nums)

    print(f"  TREC-ID 前綴: {dict(prefixes)}")
    print(f"  原始 doc_num 範圍: {lo} – {hi}（{len(raw_nums)} 筆）")
    print(f"  重複: {dup}   非遞增: {non_inc}   缺號: {len(missing)}")
    if missing:
        print(f"  前 20 個缺號: {missing[:20]}")
    print(f"  未進索引的 doc_num: {len(dropped)}（排除數 {n_excluded}）")

    checks = [
        (len(prefixes) == 1, "所有 TREC-ID 前綴相同（doc_num 不會撞號）"),
        (dup == 0, "沒有重複的 doc_num"),
        (non_inc == 0, "doc_num 依檔案順序嚴格遞增"),
        (lo == 0 and not missing, "原始 doc_num 從 0 開始且無缺號"),
        (len(dropped) == n_excluded, "未進索引數 = 排除數"),
    ]
    for passed, label in checks:
        print(f"  {'✓' if passed else '✗'} {label}")
    return all(p for p, _ in checks)


def main() -> None:
    ap = argparse.ArgumentParser(description="ClueWeb09 WARC 資料集報告")
    ap.add_argument("warc", help="WARC 檔路徑，例如04.warc")
    ap.add_argument("--samples", type=int, default=3, help="節錄前幾筆文件")
    ap.add_argument("--excerpt", type=int, default=300, help="每筆節錄字元數")
    ap.add_argument("--no-lang", action="store_true", help="跳過語言偵測（加速）")
    args = ap.parse_args()
    DetectorFactory.seed = 0                     # 讓 langdetect 結果可重現

    info, info_body = read_warcinfo(args.warc)
    print("[warcinfo 標頭]")
    for k, v in info.items():
        print(f"  {k}: {v}")
    print("[warcinfo 內容]")
    print("  " + info_body.replace("\n", "\n  "))

    stats = ExtractionStats()
    record_types: Counter = Counter()
    prefixes: Counter = Counter()
    segments: Counter = Counter()
    langs: Counter = Counter()
    raw_nums: list[int] = []
    kept_nums: list[int] = []
    samples = []
    t0 = time.time()

    for resp in iter_responses(args.warc, record_types):
        raw_nums.append(resp.doc_num)
        prefixes[parse_trec_id(resp.trec_id)[0]] += 1
        m = SEGMENT_RE.match(resp.trec_id)
        segments[m.group(1) if m else "(unknown)"] += 1
        if len(raw_nums) % PROGRESS_EVERY == 0:
            print(f"  ...已處理 {len(raw_nums)} 筆 ({time.time() - t0:.0f}s)")

        doc = to_document(resp, stats)
        if doc is None:
            continue
        kept_nums.append(doc.doc_num)
        if not doc.text:
            langs["(empty)"] += 1
            continue
        lang = "(skipped)" if args.no_lang else detect_lang(doc.text)
        langs[lang] += 1
        if len(samples) < args.samples:
            samples.append((doc, resp.content_type, lang))

    print("\n" + "=" * 60)
    print(f"檔案: {args.warc}    耗時: {time.time() - t0:.1f}s")
    print(stats.summary())

    print_counter("[WARC] 紀錄類型", record_types, sum(record_types.values()))
    print_counter("[1] Content-Type 分布", stats.content_types, stats.total)

    print(f"\n[1] 前 {len(samples)} 筆保留文件節錄")
    for i, (doc, ctype, lang) in enumerate(samples, 1):
        print("=" * 60)
        print(f"#{i}  {doc.trec_id}  (doc_num={doc.doc_num})")
        print(f"URL: {doc.url}")
        print(f"Content-Type: {ctype}   kind: {doc.kind}   偵測語言: {lang}   長度: {len(doc.text)}")
        print("-" * 60)
        print(doc.text[:args.excerpt])
    print("=" * 60)

    print_counter("[2] docID 前綴語言（ClueWeb 官方分類）", segments, stats.total)
    print_counter("[2] 內文偵測語言（保留文件）", langs, stats.kept)

    ok = report_ids(raw_nums, kept_nums, prefixes, stats.n_excluded)
    print(f"\n整體 docID 檢查: {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    main()