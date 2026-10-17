import resource
import sys
import time

from indexer import Indexer, add_document
from tokenizer import Preprocessor


def unit():
    index, dm = {}, {}
    add_document(index, dm, 5, "t5", "u5", [(1, "a"), (2, "b"), (3, "a"), (5, "a")])
    add_document(index, dm, 7, "t7", "u7", [(2, "a")])
    add_document(index, dm, 9, "t9", "u9", [])
    assert [(p.doc_num, p.tf, list(p.positions)) for p in index["a"]] == [(5, 3, [1, 3, 5]), (7, 1, [2])]
    assert index["b"][0].tf == 1
    assert dm[5].doc_len == 4 and dm[9].doc_len == 0
    assert all(p.doc_num != 9 for pl in index.values() for p in pl)
    try:
        add_document(index, dm, 6, "t6", "u6", [(1, "a")])
        raise SystemExit("decreasing doc_num not caught")
    except AssertionError:
        pass
    assert Preprocessor(stopword=True).process("the of and to") == []
    print("unit OK")


def check(idx):
    bad = 0
    for plist in idx.index.values():
        prev = -1
        for p in plist:
            ps = p.positions
            if p.doc_num <= prev or p.tf != len(ps) or any(a >= b for a, b in zip(ps, ps[1:])):
                bad += 1
            prev = p.doc_num
    return bad


unit()

path = sys.argv[1] if len(sys.argv) > 1 else "../../04.warc"
n = int(sys.argv[2]) if len(sys.argv) > 2 else 200

t0 = time.time()
# idx = Indexer().build(path, Preprocessor(), limit=n or None)
flags = sys.argv[3:]
pre = Preprocessor(casefold="nocase" not in flags, stopword="stop" in flags, stem="stem" in flags)
idx = Indexer().build(path, pre, limit=n or None)
dt = time.time() - t0
s = idx.stats
print("\nstats:", s)

npost = sum(len(pl) for pl in idx.index.values())
npos = sum(p.tf for pl in idx.index.values() for p in pl)
print(f"postings (term,doc pairs): {npost}   positions: {npos}")
print("sum(tf) == total_tokens:", npos == s["total_tokens"])
print("doc_len sum == total_tokens:", sum(e.doc_len for e in idx.doc_map.values()) == s["total_tokens"])
if n:
    print("N == n:", s["N"] == n)
print("bad postings:", check(idx))
empty = [k for k, e in idx.doc_map.items() if e.doc_len == 0]
print(f"empty docs: {len(empty)} {empty[:5]}")

print(f"\ntime {dt:.1f}s   {s['N'] / dt:.1f} docs/s (incl. extract + tokenize)")
print(f"peak RSS: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MB")

print("\ntop 10 df:")
for t, pl in sorted(idx.index.items(), key=lambda kv: -len(kv[1]))[:10]:
    print(f"{len(pl):8d}  {t}")