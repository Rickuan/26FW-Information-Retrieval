"""擷取品質檢查：空文件、疑似截斷、殘留亂碼（一次讀檔完成）。

執行：uv run python -m tools.check_extraction data/04.warc
樣本輸出至 samples/{empty,truncation,mojibake}/，每個網站每類最多一筆；
每次執行會先清空這三個子目錄。
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from bs4 import UnicodeDammit

from documents import ExtractionStats, to_document
from extract import MOJIBAKE, decode_body
from warc import WarcResponse, iter_responses

COMMENT = re.compile(r"<!--.*?-->", re.S)
SCRIPT_STYLE = re.compile(r"<(script|style|noscript)\b.*?</\1\s*>", re.S | re.I)
TAG = re.compile(r"<[^>]+>")
WORD = re.compile(r"[A-Za-z]{3,}")
CATEGORIES = ("empty", "truncation", "mojibake")
PROGRESS_EVERY = 5000


def crude_text(decoded: str) -> str:
    """粗擷取（交叉比對用）：去註解、script/style、標籤，再還原實體。"""
    t = COMMENT.sub(" ", decoded)
    t = SCRIPT_STYLE.sub(" ", t)
    t = TAG.sub(" ", t)
    t = html.unescape(t)
    return " ".join(t.split())


def diagnose_empty(body: bytes) -> list[str]:
    low = body[:50000].lower()
    reasons = []
    if len(body.strip()) < 200:
        reasons.append("tiny body")
    if b"<frameset" in low or b"<frame " in low:
        reasons.append("frameset")
    if b"<iframe" in low:
        reasons.append("iframe")
    if re.search(rb"<meta[^>]+http-equiv\s*=\s*[\"']?refresh", low):
        reasons.append("meta refresh")
    if re.search(rb"location\.(href|replace)|window\.location", low):
        reasons.append("js redirect")
    if low.count(b"<script") >= 3:
        reasons.append("script-heavy")
    if b"<body" not in low:
        reasons.append("no <body>")
    return reasons or ["?"]


class SampleSaver:
    def __init__(self, root: Path, limit: int):
        self.root, self.limit = root, limit
        self.hosts = {c: set() for c in CATEGORIES}
        self.counts: Counter = Counter()
        for c in CATEGORIES:
            d = root / c
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True)

    def save(self, cat: str, resp: WarcResponse, kind: str) -> None:
        host = urlparse(resp.url).netloc or "(no host)"
        if self.counts[cat] >= self.limit or host in self.hosts[cat]:
            return
        self.hosts[cat].add(host)
        self.counts[cat] += 1
        ext = ".txt" if kind == "plain" else ".html"
        (self.root / cat / f"{resp.trec_id}{ext}").write_bytes(resp.body)


def main() -> None:
    ap = argparse.ArgumentParser(description="擷取品質檢查")
    ap.add_argument("warc")
    ap.add_argument("--out", default="samples", help="樣本輸出目錄")
    ap.add_argument("--save-n", type=int, default=30, help="每類最多存幾筆")
    ap.add_argument("--show-n", type=int, default=15, help="每類列出幾筆")
    ap.add_argument("--min-crude", type=int, default=200, help="粗擷取長度門檻")
    ap.add_argument("--ratio", type=float, default=0.5, help="截斷判定比例")
    args = ap.parse_args()

    saver = SampleSaver(Path(args.out), args.save_n)
    stats = ExtractionStats()
    empty_rows, trunc_rows, moji_rows = [], [], []
    empty_reasons: Counter = Counter()
    missing_df: Counter = Counter()     # 在多少份被標記文件中「消失」
    moji_enc: Counter = Counter()
    n_html_ends_ok = n_html = 0
    t0 = time.time()

    for resp in iter_responses(args.warc):
        doc = to_document(resp, stats)
        if stats.total % PROGRESS_EVERY == 0:
            print(f"  ...已處理 {stats.total} 筆 ({time.time() - t0:.0f}s)")
        if doc is None:
            continue

        # (1) 空文件
        if not doc.text:
            reasons = diagnose_empty(resp.body)
            empty_reasons.update(reasons)
            empty_rows.append((doc.trec_id, resp.http_status, len(resp.body), reasons))
            saver.save("empty", resp, doc.kind)

        # (2) 疑似截斷（僅 HTML）
        if doc.kind == "html":
            n_html += 1
            ends_ok = resp.body.rstrip().lower().endswith(b"</html>")
            n_html_ends_ok += ends_ok
            crude = crude_text(decode_body(resp.body))
            if len(crude) >= args.min_crude:
                ratio = len(doc.text) / len(crude)
                if ratio < args.ratio:
                    gone = Counter(w.lower() for w in WORD.findall(crude))
                    gone.subtract(Counter(w.lower() for w in WORD.findall(doc.text)))
                    missing_df.update(w for w, n in gone.items() if n > 0)
                    trunc_rows.append((doc.trec_id, len(crude), len(doc.text), ratio, ends_ok))
                    saver.save("truncation", resp, doc.kind)

        # (3) 殘留亂碼
        hits = MOJIBAKE.findall(doc.text)
        if hits:
            enc = UnicodeDammit(resp.body, is_html=True).original_encoding or "(none)"
            moji_enc[enc] += 1
            m = MOJIBAKE.search(doc.text)
            ctx = doc.text[max(0, m.start() - 30): m.end() + 30]
            moji_rows.append((doc.trec_id, len(hits), enc, ctx))
            saver.save("mojibake", resp, doc.kind)

    # ---------- 報告 ----------
    print("\n" + "=" * 60)
    print(f"耗時: {time.time() - t0:.1f}s")
    print(stats.summary())

    print(f"\n[1] 擷取後無文字: {len(empty_rows)} 筆")
    print("-" * 60)
    for r, n in empty_reasons.most_common():
        print(f"{n:6d}  {r}")
    for trec_id, status, size, reasons in empty_rows[:args.show_n]:
        print(f"{trec_id}  [{status}]  {size} bytes  {', '.join(reasons)}")

    n_tr = len(trunc_rows)
    n_tr_ends_ok = sum(r[4] for r in trunc_rows)
    print(f"\n[2] 疑似截斷（擷取 < 粗擷取 × {args.ratio}）: {n_tr} 筆")
    print("-" * 60)
    if n_html:
        print(f"全部 HTML 以 </html> 結尾的比例: {n_html_ends_ok / n_html:.1%}")
    if n_tr:
        print(f"被標記者以 </html> 結尾的比例: {n_tr_ends_ok / n_tr:.1%}")
    print(f"\n消失最多的詞（出現於幾份被標記文件）:")
    for w, n in missing_df.most_common(40):
        print(f"{n:6d}  {w}")
    print(f"\n比例最低的 {args.show_n} 筆:")
    for trec_id, c_len, t_len, ratio, ends_ok in sorted(trunc_rows, key=lambda r: r[3])[:args.show_n]:
        print(f"{trec_id}  粗擷取 {c_len}  擷取 {t_len}  比例 {ratio:.2f}  </html>結尾={ends_ok}")

    print(f"\n[3] 殘留亂碼: {len(moji_rows)} 筆")
    print("-" * 60)
    print("UnicodeDammit 選用的編碼:")
    for enc, n in moji_enc.most_common():
        print(f"  {n:6d}  {enc}")
    for trec_id, n_hits, enc, ctx in sorted(moji_rows, key=lambda r: -r[1])[:args.show_n]:
        print(f"{trec_id}  [{enc}]  {n_hits} 處")
        print(f"    …{ctx}…")

    print(f"\n樣本已存至 {args.out}/：" +
          "、".join(f"{c} {saver.counts[c]} 筆" for c in CATEGORIES))


if __name__ == "__main__":
    main()