"""t1.test.py — T1 核心：IndexReader.N / df() 與 Preprocessor.from_config()

執行：
  uv run python HW2/tests/t1.test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# 確保可以 import HW2/src 的模組
SRC = Path(__file__).resolve().parent.parent / "src"
INDEX = Path(__file__).resolve().parent.parent / "index"
sys.path.insert(0, str(SRC))

from tokenizer import Preprocessor
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


def raises_value_error(cfg, must_contain: tuple[str, ...] = ()):
    try:
        Preprocessor.from_config(cfg)
    except ValueError as e:
        msg = str(e)
        ok = all(s in msg for s in must_contain)
        return ok, f"ValueError: {msg}"
    return False, "未拋出 ValueError"


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def lexicon_first_last() -> tuple[str, str]:
    """直接讀 lexicon.tsv 取第一個與最後一個 term（不經 IndexReader）。"""
    with (INDEX / "lexicon.tsv").open("r", encoding="utf-8", newline="") as f:
        first = last = None
        for line in f:
            term = line.split("\t", 1)[0]
            if first is None:
                first = term
            last = term
    return first, last


reader = IndexReader(INDEX)
metadata = reader.get_metadata()
cfg = metadata["preprocessor"]
results: list[bool] = []

# ===========================================================================
section("IndexReader.N / df()")
# ===========================================================================
results.append(run("reader.N == 34786", lambda: (reader.N == 34786, f"N={reader.N}")))
results.append(run("df('linux') == 997", lambda: (reader.df("linux") == 997, f"df={reader.df('linux')}")))
results.append(run("df('sourc') == 4062", lambda: (reader.df("sourc") == 4062, f"df={reader.df('sourc')}")))
results.append(run("df('不存在的詞') == 0", lambda: (reader.df("不存在的詞") == 0, f"df={reader.df('不存在的詞')}")))

first, last = lexicon_first_last()
for t in ["linux", "sourc", "open", first, last]:
    def _df_matches(t=t):
        d, n = reader.df(t), len(reader.get_postings(t))
        return d == n and d > 0, f"df={d}, len(postings)={n}"
    results.append(run(f"df({t!r}) == len(get_postings({t!r}))", _df_matches))

# ===========================================================================
section("Preprocessor.from_config()")
# ===========================================================================
def _query_terms():
    pre = Preprocessor.from_config(cfg)
    terms = [t for _, t in pre.process("open source AND Linux")]
    return terms == ["open", "sourc", "linux"], f"terms={terms}"


def _flags_match():
    pre = Preprocessor.from_config(cfg)
    got = {k: getattr(pre, k) for k in ("casefold", "stopword", "stem", "lemma")}
    return got == cfg, f"got={got}, metadata={cfg}"


def _lemma_default():
    pre = Preprocessor.from_config({"casefold": True, "stopword": True, "stem": True})
    return pre.lemma is False, f"lemma={pre.lemma!r}"


results.append(run("'open source AND Linux' → ['open', 'sourc', 'linux']", _query_terms))
results.append(run("casefold/stopword/stem/lemma 與 metadata 完全一致", _flags_match))
results.append(run("缺 lemma 不報錯且 .lemma is False", _lemma_default))
results.append(run("from_config({}) 拋出 ValueError", lambda: raises_value_error({})))
results.append(run("from_config(None) 拋出 ValueError", lambda: raises_value_error(None)))
results.append(run(
    "from_config({'casefold': True}) 拋出 ValueError，訊息含 stopword、stem",
    lambda: raises_value_error({"casefold": True}, ("stopword", "stem")),
))

# ===========================================================================
section("Test Summary")
# ===========================================================================
all_passed = all(results)
print(f"\n  {sum(results)}/{len(results)} passed")
print(f"  Overall: {'ALL PASSED ✓' if all_passed else 'SOME FAILED ✗'}\n")
sys.exit(0 if all_passed else 1)
