"""t2.test.py — T2 核心：weighting.weight()（ltc）與 IndexReader.get_norms()

執行（需先跑過 build_norms.py）：
  uv run python HW2/src/build_norms.py --index-dir HW2/index
  uv run python HW2/tests/t2.test.py
"""
from __future__ import annotations

import json
import math
import random
import shutil
import sys
import tempfile
from pathlib import Path

# 確保可以 import HW2/src 的模組
SRC = Path(__file__).resolve().parent.parent / "src"
INDEX = Path(__file__).resolve().parent.parent / "index"
sys.path.insert(0, str(SRC))

from weighting import weight
from writer import IndexReader

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

N = 34786
EMPTY_DOC = 24621


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


results: list[bool] = []

# ===========================================================================
section("weight()：手算值")
# ===========================================================================
def _close(got: float, want: float, tol: float = 1e-12):
    return abs(got - want) < tol, f"got={got!r}, want={want!r}"


results.append(run("weight(1, 997, N) == log10(N/997)",
                   lambda: _close(weight(1, 997, N), math.log10(N / 997))))
results.append(run("weight(1, 997, N) ≈ 1.5427093343",
                   lambda: _close(weight(1, 997, N), 1.5427093343, 1e-9)))
results.append(run("weight(10, 997, N) ≈ 3.0854186686（為 tf=1 的 2 倍）",
                   lambda: _close(weight(10, 997, N), 2 * weight(1, 997, N))))
results.append(run("weight(10, 997, N) ≈ 3.0854186686",
                   lambda: _close(weight(10, 997, N), 3.0854186686, 1e-9)))
results.append(run("weight(0, 997, N) == 0.0", lambda: _close(weight(0, 997, N), 0.0)))
results.append(run("weight(1, 0, N) == 0.0", lambda: _close(weight(1, 0, N), 0.0)))
results.append(run("weight(1, N, N) == 0.0", lambda: _close(weight(1, N, N), 0.0)))


def _bad_scheme(*args):
    try:
        weight(*args)
    except ValueError as e:
        return True, f"ValueError: {e}"
    return False, "未拋出 ValueError"


results.append(run("weight(1, 997, N, 'xyz') 拋出 ValueError", lambda: _bad_scheme(1, 997, N, "xyz")))
results.append(run("weight(0, 997, N, 'xyz') 拋出 ValueError（先檢查 scheme）",
                   lambda: _bad_scheme(0, 997, N, "xyz")))

# ===========================================================================
section("獨立路徑對照：postings.txt 解析 vs get_norms()")
# ===========================================================================
reader = IndexReader(INDEX)
sample = random.Random(42).sample(range(N), 20)


def independent_norms(docs: list[int]) -> dict[int, float]:
    """自行解析 postings.txt（不用 writer、postings.bin、IndexReader），累加指定文件的 norm²。"""
    want = set(docs)
    norm2 = dict.fromkeys(docs, 0.0)
    with (INDEX / "postings.txt").open("r", encoding="utf-8", newline="") as f:
        for line in f:
            line = line.rstrip("\r\n")
            _term, rest = line.split(", ", 1)
            df_str, rest = rest.split(": <", 1)
            df = int(df_str)
            body = rest[:-1]
            if not body:
                continue
            idf = math.log10(N / df)
            for item in body.split("; "):
                head = item.split(": <", 1)[0]  # "doc, tf"
                doc_s, tf_s = head.split(", ")
                doc = int(doc_s)
                if doc in want:
                    w = (1 + math.log10(int(tf_s))) * idf
                    norm2[doc] += w * w
    return {d: math.sqrt(v) for d, v in norm2.items()}


def _independent():
    norms = reader.get_norms()
    ref = independent_norms(sample)
    worst = max(abs(norms[d] - ref[d]) for d in sample)
    return worst < 1e-9, f"20 篇最大誤差={worst:.3e}"


results.append(run("20 篇文件 norm 與獨立解析一致（< 1e-9）", _independent))

# ===========================================================================
section("get_norms()：形狀")
# ===========================================================================
results.append(run("len(get_norms()) == 34786",
                   lambda: (len(reader.get_norms()) == N, f"len={len(reader.get_norms())}")))
results.append(run("get_norms()[24621] == 0.0",
                   lambda: (reader.get_norms()[EMPTY_DOC] == 0.0, f"{reader.get_norms()[EMPTY_DOC]!r}")))


def _others_positive():
    norms = reader.get_norms()
    bad = [d for d in range(N) if d != EMPTY_DOC and not norms[d] > 0]
    return not bad, f"非正值文件數={len(bad)}"


results.append(run("其餘 34,785 篇文件 norm 都 > 0", _others_positive))
results.append(run("get_norms() 以 array('d') 回傳且有快取",
                   lambda: (reader.get_norms().typecode == "d" and reader.get_norms() is reader.get_norms(),
                            f"typecode={reader.get_norms().typecode}")))

# ===========================================================================
section("竄改 meta / 缺檔")
# ===========================================================================
def make_tmp_index() -> Path:
    """暫存目錄：symlink 指向真實 index 來源檔，norm 檔與 meta 複製一份。"""
    tmp = Path(tempfile.mkdtemp(prefix="t2_idx_"))
    for name in ("lexicon.tsv", "postings.bin", "metadata.json"):
        (tmp / name).symlink_to((INDEX / name).resolve())
    for name in ("doc_norms.bin", "doc_norms.meta.json"):
        shutil.copy(INDEX / name, tmp / name)
    return tmp


def tamper_meta(mutate):
    def _go():
        tmp = make_tmp_index()
        try:
            meta_path = tmp / "doc_norms.meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            mutate(meta)
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            IndexReader(tmp).get_norms()
        except ValueError as e:
            return True, f"ValueError: {e}"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return False, "未拋出 ValueError"
    return _go


def _flip_sha(meta):
    s = meta["sources"]["postings.bin"]["sha256"]
    meta["sources"]["postings.bin"]["sha256"] = ("0" if s[0] != "0" else "1") + s[1:]


def _set(key, value):
    def _m(meta):
        meta[key] = value
    return _m


results.append(run("log_base 改成 'e' → ValueError", tamper_meta(_set("log_base", "e"))))
results.append(run("N 改成 34785 → ValueError", tamper_meta(_set("N", 34785))))
results.append(run("postings.bin 的 sha256 改一個字元 → ValueError", tamper_meta(_flip_sha)))


def _truncated_bin():
    tmp = make_tmp_index()
    try:
        p = tmp / "doc_norms.bin"
        data = p.read_bytes()
        p.write_bytes(data[:-8])
        IndexReader(tmp).get_norms()
    except ValueError as e:
        return True, f"ValueError: {e}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return False, "未拋出 ValueError"


results.append(run("doc_norms.bin 截掉 8 bytes → ValueError", _truncated_bin))


def _missing_bin():
    tmp = make_tmp_index()
    try:
        (tmp / "doc_norms.bin").unlink()
        IndexReader(tmp).get_norms()
    except FileNotFoundError as e:
        return True, f"FileNotFoundError: {e}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return False, "未拋出 FileNotFoundError"


results.append(run("刪掉 doc_norms.bin → FileNotFoundError", _missing_bin))

# ===========================================================================
section("Test Summary")
# ===========================================================================
all_passed = all(results)
print(f"\n  {sum(results)}/{len(results)} passed")
print(f"  Overall: {'ALL PASSED ✓' if all_passed else 'SOME FAILED ✗'}\n")
sys.exit(0 if all_passed else 1)
