"""t3.test.py — T3 核心：get_doc_tf 只取 doc／tf

執行：
  uv run python HW2/tests/t3.test.py          # 預設流程（抽樣 term + 計時）
  uv run python HW2/tests/t3.test.py --full   # 另外對全部 term 與 get_postings 對照
"""
from __future__ import annotations

import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
INDEX = ROOT / "index"
sys.path.insert(0, str(SRC))

from writer import IndexReader, decode_postings_block

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
FULL = "--full" in sys.argv


def check(name: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
    return condition


def run(name: str, fn) -> bool:
    """執行 fn() -> (condition, detail)；例外（含 NotImplementedError）視為 FAIL，不中斷。"""
    try:
        cond, detail = fn()
    except Exception as e:  # noqa: BLE001
        return check(name, False, f"{type(e).__name__}: {e}")
    return check(name, cond, detail)


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


reader = IndexReader(INDEX)
lex = reader._load_lexicon()
terms_all = list(lex)
FIXED = ["home", "new", "linux", "kernel", ",ltd.is", terms_all[-1]]
SAMPLE = random.Random(42).sample(terms_all, 20)
TERMS = FIXED + SAMPLE

results: list[bool] = []


def reference(term: str) -> list[tuple[int, int]]:
    return [(p.doc_num, p.tf) for p in reader.get_postings(term)]


# ===========================================================================
section("與 get_postings 對照")
# ===========================================================================
def _lexicon_ends():
    return (terms_all[-1] == "𣲛" and terms_all[0] == ",ltd.is"), f"last={terms_all[-1]!r}"


results.append(run("lexicon 首尾 term 符合計畫（,ltd.is / 𣲛）", _lexicon_ends))


def _match(term: str):
    def _go():
        d, tf = reader.get_doc_tf(term)
        ok = list(zip(d, tf)) == reference(term) and len(d) == len(tf)
        return ok, f"df={len(d)}"
    return _go


for t in FIXED:
    results.append(run(f"get_doc_tf({t!r}) == get_postings 的 (doc, tf)", _match(t)))


def _sample_match():
    bad = []
    for t in SAMPLE:
        d, tf = reader.get_doc_tf(t)
        if list(zip(d, tf)) != reference(t):
            bad.append(t)
    return not bad, f"{len(SAMPLE)} 個抽樣 term" + (f"，不符：{bad}" if bad else "")


results.append(run("random.Random(42) 抽 20 個 term 全部一致", _sample_match))


def _len_eq_df():
    bad = [t for t in TERMS if len(reader.get_doc_tf(t)[0]) != reader.df(t)]
    return not bad, f"不符：{bad}" if bad else f"{len(TERMS)} 個 term"


results.append(run("len(doc_nums) == df(t)", _len_eq_df))


def _df_known():
    got = {t: reader.df(t) for t in ("home", "new", "linux", "kernel", ",ltd.is")}
    ok = got == {"home": 22611, "new": 18412, "linux": 997, "kernel": 279, ",ltd.is": 1}
    return ok, str(got)


results.append(run("代表 term 的 df（22611／18412／997／279／1）", _df_known))

# ===========================================================================
section("不存在的 term、順序與數值")
# ===========================================================================
results.append(run("get_doc_tf('不存在的詞') == ([], [])",
                   lambda: (reader.get_doc_tf("不存在的詞") == ([], []), "")))
results.append(run("get_doc_tf('') == ([], [])",
                   lambda: (reader.get_doc_tf("") == ([], []), "")))


def _monotone():
    for t in TERMS:
        d, tf = reader.get_doc_tf(t)
        if not all(a < b for a, b in zip(d, d[1:])):
            return False, f"{t!r}: doc_nums 非嚴格遞增"
        if not all(x >= 1 for x in tf):
            return False, f"{t!r}: 有 tf < 1"
    return True, f"{len(TERMS)} 個 term"


results.append(run("doc_nums 嚴格遞增、tfs ≥ 1", _monotone))


def _types():
    d, tf = reader.get_doc_tf("linux")
    return (type(d) is list and type(tf) is list
            and all(type(x) is int for x in d[:5] + tf[:5])), ""


results.append(run("回傳型別為 list[int]", _types))

# ===========================================================================
section("mmap 只開一次")
# ===========================================================================
def _mm_once():
    r = IndexReader(INDEX)
    r.get_doc_tf("linux")
    a = r._postings_mm()
    r.get_doc_tf("kernel")
    b = r._postings_mm()
    return a is b, f"size={len(a)}"


results.append(run("連續呼叫後 _postings_mm() 回傳同一個物件", _mm_once))


def _corrupt():
    """block 長度與解碼結果不符時要拋 ValueError。"""
    r = IndexReader(INDEX)
    df, off, length = r._load_lexicon()["kernel"]
    r._lexicon = dict(r._load_lexicon())
    r._lexicon["kernel"] = (df, off, length + 1)
    try:
        r.get_doc_tf("kernel")
    except ValueError as e:
        return True, str(e)
    return False, "未拋出 ValueError"


results.append(run("lexicon length 與實際 block 不符時拋 ValueError", _corrupt))

# ===========================================================================
section("5.1 計時：get_doc_tf vs get_postings")
# ===========================================================================
def median_ms(fn, n: int = 5) -> float:
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000)
    return statistics.median(ts)


def _timing():
    r = IndexReader(INDEX)
    r._load_lexicon()
    t0 = time.perf_counter()
    r._postings_mm()
    cold = (time.perf_counter() - t0) * 1000
    print(f"\n  mmap 第一次建立（_postings_mm() 冷呼叫）：{cold:.3f} ms\n")
    print("  | term | df | get_postings (ms) | decode_postings_block only (ms) | get_doc_tf (ms) | 倍數 |")
    print("  | --- | --- | --- | --- | --- | --- |")
    ok = True
    for t in ("home", "new", "linux", "kernel"):
        df, off, length = r._load_lexicon()[t]
        r.get_postings(t)
        r.get_doc_tf(t)  # 暖身
        with (INDEX / "postings.bin").open("rb") as f:
            f.seek(off)
            raw = f.read(length)
        gp = median_ms(lambda: r.get_postings(t))
        dec = median_ms(lambda: decode_postings_block(raw))
        gd = median_ms(lambda: r.get_doc_tf(t))
        ratio = gp / gd
        print(f"  | {t} | {df:,} | {gp:.3f} | {dec:.3f} | {gd:.3f} | {ratio:.2f}x |")
        if t in ("home", "new") and ratio <= 1:
            ok = False
    return ok, "高 df 詞倍數 > 1"


results.append(run("計時表（高 df 詞倍數 > 1）", _timing))

# ===========================================================================
if FULL:
    section("--full：全部 term 與 get_postings 對照")
# ===========================================================================
    def _full():
        r = IndexReader(INDEX)
        lx = r._load_lexicon()
        n = len(lx)
        t0 = time.perf_counter()
        for t in lx:
            r.get_doc_tf(t)
        t_doc_tf = time.perf_counter() - t0

        t0 = time.perf_counter()
        with (INDEX / "postings.bin").open("rb") as f:
            for _t, (_df, off, length) in lx.items():
                f.seek(off)
                decode_postings_block(f.read(length))
        t_decode = time.perf_counter() - t0

        # 逐 term 對照（不計時，不保留結果以免佔用大量記憶體）
        bad, bad_df = [], []
        for t, (df, _o, _l) in lx.items():
            d, tf = r.get_doc_tf(t)
            if list(zip(d, tf)) != [(p.doc_num, p.tf) for p in r.get_postings(t)]:
                bad.append(t)
            if len(d) != df:
                bad_df.append(t)
        print(f"\n  全部 {n:,} 個 term")
        print(f"  get_doc_tf 全掃描：{t_doc_tf:.2f} s")
        print(f"  開一次檔 + decode_postings_block 全掃描（build_norms 的讀法）：{t_decode:.2f} s")
        return (not bad and not bad_df and n == 573233), f"不符 {len(bad)}，df 不符 {len(bad_df)}"

    results.append(run("全部 573,233 個 term 與 get_postings 一致", _full))

# ===========================================================================
section("Test Summary")
# ===========================================================================
all_passed = all(results)
print(f"\n  {sum(results)}/{len(results)} passed")
print(f"  Overall: {'ALL PASSED ✓' if all_passed else 'SOME FAILED ✗'}\n")
sys.exit(0 if all_passed else 1)
