"""
compare_preprocessing.py — 比較不同前處理方式對索引大小與詞彙組成的影響

注意：沒有查詢集與相關性判斷，只能比較「索引大小 / 雜訊」，不能比較檢索效果。

版本：
  raw split        只依空白切開（完全不處理）
  current          目前的 tokenize() + casefold
  no numbers       current 再移除不含任何字母的詞（2008、3.14、1/2、7:30、10,000）
  no urls          current 再移除網址與 email
  no numbers+urls  兩者皆移除

用法（在 repo 根目錄）：
  uv run python HW1/src/compare_preprocessing.py HW1/dataset/04.warc --limit 2000      # 快速確認
  uv run python HW1/src/compare_preprocessing.py HW1/dataset/04.warc | tee HW1/logs/compare_preprocessing.txt
"""
import argparse
import time
from collections import Counter
from itertools import islice

from spacy.lang.lex_attrs import like_url

from documents import iter_documents
from tokenizer import tokenize

VARIANTS = ["raw split", "current", "no numbers", "no urls", "no numbers+urls"]

_url_cache = {}


def is_number(t):
    # 不含任何字母即視為「數字類」：2008、3.14、1/2、7:30、10,000、025
    # 字母數字混合（mp3、rmb500yuan）保留
    return not any(c.isalpha() for c in t)


def is_url(t):
    # 對每個不同的詞只判斷一次（全量約 64 萬個詞，2,700 萬個 token）
    r = _url_cache.get(t)
    if r is None:
        r = like_url(t) or ("@" in t and "." in t.rsplit("@", 1)[-1])
        _url_cache[t] = r
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("warc")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    stats = {v: {"tokens": 0, "postings": 0, "vocab": Counter()} for v in VARIANTS}
    removed_num, removed_url = Counter(), Counter()
    docs = iter_documents(args.warc)
    if args.limit:
        docs = islice(docs, args.limit)

    t0 = time.time()
    n = 0
    for doc in docs:
        n += 1
        raw = doc.text.split()
        cur = [t.casefold() for t in tokenize(doc.text)]
        num = [is_number(t) for t in cur]
        url = [is_url(t) for t in cur]
        nonum = [t for t, a in zip(cur, num) if not a]
        nourl = [t for t, b in zip(cur, url) if not b]
        both = [t for t, a, b in zip(cur, num, url) if not a and not b]

        for v, toks in zip(VARIANTS, (raw, cur, nonum, nourl, both)):
            s = stats[v]
            s["tokens"] += len(toks)
            s["postings"] += len(set(toks))      # 這份文件貢獻的 (詞, 文件) 組合數
            s["vocab"].update(toks)

        for t, a, b in zip(cur, num, url):
            if a:
                removed_num[t] += 1
            elif b:
                removed_url[t] += 1

        if n % 5000 == 0:
            print(f"  ...{n} docs ({time.time() - t0:.0f}s)")

    print(f"\n{n} docs in {time.time() - t0:.1f}s\n")

    base = stats["current"]
    base_vocab = len(base["vocab"])
    print(f"{'variant':17s} {'tokens':>12s} {'vocab':>10s} {'vs current':>11s} "
          f"{'hapax %':>8s} {'postings':>12s} {'avg doc len':>12s}")
    print("-" * 88)
    for v in VARIANTS:
        s = stats[v]
        vocab = len(s["vocab"])
        hapax = sum(1 for c in s["vocab"].values() if c == 1)
        print(f"{v:17s} {s['tokens']:12,d} {vocab:10,d} {(vocab - base_vocab) / base_vocab:+10.1%} "
              f"{hapax / vocab:8.1%} {s['postings']:12,d} {s['tokens'] / n:12.1f}")

    n_num_terms = sum(1 for t in base["vocab"] if is_number(t))
    n_url_terms = sum(1 for t in base["vocab"] if is_url(t) and not is_number(t))
    print(f"\nin current vocab: {n_num_terms:,} number-like terms ({n_num_terms / base_vocab:.1%}), "
          f"{n_url_terms:,} url/email terms ({n_url_terms / base_vocab:.1%})")
    print(f"number-like tokens: {sum(removed_num.values()):,} ({sum(removed_num.values()) / base['tokens']:.1%} of tokens)")
    print(f"url/email tokens  : {sum(removed_url.values()):,} ({sum(removed_url.values()) / base['tokens']:.1%} of tokens)")

    print("\ntop 20 removed by 'no numbers':")
    print("  " + ", ".join(f"{t} ({c:,})" for t, c in removed_num.most_common(20)))
    print("\ntop 20 removed by 'no urls':")
    print("  " + ", ".join(f"{t} ({c:,})" for t, c in removed_url.most_common(20)))

    raw_top = [t for t, _ in stats["raw split"]["vocab"].most_common(2000)
               if not t.isalnum()][:20]
    print("\nraw split: frequent tokens with punctuation attached (examples):")
    print("  " + ", ".join(f"{t} ({stats['raw split']['vocab'][t]:,})" for t in raw_top))


if __name__ == "__main__":
    main()