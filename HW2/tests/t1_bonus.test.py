"""t1_bonus.test.py — T1 加分：IndexReader.vocabulary() / prefix_terms()

執行：
  uv run python HW2/tests/t1_bonus.test.py
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

# 確保可以 import HW2/src 的模組
SRC = Path(__file__).resolve().parent.parent / "src"
INDEX = Path(__file__).resolve().parent.parent / "index"
sys.path.insert(0, str(SRC))

from trie import RadixTrie
from writer import IndexReader

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def check(name: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
    return condition


def run(name: str, fn) -> bool:
    """執行 fn() -> (condition, detail)；例外視為 FAIL，不中斷後續測試。"""
    try:
        cond, detail = fn()
    except Exception as e:  # noqa: BLE001
        return check(name, False, f"{type(e).__name__}: {e}")
    return check(name, cond, detail)


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


reader = IndexReader(INDEX)
results: list[bool] = []
timings: dict[str, float] = {}

# ===========================================================================
section("vocabulary()")
# ===========================================================================
# 分開量測：lexicon 載入（核心既有成本）與 vocabulary() 第一次建 list 的成本
t0 = time.perf_counter()
reader._load_lexicon()
timings["_load_lexicon()"] = time.perf_counter() - t0
try:
    t0 = time.perf_counter()
    vocab = reader.vocabulary()
    timings["vocabulary() 第一次（lexicon 已載入）"] = time.perf_counter() - t0
except Exception as e:  # noqa: BLE001
    vocab = None
    print(f"  vocabulary() 失敗：{type(e).__name__}: {e}")

results.append(run("len(vocabulary()) == 573233", lambda: (len(vocab) == 573233, f"len={len(vocab)}")))
results.append(run("vocabulary() == sorted(vocabulary())", lambda: (vocab == sorted(vocab), "")))
results.append(run("vocabulary()[0] == ',ltd.is'", lambda: (vocab[0] == ",ltd.is", f"got={vocab[0]!r}")))
results.append(run("vocabulary()[-1] == '𣲛'", lambda: (vocab[-1] == "𣲛", f"got={vocab[-1]!r}")))
results.append(run("vocabulary() is vocabulary()", lambda: (reader.vocabulary() is reader.vocabulary(), "")))

# ===========================================================================
section("prefix_terms()")
# ===========================================================================
def _comput():
    r = reader.prefix_terms("comput")
    ok = len(r) == 64 and r[0] == "comput" and all(t.startswith("comput") for t in r) and r == sorted(r)
    return ok, f"len={len(r)}, first={r[0] if r else None!r}"


results.append(run("prefix_terms('comput')：64 筆、首筆 'comput'、皆以 comput 開頭、已排序", _comput))
results.append(run("len(prefix_terms('lin')) == 629",
                   lambda: (len(reader.prefix_terms("lin")) == 629, f"len={len(reader.prefix_terms('lin'))}")))
results.append(run("len(prefix_terms('a')) == 31236",
                   lambda: (len(reader.prefix_terms("a")) == 31236, f"len={len(reader.prefix_terms('a'))}")))
results.append(run("prefix_terms('zzzq') == []",
                   lambda: (reader.prefix_terms("zzzq") == [], f"got={reader.prefix_terms('zzzq')}")))


def _empty_raises():
    try:
        reader.prefix_terms("")
    except ValueError as e:
        return True, f"ValueError: {e}"
    return False, "未拋出 ValueError"


results.append(run("prefix_terms('') 拋出 ValueError", _empty_raises))

# ===========================================================================
section("獨立路徑對照：暴力掃描 + RadixTrie")
# ===========================================================================
def _cross_check():
    t0 = time.perf_counter()
    trie = RadixTrie()
    for t in vocab:
        trie.insert(t, None)
    timings["RadixTrie 建置（對照用）"] = time.perf_counter() - t0

    rng = random.Random(42)
    prefixes = [t[: rng.randint(1, 3)] for t in rng.sample(vocab, 20)]
    bad = []
    for p in prefixes:
        got = reader.prefix_terms(p)
        brute = [t for t in vocab if t.startswith(p)]
        via_trie = [k for k, _ in trie.prefix_search(p)]
        if not (got == brute == via_trie):
            bad.append((p, len(got), len(brute), len(via_trie)))
    return not bad, f"prefixes={prefixes}" if not bad else f"mismatch={bad}"


results.append(run("20 個隨機 prefix：prefix_terms == 暴力掃描 == RadixTrie", _cross_check))

# ===========================================================================
section("量測")
# ===========================================================================
try:
    for p in ("comput", "a"):
        reps = 1000 if p == "comput" else 100
        t0 = time.perf_counter()
        for _ in range(reps):
            reader.prefix_terms(p)
        timings[f"prefix_terms({p!r})（{reps} 次平均）"] = (time.perf_counter() - t0) / reps
except Exception as e:  # noqa: BLE001
    print(f"  量測失敗：{type(e).__name__}: {e}")
for k, v in timings.items():
    print(f"  {k}: {v * 1000:.3f} ms")

# ===========================================================================
section("Test Summary")
# ===========================================================================
all_passed = all(results)
print(f"\n  {sum(results)}/{len(results)} passed")
print(f"  Overall: {'ALL PASSED ✓' if all_passed else 'SOME FAILED ✗'}\n")
sys.exit(0 if all_passed else 1)
