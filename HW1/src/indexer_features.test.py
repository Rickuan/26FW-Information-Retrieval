"""
indexer_features.test.py — 驗證三項新功能：array 位置、SPIMI、Radix Trie

用法（在 repo 根目錄）：
  # 1) 單元測試 + SPIMI 與全記憶體結果逐筆比對 + trie 驗證（前 2000 篇，約 1 分鐘）
  uv run python HW1/src/indexer_features.test.py HW1/dataset/04.warc compare 2000

  # 2) 全量記憶體峰值比較（兩種模式要分開兩個 process 跑，peak RSS 才準）
  uv run python HW1/src/indexer_features.test.py HW1/dataset/04.warc bench memory
  uv run python HW1/src/indexer_features.test.py HW1/dataset/04.warc bench spimi
"""
import random
import resource
import sys
import time
from itertools import zip_longest

from indexer import Indexer, add_document
from tokenizer import Preprocessor
from trie import RadixTrie


def peak_rss_mb():
    # Linux 上 ru_maxrss 的單位是 KB
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def as_tuples(plist):
    """把 postings 轉成可直接比較的形式（array 不能直接和 list 比較）。"""
    return [(p.doc_num, p.tf, list(p.positions)) for p in plist]


# ---------------------------------------------------------------------------
# 單元測試
# ---------------------------------------------------------------------------
def test_array_positions():
    index, dm = {}, {}
    add_document(index, dm, 5, "t5", "u5", [(1, "a"), (2, "b"), (3, "a")])
    p = index["a"][0]
    assert p.positions.typecode == "I" and p.positions.itemsize == 4
    assert list(p.positions) == [1, 3] and p.tf == 2
    print("array positions OK")


def test_trie_unit():
    t = RadixTrie()
    words = ["test", "team", "te", "toast", "tea", "a", "apple", "app"]
    for i, w in enumerate(words):
        t.insert(w, i)

    assert len(t) == len(words)
    for i, w in enumerate(words):
        assert t.get(w) == i
    assert t.get("tes") is None and "t" not in t and "teams" not in t

    assert [w for w, _ in t.prefix_search("te")] == ["te", "tea", "team", "test"]
    assert [w for w, _ in t.prefix_search("tes")] == ["test"]       # prefix 在邊中間結束
    assert [w for w, _ in t.prefix_search("ap")] == ["app", "apple"]
    assert t.prefix_search("x") == []
    assert [w for w, _ in t.prefix_search("")] == sorted(words)     # 全部，依字典序
    assert len(t.prefix_search("t", limit=2)) == 2

    t.insert("test", 99)                                            # 覆寫不增加大小
    assert t.get("test") == 99 and len(t) == len(words)
    print("trie unit OK")


# ---------------------------------------------------------------------------
# SPIMI vs 全記憶體：逐詞逐筆比對
# ---------------------------------------------------------------------------
def test_spimi_equivalence(path, n):
    pre = Preprocessor()

    t0 = time.time()
    mem = Indexer().build(path, pre, limit=n, progress=0)
    t_mem = time.time() - t0

    # flush 門檻設很小，強迫產生多個 partial，才能測到歸併邏輯
    t0 = time.time()
    sp = Indexer(spimi=True, flush_every=200_000, tmp_dir="spimi_test_tmp").build(
        path, pre, limit=n, progress=0)
    t_sp = time.time() - t0

    print(f"\nmemory: {t_mem:.1f}s   spimi: {t_sp:.1f}s ({sp.n_partials} partials)")
    print("stats memory:", mem.stats)
    print("stats spimi :", sp.stats)
    assert mem.stats == sp.stats, "stats differ"
    assert sp.n_partials > 1, "flush_every too large: only one partial, merge not exercised"

    count = 0
    for a, b in zip_longest(mem.iter_postings(), sp.iter_postings()):
        assert a is not None and b is not None, "different number of terms"
        (t1, p1), (t2, p2) = a, b
        assert t1 == t2, f"term mismatch: {t1!r} vs {t2!r}"
        assert as_tuples(p1) == as_tuples(p2), f"postings mismatch for {t1!r}"
        count += 1
    assert count == mem.stats["vocab_size"]
    sp.cleanup()
    print(f"SPIMI == in-memory for all {count} terms: OK")
    return mem


# ---------------------------------------------------------------------------
# Trie 建在真實索引上
# ---------------------------------------------------------------------------
def test_trie_on_index(idx):
    t0 = time.time()
    trie = idx.build_trie()
    dt = time.time() - t0
    print(f"\ntrie: {len(trie)} terms, {trie.node_count()} nodes, built in {dt:.1f}s")
    assert len(trie) == idx.stats["vocab_size"]

    # 抽 1000 個詞：trie 取回的必須是同一個 postings 物件
    sample = random.Random(0).sample(sorted(idx.index), 1000)
    for term in sample:
        assert trie.get(term) is idx.index[term]
    print("trie lookup == dict lookup for 1000 sampled terms: OK")

    # 精確查詢速度：dict vs trie
    t0 = time.time()
    for _ in range(100):
        for term in sample:
            idx.index[term]
    t_dict = time.time() - t0
    t0 = time.time()
    for _ in range(100):
        for term in sample:
            trie.get(term)
    t_trie = time.time() - t0
    print(f"100k exact lookups: dict {t_dict * 1000:.0f} ms, trie {t_trie * 1000:.0f} ms")

    # 前綴查詢示範（顯示詞與 df）
    for prefix in ["comput", "inform", "retriev", "zzzz"]:
        res = trie.prefix_search(prefix, limit=10)
        print(f"prefix {prefix!r}: {[(w, len(pl)) for w, pl in res]}")

     # 透過 Indexer 的介面查詢
    for term in sample[:100]:
        assert idx.get_postings(term) is idx.index[term]
    assert idx.get_postings("no-such-term-xyz") == []
    assert [w for w, _ in idx.prefix_search("comput", 10)] == [w for w, _ in trie.prefix_search("comput", 10)]
    print("get_postings / prefix_search via Indexer: OK")


# ---------------------------------------------------------------------------
# 全量記憶體峰值
# ---------------------------------------------------------------------------
def bench(path, mode):
    pre = Preprocessor()
    t0 = time.time()
    idx = Indexer(spimi=(mode == "spimi")).build(path, pre)
    dt = time.time() - t0
    print(f"\nmode={mode}  time={dt:.1f}s  peak RSS={peak_rss_mb():.0f} MB")
    print("stats:", idx.stats)
    if mode == "memory":
        before = peak_rss_mb()
        t0 = time.time()
        trie = idx.build_trie()
        print(f"trie: {len(trie)} terms, {trie.node_count()} nodes, "
              f"built in {time.time() - t0:.1f}s, peak RSS {before:.0f} -> {peak_rss_mb():.0f} MB")
    if mode == "spimi":
        print("partials:", idx.n_partials)
        idx.cleanup()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "HW1/dataset/04.warc"
    cmd = sys.argv[2] if len(sys.argv) > 2 else "compare"

    if cmd == "compare":
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 2000
        test_array_positions()
        test_trie_unit()
        idx = test_spimi_equivalence(path, n)
        test_trie_on_index(idx)
    elif cmd == "bench":
        bench(path, sys.argv[3] if len(sys.argv) > 3 else "memory")
    else:
        raise SystemExit(f"unknown command: {cmd}")