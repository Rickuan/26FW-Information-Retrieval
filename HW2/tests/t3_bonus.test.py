"""t3_bonus.test.py — T3 加分：get_champions 與 get_doc_tf 的 LRU 快取

執行（需先有 HW2/index/champions.r50.*，即 T2 加分的 build_champions）：
  uv run python HW2/tests/t3_bonus.test.py

竄改測試在暫存目錄進行（symlink 指向真實 index 來源檔，champion 檔複製後修改），
不會改動 HW2/index。
"""
from __future__ import annotations

import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
INDEX = ROOT / "index"
sys.path.insert(0, str(SRC))

from writer import IndexReader

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


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


def raises(exc, fn):
    try:
        fn()
    except exc as e:
        return True, f"{exc.__name__}: {e}"
    return False, f"未拋出 {exc.__name__}"


def make_tmp_index() -> Path:
    """暫存目錄：index 來源檔用 symlink，champion 檔複製（可修改）。"""
    tmp = Path(tempfile.mkdtemp(prefix="t3b_idx_"))
    for name in ("lexicon.tsv", "postings.bin", "metadata.json"):
        (tmp / name).symlink_to((INDEX / name).resolve())
    for name in ("champions.r50.bin", "champions.r50.tsv", "champions.r50.meta.json"):
        shutil.copy(INDEX / name, tmp / name)
    return tmp


def median_ms(fn, n: int = 5) -> float:
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000)
    return statistics.median(ts)


reader = IndexReader(INDEX)
results: list[bool] = []

# ===========================================================================
section("get_champions")
# ===========================================================================
def _linux():
    d, tf = reader.get_champions("linux")
    full = dict(zip(*reader.get_doc_tf("linux")))
    in_full = all(full.get(x) == y for x, y in zip(d, tf))
    strict = all(a < b for a, b in zip(d, d[1:]))
    outside = [v for k, v in full.items() if k not in set(d)]
    ok = len(d) == len(tf) == 50 and strict and in_full and min(tf) >= max(outside)
    return ok, f"n={len(d)}, min tf in={min(tf)}, max tf out={max(outside)}"


results.append(run("linux：50 筆、doc 遞增、皆在 get_doc_tf 中、champion 內最小 tf ≥ 外最大 tf", _linux))


def _rule(term: str):
    def _go():
        d, tf = reader.get_champions(term)
        full = reader.get_doc_tf(term)
        top = sorted(zip(*full), key=lambda p: (-p[1], p[0]))[:50]
        want = sorted(top)
        return list(zip(d, tf)) == want, f"n={len(d)}"
    return _go


for t in ("home", "new", "linux", "kernel"):
    results.append(run(f"{t}：與 (-tf, doc) 排序前 50 筆逐筆相同", _rule(t)))

results.append(run("get_champions(',ltd.is') == get_doc_tf(',ltd.is')",
                   lambda: (reader.get_champions(",ltd.is") == reader.get_doc_tf(",ltd.is"), "")))
results.append(run("get_champions('retreiv') == get_doc_tf('retreiv')（df 11 ≤ 50）",
                   lambda: (reader.get_champions("retreiv") == reader.get_doc_tf("retreiv")
                            and reader.df("retreiv") == 11, "")))
results.append(run("get_champions('不存在的詞') == ([], [])",
                   lambda: (reader.get_champions("不存在的詞") == ([], []), "")))
results.append(run("get_champions('linux', r=20) 拋 FileNotFoundError",
                   lambda: raises(FileNotFoundError, lambda: reader.get_champions("linux", r=20))))
results.append(run("get_champions('linux', r=0) 拋 ValueError",
                   lambda: raises(ValueError, lambda: reader.get_champions("linux", r=0))))

# --- 竄改 ---
def _tamper(mutate):
    def _go():
        tmp = make_tmp_index()
        try:
            mutate(tmp)
            return raises(ValueError, lambda: IndexReader(tmp).get_champions("linux"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return _go


def _edit_meta(fn):
    def _m(tmp: Path):
        p = tmp / "champions.r50.meta.json"
        meta = json.loads(p.read_text(encoding="utf-8"))
        fn(meta)
        p.write_text(json.dumps(meta), encoding="utf-8")
    return _m


def _flip_sha(meta):
    h = meta["sources"]["postings.bin"]["sha256"]
    meta["sources"]["postings.bin"]["sha256"] = ("0" if h[0] != "0" else "1") + h[1:]


def _drop_last_tsv_line(tmp: Path):
    p = tmp / "champions.r50.tsv"
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    p.write_text("".join(lines[:-1]), encoding="utf-8")


def _swap_r_files(tmp: Path):
    """把 r50 檔案當成 r20 檔案（meta 的 r 仍是 50）。"""
    for ext in ("bin", "tsv", "meta.json"):
        (tmp / f"champions.r50.{ext}").rename(tmp / f"champions.r20.{ext}")


results.append(run("meta sources['postings.bin'].sha256 被改 → ValueError",
                   _tamper(_edit_meta(_flip_sha))))
results.append(run("meta r 改成 20 → ValueError",
                   _tamper(_edit_meta(lambda m: m.__setitem__("r", 20)))))
results.append(run("meta rule 改成 '(-tf)' → ValueError",
                   _tamper(_edit_meta(lambda m: m.__setitem__("rule", "(-tf)")))))
results.append(run("tsv 刪掉最後一行 → ValueError", _tamper(_drop_last_tsv_line)))


def _renamed():
    tmp = make_tmp_index()
    try:
        _swap_r_files(tmp)
        return raises(ValueError, lambda: IndexReader(tmp).get_champions("linux", r=20))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


results.append(run("檔名 r20 但 meta r=50 → ValueError", _renamed))

# ===========================================================================
section("get_doc_tf 的 LRU 快取")
# ===========================================================================
def _default_off():
    r = IndexReader(INDEX)
    r.get_doc_tf("linux"); r.get_doc_tf("linux"); r.get_doc_tf("kernel")
    return r.doc_tf_cache_info() == (0, 0), str(r.doc_tf_cache_info())


results.append(run("預設（關閉）：呼叫幾次後 info == (0, 0)", _default_off))


def _lru_seq():
    r = IndexReader(INDEX)
    r.set_doc_tf_cache(2)
    for t in ("linux", "kernel", "linux", "home", "kernel"):
        r.get_doc_tf(t)
    return r.doc_tf_cache_info() == (1, 4), str(r.doc_tf_cache_info())


results.append(run("maxsize=2，linux/kernel/linux/home/kernel → (1, 4)", _lru_seq))


def _same_results():
    off = IndexReader(INDEX)
    on = IndexReader(INDEX)
    on.set_doc_tf_cache(8)
    for t in ("linux", "kernel", "home", "不存在的詞"):
        for _ in range(2):  # 第二次必為命中（或不存在 term）
            if on.get_doc_tf(t) != off.get_doc_tf(t):
                return False, t
    return True, ""


results.append(run("開啟快取時結果與關閉時相同", _same_results))


def _no_pollution():
    r = IndexReader(INDEX)
    r.set_doc_tf_cache(4)
    want = r.get_doc_tf("linux")
    want = (list(want[0]), list(want[1]))
    d, tf = r.get_doc_tf("linux")  # 命中
    d.clear(); tf.append(-1)
    d2, tf2 = r.get_doc_tf("linux")
    d3, tf3 = r.get_doc_tf("linux")
    d3.append(-5)
    d4, tf4 = r.get_doc_tf("linux")
    return ((d2, tf2) == want and (d4, tf4) == want), ""


results.append(run("修改回傳的 list 不會污染快取", _no_pollution))


def _reset():
    r = IndexReader(INDEX)
    r.set_doc_tf_cache(2)
    r.get_doc_tf("linux"); r.get_doc_tf("linux")
    before = r.doc_tf_cache_info()
    r.set_doc_tf_cache(0)
    after = r.doc_tf_cache_info()
    r.get_doc_tf("linux")
    still_off = r.doc_tf_cache_info()
    return before == (1, 1) and after == (0, 0) and still_off == (0, 0), f"{before}→{after}→{still_off}"


results.append(run("set_doc_tf_cache(0)：清空並歸零，且之後不計數", _reset))
results.append(run("set_doc_tf_cache(-1) 拋 ValueError",
                   lambda: raises(ValueError, lambda: IndexReader(INDEX).set_doc_tf_cache(-1))))


def _reset_clears_entries():
    r = IndexReader(INDEX)
    r.set_doc_tf_cache(2)
    r.get_doc_tf("linux")
    r.set_doc_tf_cache(2)  # 重設：清空
    r.get_doc_tf("linux")
    return r.doc_tf_cache_info() == (0, 1), str(r.doc_tf_cache_info())


results.append(run("重設 maxsize 會清空快取與計數", _reset_clears_entries))

# ===========================================================================
section("計時")
# ===========================================================================
def _top5():
    lex = reader._load_lexicon()
    top = sorted(lex, key=lambda t: (-lex[t][0], t))[:5]
    print(f"\n  全 index df 最高的 5 個 term：{[(t, lex[t][0]) for t in top]}")
    return set(top) == {"home", "new", "1", "us", "site"}, ""


results.append(run("df 最高的 5 個 term 為 home/new/1/us/site", _top5))


def _timing_lru():
    group = ["home", "new", "1", "us", "site"]
    r = IndexReader(INDEX)
    r.get_doc_tf("home")  # 預先建立 mmap

    def cold():
        r.set_doc_tf_cache(8)  # 重設 = 清空
        for t in group:
            r.get_doc_tf(t)

    r.set_doc_tf_cache(8)
    for t in group:
        r.get_doc_tf(t)

    def hot():
        for t in group:
            r.get_doc_tf(t)

    c = median_ms(cold)
    h = median_ms(hot)
    print(f"\n  5 個高 df term 整組查一次（5 次中位數）：冷快取 {c:.3f} ms，熱快取 {h:.3f} ms，{c / h:.1f}x")
    return h < c, ""


results.append(run("LRU 冷／熱計時（熱 < 冷）", _timing_lru))


def _timing_champ():
    r = IndexReader(INDEX)
    r.get_champions("home"); r.get_doc_tf("home")  # 暖身（含載入 champion 檔）
    print("\n  | term | get_doc_tf (ms) | get_champions (ms) |")
    print("  | --- | --- | --- |")
    for t in ("home", "new"):
        a = median_ms(lambda: r.get_doc_tf(t))
        b = median_ms(lambda: r.get_champions(t))
        print(f"  | {t} | {a:.3f} | {b:.3f} |")
    return True, ""


results.append(run("get_champions vs get_doc_tf 計時", _timing_champ))

# ===========================================================================
section("Test Summary")
# ===========================================================================
all_passed = all(results)
print(f"\n  {sum(results)}/{len(results)} passed")
print(f"  Overall: {'ALL PASSED ✓' if all_passed else 'SOME FAILED ✗'}\n")
sys.exit(0 if all_passed else 1)
