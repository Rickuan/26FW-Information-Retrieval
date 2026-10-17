"""
indexer_features.test.py — 驗證三項新功能：array 位置、SPIMI、Radix Trie

用法（在 repo 根目錄）：
  # 1) 單元測試 + SPIMI 與全記憶體結果逐筆比對 + trie 驗證（前 2000 篇，約 1 分鐘）
  uv run python HW1/src/indexer_features.test.py HW1/dataset/04.warc compare 2000

  # 2) 全量記憶體峰值比較（兩種模式要分開兩個 process 跑，peak RSS 才準）
  uv run python HW1/src/indexer_features.test.py HW1/dataset/04.warc bench memory
  uv run python HW1/src/indexer_features.test.py HW1/dataset/04.warc bench spimi

   # 3) M4 / M5 讀取效能：舊版（list of Posting）vs 新版（欄式儲存）
  uv run python HW1/src/indexer_features.test.py HW1/dataset/04.warc m4 5000   # 前 5000 篇，約 1.5 分鐘
  uv run python HW1/src/indexer_features.test.py HW1/dataset/04.warc m4 0      # 全量，約 7～8 分鐘、約 5 GB 記憶體
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


def test_columnar_equivalence(path, n):
    from itertools import islice
    from documents import iter_documents
    pre = Preprocessor()
    ref, ref_map = {}, {}
    new = Indexer()
    for doc in islice(iter_documents(path), n):
        terms = pre.process(doc.text)
        add_document(ref, ref_map, doc.doc_num, doc.trec_id, doc.url, terms)
        new.add_document(doc, terms)
    new.get_stats()
    assert sorted(ref) == sorted(new.index)
    for term in ref:
        assert as_tuples(ref[term]) == as_tuples(new.index[term]), f"mismatch for {term!r}"
    assert ref_map == new.doc_map
    print(f"columnar == reference (list-of-Posting) for all {len(ref)} terms: OK")

# ---------------------------------------------------------------------------
# Trie 建在真實索引上
# ---------------------------------------------------------------------------
def test_trie_on_index(idx):
    t0 = time.time()
    trie = idx.build_trie()
    dt = time.time() - t0
    print(f"\ntrie: {len(trie)} terms, {trie.node_count()} nodes, built in {dt:.1f}s")
    assert len(trie) == idx.stats["vocab_size"]

    sample = random.Random(0).sample(sorted(idx.index), 1000)
    for term in sample:
        assert trie.get(term) == idx.df(term) == len(idx.index[term])
    print("trie df == index df for 1000 sampled terms: OK")

    t0 = time.time()
    for _ in range(100):
        for term in sample:
            idx.df(term)
    t_dict = time.time() - t0
    t0 = time.time()
    for _ in range(100):
        for term in sample:
            trie.get(term)
    t_trie = time.time() - t0
    print(f"100k exact lookups (df): dict {t_dict * 1000:.0f} ms, trie {t_trie * 1000:.0f} ms")

    for prefix in ["comput", "inform", "retriev", "zzzz"]:
        res = idx.prefix_search(prefix, limit=10)
        print(f"prefix {prefix!r}: {[(w, len(pl)) for w, pl in res]}")

    for term in sample[:100]:
        assert as_tuples(idx.get_postings(term)) == as_tuples(idx.index[term])
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



# ---------------------------------------------------------------------------
# M4 / M5 讀取效能：舊版（dict[str, list[Posting]]）vs 新版（欄式儲存）
# ---------------------------------------------------------------------------
def format_line(term, plist):
    # 作業規定格式：term, df: <docID, tf: <pos1, pos2, …>; …>
    body = "; ".join(f"{p.doc_num}, {p.tf}: <{', '.join(map(str, p.positions))}>" for p in plist)
    return f"{term}, {len(plist)}: <{body}>\n"


def bench_m4(path, n):
    import gc
    import hashlib
    from itertools import islice
    from documents import iter_documents

    # 同一批文件只斷詞一次，同時餵給舊版與新版，確保兩者資料完全相同
    pre = Preprocessor()
    ref, ref_map = {}, {}
    new = Indexer()
    docs = iter_documents(path)
    if n:
        docs = islice(docs, n)
    t0 = time.time()
    for i, doc in enumerate(docs, 1):
        terms = pre.process(doc.text)
        add_document(ref, ref_map, doc.doc_num, doc.trec_id, doc.url, terms)
        new.add_document(doc, terms)
        if i % 5000 == 0:
            print(f"  ...{i} docs ({time.time() - t0:.0f}s)")
    new.get_stats()
    print(f"\nbuilt both indexes in {time.time() - t0:.1f}s   stats: {new.stats}")

    # 舊版索引有上千萬個長期存在的物件，Python GC 每次全掃都要走過它們，
    # 會讓「新版建立大量暫時物件」的測試被不公平地拖慢。
    # freeze() 把目前所有物件移出 GC 掃描範圍，兩邊都在相同條件下計時。
    gc.collect()
    gc.freeze()

    def old_iter():
        for t in sorted(ref):                 # 原計畫 M4 的寫法：sorted(idx.index)
            yield t, ref[t]

    def traverse(it):
        total = 0
        for _, plist in it:
            for p in plist:
                total += p.tf
        return total

    def write_text(it):
        h = hashlib.sha1()
        for term, plist in it:
            h.update(format_line(term, plist).encode())
        return h.hexdigest()

    def timed(fn):
        t = time.perf_counter()
        r = fn()
        return time.perf_counter() - t, r

    rng = random.Random(0)
    vocab = sorted(ref)
    sample = rng.sample(vocab, min(10_000, len(vocab)))
    top = sorted(ref, key=lambda t: -len(ref[t]))[:100]

    tasks = [
        ("traverse all postings",
         lambda: traverse(old_iter()),
         lambda: traverse(new.iter_postings())),
        ("format assignment text (M4)",
         lambda: write_text(old_iter()),
         lambda: write_text(new.iter_postings())),
        ("10k random term lookups",
         lambda: sum(len(ref[t]) for t in sample),
         lambda: sum(len(new.get_postings(t)) for t in sample)),
        ("top-100 df lookups x 10 (M5)",
         lambda: sum(len(ref[t]) for _ in range(10) for t in top),
         lambda: sum(len(new.get_postings(t)) for _ in range(10) for t in top)),
    ]

    print(f"\n{'task':32s} {'old (list)':>12s} {'new (columnar)':>15s} {'new/old':>9s}  same result")
    print("-" * 82)
    for name, f_old, f_new in tasks:
        t_old, r_old = timed(f_old)
        t_new, r_new = timed(f_new)
        ratio = t_new / t_old if t_old else float("inf")
        print(f"{name:32s} {t_old:11.2f}s {t_new:14.2f}s {ratio:8.2f}x  {r_old == r_new}")

    gc.unfreeze()
    print(f"\npeak RSS (both indexes in memory): {peak_rss_mb():.0f} MB")


# ---------------------------------------------------------------------------
# 重現舊版（v1 list / v2 array）的全記憶體 Peak RSS，供報告對照
# v2 直接使用 indexer.py 保留的參考實作 add_document；
# v1 只差在 positions 用 list，這裡複製一份 list 版本。
# ---------------------------------------------------------------------------
def add_document_list(index, doc_map, doc_num, trec_id, url, terms):
    from indexer import DocEntry, Posting
    doc_map[doc_num] = DocEntry(trec_id, len(terms), url)
    for pos, tok in terms:
        plist = index.get(tok)
        if plist is None:
            index[tok] = [Posting(doc_num, 1, [pos])]
            continue
        last = plist[-1]
        if last.doc_num == doc_num:
            last.tf += 1
            last.positions.append(pos)
        else:
            plist.append(Posting(doc_num, 1, [pos]))


def bench_legacy(path, kind):
    from documents import iter_documents
    fn = {"array": add_document, "list": add_document_list}[kind]
    pre = Preprocessor()
    index, doc_map = {}, {}
    t0 = time.time()
    for i, doc in enumerate(iter_documents(path), 1):
        fn(index, doc_map, doc.doc_num, doc.trec_id, doc.url, pre.process(doc.text))
        if i % 5000 == 0:
            print(f"  ...{i} docs ({time.time() - t0:.0f}s)")
    dt = time.time() - t0
    npos = sum(p.tf for pl in index.values() for p in pl)
    print(f"\nlegacy={kind}  time={dt:.1f}s  peak RSS={peak_rss_mb():.0f} MB")
    print(f"N={len(doc_map)}  vocab={len(index)}  positions={npos}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "HW1/dataset/04.warc"
    cmd = sys.argv[2] if len(sys.argv) > 2 else "compare"

    if cmd == "compare":
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 2000
        test_array_positions()
        test_trie_unit()
        test_columnar_equivalence(path, n)
        idx = test_spimi_equivalence(path, n)
        test_trie_on_index(idx)
    elif cmd == "bench":
        bench(path, sys.argv[3] if len(sys.argv) > 3 else "memory")
    elif cmd == "m4":
        bench_m4(path, int(sys.argv[3]) if len(sys.argv) > 3 else 5000)
    elif cmd == "legacy":
        bench_legacy(path, sys.argv[3] if len(sys.argv) > 3 else "array")
    else:
        raise SystemExit(f"unknown command: {cmd}")